import { Link } from "react-router-dom";
import type { Fixture } from "../api/types";
import { fmtTime } from "../lib/format";
import { verdict } from "../lib/language";
import { cx, ProbChips, TeamLogo } from "./ui";

/** A fixture as one tappable row: kickoff time, the two teams, then the 1 / X / 2 chances. */
export function MatchRow({ f }: { f: Fixture }) {
  const p = f.latest_prediction;
  const started = f.status === "scheduled" && new Date(f.kickoff_utc).getTime() <= Date.now();
  const lead = p ? (["home", "draw", "away"] as const).reduce((a, b) => ((p.one_x_two[b] ?? 0) > (p.one_x_two[a] ?? 0) ? b : a)) : null;
  const status = started ? "Live" : f.status !== "scheduled" ? f.status : null;
  const [clock, meridiem] = fmtTime(f.kickoff_utc).split(" ");
  const v = p ? verdict(p.classification) : null;
  return (
    <Link to={`/match/${f.id}`} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-subtle/60">
      <div className="w-11 shrink-0 text-center leading-tight">
        <div className="text-sm font-medium num">{clock}</div>
        {meridiem && <div className="text-[10px] text-ink-4">{meridiem}</div>}
        {status && <div className="mt-0.5 text-[10px] font-semibold uppercase text-warn">{status}</div>}
      </div>

      <div className="min-w-0 flex-1 space-y-1">
        {[f.home_team, f.away_team].map((t, i) => (
          <div key={t.id} className="flex items-center gap-2 min-w-0">
            <TeamLogo name={t.name} src={t.logo_url} size={18} />
            <span className={cx("truncate text-sm", lead === (i === 0 ? "home" : "away") ? "font-semibold text-ink" : "text-ink-2")}>{t.name}</span>
            {f.score && <span className="ml-auto text-sm font-semibold num">{i === 0 ? f.score.home : f.score.away}</span>}
          </div>
        ))}
        {p?.classification === "consider" && (
          <div className="flex items-center gap-1.5 pt-0.5 text-xs font-medium text-pos" title={v!.explain}>
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-pos" />Value bet
          </div>
        )}
      </div>

      <div className="shrink-0 w-[118px] sm:w-[144px]">
        {p ? <ProbChips p={p.one_x_two} /> : <div className="text-center text-xs text-ink-4">No prediction yet</div>}
      </div>
    </Link>
  );
}
