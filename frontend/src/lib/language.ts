/** Plain-language labels for model concepts, so every screen uses the same friendly wording. */

export type Tone = "neutral" | "pos" | "neg" | "warn" | "brand";

export const VERDICT: Record<string, { label: string; short: string; tone: Tone; explain: string }> = {
  consider: {
    label: "Value spotted", short: "Value", tone: "pos",
    explain: "A bookmaker price looks better than our estimated chance, and every safety check passed. Still not a guarantee.",
  },
  no_bet: {
    label: "No value bet", short: "No value", tone: "neutral",
    explain: "Our probabilities are close to the bookmakers'. There is no price worth taking.",
  },
  high_uncertainty: {
    label: "Too uncertain", short: "Uncertain", tone: "warn",
    explain: "The data is too thin, stale or contradictory to trust a recommendation for this match.",
  },
};

export const verdict = (v: string) => VERDICT[v] ?? { label: v, short: v, tone: "neutral" as Tone, explain: "" };

export const CONFIDENCE: Record<string, { label: string; tone: Tone }> = {
  high: { label: "High", tone: "pos" },
  moderate: { label: "Medium", tone: "warn" },
  low: { label: "Low", tone: "neg" },
};

export const GLOSSARY = {
  confidence: "How much we trust this prediction's inputs: sample size, data freshness, lineups and whether our models agree. It is separate from the chance of the result.",
  value: "Expected value: what a 1-unit bet would return on average if our probability is right. +5% means +0.05 units per bet in the long run.",
  edge: "Our probability minus the probability implied by the bookmaker's price.",
  implied: "The chance the bookmaker's price suggests (1 ÷ odds), including their margin.",
  logloss: "A score for probability forecasts. Lower is better. The bookmaker market is the benchmark to beat.",
  calibrated: "When we say 40%, it happens about 40% of the time. Checked statistically on past matches.",
  clv: "Closing-line value: whether the price we would have taken was better than the final price before kickoff — the best early sign of a real edge.",
  interval: "Range the probability could plausibly be in, given uncertainty in the model's estimates.",
} as const;

export function outcomeLabel(key: "home" | "draw" | "away", home: string, away: string): string {
  return key === "home" ? `${home} win` : key === "away" ? `${away} win` : "Draw";
}

export function selectionLabel(market: string, selection: string, home?: string, away?: string): string {
  const s = selection.toLowerCase();
  if (market === "1x2") {
    if (s === "home") return home ? `${home} to win` : "Home win";
    if (s === "away") return away ? `${away} to win` : "Away win";
    return "Draw";
  }
  if (market.startsWith("totals_")) {
    const line = market.split("_")[1];
    return `${s === "over" ? "Over" : "Under"} ${line} goals`;
  }
  if (market === "asian_handicap") {
    const [side, line] = selection.split(" ");
    const team = side === "home" ? home ?? "Home" : away ?? "Away";
    return `${team} ${line}`;
  }
  return selection;
}

export const MARKET_GROUPS: { key: string; label: string; match: (m: string) => boolean }[] = [
  { key: "all", label: "All markets", match: () => true },
  { key: "1x2", label: "Match result", match: (m) => m === "1x2" },
  { key: "goals", label: "Goals", match: (m) => m.startsWith("totals_") },
  { key: "ah", label: "Handicap", match: (m) => m === "asian_handicap" },
];

type Expl = { category: string; text: string; evidence: Record<string, any> };
const n1 = (x: number) => x.toFixed(1);
const vsAvg = (mult: number, better: string, worse: string) => {
  const d = Math.round((mult - 1) * 100);
  return Math.abs(d) < 3 ? "about league average" : `${Math.abs(d)}% ${d > 0 ? better : worse} than the league average`;
};

