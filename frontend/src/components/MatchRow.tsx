import { Link } from "react-router-dom";
import type { Fixture } from "../api/types";
import { fmtTime } from "../lib/format";
import { outcomeLabel } from "../lib/language";
import { Icon } from "./icons";
import { ClassificationBadge, cx, Freshness, ProbChips, ReliabilityBadge, TeamLogo } from "./ui";

/** A fixture as a tappable row. On phones the time and verdict sit on a header line so team
 *  names get the full width; from `sm` up everything aligns in columns. */
export function MatchRow({ f }: { f: Fixture }) {
  const p = f.latest_prediction;
  const started = f.status === "scheduled" && new Date(f.kickoff_utc).getTime() <= Date.now();
  const lead = p ? (["home", "draw", "away"] as const).reduce((a, b) => ((p.one_x_two[b] ?? 0) > (p.one_x_two[a] ?? 0) ? b : a)) : null;
  const status = started ? "Kicked off" : f.status !== "scheduled" ? f.status : null;
  const teams = (
    <div className="min-w-0 flex-1 space-y-2">
      {[f.home_team, f.away_team].map((t, i) => (
        <div key={t.id} className="flex items-center gap-2.5 min-w-0">
          <TeamLogo name={t.name} src={t.logo_url} size={26} />
          <span className={cx("truncate text-[15px]", lead === (i === 0 ? "home" : "away") ? "font-bold text-ink" : "font-medium text-ink-2")}>{t.name}</span>
          {f.score && <span className="ml-auto num font-extrabold">{i === 0 ? f.score.home : f.score.away}</span>}
        </div>
      ))}
    </div>
  );
  return (
    <Link to={`/match/${f.id}`} className="group block px-4 sm:px-5 py-4 transition-colors hover:bg-white/[0.035] active:bg-white/[0.06]">
      {/* phone header line */}
      <div className="sm:hidden flex items-center gap-2 mb-3">
        <span className="text-[14px] font-extrabold num">{fmtTime(f.kickoff_utc)}</span>
        {status && <span className="text-[11px] font-bold uppercase tracking-wide text-ink-4">· {status}</span>}
        <span className="ml-auto">{p && <ClassificationBadge value={p.classification} />}</span>
      </div>

      <div className="flex items-center gap-3 sm:gap-5">
        <div className="hidden sm:block w-[76px] shrink-0">
          <div className="text-[15px] font-extrabold num leading-none whitespace-nowrap">{fmtTime(f.kickoff_utc)}</div>
          {status && <div className="mt-1.5 text-[10.5px] font-bold uppercase tracking-wide text-ink-4 whitespace-nowrap">{status}</div>}
        </div>
        {teams}
        <div className="shrink-0 w-[138px] sm:w-[168px]">
          {p ? <ProbChips p={p.one_x_two} /> : <div className="text-center text-xs text-ink-4">No prediction yet</div>}
        </div>
        <Icon name="chevronRight" size={18} className="hidden sm:block shrink-0 text-ink-4 group-hover:text-ink-2 transition-colors" />
      </div>

      {p && (
        <div className="mt-3 sm:ml-[96px] flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="hidden sm:inline-flex"><ClassificationBadge value={p.classification} /></span>
          <span className="text-xs text-ink-3 hidden md:inline">
            Most likely: <b className="font-semibold text-ink-2">{outcomeLabel(lead!, f.home_team.name, f.away_team.name)}</b>
          </span>
          <span className="sm:ml-auto flex items-center gap-3">
            <ReliabilityBadge score={p.reliability_score} label={p.reliability_label} />
            <Freshness hours={p.odds_age_hours} label="Odds" />
          </span>
        </div>
      )}
    </Link>
  );
}
