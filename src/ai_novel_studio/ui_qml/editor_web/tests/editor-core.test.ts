// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";
import { splitBlock } from "@tiptap/pm/commands";
import { TextSelection, Transaction } from "@tiptap/pm/state";
import { EditorView } from "@tiptap/pm/view";
import {
  buildSelectionPatchCapture,
  DebouncedSaveController,
  createNovelState,
  createSnapshot,
  docText,
  findNext,
  insertTextAt,
  redoState,
  replaceAll,
  selectionText,
  sha256Hex,
  stateToMarkdown,
  typeText,
  undoState,
} from "../src/editor-core";
import { NovelEditor } from "../src/editor";

function textPosition(
  state: ReturnType<typeof createNovelState>,
  needle: string,
  occurrence = 0,
  atEnd = false,
): number {
  let seen = 0;
  let result = -1;
  state.doc.descendants((node, pos) => {
    const text = node.text;
    if (!node.isText || text === null || text === undefined || result >= 0) {
      return true;
    }
    let offset = text.indexOf(needle);
    while (offset >= 0) {
      if (seen === occurrence) {
        result = pos + offset + (atEnd ? needle.length : 0);
        return false;
      }
      seen += 1;
      offset = text.indexOf(needle, offset + needle.length);
    }
    return true;
  });
  if (result < 0) throw new Error(`missing fixture text: ${needle}`);
  return result;
}

function codePointOffset(source: string, utf16Offset: number): number {
  return Array.from(source.slice(0, utf16Offset)).length;
}

describe("enter / shift-enter editing commands", () => {
  it("splitBlock splits the paragraph at the cursor (Enter)", () => {
    const state = createNovelState("第一段内容");
    const end = state.doc.content.size - 1;
    const withCursor = state.apply(
      state.tr.setSelection(TextSelection.create(state.doc, end, end)),
    );
    let transaction: Transaction | null = null;

    const handled = splitBlock(withCursor, (tr) => {
      transaction = tr;
    });

    expect(handled).toBe(true);
    expect(transaction).not.toBeNull();
    const after = withCursor.apply(transaction!);
    expect(docText(after.doc)).toContain("第一段内容\n");
  });

  it("hard_break node exists in the schema (Shift+Enter target)", () => {
    const state = createNovelState("行一\n行二");
    let found = false;
    state.doc.descendants((node) => {
      if (node.type.name === "hard_break") {
        found = true;
      }
      return true;
    });
    expect(found).toBe(true);
    expect(stateToMarkdown(state)).toContain("行一\n行二");
  });
});

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

