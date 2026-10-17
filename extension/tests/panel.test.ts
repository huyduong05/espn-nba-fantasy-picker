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

  it("keeps the board and offers an explicit retry after a failed request", async () => {
    let requests = 0;
    const boards: unknown[] = [];
    const mounted = mountPanel(document, index, {
      loadBoard: async () => emptyBoard(),
      saveBoard: async () => undefined,
      suggest: async (board) => {
        requests += 1;
        boards.push(board);
        throw new Error("The local recommendation service is unavailable.");
      },
    });
    await Promise.resolve();
    const root = mounted.host.shadowRoot!;
    const slot = root.querySelector(
      'select[aria-label="My draft slot"]',
    ) as HTMLSelectElement;
    slot.value = "1";
    slot.dispatchEvent(new Event("change"));
    await Promise.resolve();

    const suggest = [...root.querySelectorAll("button")].find(
      (button) => button.textContent === "Suggest picks",
    ) as HTMLButtonElement;
    suggest.click();
    await Promise.resolve();
    await Promise.resolve();
    await new Promise<void>((resolve) => setTimeout(resolve));

    const retry = [...root.querySelectorAll("button")].find(
      (button) => button.textContent === "Retry suggestions",
    ) as HTMLButtonElement;
    expect(retry.hidden).toBe(false);
    expect(root.textContent).toContain("service is unavailable");
    retry.click();
    await Promise.resolve();
    await Promise.resolve();
    await new Promise<void>((resolve) => setTimeout(resolve));

    expect(requests).toBe(2);
    expect(boards).toEqual([
      { draft_slot: 1, roster_ids: [], taken_ids: [] },
      { draft_slot: 1, roster_ids: [], taken_ids: [] },
    ]);
    mounted.destroy();
  });
});
