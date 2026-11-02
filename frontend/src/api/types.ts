import { z } from "zod";

export const OneXTwo = z.object({ home: z.number(), draw: z.number(), away: z.number() });
export type OneXTwo = z.infer<typeof OneXTwo>;

export const Competition = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
  country: z.string(),
  tier: z.number().nullable(),
});
export type Competition = z.infer<typeof Competition>;

export const PredictionBrief = z.object({
  id: z.number(),
  created_at: z.string(),
  classification: z.enum(["consider", "no_bet", "high_uncertainty"]),
  one_x_two: OneXTwo.partial(),
  reliability_score: z.number(),
  reliability_label: z.string(),
  lineup_status: z.string(),
  best_selection: z
    .object({
      market: z.string(),
      selection: z.string(),
      odds: z.number(),
      probability: z.number(),
      expected_value: z.number(),
      edge: z.number(),
      bookmaker: z.string().nullable(),
    })
    .nullable(),
  odds_age_hours: z.number().nullable(),
});
export type PredictionBrief = z.infer<typeof PredictionBrief>;

export const TeamRef = z.object({ id: z.number(), name: z.string(), logo_url: z.string().nullable().optional() });
export type TeamRef = z.infer<typeof TeamRef>;

export const StandingRow = z.object({
  position: z.number(), movement: z.number(), team: TeamRef, played: z.number(), won: z.number(), drawn: z.number(),
  lost: z.number(), gf: z.number(), ga: z.number(), gd: z.number(), points: z.number(), form: z.string(),
});
export type StandingRow = z.infer<typeof StandingRow>;
export const Standings = z.object({ competition: z.string(), rows: z.array(StandingRow) });

export const Fixture = z.object({
  id: z.number(),
  competition: Competition,
  season: z.string(),
  home_team: TeamRef,
  away_team: TeamRef,
  kickoff_utc: z.string(),
  status: z.string(),
  neutral: z.boolean(),
  venue: z.string().nullable(),
  score: z.record(z.number().nullable()).nullable(),
  latest_prediction: PredictionBrief.nullable(),
});
export type Fixture = z.infer<typeof Fixture>;

export const pageOf = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), page: z.number(), page_size: z.number() });
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export const SelectionRow = z.object({
  selection_id: z.number(),
  prediction_id: z.number(),
  fixture_id: z.number(),
  match: z.string(),
  home_team: TeamRef.optional(),
  away_team: TeamRef.optional(),
  competition: z.string(),
  kickoff_utc: z.string(),
  market: z.string(),
  selection: z.string(),
  probability: z.number(),
  probability_lower: z.number().nullable(),
  odds: z.number(),
  bookmaker: z.string().nullable(),
  implied_probability: z.number(),
  fair_probability: z.number().nullable(),
  edge: z.number(),
  expected_value: z.number(),
  qualifies: z.boolean(),
  rejection_reasons: z.array(z.string()),
  reliability_score: z.number(),
  reliability_label: z.string(),
  odds_age_hours: z.number().nullable(),
  predicted_at: z.string(),
  status: z.enum(["upcoming", "settled", "awaiting_result"]),
  outcome: z.string().nullable(),
  profit: z.number().nullable(),
  clv: z.number().nullable(),
});
export type SelectionRow = z.infer<typeof SelectionRow>;

export const TopPick = SelectionRow.extend({
  rank: z.number(),
  tier: z.enum(["recommended", "watchlist"]),
  score: z.number(),
  ai: z.object({
    analysis_id: z.number(),
    created_at: z.string(),
    summary: z.string(),
    confidence: z.string().nullable(),
    probability: z.number().nullable(),
    verdict: z.enum(["supports", "doubts"]).nullable(),
    current: z.boolean(),
  }).nullable(),
});
export type TopPick = z.infer<typeof TopPick>;
export const TopPicks = z.object({
  generated_at: z.string(), days: z.number(), day: z.enum(["today", "tomorrow"]).nullable().optional(),
  window_start: z.string(), window_end: z.string(), ai_configured: z.boolean(), items: z.array(TopPick),
});
export type TopPicks = z.infer<typeof TopPicks>;

