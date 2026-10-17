export const SCHEMA_VERSION = "1.0.0" as const;

export type Category =
  "PTS" | "REB" | "AST" | "STL" | "BLK" | "3PM" | "FG%" | "FT%" | "TO";
export type Position = "PG" | "SG" | "SF" | "PF" | "C";

export interface DraftPlayer {
  canonical_player_id: string | null;
  display_name: string;
  positions: Position[];
  match_status:
    "EXACT_ID" | "EXACT_ALIAS" | "MANUAL" | "AMBIGUOUS" | "UNRESOLVED";
}

export interface DraftState {
  schema_version: typeof SCHEMA_VERSION;
  league_config_version: typeof SCHEMA_VERSION;
  round: number;
  overall_pick: number;
  user_roster: DraftPlayer[];
  remaining_players: DraftPlayer[];
  manual_overrides: {
    added_player_names: string[];
    removed_player_names: string[];
  };
}

export interface Recommendation {
  rank: number;
  canonical_player_id: string;
  display_name: string;
  score: number;
  strong_categories: Category[];
  category_win_gain: number;
  injury_penalty_pct: number;
  positions: Position[];
  reason_codes: string[];
}

export interface RecommendationResponse {
  schema_version: typeof SCHEMA_VERSION;
  generated_at: string;
  data_version: string;
  model_version: string;
  latency_ms: number;
  recommendations: Recommendation[];
  warnings: string[];
}

export interface PlayerIndexPlayer {
  canonical_player_id: string;
  display_name: string;
  aliases: string[];
  positions: Position[];
}

export interface PlayerIndex {
  schema_version: typeof SCHEMA_VERSION;
  index_version: "phase_9_player_index_v1";
  generated_at: string;
  input_fingerprint: string;
  players: PlayerIndexPlayer[];
}

export interface ManualBoardState {
  roster_ids: string[];
  taken_ids: string[];
}

export interface RecommendationRequestMessage {
  type: "recommend";
  draft_state: DraftState;
}

export interface MetadataRequestMessage {
  type: "metadata";
}

export interface LoadBoardRequestMessage {
  type: "load_board";
}

export interface SaveBoardRequestMessage {
  type: "save_board";
  board: ManualBoardState;
}

export type ExtensionRequestMessage =
  | RecommendationRequestMessage
  | MetadataRequestMessage
  | LoadBoardRequestMessage
  | SaveBoardRequestMessage;

export type RecommendationResponseMessage =
  | { ok: true; response: unknown }
  | { ok: false; code: string; message: string };

export type MetadataResponseMessage =
  | { ok: true; metadata: unknown }
  | { ok: false; code: string; message: string };

export type LoadBoardResponseMessage =
  | { ok: true; board: ManualBoardState }
  | { ok: false; code: string; message: string };

export type SaveBoardResponseMessage =
  { ok: true } | { ok: false; code: string; message: string };

export type ExtensionResponseMessage =
  | RecommendationResponseMessage
  | MetadataResponseMessage
  | LoadBoardResponseMessage
  | SaveBoardResponseMessage;
