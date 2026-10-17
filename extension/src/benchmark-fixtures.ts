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
  const draftSlot = 6;
  const rosterIds: string[] = [];
  const takenIds: string[] = [];
  for (let pick = 1; pick < overallPick; pick += 1) {
    const round = Math.ceil(pick / 12);
    const pickInRound = ((pick - 1) % 12) + 1;
    const ownPick = round % 2 === 1 ? draftSlot : 13 - draftSlot;
    const playerId = index.players[pick - 1]!.canonical_player_id;
    (pickInRound === ownPick ? rosterIds : takenIds).push(playerId);
  }
  return { draft_slot: draftSlot, roster_ids: rosterIds, taken_ids: takenIds };
}
