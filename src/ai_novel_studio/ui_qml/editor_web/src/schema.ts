/**
 * Restricted novel-writing schema (Phase 1).
 *
 * Only the Markdown subset the product plan supports: H1/H2 headings, plain
 * paragraphs, bold, italic, blockquote, horizontal rule (scene break), soft
 * line breaks and paragraph gaps. Everything else is rejected at parse time so
 * a golden-sample round trip cannot silently change the manuscript.
 */
import { Schema } from "@tiptap/pm/model";

export const NOVEL_SCHEMA = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: {
      content: "inline*",
      group: "block",
      parseDOM: [{ tag: "p" }],
      toDOM: () => ["p", 0],
    },
    heading: {
      attrs: { level: { default: 1 } },
      content: "inline*",
      group: "block",
      defining: true,
      parseDOM: [
        { tag: "h1", attrs: { level: 1 } },
        { tag: "h2", attrs: { level: 2 } },
      ],
      toDOM: (node) => [`h${node.attrs.level}`, 0],
    },
    blockquote: {
      content: "block+",
      group: "block",
      defining: true,
      parseDOM: [{ tag: "blockquote" }],
      toDOM: () => ["blockquote", 0],
    },
    horizontal_rule: {
      group: "block",
      parseDOM: [{ tag: "hr" }],
      toDOM: () => ["hr"],
    },
    hard_break: {
      inline: true,
      group: "inline",
      selectable: false,
      parseDOM: [{ tag: "br" }],
      toDOM: () => ["br"],
    },
    text: { group: "inline" },
  },
  marks: {
    strong: { parseDOM: [{ tag: "strong" }, { tag: "b" }], toDOM: () => ["strong", 0] },
    em: { parseDOM: [{ tag: "em" }, { tag: "i" }], toDOM: () => ["em", 0] },
  },
});

export const schemaNodes = Object.keys(NOVEL_SCHEMA.nodes);
export const schemaMarks = Object.keys(NOVEL_SCHEMA.marks);

