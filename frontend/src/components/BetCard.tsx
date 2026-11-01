import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useCompetitions } from "../api/hooks";
import type { SelectionRow } from "../api/types";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { GLOSSARY, selectionLabel } from "../lib/language";
import { cx, Hex, InfoTip, TeamLogo } from "./ui";

/** One priced bet as a match tile: crests either side of the odds, the pick, then a slider of our chance
 *  against the bookmaker's (the tick), and links to the match. */
export function BetCard({ r, rank, status, children, highlight }: {
  r: SelectionRow; rank?: number; status: ReactNode; children?: ReactNode; highlight?: boolean;
}) {
  const home = r.home_team, away = r.away_team;
  const ours = Math.min(1, Math.max(0, r.probability));
  const book = Math.min(1, Math.max(0, r.implied_probability));
  const comps = useCompetitions();
  const league = comps.data?.find((c) => c.code === r.competition)?.name ?? r.competition;
  return (
    <article className={cx("tile card-link relative flex h-full flex-col p-4 sm:p-5", highlight && "!border-brand/40")}>
      <div className="flex items-start gap-3">
        {rank !== undefined && (
          <span className={cx("grid h-8 min-w-8 shrink-0 place-items-center rounded-full px-2 text-sm font-extrabold num",
                              rank <= 3 ? "bg-gradient-to-b from-brand-2 to-brand text-white glow-blue" : "bg-bg/60 text-ink-3 ring-1 ring-inset ring-white/10")}>
            {rank}
          </span>
        )}
        <div className="min-w-0 flex-1 text-center">
          <div className="truncate text-sm font-bold">{league}</div>
          <div className="truncate text-xs text-ink-3">{fmtDateTime(r.kickoff_utc)}</div>
        </div>
        <span className={cx("shrink-0 rounded-full px-2.5 py-1 text-xs font-bold num ring-1 ring-inset",
                            r.expected_value > 0 ? "bg-pos/15 text-pos ring-pos/30" : "bg-bg/60 text-ink-3 ring-white/10")}
              title="Value">
          {signedPct(r.expected_value)}
        </span>
      </div>

      {!home || !away ? (
        <div className="mt-4 flex items-center justify-between gap-3">
          <span className="min-w-0 truncate text-sm font-semibold">{r.match}</span>
          <Hex className="h-11"><span className="text-lg font-extrabold num">{odds(r.odds)}</span></Hex>
        </div>
      ) : (
      <div className="mt-4 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
        {[home, null, away].map((t, i) => t !== null ? (
          <div key={i} className="flex min-w-0 flex-col items-center gap-2 text-center">
            <TeamLogo name={t?.name ?? ""} src={t?.logo_url} size={52} />
            <span className="w-full line-clamp-2 text-xs font-semibold leading-snug">{t?.name}</span>
          </div>
        ) : (
          <div key="odds" className="flex flex-col items-center gap-1">
            <Hex className="h-12"><span className="text-xl font-extrabold num">{odds(r.odds)}</span></Hex>
            <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-4">Odds</span>
          </div>
        ))}
      </div>
      )}

      <div className="mt-4 text-center">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-4">Pick</div>
        <div className="mt-0.5 text-base font-extrabold leading-snug">{selectionLabel(r.market, r.selection, home?.name, away?.name)}</div>
      </div>

      <div className="mt-5" role="img" aria-label={`Our chance ${pct(ours, 0)}, bookmaker ${pct(book, 0)}`}>
        <div className="relative h-1.5 rounded-full bg-white/[0.12]">
          <div className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-brand to-brand-2" style={{ width: `${ours * 100}%` }} />
          <span aria-hidden className="absolute -top-1 h-3.5 w-0.5 rounded-full bg-ink-3" style={{ left: `calc(${book * 100}% - 1px)` }} />
          <span aria-hidden className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-white bg-brand shadow"
                style={{ left: `${ours * 100}%` }} />
        </div>
        <div className="mt-2.5 flex items-center justify-between gap-2 text-xs">
          <span className="text-ink-3">Our chance <b className="text-ink num">{pct(ours, 0)}</b></span>
          <span className="flex items-center gap-0.5 text-ink-3">Bookmaker <b className="text-ink-2 num">{pct(book, 0)}</b><InfoTip text={GLOSSARY.value} /></span>
        </div>
      </div>

      <div className="mt-3 text-xs text-ink-3 min-w-0">{status}</div>
      {children}

      <div className="mt-auto grid grid-cols-2 gap-2 pt-4">
        <Link to={`/match/${r.fixture_id}?tab=odds`} className="btn">Compare odds</Link>
        <Link to={`/match/${r.fixture_id}`} className="btn btn-primary">Match details</Link>
      </div>
    </article>
  );
}

/** "Recommended" or the first reason a bet was held back, as one quiet line. */
export function BetStatus({ ok, reason, okLabel = "Recommended", warnLabel }: { ok: boolean; reason?: string; okLabel?: string; warnLabel?: string }) {
  return (
    <span className="flex items-center justify-center gap-1.5 min-w-0">
      <span aria-hidden className={cx("h-1.5 w-1.5 shrink-0 rounded-full", ok ? "bg-pos" : "bg-warn")} />
      <span className={cx("shrink-0 font-bold", ok ? "text-pos" : "text-warn")}>{ok ? okLabel : warnLabel}</span>
      {!ok && reason && <span className="truncate">· {reason}</span>}
    </span>
  );
}
