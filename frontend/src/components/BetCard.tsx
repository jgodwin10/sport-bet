import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { SelectionRow } from "../api/types";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { GLOSSARY, selectionLabel } from "../lib/language";
import { cx, Figures, TeamLogo } from "./ui";

/** One priced bet: the match, the selection and its odds, then our chance against the bookmaker's. */
export function BetCard({ r, rank, status, children }: { r: SelectionRow; rank?: number; status: ReactNode; children?: ReactNode }) {
  const home = r.home_team?.name, away = r.away_team?.name;
  return (
    <Link to={`/match/${r.fixture_id}`} className="card flex gap-3 sm:gap-4 p-4 h-full transition-colors hover:border-line-strong">
      {rank !== undefined && <span className={cx("w-5 shrink-0 text-sm font-semibold num", rank <= 3 ? "text-ink" : "text-ink-4")}>{rank}</span>}
      <div className="min-w-0 flex-1 flex flex-col">
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex -space-x-1 shrink-0">
            <TeamLogo name={home ?? ""} src={r.home_team?.logo_url} size={16} />
            <TeamLogo name={away ?? ""} src={r.away_team?.logo_url} size={16} />
          </span>
          <span className="truncate text-[13px] text-ink-3">{r.match}</span>
        </div>
        <div className="mt-0.5 truncate text-xs text-ink-4">{r.competition} · {fmtDateTime(r.kickoff_utc)}</div>

        <div className="mt-3 flex items-baseline justify-between gap-3">
          <span className="min-w-0 text-base font-semibold leading-snug">{selectionLabel(r.market, r.selection, home, away)}</span>
          <span className="shrink-0 text-xl font-semibold num">{odds(r.odds)}</span>
        </div>

        <Figures className="mt-3" items={[
          ["Our chance", pct(r.probability, 0)],
          ["Bookmaker", pct(r.implied_probability, 0)],
          ["Value", signedPct(r.expected_value), r.expected_value > 0 ? "pos" : undefined, GLOSSARY.value],
        ]} />

        {children}
        <div className="mt-auto pt-3 text-xs text-ink-3 min-w-0">{status}</div>
      </div>
    </Link>
  );
}

/** "Recommended" or the first reason a bet was held back, as one quiet line. */
export function BetStatus({ ok, reason, okLabel = "Recommended", warnLabel }: { ok: boolean; reason?: string; okLabel?: string; warnLabel?: string }) {
  return (
    <span className="flex items-center gap-1.5 min-w-0">
      <span aria-hidden className={cx("h-1.5 w-1.5 shrink-0 rounded-full", ok ? "bg-pos" : "bg-warn")} />
      <span className={cx("shrink-0 font-medium", ok ? "text-pos" : "text-warn")}>{ok ? okLabel : warnLabel}</span>
      {!ok && reason && <span className="truncate">· {reason}</span>}
    </span>
  );
}
