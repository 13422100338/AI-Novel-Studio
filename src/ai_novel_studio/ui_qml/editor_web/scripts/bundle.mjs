import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
mkdirSync(path.join(root, "dist"), { recursive: true });

await esbuild.build({
  entryPoints: [path.join(root, "src", "editor.ts")],
  bundle: true,
  format: "iife",
  outfile: path.join(root, "dist", "editor.js"),
  target: "es2020",
  sourcemap: false,
  minify: false,
  platform: "browser",
});

copyFileSync(path.join(root, "src", "index.html"), path.join(root, "dist", "index.html"));
copyFileSync(path.join(root, "src", "style.css"), path.join(root, "dist", "style.css"));

console.log("editor bundle + html + css written to dist/");
