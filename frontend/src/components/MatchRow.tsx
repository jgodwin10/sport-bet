import { Link } from "react-router-dom";
import type { Fixture } from "../api/types";
import { fmtTime } from "../lib/format";
import { verdict } from "../lib/language";
import { Icon } from "./icons";
import { cx, ProbChips, TeamLogo } from "./ui";

/** Column layout shared by the fixtures header and every row. */
export const MATCH_GRID = "grid grid-cols-[44px_minmax(0,1fr)_108px] sm:grid-cols-[56px_minmax(0,1fr)_156px_16px] items-center gap-3";

/** A fixture as one tappable table row: kickoff, the two teams, then the 1 / X / 2 chances. */
export function MatchRow({ f, showLeague = false }: { f: Fixture; showLeague?: boolean }) {
  const p = f.latest_prediction;
  const started = f.status === "scheduled" && new Date(f.kickoff_utc).getTime() <= Date.now();
  const lead = p ? (["home", "draw", "away"] as const).reduce((a, b) => ((p.one_x_two[b] ?? 0) > (p.one_x_two[a] ?? 0) ? b : a)) : null;
  const status = started ? "Live" : f.status !== "scheduled" ? f.status : null;
  const [clock, meridiem] = fmtTime(f.kickoff_utc).split(" ");
  const v = p ? verdict(p.classification) : null;
  return (
    <Link to={`/match/${f.id}`} className={cx(MATCH_GRID, "group px-4 sm:px-6 py-3.5 transition-colors hover:bg-white/[0.03]")}>
      <div className="text-center leading-tight">
        {status
          ? <span className="inline-block rounded-full bg-neg px-2 py-0.5 text-[10px] font-bold uppercase text-white">{status}</span>
          : <><div className="text-sm font-bold num">{clock}</div>{meridiem && <div className="text-[10px] font-semibold text-ink-4">{meridiem}</div>}</>}
      </div>

      <div className="min-w-0 space-y-1.5">
        {[f.home_team, f.away_team].map((t, i) => (
          <div key={t.id} className="flex items-center gap-2.5 min-w-0">
            <TeamLogo name={t.name} src={t.logo_url} size={22} />
            <span className={cx("truncate text-sm", lead === (i === 0 ? "home" : "away") ? "font-bold text-ink" : "font-medium text-ink-3")}>{t.name}</span>
            {f.score && <span className="ml-auto text-sm font-bold num">{i === 0 ? f.score.home : f.score.away}</span>}
          </div>
        ))}
        {(showLeague || p?.classification === "consider") && (
          <div className="flex flex-wrap items-center gap-2 pt-0.5">
            {p?.classification === "consider" && (
              <span title={v!.explain} className="inline-flex items-center gap-1 rounded-full bg-pos/15 px-2 py-0.5 text-[11px] font-bold text-pos ring-1 ring-inset ring-pos/30">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-pos" />Value bet
              </span>
            )}
            {showLeague && <span className="truncate text-[11px] font-medium text-ink-4">{f.competition.name}</span>}
          </div>
        )}
      </div>

      <div>{p ? <ProbChips p={p.one_x_two} /> : <div className="text-center text-xs text-ink-4">No prediction yet</div>}</div>
      <Icon name="chevronRight" size={16} className="hidden sm:block text-ink-4 transition-colors group-hover:text-ink-2" />
    </Link>
  );
}
