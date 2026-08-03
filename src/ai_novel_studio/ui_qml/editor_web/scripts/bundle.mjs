import * as esbuild from "esbuild";
import { mkdirSync } from "node:fs";
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

console.log("editor bundle written to dist/editor.js");
