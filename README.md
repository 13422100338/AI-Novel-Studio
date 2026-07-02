# AI Novel Studio

AI Novel Studio 是一个从零实现的、本地优先的 AI 长篇小说创作工作台。

当前状态：V3 Phase 0 工程基线。项目尚未发布正式版本。

## Development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

## Privacy

公开提交和发布产物不得包含真实姓名、本机用户名、用户目录、API Key 或用户稿件。

## Windows build

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The output is `dist/AI-Novel-Studio/AI-Novel-Studio.exe`.

## Release privacy gate

Create the ignored `.privacy-blocklist` locally, one private term per line, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_release.ps1
```

Do not publish an artifact unless this command succeeds.
