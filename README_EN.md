# AI Novel Studio

[简体中文](README.md) · **English**

**A local novel-writing workspace built around your complete outline.** Discuss the story with Codex inside the app, turn ideas into editable notes, and draft with a separately configured prose model.

Complete outline → Story discussion → Scene plans and notes → Review model input → Generate a candidate → Review and adopt

![Outline workspace with event navigation, chapter and note links, and the Codex assistant](docs/images/outline-workspace.png)

## Designed for snowflake-style writing

- **Keep the whole story in view.** Creative conversations and prose generation start with the current complete outline. Codex can read specific chapters or batches through the novel MCP connection. Context-budget limits are reported explicitly.
- **Write from any event.** Manuscript, Outline and Notes are equal workspaces. Markdown headings organize the story; events link to chapters and notes through inline links and margin connectors. Chapter links survive outline edits and require reconfirmation.
- **Keep the discussion useful.** Save scene plans, character traits, style and reminders as editable, versioned notes. For each draft, choose no notes, selected originals or a Codex-prepared summary.
- **Review what the writer receives.** Codex handles discussion, research and instructions; the prose model is independent. Inspect the complete outgoing messages, including the outline, selected notes and manuscript references, before generation. Candidates become formal prose only when adopted.

Also includes volume/chapter management, Markdown/text import, autosave, revision history, exemplar and recent-chapter references, candidate preview and recovery. Codex controls cover models, reasoning effort, chat forks, compaction, attachments and optional web search.

## Inside the workspace

<details>
<summary>Manuscript and assistant: edit the story and discuss the next step side by side</summary>

![Manuscript editing alongside a Codex story discussion](docs/images/writing-workspace.png)

</details>

<details>
<summary>Discussion becomes notes: keep scene beats and select materials for the next draft</summary>

![Editable scene notes with Markdown tables and prose-input selection](docs/images/notes-workspace.png)

</details>

<details>
<summary>Before generation: inspect the actual input, then decide whether to proceed</summary>

![Complete prose-model input preview and author confirmation](docs/images/writer-input-review.png)

</details>

*Screenshots use a fictional demo project, example conversations and example model configuration.*

## Setup

Development preview, primarily for **Windows**. Requirements: **Python 3.11+, Node.js/npm**, and a signed-in Codex CLI or Codex desktop app.

1. Clone the repository or extract its ZIP, then run `setup.bat`.
2. Open PowerShell in the project directory and build the manuscript editor before first use:

   ```powershell
   Push-Location src/ai_novel_studio/ui_qml/editor_web
   npm ci
   npm run build
   Pop-Location
   ```

3. Run `启动程序.bat` or `launch.bat`, create or open a project, and import an outline.
4. Configure the prose model's API connection and model in Settings. Codex uses its own sign-in.

Feedback is welcome through Issues. License: [MIT](LICENSE).
