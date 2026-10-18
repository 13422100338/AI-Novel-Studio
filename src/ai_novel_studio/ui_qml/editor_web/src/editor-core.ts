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

export function countWords(text: string): number {
  const cjk = text.match(/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g);
  const latin = text.match(/[A-Za-z0-9]+/g);
  return (cjk?.length ?? 0) + (latin?.length ?? 0);
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

const SHA256_CONSTANTS = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

/** Synchronous lowercase SHA-256 of the exact UTF-8 bytes. */
export function sha256Hex(text: string): string {
  const input = new TextEncoder().encode(text);
  const paddedLength = Math.ceil((input.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(input);
  padded[input.length] = 0x80;
  const view = new DataView(padded.buffer);
  const bitLength = input.length * 8;
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x1_0000_0000));
  view.setUint32(paddedLength - 4, bitLength >>> 0);
  const hash = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const words = new Uint32Array(64);
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4);
    }
    for (let index = 16; index < 64; index += 1) {
      const left = words[index - 15];
      const right = words[index - 2];
      const sigma0 =
        rotateRight(left, 7) ^ rotateRight(left, 18) ^ (left >>> 3);
      const sigma1 =
        rotateRight(right, 17) ^ rotateRight(right, 19) ^ (right >>> 10);
      words[index] =
        (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = hash;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 =
        (h + sum1 + choice + SHA256_CONSTANTS[index] + words[index]) >>> 0;
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }
  return Array.from(hash, (word) => word.toString(16).padStart(8, "0")).join("");
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
  private _savedCount = 0;
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
    this._savedCount += 1;
    this.observer.onSave(snapshot);
  }

  get savedCount(): number {
    return this._savedCount;
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
 * Text of a selection with block boundaries preserved as newlines.
 *
 * ProseMirror's plain `textBetween(from, to, "", "")` concatenates paragraphs,
 * so a cross-paragraph selection loses its structure. Using "\n" as the block
 * separator keeps the quoted reference (and its hash) faithful to the editor.
 */
export function selectionText(
  state: EditorState,
  from: number,
  to: number,
): string {
  return from === to ? "" : state.doc.textBetween(from, to, "\n", "\n");
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

export interface SelectionPatchSpanPayload {
  start: number;
  end: number;
  text: string;
  text_hash: string;
}

export interface SelectionPatchCapturePayload {
  schema_version: "selection-patch-v1";
  chapter_id: string;
  base_revision: number;
  base_source_hash: string;
  selection: SelectionPatchSpanPayload;
  before_anchor: SelectionPatchSpanPayload;
  after_anchor: SelectionPatchSpanPayload;
}

export const MAX_SELECTION_CODEPOINTS = 20_000;
export const SELECTION_ANCHOR_CODEPOINTS = 64;
const SELECTION_START_MARKER = "\ufdd0";
const SELECTION_END_MARKER = "\ufdd1";

function canonicalToExactBoundaries(
  canonical: string,
  exact: string,
): number[] | null {
  const canonicalPoints = Array.from(canonical);
  const exactPoints = Array.from(exact);
  const boundaries: number[] = [0];
  let canonicalIndex = 0;
  let exactIndex = 0;
  while (canonicalIndex < canonicalPoints.length) {
    const canonicalPoint = canonicalPoints[canonicalIndex];
    if (
      canonicalPoint === "\n" &&
      (exactPoints[exactIndex] === "\n" ||
        (exactPoints[exactIndex] === "\r" &&
          exactPoints[exactIndex + 1] === "\n"))
    ) {
      let canonicalEnd = canonicalIndex;
      while (canonicalPoints[canonicalEnd] === "\n") canonicalEnd += 1;
      let exactEnd = exactIndex;
      while (exactEnd < exactPoints.length) {
        if (exactPoints[exactEnd] === "\n") {
          exactEnd += 1;
          continue;
        }
        if (
          exactPoints[exactEnd] === "\r" &&
          exactPoints[exactEnd + 1] === "\n"
        ) {
          exactEnd += 2;
          continue;
        }
        break;
      }
      for (
        let boundary = canonicalIndex + 1;
        boundary < canonicalEnd;
        boundary += 1
      ) {
        boundaries[boundary] = -1;
      }
      boundaries[canonicalEnd] = exactEnd;
      canonicalIndex = canonicalEnd;
      exactIndex = exactEnd;
      continue;
    }
    if (canonicalPoint === exactPoints[exactIndex]) {
      canonicalIndex += 1;
      exactIndex += 1;
      boundaries[canonicalIndex] = exactIndex;
      continue;
    }
    if (
      canonicalPoint === "\n" &&
      canonicalIndex === canonicalPoints.length - 1 &&
      exactIndex === exactPoints.length
    ) {
      canonicalIndex += 1;
      boundaries[canonicalIndex] = exactIndex;
      continue;
    }
    return null;
  }
  const trailing = exactPoints.slice(exactIndex);
  if (
    trailing.length === 0 ||
    (trailing.length === 1 && trailing[0] === "\n") ||
    (trailing.length === 2 && trailing[0] === "\r" && trailing[1] === "\n")
  ) {
    return boundaries;
  }
  return null;
}

function spanPayload(
  sourcePoints: string[],
  start: number,
  end: number,
): SelectionPatchSpanPayload {
  const text = sourcePoints.slice(start, end).join("");
  return { start, end, text, text_hash: sha256Hex(text) };
}

/**
 * Convert one ProseMirror selection to exact loaded-Markdown code-point ranges.
 *
 * Boundary markers travel through the one authoritative serializer. Removing
 * them must reproduce the editor Markdown exactly; that canonical output must
 * then map to the loaded source with only CRLF and the serializer's terminal
 * newline equivalence. Any other normalization fails closed.
 */
export function buildSelectionPatchCapture(
  state: EditorState,
  chapterId: string,
  baseRevision: number,
  exactMarkdown: string,
  from: number,
  to: number,
): SelectionPatchCapturePayload | null {
  if (
    !chapterId ||
    baseRevision < 0 ||
    from < 0 ||
    to <= from ||
    to > state.doc.content.size
  ) {
    return null;
  }
  if (
    exactMarkdown.includes(SELECTION_START_MARKER) ||
    exactMarkdown.includes(SELECTION_END_MARKER)
  ) {
    return null;
  }
  const markedState = state.apply(
    state.tr
      .insertText(SELECTION_END_MARKER, to)
      .insertText(SELECTION_START_MARKER, from),
  );
  const marked = stateToMarkdown(markedState);
  if (
    marked.indexOf(SELECTION_START_MARKER) < 0 ||
    marked.indexOf(SELECTION_END_MARKER) < 0 ||
    marked.indexOf(SELECTION_START_MARKER) !==
      marked.lastIndexOf(SELECTION_START_MARKER) ||
    marked.indexOf(SELECTION_END_MARKER) !==
      marked.lastIndexOf(SELECTION_END_MARKER)
  ) {
    return null;
  }
  const markedPoints = Array.from(marked);
  const startMarker = markedPoints.indexOf(SELECTION_START_MARKER);
  const endMarker = markedPoints.indexOf(SELECTION_END_MARKER);
  if (startMarker < 0 || endMarker <= startMarker) {
    return null;
  }
  const canonical = markedPoints
    .filter(
      (point) =>
        point !== SELECTION_START_MARKER && point !== SELECTION_END_MARKER,
    )
    .join("");
  if (canonical !== stateToMarkdown(state)) {
    return null;
  }
  const boundaries = canonicalToExactBoundaries(canonical, exactMarkdown);
  if (boundaries === null) {
    return null;
  }
  const canonicalStart = startMarker;
  const canonicalEnd = endMarker - 1;
  const start = boundaries[canonicalStart];
  const end = boundaries[canonicalEnd];
  if (
    start === undefined ||
    end === undefined ||
    start < 0 ||
    end < 0 ||
    end <= start
  ) {
    return null;
  }
  const sourcePoints = Array.from(exactMarkdown);
  if (end - start > MAX_SELECTION_CODEPOINTS) {
    return null;
  }
  const beforeStart = Math.max(0, start - SELECTION_ANCHOR_CODEPOINTS);
  const afterEnd = Math.min(
    sourcePoints.length,
    end + SELECTION_ANCHOR_CODEPOINTS,
  );
  return {
    schema_version: "selection-patch-v1",
    chapter_id: chapterId,
    base_revision: baseRevision,
    base_source_hash: sha256Hex(exactMarkdown),
    selection: spanPayload(sourcePoints, start, end),
    before_anchor: spanPayload(sourcePoints, beforeStart, start),
    after_anchor: spanPayload(sourcePoints, end, afterEnd),
  };
}

export function createDecorationsKey(): PluginKey {
  return new PluginKey("phase1Decorations");
}

export function decorationsPlugin(): Plugin {
  return new Plugin({ key: createDecorationsKey() });
}
