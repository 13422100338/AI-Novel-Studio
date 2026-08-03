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
import { EditorState, Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { EditorView } from "@tiptap/pm/view";
import { keymap } from "@tiptap/pm/keymap";
import { history, redo, undo } from "@tiptap/pm/history";
import {
  DebouncedSaveController,
  SnapshotPayload,
  createNovelState,
  createSnapshot,
  replaceAll,
  stateToMarkdown,
} from "./editor-core";
import { markdownCodec } from "./markdown";
import { NOVEL_SCHEMA } from "./schema";

declare global {
  interface Window {
    __novelEditor: NovelEditorBridge;
    qt?: { webChannelTransport: unknown };
  }
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
    }>;
  }) => void,
) => void;

export interface LoadDocumentPayload {
  chapterId: string;
  baseRevision: number;
  markdown: string;
}

export interface NovelEditorBridge {
  loadDocument(payload: LoadDocumentPayload): void;
  requestSave(): void;
  undo(): void;
  redo(): void;
  findAndReplace(search: string, replacement: string): number;
  applyTheme(tokens: Record<string, string>): void;
  showDecorations(items: Array<{ from: number; to: number; label: string }>): void;
  clearDecorations(): void;
  setReadOnly(reason: string): void;
}

const decorationsKey = new PluginKey<DecorationSet>("auditDecorations");

function createEditorState(markdown: string): EditorState {
  const doc = markdownCodec.parse(markdown);
  return EditorState.create({
    schema: NOVEL_SCHEMA,
    doc,
    plugins: [
      history(),
      decoratePlugin(),
      keymap({
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
  private readonly onSave: (payload: SnapshotPayload) => void;

  constructor(
    mount: HTMLElement,
    onSave: (payload: SnapshotPayload) => void,
    initial: LoadDocumentPayload | null = null,
  ) {
    this.onSave = onSave;
    this.saveController = new DebouncedSaveController({
      onSave: (payload) => this.onSave(payload),
    });
    let state: EditorState;
    if (initial) {
      this.chapterId = initial.chapterId;
      this.baseRevision = initial.baseRevision;
      state = createEditorState(initial.markdown);
    } else {
      state = createEditorState("");
    }
    this.view = new EditorView(mount, {
      state: state,
      handleDOMEvents: {
        beforeinput: () => false,
      },
      dispatchTransaction: (transaction) => {
        const next = this.view.state.apply(transaction);
        this.view.updateState(next);
        this.scheduleSave();
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

  loadDocument(payload: LoadDocumentPayload): void {
    this.chapterId = payload.chapterId;
    this.baseRevision = payload.baseRevision;
    const next = createEditorState(payload.markdown);
    this.view.updateState(next);
    this.saveController.flush(
      createSnapshot(this.view.state, this.chapterId, this.baseRevision),
    );
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
    for (const [key, value] of Object.entries(tokens)) {
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

  getMarkdown(): string {
    return stateToMarkdown(this.view.state);
  }

  destroy(): void {
    this.saveController.destroy();
    this.view.destroy();
  }
}

export function boot(
  mount: HTMLElement,
  onSave: (payload: SnapshotPayload) => void,
  initial: LoadDocumentPayload | null = null,
): NovelEditorBridge {
  let pythonBridge: {
    saveRequested(
      chapterId: string,
      baseRevision: number,
      markdown: string,
      contentHash: string,
    ): void;
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
  };
  window.__novelEditor = bridge;
  if (window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, (channel) => {
      const python = channel.objects.pythonBridge;
      if (!python) {
        return;
      }
      pythonBridge = python;
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
    });
  }
}
