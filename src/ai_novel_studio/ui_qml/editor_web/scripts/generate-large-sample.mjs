import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outDir = path.join(root, "dist", "samples");
mkdirSync(outDir, { recursive: true });

const CJK = "雾港的清晨潮汐灯塔旧信，林默沿着湿漉漉的栈桥走进镇子。";
const paragraphs = [];
let total = 0;
while (total < 200_000) {
  const repeat = Math.max(1, Math.floor(120 / CJK.length));
  const paragraph = CJK.repeat(repeat);
  paragraphs.push(paragraph);
  total += paragraph.length;
}

const markdown =
  "# 第一章 雾港的清晨（20 万字符压力稿）\n\n" + paragraphs.join("\n\n") + "\n";
const target = path.join(outDir, "large-sample.md");
writeFileSync(target, markdown, "utf8");

console.log(
  `wrote ${target} (${markdown.length.toLocaleString("en-US")} characters)`,
);

