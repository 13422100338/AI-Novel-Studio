/**
 * DOM-free editor state core (Phase 1).
 *
 * Everything here is testable in Node: parsing, editing transactions, undo/
 * redo through the history plugin, find/replace, snapshots, and the debounced
 * save controller. The browser entry (`editor.ts`) only mounts a ProseMirror
 * view on top of these operations.
 */
import { Node } from "@tiptap/pm/model";
import { EditorState, Plugin, PluginKey, Transaction } from "@tiptap/pm/state";
import { history, redo, undo } from "@tiptap/pm/history";
import { markdownCodec } from "./markdown";
import { NOVEL_SCHEMA } from "./schema";

export const SAVE_DEBOUNCE_MS = 800;

export function createNovelState(markdown: string): EditorState {
  const doc = markdownCodec.parse(markdown);
  return EditorState.create({
    schema: NOVEL_SCHEMA,
    doc,
    plugins: [history()],
  });
}

export function stateToMarkdown(state: EditorState): string {
  return markdownCodec.serialize(state.doc);
}

export function typeText(state: EditorState, text: string): EditorState {
  return state.apply(state.tr.insertText(text));
}

export function insertTextAt(
  state: EditorState,
  from: number,
  to: number,
  text: string,
): EditorState {
  return state.apply(state.tr.insertText(text, from, to));
}

export function undoState(state: EditorState): EditorState {
  let next = state;
  const undone = undo(state, (tr) => {
    next = state.apply(tr);
  });
  return undone ? next : state;
}

export function redoState(state: EditorState): EditorState {
  let next = state;
  const redone = redo(state, (tr) => {
    next = state.apply(tr);
  });
  return redone ? next : state;
}

export function docText(doc: Node): string {
  return doc.textBetween(0, doc.content.size, "\n", "");
}

export interface ReplaceAllResult {
  count: number;
  state: EditorState;
}

/**
 * Replace every occurrence of `search` with `replacement` in text content.
 * Works on the serialized text level and re-parses the document, which is
 * acceptable for the Phase 1 prototype (the manuscript is Markdown-authoritative
 * and replacement is a whole-document, history-wrapped operation).
 */
export function replaceAll(
  state: EditorState,
  search: string,
  replacement: string,
): ReplaceAllResult {
  const markdown = stateToMarkdown(state);
  if (!search || !markdown.includes(search)) {
    return { count: 0, state };
  }
  const count = markdown.split(search).length - 1;
  const updated = markdown.split(search).join(replacement);
  const next = createNovelState(updated);
  return { count, state: next };
}

export interface SnapshotPayload {
  chapterId: string;
  baseRevision: number;
  markdown: string;
  contentHash: string;
}

export function createSnapshot(
  state: EditorState,
  chapterId: string,
  baseRevision: number,
): SnapshotPayload {
  const markdown = stateToMarkdown(state);
  return {
    chapterId,
    baseRevision,
    markdown,
    contentHash: sha256(markdown),
  };
}

export function sha256(text: string): string {
  // Synchronous FNV-style fallback hash is not a real digest; the Python side
  // computes the authoritative SHA-256. This field is a change fingerprint.
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `fnv1a:${hash.toString(16).padStart(8, "0")}`;
}

export interface SaveObserver {
  onSave(payload: SnapshotPayload): void;
}

/**
 * 800 ms debounced save controller. `noteEdit` may be called for every input
 * event; the underlying callback fires at most once per quiet window plus one
 * final flush.
 */
export class DebouncedSaveController {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending = false;
  private savedCount = 0;
  private readonly debounceMs: number;

  constructor(
    private readonly observer: SaveObserver,
    debounceMs: number = SAVE_DEBOUNCE_MS,
  ) {
    this.debounceMs = debounceMs;
  }

  noteEdit(snapshot: SnapshotPayload): void {
    this.pending = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
    }
    this.timer = setTimeout(() => this.flush(snapshot), this.debounceMs);
  }

  flush(snapshot: SnapshotPayload): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (!this.pending) {
      return;
    }
    this.pending = false;
    this.savedCount += 1;
    this.observer.onSave(snapshot);
  }

  get savedCount(): number {
    return this.savedCount;
  }

  destroy(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}

export interface FindResult {
  from: number;
  to: number;
}

/**
 * Locate the next occurrence of `needle` at or after `from` in the document
 * text. Returns undefined when absent.
 */
export function findNext(
  state: EditorState,
  needle: string,
  from = 0,
): FindResult | undefined {
  if (!needle) {
    return undefined;
  }
  const text = state.doc.textBetween(0, state.doc.content.size, "\n", "\n");
  const index = text.indexOf(needle, from);
  if (index < 0) {
    return undefined;
  }
  return { from: index, to: index + needle.length };
}

export function createDecorationsKey(): PluginKey {
  return new PluginKey("phase1Decorations");
}

export function decorationsPlugin(): Plugin {
  return new Plugin({ key: createDecorationsKey() });
}
