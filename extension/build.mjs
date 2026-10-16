import { build } from "esbuild";
import { access, cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(directory, "dist");
const generatedIndex = path.join(directory, "generated", "player-index.json");

await access(generatedIndex).catch(() => {
  throw new Error(
    "Missing generated/player-index.json. Run `fantasy-picker extension build-player-index` first.",
  );
});
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await build({
  entryPoints: ["src/content.ts", "src/background.ts"],
  bundle: true,
  format: "esm",
  outdir: output,
  platform: "browser",
  target: "chrome120",
});
await cp(
  path.join(directory, "manifest.json"),
  path.join(output, "manifest.json"),
);
await cp(generatedIndex, path.join(output, "player-index.json"));
