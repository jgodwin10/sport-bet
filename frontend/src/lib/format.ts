const TZ_KEY = "footy.timezone";

export function getTimezone(): string {
  try {
    return localStorage.getItem(TZ_KEY) || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function setTimezone(tz: string): void {
  try {
    localStorage.setItem(TZ_KEY, tz);
  } catch {
    /* ignore */
  }
}

/** Timestamps arrive as UTC ISO strings and are shown in the user's timezone. */
export function fmtDateTime(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: getTimezone(), weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    ...opts,
  }).format(new Date(iso));
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, { timeZone: getTimezone(), day: "2-digit", month: "short", year: "2-digit" })
    .format(new Date(iso));
}

export const pct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(digits)}%`;

export const signedPct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;

export const odds = (x: number | null | undefined) => (x ? x.toFixed(2) : "—");

export const num = (x: number | null | undefined, digits = 2) =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : x.toFixed(digits);

export function age(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return "no data";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min ago`;
  if (hours < 48) return `${hours.toFixed(0)} h ago`;
  return `${(hours / 24).toFixed(0)} d ago`;
}

export function ageFromIso(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

export const MARKET_LABELS: Record<string, string> = {
  "1x2": "Match result",
  "totals_2.5": "Over/Under 2.5",
  "totals_1.5": "Over/Under 1.5",
  "totals_3.5": "Over/Under 3.5",
  asian_handicap: "Asian handicap",
  double_chance: "Double chance",
  draw_no_bet: "Draw no bet",
};

export const marketLabel = (m: string) => MARKET_LABELS[m] ?? m;

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, { timeZone: getTimezone(), hour: "numeric", minute: "2-digit" }).format(new Date(iso));
}

/** Calendar day in the user's timezone, as a sortable key (YYYY-MM-DD). */
export function dayKey(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: getTimezone(), year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(iso));
}

export function dayLabel(iso: string): string {
  const key = dayKey(iso);
  const today = dayKey(new Date().toISOString());
  const tomorrow = dayKey(new Date(Date.now() + 86_400_000).toISOString());
  const yesterday = dayKey(new Date(Date.now() - 86_400_000).toISOString());
  const base = new Intl.DateTimeFormat(undefined, { timeZone: getTimezone(), weekday: "long", day: "numeric", month: "long" })
    .format(new Date(iso));
  if (key === today) return `Today · ${base}`;
  if (key === tomorrow) return `Tomorrow · ${base}`;
  if (key === yesterday) return `Yesterday · ${base}`;
  return base;
}
