import { describe, expect, it } from "vitest";

import type { PlayerIndex } from "../src/contracts.js";
import { emptyBoard } from "../src/manual-board.js";
import { mountPanel } from "../src/panel.js";

const index: PlayerIndex = {
  schema_version: "1.0.0",
  index_version: "phase_9_player_index_v1",
  generated_at: "2026-10-17T12:00:00Z",
  input_fingerprint: "phase9-fixture",
  players: [
    {
      canonical_player_id: "plr_00000000000000000000000000000001",
      display_name: "Panel Player",
      aliases: [],
      positions: ["PG"],
    },
  ],
};

describe("manual board panel", () => {
  it("starts closed and opens only from its visible toggle", async () => {
    let requests = 0;
    const mounted = mountPanel(document, index, {
      loadBoard: async () => emptyBoard(),
      saveBoard: async () => undefined,
      suggest: async () => {
        requests += 1;
        throw new Error("not requested");
      },
    });
    await Promise.resolve();
    const root = mounted.host.shadowRoot!;
    const panel = root.querySelector("section.panel") as HTMLElement;
    const toggle = root.querySelector("button.toggle") as HTMLButtonElement;

    expect(panel.hidden).toBe(true);
    toggle.click();
    expect(panel.hidden).toBe(false);
    expect(root.querySelector("button")?.textContent).toBe("Fantasy Picker");
    expect(requests).toBe(0);
    mounted.destroy();
  });
});
