/**
 * MarkdownCodec for the restricted novel schema (Phase 1).
 *
 * The production codec uses the stable `prosemirror-markdown` parser/serializer
 * (option 2 from the product plan). `@tiptap/markdown` is intentionally NOT a
 * second competing serializer; the plan forbids two serializers running at the
 * same time. A golden-sample corpus proves zero semantic loss.
 */
import { Node } from "@tiptap/pm/model";
import markdownit from "markdown-it";
import { MarkdownParser, MarkdownSerializer } from "prosemirror-markdown";
import { NOVEL_SCHEMA } from "./schema";

export interface MarkdownCodec {
  parse(markdown: string): Node;
  serialize(doc: Node): string;
  roundTrip(markdown: string): string;
  supported(markdown: string): boolean;
}

const TOKENIZER = markdownit("commonmark", {
  html: false,
  linkify: false,
  typographer: false,
});

const PARSER = new MarkdownParser(NOVEL_SCHEMA, TOKENIZER, {
  blockquote: { block: "blockquote" },
  paragraph: { block: "paragraph" },
  heading: {
    block: "heading",
    getAttrs: (tok) => ({ level: tok.tag ? +tok.tag.slice(1) : 1 }),
  },
  hr: { node: "horizontal_rule" },
  hardbreak: { node: "hard_break" },
  softbreak: { node: "hard_break" },
  strong: { mark: "strong" },
  em: { mark: "em" },
});

const SERIALIZER = new MarkdownSerializer({
  text: (state, node) => state.text(node.text ?? "", false),
  paragraph: (state, node) => {
    state.renderInline(node);
    state.closeBlock(node);
  },
  heading: (state, node) => {
    const level = Number(node.attrs.level);
    state.write(state.repeat("#", level) + " ");
    state.renderInline(node);
    state.closeBlock(node);
  },
  blockquote: (state, node) => {
    state.wrapBlock("> ", null, node, () => state.renderContent(node));
  },
  horizontal_rule: (state) => {
    state.write("---\n\n");
  },
  hard_break: (state) => {
    state.write("\n");
  },
}, {
  strong: { open: "**", close: "**" },
  em: { open: "*", close: "*" },
});

const CODE_FENCE = /^```/;

export const markdownCodec: MarkdownCodec = {
  parse(markdown: string): Node {
    if (!this.supported(markdown)) {
      throw new Error("unsupported-markdown: manuscript contains unsupported syntax");
    }
    return PARSER.parse(markdown);
  },

  serialize(doc: Node): string {
    return SERIALIZER.serialize(doc);
  },

  roundTrip(markdown: string): string {
    return normalize(this.serialize(this.parse(markdown)));
  },

  supported(markdown: string): boolean {
    if (CODE_FENCE.test(markdown)) return false;
    if (markdown.includes("```")) return false;
    if (markdown.includes("`")) return false;
    if (/<[a-zA-Z][^>]*>/.test(markdown)) return false;
    if (/^\s{4}\S/m.test(markdown)) return false;
    if (/\|.*\|/.test(markdown)) return false;
    if (/\$\$/.test(markdown) || /\\\(/.test(markdown)) return false;
    return true;
  },
};

export function normalize(markdown: string): string {
  return markdown
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^---\s*$/m, "---")
    .replace(/^\* \* \*\s*$/m, "---")
    .replace(/\*\*/g, "**")
    .replace(/__/g, "**")
    .trimEnd() + "\n";
}