const TopPickTally = z.object({
  picks: z.number(), settled: z.number(), pending: z.number(), won: z.number(), lost: z.number(),
  void: z.number(), profit: z.number(), roi: z.number().nullable(),
});
export type TopPickTally = z.infer<typeof TopPickTally>;
export const TopPickResult = z.object({
  fixture_id: z.number(), match: z.string(), home_team: TeamRef.optional(), away_team: TeamRef.optional(),
  competition: z.string(), kickoff_utc: z.string(), market: z.string(), selection: z.string(), odds: z.number(),
  probability: z.number(), expected_value: z.number(), rank: z.number(), best_rank: z.number(),
  tier: z.enum(["recommended", "watchlist"]), counted: z.boolean(),
  score: z.object({ home: z.number(), away: z.number() }).nullable(),
  outcome: z.string().nullable(), profit: z.number().nullable(), clv: z.number().nullable(), running_profit: z.number(),
});
export type TopPickResult = z.infer<typeof TopPickResult>;
export const TopPickRecord = z.object({
  summary: z.object({ all: TopPickTally, recommended: TopPickTally, watchlist: TopPickTally }),
  dropped: z.number(),
  history: z.array(TopPickResult),
});
export type TopPickRecord = z.infer<typeof TopPickRecord>;

const TwoOddsCheck = z.object({ key: z.string(), label: z.string(), status: z.enum(["pass", "note", "fail", "unchecked"]), detail: z.string() });
export type TwoOddsCheck = z.infer<typeof TwoOddsCheck>;
const TwoOddsLeg = SelectionRow.extend({
  checks: z.array(TwoOddsCheck), score: z.object({ home: z.number(), away: z.number() }).nullable(),
});
export type TwoOddsLeg = z.infer<typeof TwoOddsLeg>;
export const TwoOddsSlip = z.object({
  date: z.string(), status: z.enum(["none", "pending", "won", "lost", "void"]), built: z.boolean(), locked: z.boolean(),
  legs: z.array(TwoOddsLeg), combined_odds: z.number().nullable(), combined_probability: z.number().nullable(),
  paid_odds: z.number().nullable(), analysed: z.number(), spare: z.number(),
  rejected: z.array(z.object({
    fixture_id: z.number(), match: z.string(), home: z.string(), away: z.string(), selection: z.string(),
    probability: z.number(), odds: z.number(), reasons: z.array(z.string()),
  })),
  changes: z.array(z.object({ at: z.string(), reason: z.string() })), updated_at: z.string().nullable(), ai_configured: z.boolean(),
  min_combined_odds: z.number(), max_combined_odds: z.number(), min_leg_probability: z.number(),
});
export type TwoOddsSlip = z.infer<typeof TwoOddsSlip>;
export const TwoOddsResult = z.object({
  date: z.string(), status: z.enum(["pending", "won", "lost", "void"]), combined_odds: z.number(), combined_probability: z.number(),
  profit: z.number().nullable(), running_profit: z.number(), legs: z.array(TwoOddsLeg),
});
export type TwoOddsResult = z.infer<typeof TwoOddsResult>;
export const TwoOddsRecord = z.object({
  summary: z.record(z.number().nullable()), backtest: z.record(z.any()).nullable(), history: z.array(TwoOddsResult),
});
export type TwoOddsRecord = z.infer<typeof TwoOddsRecord>;

export const LoginForm = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(8, "At least 8 characters"),
});

