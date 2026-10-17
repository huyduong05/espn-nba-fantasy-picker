import {
  SCHEMA_VERSION,
  type DraftPlayer,
  type DraftState,
  type ManualBoardState,
  type PlayerIndex,
  type PlayerIndexPlayer,
} from "./contracts.js";

const MAX_ROSTER_SIZE = 13;
const MAX_DRAFT_PICKS = 156;

export type DraftStateResult =
  | { ok: true; draftState: DraftState; overallPick: number }
  | { ok: false; message: string };

export function emptyBoard(): ManualBoardState {
  return { roster_ids: [], taken_ids: [] };
}

export function searchPlayers(
  index: PlayerIndex,
  query: string,
): PlayerIndexPlayer[] {
  const normalizedQuery = normalizeName(query);
  if (!normalizedQuery) {
    return [];
  }
  return index.players
    .map((player, indexPosition) => ({
      player,
      indexPosition,
      score: matchScore(player, normalizedQuery),
    }))
    .filter((entry) => entry.score !== null)
    .sort(
      (left, right) =>
        left.score! - right.score! || left.indexPosition - right.indexPosition,
    )
    .map((entry) => entry.player);
}

export function addPlayer(
  board: ManualBoardState,
  playerId: string,
  destination: "roster" | "taken",
  index: PlayerIndex,
): ManualBoardState {
  if (
    !index.players.some((player) => player.canonical_player_id === playerId)
  ) {
    throw new Error(
      "The selected player is unavailable in the prepared player index.",
    );
  }
  if (
    board.roster_ids.includes(playerId) ||
    board.taken_ids.includes(playerId)
  ) {
    throw new Error("That player is already on the manual draft board.");
  }
  if (board.roster_ids.length + board.taken_ids.length >= MAX_DRAFT_PICKS) {
    throw new Error("All 156 draft picks are already recorded.");
  }
  if (destination === "roster" && board.roster_ids.length >= MAX_ROSTER_SIZE) {
    throw new Error("My roster already has the maximum 13 players.");
  }
  return {
    ...board,
    roster_ids:
      destination === "roster"
        ? [...board.roster_ids, playerId]
        : board.roster_ids,
    taken_ids:
      destination === "taken"
        ? [...board.taken_ids, playerId]
        : board.taken_ids,
  };
}

export function removePlayer(
  board: ManualBoardState,
  playerId: string,
): ManualBoardState {
  return {
    ...board,
    roster_ids: board.roster_ids.filter((id) => id !== playerId),
    taken_ids: board.taken_ids.filter((id) => id !== playerId),
  };
}

export function deriveDraftState(
  index: PlayerIndex,
  board: ManualBoardState,
): DraftStateResult {
  const draftedIds = [...board.roster_ids, ...board.taken_ids];
  if (new Set(draftedIds).size !== draftedIds.length) {
    return {
      ok: false,
      message:
        "The manual draft board contains the same player more than once.",
    };
  }
  const playersById = new Map(
    index.players.map((player) => [player.canonical_player_id, player]),
  );
  const unknownId = draftedIds.find((playerId) => !playersById.has(playerId));
  if (unknownId) {
    return {
      ok: false,
      message:
        "The manual draft board contains a player outside the prepared index.",
    };
  }
  const overallPick = draftedIds.length + 1;
  if (overallPick > MAX_DRAFT_PICKS) {
    return { ok: false, message: "All 156 draft picks are already recorded." };
  }
  const round = Math.ceil(overallPick / 12);
  const remaining = index.players.filter(
    (player) => !draftedIds.includes(player.canonical_player_id),
  );
  if (!remaining.length) {
    return { ok: false, message: "No indexed players remain available." };
  }
  return {
    ok: true,
    overallPick,
    draftState: {
      schema_version: SCHEMA_VERSION,
      league_config_version: SCHEMA_VERSION,
      round,
      overall_pick: overallPick,
      user_roster: board.roster_ids.map((id) =>
        draftPlayer(playersById.get(id)!),
      ),
      remaining_players: remaining.map(draftPlayer),
      manual_overrides: { added_player_names: [], removed_player_names: [] },
    },
  };
}

function draftPlayer(player: PlayerIndexPlayer): DraftPlayer {
  return {
    canonical_player_id: player.canonical_player_id,
    display_name: player.display_name,
    positions: player.positions,
    match_status: "MANUAL",
  };
}

function normalizeName(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/gu, "")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/gu, " ")
    .trim();
}

function matchScore(player: PlayerIndexPlayer, query: string): number | null {
  const names = [player.display_name, ...player.aliases].map(normalizeName);
  let best: number | null = null;
  for (const name of names) {
    if (name === query) {
      best = Math.min(best ?? 0, 0);
    } else if (name.startsWith(query)) {
      best = Math.min(best ?? 1, 1);
    } else if (name.includes(query)) {
      best = Math.min(best ?? 2, 2);
    }
  }
  return best;
}
