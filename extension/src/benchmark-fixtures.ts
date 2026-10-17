import type { ManualBoardState, PlayerIndex } from "./contracts.js";

export const PHASE10_SCENARIOS = [
  { name: "early", overallPick: 6 },
  { name: "middle", overallPick: 78 },
  { name: "late", overallPick: 150 },
] as const;

export function boardForOverallPick(
  index: PlayerIndex,
  overallPick: number,
): ManualBoardState {
  if (index.players.length < overallPick) {
    throw new Error(
      `The prepared player index needs at least ${overallPick} players.`,
    );
  }
  const rosterIds: string[] = [];
  const takenIds: string[] = [];
  for (let pick = 1; pick < overallPick; pick += 1) {
    const playerId = index.players[pick - 1]!.canonical_player_id;
    (rosterIds.length < 13 ? rosterIds : takenIds).push(playerId);
  }
  return { roster_ids: rosterIds, taken_ids: takenIds };
}
