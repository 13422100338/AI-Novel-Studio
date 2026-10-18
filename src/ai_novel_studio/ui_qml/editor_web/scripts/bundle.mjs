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
copyFileSync(path.join(root, "src", "qwebchannel.js"), path.join(root, "dist", "qwebchannel.js"));
copyFileSync(
  path.join(root, "node_modules", "prosemirror-view", "style", "prosemirror.css"),
  path.join(root, "dist", "prosemirror.css"),
);

console.log("editor bundle + html + css + qwebchannel.js + prosemirror.css written to dist/");