// The analysis payload is large and nested; it is typed but not deeply validated.
export interface ReliabilityFactor { factor: string; penalty: number; detail: string }
export interface Explanation { category: string; text: string; evidence: Record<string, unknown> }
export interface PredictionSelection {
  id: number; market: string; selection: string; line: number; probability: number;
  probability_lower: number | null; odds: number; bookmaker: string | null; implied_probability: number;
  fair_probability: number | null; edge: number; expected_value: number; qualifies: boolean;
  rejection_reasons: string[];
}
export interface AHOutcome { win: number; half_win: number; push: number; half_loss: number; loss: number }
export interface PredictionDetail {
  id: number; created_at: string; information_cutoff: string; trigger: string; lineup_status: string;
  markets: {
    "1x2": OneXTwo;
    double_chance: Record<string, number>;
    draw_no_bet: Record<string, number>;
    totals?: Record<string, { over: number; under: number }>;
    team_totals?: Record<"home" | "away", Record<string, { over: number; under: number }>>;
    btts?: { yes: number; no: number };
    asian_handicap?: Record<string, { home: AHOutcome; away: AHOutcome }>;
    correct_score?: { home: number; away: number; probability: number }[];
    score_grid?: { matrix: number[][]; other: number };
    expected_goals?: { home: number; away: number };
    supported?: Record<string, unknown>;
  };
  components: { one_x_two: Record<string, number[]>; weights: Record<string, number>; disagreement: number | null;
    weights_source: string };
  intervals: Record<string, [number, number] | string> | null;
  reliability: { score: number; label: string; factors: ReliabilityFactor[] };
  classification: "consider" | "no_bet" | "high_uncertainty";
  data_quality: Record<string, unknown>;
  change_summary: { field: string; before?: unknown; after?: unknown; delta?: number }[] | null;
  explanations: Explanation[];
  selections: PredictionSelection[];
}
export interface FormSummary {
  matches: number; wins: number; draws: number; losses: number; goals_for: number; goals_against: number;
  points_per_game: number; clean_sheets: number; failed_to_score: number; xg_for: number | null;
  xg_against: number | null; sot_for: number | null; sot_against: number | null; xg_coverage: number;
}
export interface RecentMatch {
  fixture_id: number; date: string; venue: "H" | "A"; opponent: string; opponent_logo?: string | null; goals_for: number; goals_against: number;
  result: "W" | "D" | "L"; xg_for: number | null; xg_against: number | null;
  shots_on_target_for: number | null; shots_on_target_against: number | null;
}
export interface TeamForm {
  summary: { last_5: FormSummary | null; last_10: FormSummary | null; last_15: FormSummary | null;
    home: FormSummary | null; away: FormSummary | null; sequence: string };
  matches: RecentMatch[];
}
export interface OddsRow {
  bookmaker: string; bookmaker_name: string; market: string; line: number; selection: string; odds: number;
  observed_at: string;
}
export interface Analysis {
  fixture: Fixture;
  prediction: PredictionDetail | null;
  prediction_history: { id: number; created_at: string; trigger: string; lineup_status: string;
    one_x_two: OneXTwo | null; classification: string; reliability: number;
    change_summary: PredictionDetail["change_summary"] }[];
  form: { home: TeamForm; away: TeamForm };
  head_to_head: { date: string; season: string; home: string; away: string; home_logo?: string | null;
    away_logo?: string | null; home_goals: number;
    away_goals: number; age_days: number }[];
  standings_context: { home: Record<string, number | string> | null; away: Record<string, number | string> | null;
    teams: number };
  availability: { team: string; player: string; kind: string; reason: string | null; verification: string;
    source: string; retrieved_at: string }[];
  lineups: { team_id: number; team: string; status: string; formation: string | null;
    players: { name: string; number?: number; position?: string; starter: boolean }[]; source: string;
    retrieved_at: string }[];
  odds: { latest: OddsRow[]; latest_observed: string | null; age_hours: number | null; closing: OddsRow[] };
  data_quality: Record<string, unknown>;
  sources: { id: number; provider: string; resource: string; retrieved_at: string; trust_level: number;
    verification: string }[];
  disclaimer: string;
}

export interface PredictedLineup {
  formation: string | null; source: string; players: { name: string; position: "GK" | "DF" | "MF" | "FW" | null }[];
}

export interface AiAnalysisContent {
  summary: string;
  structured: boolean;
  key_factors: { title: string; detail: string; favours: "home" | "away" | "draw" | "neither";
    weight: "low" | "medium" | "high"; basis: "model" | "news" | "both" }[];
  team_news: { team: string; detail: string; status: "confirmed" | "reported" | "rumour" }[];
  risks: string[];
  model_assessment: string;
  probability_view: OneXTwo | null;
  confidence: "low" | "medium" | "high";
  predicted_lineups?: { home: PredictedLineup | null; away: PredictedLineup | null } | null;
  basis?: { prediction_id: number; lineup_status: string; model_1x2: OneXTwo | null };
}

export interface AiAnalysis {
  id: number; fixture_id: number; prediction_id: number | null; created_at: string;
  status: "ok" | "failed"; provider: string; model: string | null; trigger: string;
  content: AiAnalysisContent | null; sources: { title: string; uri: string }[]; search_queries: string[];
  error: string | null;
}

export interface AiAnalysisState {
  configured: boolean; available: boolean; analysis: AiAnalysis | null; note: string;
}
