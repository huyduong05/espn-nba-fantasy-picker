import { describe, expect, it } from "vitest";

import type { ManualBoardState, PlayerIndex } from "../src/contracts.js";
import { emptyBoard } from "../src/manual-board.js";
import { mountPanel } from "../src/panel.js";

const index: PlayerIndex = {
  schema_version: "1.0.0",
  index_version: "phase_9_player_index_v1",
  generated_at: "2026-10-17T12:00:00Z",
  input_fingerprint: "phase9-fixture",
  players: Array.from({ length: 7 }, (_, value) => ({
    canonical_player_id: `plr_${String(value + 1).padStart(32, "0")}`,
    display_name: `Player ${value + 1}`,
    aliases: [],
    positions: ["PG"],
  })),
};

describe("manual board panel", () => {
  it("opens from the launcher, closes, and reopens", async () => {
    const mounted = mount(index, async () => emptyBoard());
    await flush();
    const root = mounted.host.shadowRoot!;
    const drawer = root.querySelector("aside.drawer") as HTMLElement;
    const launcher = root.querySelector("button.launcher") as HTMLButtonElement;

    expect(drawer.hidden).toBe(true);
    launcher.click();
    expect(drawer.hidden).toBe(false);
    (
      root.querySelector(
        '[aria-label="Close Fantasy Picker"]',
      ) as HTMLButtonElement
    ).click();
    expect(drawer.hidden).toBe(true);
    expect(launcher.hidden).toBe(false);
    mounted.destroy();
  });

  it("shows a live top-five result list and adds the selected player", async () => {
    const saved: ManualBoardState[] = [];
    const mounted = mount(
      index,
      async () => emptyBoard(),
      async (board) => {
        saved.push(board);
      },
    );
    await flush();
    const root = mounted.host.shadowRoot!;
    const search = root.querySelector(
      'input[aria-label="Search prepared players"]',
    ) as HTMLInputElement;
    search.value = "player";
    search.dispatchEvent(new Event("input"));

    const results = root.querySelectorAll("button.result-card");
    expect(results).toHaveLength(5);
    (results[0] as HTMLButtonElement).click();
    const add = [...root.querySelectorAll("button")].find(
      (control) => control.textContent === "Add to roster",
    ) as HTMLButtonElement;
    expect(add).toBeTruthy();
    add.click();
    await flush();

    expect(saved).toEqual([
      {
        roster_ids: [index.players[0]!.canonical_player_id],
        taken_ids: [],
      },
    ]);
    expect(root.textContent).toContain("My roster");
    expect(root.textContent).toContain("Player 1");
    mounted.destroy();
  });

  it("shows an existing board status instead of add actions for duplicate players", async () => {
    const mounted = mount(index, async () => ({
      roster_ids: [index.players[0]!.canonical_player_id],
      taken_ids: [],
    }));
    await flush();
    const root = mounted.host.shadowRoot!;
    const search = root.querySelector(
      'input[aria-label="Search prepared players"]',
    ) as HTMLInputElement;
    search.value = "Player 1";
    search.dispatchEvent(new Event("input"));
    (root.querySelector("button.result-card") as HTMLButtonElement).click();

    expect(root.textContent).toContain("Already added to your roster.");
    expect(root.textContent).not.toContain("Add to roster");
    mounted.destroy();
  });

  it("renders a storage error without leaving an empty drawer", async () => {
    const mounted = mount(index, async () => {
      throw new Error("The manual draft board could not be loaded.");
    });
    await flush();

    expect(mounted.host.shadowRoot!.textContent).toContain(
      "The manual draft board could not be loaded.",
    );
    mounted.destroy();
  });
});

function mount(
  playerIndex: PlayerIndex,
  loadBoard: () => Promise<ManualBoardState>,
  saveBoard: (board: ManualBoardState) => Promise<void> = async () => undefined,
) {
  return mountPanel(document, playerIndex, {
    loadBoard,
    saveBoard,
    suggest: async () => {
      throw new Error("not requested");
    },
  });
}

async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}