/** Short, plain-English facts built from the model's evidence numbers (no jargon). */
export function plainFacts(explanations: Expl[], home: string, away: string): { icon: string; text: string }[] {
  const by = Object.fromEntries(explanations.map((e) => [e.category, e.evidence]));
  const out: { icon: string; text: string }[] = [];
  const g = by.goal_model;
  if (g?.expected_goals) {
    out.push({ icon: "activity", text: `We expect about ${n1(g.expected_goals.home)} goals from ${home} and ${n1(g.expected_goals.away)} from ${away}.` });
    out.push({ icon: "target", text: `${home}'s attack is ${vsAvg(g.home_attack, "stronger", "weaker")}; ${away}'s defence lets in ${vsAvg(g.away_defence, "more", "fewer")}.` });
  }
  const f = by.form;
  if (f && f.home_gf != null && f.away_gf != null) {
    out.push({ icon: "chart", text: `Recent form: ${home} score ${n1(f.home_gf)} and concede ${n1(f.home_ga)} per game; ${away} score ${n1(f.away_gf)} and concede ${n1(f.away_ga)}.` });
  }
  const r = by.ratings;
  if (r && typeof r.home === "number") {
    const stronger = r.home >= r.away ? home : away;
    const gap = Math.abs(r.home - r.away);
    out.push({ icon: "shield", text: gap < 25 ? `The teams are rated about equal in strength${r.diff > 0 ? ", and home advantage tips it slightly to " + home : ""}.`
      : `${stronger} are rated clearly stronger (${Math.round(Math.max(r.home, r.away))} vs ${Math.round(Math.min(r.home, r.away))}).` });
  }
  const m = by.market;
  if (m?.market_1x2) {
    const diff = Object.values(m.difference ?? {}).reduce((a: number, b: any) => Math.max(a, Math.abs(Number(b))), 0);
    out.push({ icon: "target", text: diff < 0.03
      ? "Bookmakers see the match almost exactly as we do, which is why there's no value here."
      : `We differ from the bookmakers by up to ${Math.round(diff * 100)} percentage points on one outcome.` });
  }
  const s = by.schedule;
  if (s && s.home_rest_days != null) {
    const fresher = s.home_rest_days > s.away_rest_days ? home : away;
    out.push({ icon: "clock", text: `${fresher} have had more rest (${Math.round(Math.max(s.home_rest_days, s.away_rest_days))} vs ${Math.round(Math.min(s.home_rest_days, s.away_rest_days))} days).` });
  }
  return out;
}

const BOOKMAKERS: Record<string, string> = {
  b365: "Bet365", pp: "Paddy Power", bw: "Bet&Win", ps: "Pinnacle", wh: "William Hill", vc: "BetVictor", bv: "BetVictor",
  iw: "Interwetten", bfd: "Betfred", bmgm: "BetMGM", cl: "Coral", lb: "Ladbrokes", skb: "Sky Bet", bfe: "Betfair Exchange",
  avg: "Market average", max: "Best market price",
};
export const bookmakerName = (key: string | null | undefined) => (key ? BOOKMAKERS[key.toLowerCase()] ?? key : "—");

const REASONS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^market not validated by backtest$/, () => "This bet type hasn't passed our test on past seasons yet"],
  [/^edge (.+) below minimum (.+)$/, (m) => `The price isn't generous enough (edge ${m[1]}, we need ${m[2]})`],
  [/^expected value (.+) below minimum (.+)$/, (m) => `Not enough value (${m[1]}, we need ${m[2]})`],
  [/^reliability (\d+) below minimum (\d+)$/, (m) => `Data confidence too low (${m[1]}, we need ${m[2]})`],
  [/^odds missing or stale$/, () => "The odds are too old to trust"],
  [/^odds (.+) outside \[(.+), (.+)\]$/, (m) => `Odds outside the range we consider (${m[2]}–${m[3]})`],
  [/^probability (.+) below minimum (.+)$/, (m) => `Too unlikely to happen (${m[1]} chance)`],
  [/^model disagreement (.+) exceeds (.+)$/, () => "Our models disagree too much about this match"],
  [/^EV is not positive at the lower end/, () => "The value disappears once uncertainty is taken into account"],
  [/^market disabled in settings$/, () => "This bet type is switched off in settings"],
  [/^another selection in this market has higher EV$/, () => "A better bet exists in the same market"],
];
/** Turn a rule-engine rejection reason into a plain sentence. */
export function friendlyReason(reason: string): string {
  for (const [re, fn] of REASONS) {
    const m = reason.match(re);
    if (m) return fn(m);
  }
  return reason.charAt(0).toUpperCase() + reason.slice(1);
}

const PROVIDERS: Record<string, string> = {
  football_data_co_uk: "football-data.co.uk", football_data_org: "football-data.org", the_odds_api: "The Odds API",
  api_football: "API-Football", thesportsdb: "TheSportsDB (crests)",
};
export const providerName = (key: string) => PROVIDERS[key] ?? key.replace(/_/g, " ");

const AI_PROVIDERS: Record<string, string> = { openai: "OpenAI", gemini: "Gemini" };
export const aiProviderName = (key: string) => AI_PROVIDERS[key] ?? "AI";
