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
  draft_slot: number;
  direction: "FORWARD" | "REVERSE";
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
