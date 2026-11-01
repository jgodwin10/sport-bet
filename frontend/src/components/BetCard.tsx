import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { SelectionRow } from "../api/types";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { GLOSSARY, selectionLabel } from "../lib/language";
import { cx, Figures } from "./ui";

/** One priced bet: the match, the selection and its odds, then our chance against the bookmaker's. */
export function BetCard({ r, rank, status, children, highlight }: {
  r: SelectionRow; rank?: number; status: ReactNode; children?: ReactNode; highlight?: boolean;
}) {
  const home = r.home_team?.name, away = r.away_team?.name;
  return (
    <Link to={`/match/${r.fixture_id}`}
          className={cx("card card-link relative flex gap-3 sm:gap-4 p-4 sm:p-5 h-full overflow-hidden", highlight && "!border-brand/35")}>
      {highlight && <span aria-hidden className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-brand to-brand-2" />}
      {rank !== undefined && (
        <span className={cx("grid h-8 w-8 shrink-0 place-items-center rounded-xl text-sm font-extrabold num",
                            rank <= 3 ? "bg-gradient-to-br from-brand to-brand-2 text-brand-ink" : "bg-subtle text-ink-3 ring-1 ring-inset ring-line")}>
          {rank}
        </span>
      )}
      <div className="min-w-0 flex-1 flex flex-col">
        <div className="truncate text-[13px] font-semibold text-ink-2">{r.match}</div>
        <div className="mt-0.5 truncate text-xs text-ink-4">{r.competition} · {fmtDateTime(r.kickoff_utc)}</div>

        <div className="mt-3 flex items-baseline justify-between gap-3">
          <span className="min-w-0 text-[17px] font-extrabold leading-snug tracking-[-0.01em]">{selectionLabel(r.market, r.selection, home, away)}</span>
          <span className="shrink-0 rounded-xl bg-bg/60 px-2.5 py-1 text-lg font-extrabold num ring-1 ring-inset ring-line-strong">{odds(r.odds)}</span>
        </div>

        <Figures className="mt-4 rounded-xl bg-bg/40 px-3 py-2.5 ring-1 ring-inset ring-line" items={[
          ["Our chance", pct(r.probability, 0)],
          ["Bookmaker", pct(r.implied_probability, 0)],
          ["Value", signedPct(r.expected_value), r.expected_value > 0 ? "pos" : undefined, GLOSSARY.value],
        ]} />

        {children}
        <div className="mt-auto pt-3.5 text-xs text-ink-3 min-w-0">{status}</div>
      </div>
    </Link>
  );
}

/** "Recommended" or the first reason a bet was held back, as one quiet line. */
export function BetStatus({ ok, reason, okLabel = "Recommended", warnLabel }: { ok: boolean; reason?: string; okLabel?: string; warnLabel?: string }) {
  return (
    <span className="flex items-center gap-1.5 min-w-0">
      <span aria-hidden className={cx("h-1.5 w-1.5 shrink-0 rounded-full", ok ? "bg-pos" : "bg-warn")} />
      <span className={cx("shrink-0 font-bold", ok ? "text-pos" : "text-warn")}>{ok ? okLabel : warnLabel}</span>
      {!ok && reason && <span className="truncate">· {reason}</span>}
    </span>
  );
}
