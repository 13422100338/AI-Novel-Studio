# AI Novel Studio

[简体中文](README.md) · **English**

A local novel-writing workspace driven by the complete outline. Chat with **Codex** inside the app, read manuscript references, and generate candidates with a **separately configured prose model**.

Development preview, primarily for Windows.

## Features

- **Novel workspace:** projects, volumes and chapters, Markdown/text manuscript import, editing, autosave and revision history.
- **Outline workspace:** Markdown editing, import/export, navigation, autosave, version history and chapter links that require reconfirmation after outline changes.
- **Codex assistant:** the complete current outline on every turn, ChatGPT sign-in, model/reasoning controls, chat history, forks, compaction, attachments and optional web search.
- **Novel retrieval:** a novel MCP connection for chapters, author constraints and manuscript evidence, with batch reading and a compact progress summary.
- **Independent prose generation:** confirm the full outline and references, generate candidates, adopt a selection or chapter, discard, and recover drafts with their original input.
- **Selections and legacy records:** writing commands such as `/polish` and `/rewrite`, Markdown replies, and read-only access to old character, memory and audit records.

## Setup

Requirements: **Python 3.11+, Node.js/npm**, and Codex CLI or the Codex desktop app signed in with ChatGPT.

1. Clone the repository or extract its ZIP, then run `setup.bat` to install Python dependencies.
2. Open PowerShell in the project directory and build the manuscript editor before first use:

   ```powershell
   Push-Location src/ai_novel_studio/ui_qml/editor_web
   npm ci
   npm run build
   Pop-Location
   ```

3. Run `启动程序.bat` or `launch.bat`, then create or open a novel project.
4. Configure the independent writing model's API connection and model in Settings. The Codex assistant uses its own ChatGPT sign-in.

## Workflow

Prose generation now requires a registered complete outline and author-confirmed input. Existing projects can still be edited and discussed before an outline is imported or created.
See the [workflow and progress](docs/FULL_OUTLINE_WORKFLOW_2026-10-18.md) in Chinese.

Feedback is welcome through Issues. License: [MIT](LICENSE).