describe("selection patch capture (H-SEL1)", () => {
  it("does not save a selection-only transaction but still saves document edits", () => {
    vi.useFakeTimers();
    const saveObserver = vi.fn();
    const editor = new NovelEditor(
      document.createElement("div"),
      saveObserver,
      null,
      vi.fn(),
      { chapterId: "c1", baseRevision: 3, markdown: "第一段。\n" },
    );
    const view = (editor as unknown as { view: EditorView }).view;

    view.dispatch(
      view.state.tr.setSelection(TextSelection.create(view.state.doc, 1, 3)),
    );
    vi.advanceTimersByTime(800);
    expect(saveObserver).not.toHaveBeenCalled();

    view.dispatch(view.state.tr.insertText("新"));
    vi.advanceTimersByTime(800);
    expect(saveObserver).toHaveBeenCalledTimes(1);

    editor.destroy();
    vi.useRealTimers();
  });

  it("reissues the current selection capture after the saved revision changes", () => {
    vi.useFakeTimers();
    const captures: Array<ReturnType<NovelEditor["getSelectionPatchCapture"]>> = [];
    let editor!: NovelEditor;
    editor = new NovelEditor(
      document.createElement("div"),
      vi.fn(),
      null,
      (from, to) => captures.push(editor.getSelectionPatchCapture(from, to)),
      { chapterId: "c1", baseRevision: 3, markdown: "第一段。\n" },
    );
    const view = (editor as unknown as { view: EditorView }).view;
    view.dispatch(
      view.state.tr.setSelection(TextSelection.create(view.state.doc, 1, 3)),
    );
    expect(captures.at(-1)?.base_revision).toBe(3);

    view.dispatch(view.state.tr.insertText("新", view.state.doc.content.size - 1));
    captures.length = 0;
    editor.setBaseRevision(4);

    expect(captures).toHaveLength(1);
    const refreshed = captures.at(-1);
    expect(refreshed?.base_revision).toBe(4);
    expect(refreshed?.base_source_hash).toBe(sha256Hex(editor.getMarkdown()));

    editor.destroy();
    vi.useRealTimers();
  });

  it("uses the selected repeated occurrence instead of first-match text", () => {
    const markdown = "重复段。\n\n中间段。\n\n重复段。\n";
    const state = createNovelState(markdown);
    const from = textPosition(state, "重复段", 1);
    const to = textPosition(state, "重复段", 1, true);

    const payload = buildSelectionPatchCapture(
      state,
      "c1",
      3,
      markdown,
      from,
      to,
    );

    const expectedStart = codePointOffset(markdown, markdown.lastIndexOf("重复段"));
    expect(payload?.schema_version).toBe("selection-patch-v1");
    expect(payload?.selection.start).toBe(expectedStart);
    expect(payload?.selection.end).toBe(expectedStart + 3);
    expect(payload?.selection.text).toBe("重复段");
    expect(payload?.base_source_hash).toBe(sha256Hex(markdown));
  });

  it("preserves the exact Markdown span across paragraphs", () => {
    const markdown = "第一段开头与结尾。\n\n第二段开头与结尾。\n";
    const state = createNovelState(markdown);
    const from = textPosition(state, "结尾");
    const to = textPosition(state, "第二段开头", 0, true);

    const payload = buildSelectionPatchCapture(
      state,
      "c1",
      4,
      markdown,
      from,
      to,
    );

    expect(payload?.selection.text).toBe("结尾。\n\n第二段开头");
    expect(payload?.before_anchor.end).toBe(payload?.selection.start);
    expect(payload?.after_anchor.start).toBe(payload?.selection.end);
  });

  it("maps CRLF, emoji, and Markdown lists to Unicode code-point offsets", () => {
    const markdown = "- 第一项 😀\r\n- 第二项 😀\r\n";
    const state = createNovelState(markdown);
    const from = textPosition(state, "第二项 😀");
    const to = textPosition(state, "第二项 😀", 0, true);

    const payload = buildSelectionPatchCapture(
      state,
      "c1",
      5,
      markdown,
      from,
      to,
    );

    const utf16Start = markdown.indexOf("第二项 😀");
    const expectedStart = codePointOffset(markdown, utf16Start);
    expect(payload?.selection.start).toBe(expectedStart);
    expect(payload?.selection.end).toBe(
      expectedStart + Array.from("第二项 😀").length,
    );
    expect(payload?.selection.text).toBe("第二项 😀");
  });

  it("uses explicit empty anchors at exact document boundaries", () => {
    const markdown = "开头到结尾";
    const state = createNovelState(markdown);
    const from = textPosition(state, markdown);
    const to = textPosition(state, markdown, 0, true);

    const payload = buildSelectionPatchCapture(
      state,
      "c1",
      6,
      markdown,
      from,
      to,
    );

    expect(payload?.before_anchor).toMatchObject({ start: 0, end: 0, text: "" });
    expect(payload?.after_anchor).toMatchObject({
      start: Array.from(markdown).length,
      end: Array.from(markdown).length,
      text: "",
    });
  });

  it("fails closed for empty, oversized, or non-round-trippable sources", () => {
    const state = createNovelState("正文");
    expect(
      buildSelectionPatchCapture(state, "c1", 1, "正文", 2, 2),
    ).toBeNull();
    expect(
      buildSelectionPatchCapture(
        createNovelState("字".repeat(20_001)),
        "c1",
        1,
        "字".repeat(20_001),
        1,
        20_002,
      ),
    ).toBeNull();
    expect(
      buildSelectionPatchCapture(
        createNovelState("- 项目\n"),
        "c1",
        1,
        "* 项目\n",
        3,
        5,
      ),
    ).toBeNull();
  });

  it("computes lowercase UTF-8 SHA-256 without the prototype FNV format", () => {
    expect(sha256Hex("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223" +
        "b00361a396177a9cb410ff61f20015ad",
    );
    expect(sha256Hex("雾😀")).toBe(
      "344b95df4d904df8a7cb062f8c4364d" +
        "19289bcf1ca362b7c582129591badb248",
    );
  });
});

describe("selection text (C1.1)", () => {
  it("quotes imported Markdown even when an exact replacement cannot map it", () => {
    const markdown = "* 项目  \n\n第二段。\n\n\n";
    const editor = new NovelEditor(document.createElement("div"), vi.fn(), null,
      null, { chapterId: "c1", baseRevision: 3, markdown });
    const view = (editor as unknown as { view: EditorView }).view;
    const from = textPosition(view.state, "项目");
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, from, from + 2)));
    expect(editor.getSelectionPatchCapture(from, from + 2)).toBeNull();
    expect(editor.getChatSelectionContext()).toMatchObject({
      chapter_id: "c1", base_revision: 3, content: markdown, selection: "项目",
    });
    editor.destroy();
  });

  it("keeps a newline between paragraphs instead of concatenating them", () => {
    const state = createNovelState("第一段。\n\n第二段。");
    const text = selectionText(state, 0, state.doc.content.size);
    expect(text).toBe("第一段。\n第二段。");
  });

  it("returns empty for a collapsed cursor", () => {
    const state = createNovelState("第一段。\n\n第二段。");
    expect(selectionText(state, 3, 3)).toBe("");
  });
});
