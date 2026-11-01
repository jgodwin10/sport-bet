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
    <Link to={`/match/${f.id}`} className="group flex items-center gap-3 px-3 sm:px-4 py-3 transition-colors hover:bg-subtle/40">
      <div className="w-11 sm:w-12 shrink-0 rounded-xl bg-bg/50 py-1.5 text-center leading-tight ring-1 ring-inset ring-line">
        <div className="text-[13px] font-bold num">{clock}</div>
        {status ? <div className="text-[10px] font-bold uppercase text-warn">{status}</div>
          : meridiem && <div className="text-[10px] font-semibold text-ink-4">{meridiem}</div>}
      </div>

      <div className="min-w-0 flex-1 space-y-1">
        {[f.home_team, f.away_team].map((t, i) => (
          <div key={t.id} className="flex items-center gap-2 min-w-0">
            <TeamLogo name={t.name} src={t.logo_url} size={18} />
            <span className={cx("truncate text-sm", lead === (i === 0 ? "home" : "away") ? "font-bold text-ink" : "font-medium text-ink-3")}>{t.name}</span>
            {f.score && <span className="ml-auto text-sm font-bold num">{i === 0 ? f.score.home : f.score.away}</span>}
          </div>
        ))}
        {p?.classification === "consider" && (
          <div className="pt-0.5" title={v!.explain}>
            <span className="inline-flex items-center gap-1 rounded-full bg-pos/10 px-2 py-0.5 text-[11px] font-bold text-pos ring-1 ring-inset ring-pos/25">
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-pos" />Value bet
            </span>
          </div>
        )}
      </div>

      <div className="shrink-0 w-[108px] sm:w-[150px]">
        {p ? <ProbChips p={p.one_x_two} /> : <div className="text-center text-xs text-ink-4">No prediction yet</div>}
      </div>
    </Link>
  );
}
