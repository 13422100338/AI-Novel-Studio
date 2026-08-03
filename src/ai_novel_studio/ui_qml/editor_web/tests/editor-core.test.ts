import { describe, expect, it, vi } from "vitest";
import {
  DebouncedSaveController,
  createNovelState,
  createSnapshot,
  docText,
  findNext,
  insertTextAt,
  redoState,
  replaceAll,
  stateToMarkdown,
  typeText,
  undoState,
} from "../src/editor-core";

describe("editing core", () => {
  it("parses and serializes without content loss", () => {
    const markdown = "# 第一章\n\n清晨的雾港。\n\n---\n\n第二段 *斜体*";
    const state = createNovelState(markdown);
    expect(stateToMarkdown(state)).toContain("清晨的雾港");
  });

  it("types CJK text without losing characters", () => {
    let state = createNovelState("正文");
    for (const chunk of ["雾港", "的", "清晨", "潮汐"]) {
      const size = state.doc.content.size - 1;
      state = insertTextAt(state, size, size, chunk);
    }
    const text = docText(state.doc);
    expect(text).toContain("正文雾港的清晨潮汐");
  });

  it("undo and redo restore the previous combined step", () => {
    const initial = "起点";
    const first = "，第一处修改";
    const second = "，第二处修改";
    let state = createNovelState(initial);
    state = typeText(state, first);
    state = typeText(state, second);
    const afterSecond = docText(state.doc);

    // Consecutive text insertions merge into one history step (ProseMirror
    // default), so a single undo restores the pre-edit document.
    const undone = undoState(state);
    expect(docText(undone.doc)).toBe(initial);

    const redone = redoState(undone);
    expect(docText(redone.doc)).toBe(afterSecond);
  });

  it("replaceAll replaces every occurrence", () => {
    const state = createNovelState("灯塔灯塔\n\n灯塔");
    const result = replaceAll(state, "灯塔", "钟楼");
    expect(result.count).toBe(3);
    expect(docText(result.state.doc).split("钟楼")).toHaveLength(4);
  });

  it("replaceAll with absent needle changes nothing", () => {
    const state = createNovelState("正文");
    const result = replaceAll(state, "不存在", "x");
    expect(result.count).toBe(0);
    expect(result.state).toBe(state);
  });

  it("findNext locates occurrences from a position", () => {
    const state = createNovelState("雾港灯塔\n\n雾港钟楼");
    const first = findNext(state, "雾港");
    expect(first?.from).toBe(0);
    const second = findNext(state, "雾港", (first?.to ?? 0) + 1);
    expect(second?.from).toBeGreaterThan(first?.from ?? 0);
    expect(findNext(state, "不存在")).toBeUndefined();
  });

  it("snapshot carries stable fingerprint and markdown", () => {
    const state = createNovelState("# 标题\n\n正文");
    const snapshot = createSnapshot(state, "chapter-1", 3);
    expect(snapshot.chapterId).toBe("chapter-1");
    expect(snapshot.baseRevision).toBe(3);
    expect(snapshot.markdown).toContain("# 标题");
    expect(snapshot.contentHash).toMatch(/^fnv1a:/);
  });
});

describe("debounced save controller", () => {
  it("fires at most once per quiet window", async () => {
    vi.useFakeTimers();
    const observer = vi.fn();
    const controller = new DebouncedSaveController(
      { onSave: observer },
      100,
    );
    const snapshot = createSnapshot(createNovelState("正文"), "c1", 1);

    for (let index = 0; index < 50; index += 1) {
      controller.noteEdit(snapshot);
      vi.advanceTimersByTime(10);
    }

    expect(observer).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(observer).toHaveBeenCalledTimes(1);
    controller.destroy();
    vi.useRealTimers();
  });

  it("flush forces an immediate save", () => {
    vi.useFakeTimers();
    const observer = vi.fn();
    const controller = new DebouncedSaveController(
      { onSave: observer },
      100,
    );
    const snapshot = createSnapshot(createNovelState("正文"), "c1", 1);

    controller.noteEdit(snapshot);
    controller.flush(snapshot);

    expect(observer).toHaveBeenCalledTimes(1);
    controller.destroy();
    vi.useRealTimers();
  });
});
