import { describe, expect, it } from "vitest";
import { Node } from "@tiptap/pm/model";
import { markdownCodec, normalize, parseDocument } from "../src/markdown";
import { GOLDEN_SAMPLES, GOLDEN_SAMPLES_COUNT } from "./golden.samples";

describe("golden samples round trip", () => {
  it("has exactly 100 samples", () => {
    expect(GOLDEN_SAMPLES_COUNT).toBe(100);
  });

  it.each(GOLDEN_SAMPLES.map((sample, index) => [index, sample] as const))(
    "sample %i round-trips without semantic loss",
    (_index, markdown) => {
      const roundTripped = markdownCodec.roundTrip(markdown);
      expect(roundTripped).toBe(normalize(markdown));
    },
  );
});

describe("unsupported markdown is rejected", () => {
  it("rejects fenced code blocks", () => {
    expect(markdownCodec.supported("```js\nconst x = 1\n```")).toBe(false);
  });

  it("rejects raw HTML", () => {
    expect(markdownCodec.supported("<div>html</div>")).toBe(false);
  });

  it("rejects tables", () => {
    expect(markdownCodec.supported("| a | b |\n|---|---|")).toBe(false);
  });

  it("rejects indented code blocks", () => {
    expect(markdownCodec.supported("    const x = 1")).toBe(false);
  });

  it("rejects math", () => {
    expect(markdownCodec.supported("$$x^2$$")).toBe(false);
  });

  it("parse throws on unsupported markdown", () => {
    expect(() => markdownCodec.parse("```code```")).toThrow(
      "unsupported-markdown",
    );
  });
});

describe("markdown lists are first-class (2026-08-26 ticket)", () => {
  it("parses bullet lists", () => {
    const doc = markdownCodec.parse("- 第一项\n- 第二项");
    expect(doc.textContent).toContain("第一项");
    expect(doc.textContent).toContain("第二项");
  });

  it("parses ordered lists", () => {
    const doc = markdownCodec.parse("1. 有序一\n2. 有序二");
    expect(doc.textContent).toContain("有序一");
    expect(doc.textContent).toContain("有序二");
  });

  it("round-trips the ticket fixture without losing characters", () => {
    const markdown = "# 第一章\n\n- 第一项\n- 第二项\n\n1. 有序一\n2. 有序二";
    const roundTripped = markdownCodec.roundTrip(markdown);
    for (const fragment of [
      "# 第一章",
      "第一项",
      "第二项",
      "有序一",
      "有序二",
    ]) {
      expect(roundTripped).toContain(fragment);
    }
    expect(markdownCodec.roundTrip(roundTripped)).toBe(roundTripped);
  });

  it("round-trips the real-failure minimal representative", () => {
    const markdown = "普通正文。\n\n- 设定项A\n- 设定项B\n\n后续正文。";
    const roundTripped = markdownCodec.roundTrip(markdown);
    for (const fragment of ["普通正文。", "设定项A", "设定项B", "后续正文。"]) {
      expect(roundTripped).toContain(fragment);
    }
    expect(markdownCodec.roundTrip(roundTripped)).toBe(roundTripped);
  });
});

describe("explicit document load results (2026-08-26 ticket)", () => {
  it("classifies the real-failure fixture as LOADED with a document", () => {
    const outcome = parseDocument("普通正文。\n\n- 设定项A\n- 设定项B\n\n后续正文。");
    expect(outcome.status).toBe("LOADED");
    expect(outcome.doc).not.toBeNull();
    expect(outcome.doc?.textContent).toContain("设定项A");
  });

  it("classifies unsupported syntax without throwing", () => {
    const outcome = parseDocument("```code```");
    expect(outcome.status).toBe("UNSUPPORTED_MARKDOWN");
    expect(outcome.doc).toBeNull();
  });

  it("maps parser exceptions to PARSE_FAILED exactly once", () => {
    let calls = 0;
    const outcome = parseDocument("正文", {
      parse: (_markdown: string): Node => {
        calls += 1;
        throw new Error("Token type `bullet_list_open` not supported by Markdown parser");
      },
    });
    expect(calls).toBe(1);
    expect(outcome.status).toBe("PARSE_FAILED");
    expect(outcome.doc).toBeNull();
  });
});

describe("codec invariants", () => {
  it("serializes a parsed document back to normalized markdown", () => {
    const doc = markdownCodec.parse("# 标题\n\n正文 *斜体*");
    const text = markdownCodec.serialize(doc);
    expect(text).toContain("# 标题");
    expect(text).toContain("*斜体*");
  });

  it("produces stable output for identical input", () => {
    const input = "正文\n\n---\n\n第二段";
    expect(markdownCodec.roundTrip(input)).toBe(markdownCodec.roundTrip(input));
  });

  it("does not alter CJK punctuation", () => {
    const input = "「引号」与省略号……";
    expect(markdownCodec.roundTrip(input)).toContain("「引号」与省略号……");
  });
});
