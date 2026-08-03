import { describe, expect, it } from "vitest";
import { markdownCodec, normalize } from "../src/markdown";
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

