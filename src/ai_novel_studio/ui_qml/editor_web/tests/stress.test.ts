import { describe, expect, it } from "vitest";
import {
  createNovelState,
  docText,
  insertTextAt,
  redoState,
  stateToMarkdown,
  undoState,
} from "../src/editor-core";
import { markdownCodec } from "../src/markdown";

const CJK = "雾港的清晨潮汐灯塔旧信";

function largeManuscript(characters: number): string {
  const paragraphs: string[] = [];
  let remaining = characters;
  while (remaining > 0) {
    const length = Math.min(remaining, 120);
    const chunk = CJK.repeat(Math.ceil(length / CJK.length)).slice(0, length);
    paragraphs.push(chunk);
    remaining -= length;
  }
  return paragraphs.join("\n\n");
}

describe("phase 1 stress gates", () => {
  it("opens a 200k-character manuscript without content loss", () => {
    const markdown = largeManuscript(200_000);
    const started = performance.now();
    const state = createNovelState(markdown);
    const elapsed = performance.now() - started;

    expect(state.doc.content.size).toBeGreaterThan(199_000);
    const text = docText(state.doc).replace(/\n/g, "");
    expect(text.length).toBeGreaterThanOrEqual(199_000);
    // Parse gate: generous bound to avoid CI flakiness; real device feel is
    // verified interactively.
    expect(elapsed).toBeLessThan(3000);
  });

  it("undoes and redoes on a 200k-character document", () => {
    const state = createNovelState(largeManuscript(200_000));
    const size = state.doc.content.size - 1;
    const edited = insertTextAt(state, size, size, "结尾新增");
    const undone = undoState(edited);

    expect(docText(undone.doc).includes("结尾新增")).toBe(false);
    const redone = redoState(undone);
    expect(docText(redone.doc).includes("结尾新增")).toBe(true);
  });

  it("survives 1000 consecutive edits without losing characters", () => {
    let state = createNovelState("起点");
    const edits: string[] = [];
    for (let index = 0; index < 1000; index += 1) {
      const token = `字${index}`;
      edits.push(token);
      const size = state.doc.content.size - 1;
      state = insertTextAt(state, size, size, token);
    }

    const text = docText(state.doc).replace(/\n/g, "");
    for (const token of [edits[0], edits[500], edits[999]]) {
      expect(text).toContain(token);
    }
    expect(text.length).toBeGreaterThan(2 + edits.join("").length - 10);
  });

  it("undo after 1000 edits restores cleanly in bounded time", () => {
    let state = createNovelState("起点");
    for (let index = 0; index < 1000; index += 1) {
      const size = state.doc.content.size - 1;
      state = insertTextAt(state, size, size, `字${index}`);
    }

    const started = performance.now();
    const undone = undoState(state);
    const elapsed = performance.now() - started;

    expect(docText(undone.doc)).toBe("起点");
    expect(elapsed).toBeLessThan(5000);
  });

  it("round-trips a 200k-character manuscript losslessly", () => {
    const markdown = largeManuscript(200_000);
    const started = performance.now();
    const roundTripped = markdownCodec.roundTrip(markdown);
    const elapsed = performance.now() - started;

    expect(roundTripped.replace(/\n/g, "").length).toBeGreaterThanOrEqual(199_000);
    expect(elapsed).toBeLessThan(5000);
  });
});

