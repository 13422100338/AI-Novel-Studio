import json
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from ai_novel_studio.infrastructure.codex import app_server
from ai_novel_studio.infrastructure.codex.app_server import (
    CodexAppServer,
    CodexConnectionError,
)
from ai_novel_studio.infrastructure.mcp.novel_server import NovelMcpEndpoint


def fake_server(tmp_path: Path, *, malformed: bool = False) -> CodexAppServer:
    script = tmp_path / "server.py"
    script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' not in request: continue\n"
        "    if request['method'] == 'probe':\n"
        + (
            "        print('not-json', flush=True); break\n"
            if malformed
            else "        event = {'method':'event','params':{'text':'chunk'}}\n"
            "        print(json.dumps(event), flush=True)\n"
        )
        + "    print(json.dumps({'id':request['id'], 'result':{'ok':True}}), flush=True)\n",
        encoding="utf-8",
    )
    return CodexAppServer(tmp_path, [sys.executable, "-u", str(script)])


def test_stdio_routes_responses_and_notifications_and_closes_child(tmp_path):
    client = fake_server(tmp_path)
    try:
        assert client.request("probe", {}) == {"ok": True}
        assert client.notification(1)["params"]["text"] == "chunk"
    finally:
        client.close()
    assert client._process.poll() is not None


def test_malformed_stdio_fails_without_exposing_frame(tmp_path):
    client = fake_server(tmp_path, malformed=True)
    try:
        with pytest.raises(CodexConnectionError):
            client.request("probe", {})
    finally:
        client.close()


def test_close_stops_owned_descendant_that_inherits_stdout(tmp_path):
    script = tmp_path / "descendant_server.py"
    script.write_text(
        "import json, subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' in request:\n"
        "        print(json.dumps({'id':request['id'],'result':{}}), flush=True)\n",
        encoding="utf-8",
    )
    client = CodexAppServer(tmp_path, [sys.executable, "-u", str(script)])
    started = monotonic()
    client.close()
    assert monotonic() - started < 8
    assert not client._reader.is_alive()


def test_only_owned_novel_tools_are_allowed_and_token_is_not_in_config():
    endpoint = NovelMcpEndpoint("http://127.0.0.1:1/mcp", "ephemeral-test-token")
    tools = {name: {"name": name} for name in endpoint.tools}
    statuses = {"data": [{"name": endpoint.server_name, "tools": tools}], "nextCursor": None}
    CodexAppServer.validate_tools(statuses, endpoint)
    assert endpoint.token not in str(endpoint.config())
    assert (
        endpoint.config()["mcp_servers.novel_workspace.env_http_headers.Authorization"]
        == "AI_NOVEL_MCP_AUTH"
    )
    statuses["data"].append({"name": "other", "tools": {"write": {"name": "write"}}})
    with pytest.raises(CodexConnectionError, match="额外"):
        CodexAppServer.validate_tools(statuses, endpoint)
    with pytest.raises(CodexConnectionError, match="未连接"):
        CodexAppServer.validate_tools({"data": []}, endpoint)


def test_empty_disabled_mcp_placeholders_are_permitted():
    CodexAppServer.validate_tools({"data": [{"name": "disabled", "tools": {}}]}, None)


def test_path_cli_is_preferred_to_desktop_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(app_server.shutil, "which", lambda _: "path-codex.exe")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert app_server.resolve_codex_executable() == "path-codex.exe"


def test_desktop_bundle_is_found_without_codex_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(app_server.shutil, "which", lambda _: None)
    monkeypatch.setattr(app_server.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    installed = tmp_path / "OpenAI" / "Codex" / "bin" / "installed-version" / "codex.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"test executable placeholder")
    # A newer, incomplete runtime directory must not hide the usable binary.
    (installed.parent.parent / "incomplete-version").mkdir()
    assert Path(app_server.resolve_codex_executable()) == installed.resolve()


def test_missing_cli_and_desktop_bundle_have_a_safe_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_server.shutil, "which", lambda _: None)
    monkeypatch.setattr(app_server.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    with pytest.raises(CodexConnectionError, match="没有找到 Codex"):
        app_server.resolve_codex_executable()


@pytest.mark.parametrize(
    "servers",
    [
        {},
        {"resident": {"command": "configured-transport"}},
        {
            "node_repl": {"command": "configured-transport"},
            "cua_repl": {"url": "http://127.0.0.1/mcp"},
        },
    ],
)
def test_production_startup_never_invents_a_transportless_mcp(tmp_path, monkeypatch, servers):
    """Disabling an absent MCP table fails Codex config parsing before initialize."""
    script = tmp_path / "configured_cli.py"
    script.write_text(
        "import json, sys\n"
        "servers=json.loads(sys.argv[1])\n"
        "sys.stdin.reconfigure(encoding='utf-8')\n"
        "sys.stdout.reconfigure(encoding='utf-8')\n"
        "for argument in sys.argv[2:]:\n"
        "    if argument.startswith('mcp_servers.') and '.enabled=' in argument:\n"
        "        name=argument.split('.')[1]\n"
        "        if name not in servers:\n"
        "            print('invalid transport', file=sys.stderr); sys.exit(1)\n"
        "for line in sys.stdin:\n"
        "    message=json.loads(line)\n"
        "    if 'id' not in message: continue\n"
        "    result={}\n"
        "    if message['method']=='config/read': result={'config':{'mcp_servers':servers}}\n"
        "    if message['method'] in ('mcpServerStatus/list','skills/list'): result={'data':[]}\n"
        "    print(json.dumps({'id':message['id'],'result':result}), flush=True)\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    commands = []

    def popen(command, **kwargs):
        if command[0] == "installed-codex.exe":
            commands.append(command)
            command = [sys.executable, "-u", str(script), json.dumps(servers), *command[1:]]
        return real_popen(command, **kwargs)

    monkeypatch.setattr(app_server.shutil, "which", lambda _: "installed-codex.exe")
    monkeypatch.setattr(app_server.subprocess, "Popen", popen)
    client = CodexAppServer(tmp_path)
    try:
        for name in servers:
            assert client.session_config[f"mcp_servers.{name}.enabled"] is False
        assert len(commands) == (2 if servers else 1)
    finally:
        client.close()
