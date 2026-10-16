import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { describe, expect, it } from "vitest";

const directory = path.dirname(fileURLToPath(import.meta.url));
const extensionDirectory = path.resolve(directory, "..");

describe("extension scope", () => {
  it("keeps permissions restricted to the manual panel and localhost API", () => {
    const manifest = JSON.parse(
      readFileSync(path.join(extensionDirectory, "manifest.json"), "utf8"),
    ) as { permissions: string[]; host_permissions: string[] };

    expect(manifest.permissions).toEqual(["storage"]);
    expect(manifest.host_permissions).toEqual([
      "https://fantasy.espn.com/basketball/*",
      "http://127.0.0.1:8765/*",
    ]);
  });

  it("does not add ESPN page-reading selectors to the content script", () => {
    const contentScript = readFileSync(
      path.join(extensionDirectory, "src", "content.ts"),
      "utf8",
    );

    expect(contentScript).not.toContain("querySelector");
    expect(contentScript).not.toContain("innerText");
  });
});
