import {
  SCHEMA_VERSION,
  type DraftPlayer,
  type DraftState,
  type ManualBoardState,
  type PlayerIndex,
  type PlayerIndexPlayer,
} from "./contracts.js";

const TEAM_COUNT = 12;
const MAX_ROSTER_SIZE = 13;
const MAX_DRAFT_PICKS = TEAM_COUNT * MAX_ROSTER_SIZE;

export type DraftStateResult =
  | { ok: true; draftState: DraftState; overallPick: number }
  | { ok: false; message: string };

export function emptyBoard(): ManualBoardState {
  return { draft_slot: null, roster_ids: [], taken_ids: [] };
}

export function searchPlayers(
  index: PlayerIndex,
  query: string,
): PlayerIndexPlayer[] {
  const normalizedQuery = normalizeName(query);
  if (!normalizedQuery) {
    return [];
  }
  return index.players.filter((player) =>
    [player.display_name, ...player.aliases].some((name) =>
      normalizeName(name).includes(normalizedQuery),
    ),
  );
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

export function setDraftSlot(
  board: ManualBoardState,
  draftSlot: number | null,
): ManualBoardState {
  return { ...board, draft_slot: draftSlot };
}

export function deriveDraftState(
  index: PlayerIndex,
  board: ManualBoardState,
): DraftStateResult {
  if (
    board.draft_slot === null ||
    board.draft_slot < 1 ||
    board.draft_slot > TEAM_COUNT
  ) {
    return {
      ok: false,
      message: "Choose your draft slot before requesting suggestions.",
    };
  }
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
  const round = Math.ceil(overallPick / TEAM_COUNT);
  const direction = round % 2 === 1 ? "FORWARD" : "REVERSE";
  const pickInRound = ((overallPick - 1) % TEAM_COUNT) + 1;
  const expectedPick =
    direction === "FORWARD"
      ? board.draft_slot
      : TEAM_COUNT + 1 - board.draft_slot;
  if (pickInRound !== expectedPick) {
    return {
      ok: false,
      message: "The manual board does not place you at the current pick yet.",
    };
  }
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
      draft_slot: board.draft_slot,
      direction,
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
