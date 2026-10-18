/**
 * Browser editor entry (Phase 1).
 *
 * Mounts a ProseMirror EditorView on the restricted novel schema, wires IME
 * composition handling, undo/redo, find, the selection toolbar, a decoration
 * prototype, theme variables, and the Python bridge surface. The editor owns
 * the in-memory session; Markdown remains the authoritative document and the
 * page never touches disk, models, or repositories.
 */
import { Node } from "@tiptap/pm/model";
import { EditorState, Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { EditorView } from "@tiptap/pm/view";
import { keymap } from "@tiptap/pm/keymap";
import { history, redo, undo } from "@tiptap/pm/history";
import { baseKeymap } from "@tiptap/pm/commands";
import {
  DebouncedSaveController,
  SelectionPatchCapturePayload,
  SnapshotPayload,
  buildSelectionPatchCapture,
  countWords,
  createNovelState,
  createSnapshot,
  replaceAll,
  selectionText,
  stateToMarkdown,
} from "./editor-core";
import { markdownCodec, parseDocument } from "./markdown";
import { NOVEL_SCHEMA } from "./schema";

declare global {
  interface Window {
    __novelEditor: NovelEditorBridge;
    qt?: { webChannelTransport: unknown };
  }
}

export interface RevealRangeRequest {
  from: number;
  to: number;
}

declare const QWebChannel: new (
  transport: unknown,
  callback: (channel: {
    objects: Record<string, {
      editorReady(protocolVersion: number, capabilities: string): void;
      saveRequested(
        chapterId: string,
        baseRevision: number,
        markdown: string,
        contentHash: string,
      ): void;
      selectionChanged(from: number, to: number): void;
      wordCountChanged(count: number): void;
      selectionReferenceChanged(payloadJson: string): void;
      chatSelectionChanged(payloadJson: string): void;
    }>;
  }) => void,
) => void;

export interface LoadDocumentPayload {
  chapterId: string;
  baseRevision: number;
  markdown: string;
}

/** Fixed projection returned to the host after every load attempt. */
export interface DocumentLoadResult {
  status: "LOADED" | "UNSUPPORTED_MARKDOWN" | "PARSE_FAILED";
  chapterId: string;
  revision: number;
  wordCount: number;
}

export interface NovelEditorBridge {
  loadDocument(payload: LoadDocumentPayload): DocumentLoadResult;
  requestSave(): void;
  undo(): void;
  redo(): void;
  findAndReplace(search: string, replacement: string): number;
  applyTheme(tokens: Record<string, string>): void;
  showDecorations(items: Array<{ from: number; to: number; label: string }>): void;
  clearDecorations(): void;
  setReadOnly(reason: string): void;
  revealRange(from: number, to: number): void;
  setBaseRevision(revision: number): void;
  getSelectionText(): string;
}

const decorationsKey = new PluginKey<DecorationSet>("auditDecorations");

function createEditorState(doc: Node): EditorState {
  return EditorState.create({
    schema: NOVEL_SCHEMA,
    doc,
    plugins: [
      history(),
      decoratePlugin(),
      keymap({
        ...baseKeymap,
        "Mod-z": () => {
          const view = thisRef.view;
          return view ? undo(view.state, view.dispatch) : false;
        },
        "Mod-y": () => {
          const view = thisRef.view;
          return view ? redo(view.state, view.dispatch) : false;
        },
        "Mod-Shift-z": () => {
          const view = thisRef.view;
          return view ? redo(view.state, view.dispatch) : false;
        },
      }),
    ],
  });
}

// The keymap handlers are evaluated lazily at dispatch time; a module-level
// holder lets them reference the live view without circular construction.
const thisRef: { view: EditorView | null } = { view: null };

export function decoratePlugin(): Plugin<DecorationSet> {
  return new Plugin<DecorationSet>({
    key: decorationsKey,
    state: {
      init: () => DecorationSet.empty,
      apply: (tr, set) => set.map(tr.mapping, tr.doc),
    },
    props: {
      decorations(state) {
        return decorationsKey.getState(state) ?? DecorationSet.empty;
      },
    },
  });
}

export class NovelEditor {
  private view: EditorView;
  private saveController: DebouncedSaveController;
  private chapterId = "";
  private baseRevision = 0;
  private exactMarkdown = "";
  private savedDoc: Node;
  private readonly onSave: (payload: SnapshotPayload) => void;
  private readonly onWordCount: ((count: number) => void) | null;
  private readonly onSelectionReference:
    | ((from: number, to: number) => void)
    | null;
  private lastSelectionFrom = -1;
  private lastSelectionTo = -1;

  constructor(
    mount: HTMLElement,
    onSave: (payload: SnapshotPayload) => void,
    onWordCount: ((count: number) => void) | null = null,
    onSelectionReference: ((from: number, to: number) => void) | null = null,
    initial: LoadDocumentPayload | null = null,
  ) {
    this.onSave = onSave;
    this.onWordCount = onWordCount;
    this.onSelectionReference = onSelectionReference;
    this.saveController = new DebouncedSaveController({
      onSave: (payload) => this.onSave(payload),
    });
    let state: EditorState;
    if (initial) {
      this.chapterId = initial.chapterId;
      this.baseRevision = initial.baseRevision;
      this.exactMarkdown = initial.markdown;
      state = createEditorState(markdownCodec.parse(initial.markdown));
    } else {
      state = createEditorState(markdownCodec.parse(""));
    }
    this.savedDoc = state.doc;
    this.view = new EditorView(mount, {
      state: state,
      handleDOMEvents: {
        beforeinput: () => false,
      },
      dispatchTransaction: (transaction) => {
        const next = this.view.state.apply(transaction);
        this.view.updateState(next);
        if (transaction.docChanged) {
          this.scheduleSave();
        }
        this.reportWordCount();
        this.reportSelection(transaction.docChanged);
      },
    });
    thisRef.view = this.view;
    this.view.dom.setAttribute("data-editor", "novel");
  }

  private scheduleSave(): void {
    this.saveController.noteEdit(
      createSnapshot(this.view.state, this.chapterId, this.baseRevision),
    );
  }

  reportWordCount(): void {
    if (this.onWordCount) {
      this.onWordCount(countWords(this.view.state.doc.textBetween(0, this.view.state.doc.content.size, "\n", "")));
    }
  }

  private reportSelection(force = false): void {
    const { from, to } = this.view.state.selection;
    if (!force && from === this.lastSelectionFrom && to === this.lastSelectionTo) {
      return;
    }
    this.lastSelectionFrom = from;
    this.lastSelectionTo = to;
    if (this.onSelectionReference) {
      this.onSelectionReference(from, to);
    }
  }

  loadDocument(payload: LoadDocumentPayload): DocumentLoadResult {
    // Parse first: a deterministic failure must leave the previous chapter's
    // editor state completely untouched ("new title + old body" is forbidden)
    // and must never schedule a save (2026-08-26 ticket).
    const outcome = parseDocument(payload.markdown);
    if (outcome.doc === null) {
      return {
        status: outcome.status,
        chapterId: payload.chapterId,
        revision: payload.baseRevision,
        wordCount: 0,
      };
    }
    this.chapterId = payload.chapterId;
    this.baseRevision = payload.baseRevision;
    this.exactMarkdown = payload.markdown;
    this.lastSelectionFrom = -1;
    this.lastSelectionTo = -1;
    this.view.updateState(createEditorState(outcome.doc));
    this.savedDoc = outcome.doc;
    this.reportSelection();
    this.reportWordCount();
    this.saveController.flush(
      createSnapshot(this.view.state, this.chapterId, this.baseRevision),
    );
    return {
      status: "LOADED",
      chapterId: payload.chapterId,
      revision: payload.baseRevision,
      wordCount: countWords(
        outcome.doc.textBetween(0, outcome.doc.content.size, "\n", ""),
      ),
    };
  }

  requestSave(): void {
    this.saveController.flush(
      createSnapshot(this.view.state, this.chapterId, this.baseRevision),
    );
  }

  undo(): void {
    undo(this.view.state, this.view.dispatch);
  }

  redo(): void {
    redo(this.view.state, this.view.dispatch);
  }

  findAndReplace(search: string, replacement: string): number {
    const result = replaceAll(this.view.state, search, replacement);
    this.view.updateState(result.state);
    return result.count;
  }

  applyTheme(tokens: Record<string, string>): void {
    // Theme variables must reach the page root and the mount so that the
    // html/body background and scrollbar tracks repaint with the editor
    // instead of flashing the previous (or default black) canvas.
    const root = document.documentElement;
    const mountEl = document.getElementById("editor-mount");
    for (const [key, value] of Object.entries(tokens)) {
      root.style.setProperty(key, value);
      if (mountEl) {
        mountEl.style.setProperty(key, value);
      }
      this.view.dom.style.setProperty(key, value);
    }
  }

  showDecorations(
    items: Array<{ from: number; to: number; label: string }>,
  ): void {
    const decorations = items.map((item) =>
      Decoration.inline(item.from, item.to, {
        class: "novel-audit-decoration",
        "data-label": item.label,
      }),
    );
    const set = DecorationSet.create(this.view.state.doc, decorations);
    this.view.dispatch(
      this.view.state.tr.setMeta(decorationsKey, set),
    );
  }

  clearDecorations(): void {
    this.view.dispatch(
      this.view.state.tr.setMeta(decorationsKey, DecorationSet.empty),
    );
  }

  setReadOnly(reason: string): void {
    this.view.dom.setAttribute("aria-readonly", "true");
    this.view.dom.title = reason;
  }

  revealRange(from: number, to: number): void {
    const { state } = this.view;
    const { doc } = state;
    const fromPos = Math.max(0, Math.min(from, doc.content.size));
    const toPos = Math.max(fromPos, Math.min(to, doc.content.size));
    this.view.dispatch(
      state.tr.setSelection(TextSelection.create(doc, fromPos, toPos)),
    );
    this.view.focus();
    this.view.dom.scrollIntoView({ block: "center" });
  }

  setBaseRevision(revision: number): void {
    this.baseRevision = revision;
    this.exactMarkdown = stateToMarkdown(this.view.state);
    this.savedDoc = this.view.state.doc;
    this.lastSelectionFrom = -1;
    this.lastSelectionTo = -1;
    this.reportSelection();
  }

  getSelectionText(): string {
    const { from, to } = this.view.state.selection;
    return selectionText(this.view.state, from, to);
  }

  /** Read-only chat context does not grant authority to replace Markdown spans. */
  getChatSelectionContext() {
    return {
      chapter_id: this.chapterId,
      base_revision: this.baseRevision,
      content: this.view.state.doc.eq(this.savedDoc)
        ? this.exactMarkdown : stateToMarkdown(this.view.state),
      selection: this.getSelectionText(),
    };
  }

  getSelectionPatchCapture(
    from: number,
    to: number,
  ): SelectionPatchCapturePayload | null {
    return buildSelectionPatchCapture(
      this.view.state,
      this.chapterId,
      this.baseRevision,
      this.exactMarkdown,
      from,
      to,
    );
  }

  getMarkdown(): string {
    return stateToMarkdown(this.view.state);
  }

  getChapterId(): string {
    return this.chapterId;
  }

  getBaseRevision(): number {
    return this.baseRevision;
  }

  destroy(): void {
    this.saveController.destroy();
    this.view.destroy();
  }
}

export function boot(
  mount: HTMLElement,
  onSave: (payload: SnapshotPayload) => void,
  onWordCount: ((count: number) => void) | null = null,
  initial: LoadDocumentPayload | null = null,
): NovelEditorBridge {
  let pythonBridge: {
    saveRequested(
      chapterId: string,
      baseRevision: number,
      markdown: string,
      contentHash: string,
    ): void;
    wordCountChanged(count: number): void;
    selectionReferenceChanged(payloadJson: string): void;
    chatSelectionChanged(payloadJson: string): void;
  } | null = null;
  const editor = new NovelEditor(
    mount,
    (payload) => {
      if (pythonBridge) {
        pythonBridge.saveRequested(
          payload.chapterId,
          payload.baseRevision,
          payload.markdown,
          payload.contentHash,
        );
      } else {
        onSave(payload);
      }
    },
    (count) => {
      if (pythonBridge) {
        pythonBridge.wordCountChanged(count);
      } else if (onWordCount) {
        onWordCount(count);
      }
    },
    (from, to) => {
      const payload = editor.getSelectionPatchCapture(from, to);
      const json = payload === null ? "" : JSON.stringify(payload);
      if (pythonBridge) {
        pythonBridge.selectionReferenceChanged(json);
        pythonBridge.chatSelectionChanged(JSON.stringify(editor.getChatSelectionContext()));
      }
    },
    initial,
  );
  const bridge: NovelEditorBridge = {
    loadDocument: (payload) => editor.loadDocument(payload),
    requestSave: () => editor.requestSave(),
    undo: () => editor.undo(),
    redo: () => editor.redo(),
    findAndReplace: (search, replacement) =>
      editor.findAndReplace(search, replacement),
    applyTheme: (tokens) => editor.applyTheme(tokens),
    showDecorations: (items) => editor.showDecorations(items),
    clearDecorations: () => editor.clearDecorations(),
    setReadOnly: (reason) => editor.setReadOnly(reason),
    revealRange: (from, to) => editor.revealRange(from, to),
    setBaseRevision: (revision) => editor.setBaseRevision(revision),
    getSelectionText: () => editor.getSelectionText(),
  };
  window.__novelEditor = bridge;
  if (window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, (channel) => {
      const python = channel.objects.pythonBridge;
      if (!python) {
        return;
      }
      pythonBridge = python;
      editor.reportWordCount();
      python.editorReady(1, JSON.stringify(["markdown-v1", "selection-v1", "decorations-v1"]));
    });
  }
  return bridge;
}

export { markdownCodec, NOVEL_SCHEMA, Node };

// Auto-boot the editor on page load. In the plain-browser prototype the save
// payload is logged; the QML host replaces this via the WebChannel bridge.
if (typeof document !== "undefined") {
  const mount = document.getElementById("editor-mount");
  if (mount) {
    boot(mount, (payload) => {
      console.log("[editor] save-requested", payload);
    }, (count) => {
      console.log("[editor] word-count", count);
    });
  }
}
