# AI Novel Studio

[简体中文](README.md) · **English**

A local-first desktop workspace for novel writing. Chat with **Codex** inside the app, retrieve novel materials, and generate draft candidates with a **separately configured prose model**.

Development preview, primarily for Windows.

## Features

- **Novel workspace:** projects, volumes and chapters, Markdown/text manuscript import, editing, autosave and revision history.
- **Codex assistant:** ChatGPT sign-in, model and reasoning controls, chat history, forks, compaction, image/text attachments and optional web search.
- **Novel retrieval:** a novel MCP connection for chapters, chapter requirements, characters and manuscript evidence, with batch reading and a compact progress summary.
- **Independent prose generation:** Codex prepares the task; your writing model produces a candidate. Progress and results appear in the chat sidebar for author review.
- **Selections and memory:** quote selected manuscript text, use writing commands such as `/polish` and `/rewrite`, browse character/world/plot memory, and read Markdown-formatted replies.

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

## Planned

An event-outline workflow inspired by the Snowflake Method: import an outline, link events to chapters, and assemble targeted writing context.
This is a design proposal, not an implemented feature. See the [proposal](docs/SNOWFLAKE_EVENT_WORKFLOW_2026-10-18.md) in Chinese.

Feedback is welcome through Issues. License: [MIT](LICENSE).
