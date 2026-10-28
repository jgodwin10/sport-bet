import { Link } from "react-router-dom";
import type { Fixture } from "../api/types";
import { fmtTime } from "../lib/format";
import { outcomeLabel } from "../lib/language";
import { Icon } from "./icons";
import { ClassificationBadge, cx, Freshness, ProbChips, ReliabilityBadge, TeamLogo } from "./ui";

/** A fixture as a compact, tappable scoreboard row: time column, stacked teams, 1/X/2 chances,
 *  then a meta line (verdict, data confidence, odds age). Same structure at every width. */
export function MatchRow({ f }: { f: Fixture }) {
  const p = f.latest_prediction;
  const started = f.status === "scheduled" && new Date(f.kickoff_utc).getTime() <= Date.now();
  const lead = p ? (["home", "draw", "away"] as const).reduce((a, b) => ((p.one_x_two[b] ?? 0) > (p.one_x_two[a] ?? 0) ? b : a)) : null;
  const status = started ? "Live" : f.status !== "scheduled" ? f.status : null;
  const [clock, meridiem] = fmtTime(f.kickoff_utc).split(" ");
  return (
    <Link to={`/match/${f.id}`} className="group flex gap-3 sm:gap-4 px-4 sm:px-5 py-3.5 transition-colors hover:bg-white/[0.025] active:bg-white/[0.05]">
      <div className="w-11 sm:w-14 shrink-0 pt-0.5 text-center">
        <div className="display text-[17px] num">{clock}</div>
        {meridiem && <div className="mt-0.5 text-[10px] font-bold text-ink-4">{meridiem}</div>}
        {status && <div className="mt-1 text-[9.5px] font-extrabold uppercase tracking-wide text-warn">{status}</div>}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            {[f.home_team, f.away_team].map((t, i) => (
              <div key={t.id} className="flex items-center gap-2.5 min-w-0">
                <TeamLogo name={t.name} src={t.logo_url} size={20} />
                <span className={cx("truncate text-[14.5px]", lead === (i === 0 ? "home" : "away") ? "font-bold text-ink" : "font-medium text-ink-2")}>{t.name}</span>
                {f.score && <span className="ml-auto display text-[18px] num">{i === 0 ? f.score.home : f.score.away}</span>}
              </div>
            ))}
          </div>
          <div className="shrink-0 w-[128px] sm:w-[150px]">
            {p ? <ProbChips p={p.one_x_two} /> : <div className="text-center text-2xs text-ink-4">No prediction yet</div>}
          </div>
        </div>

        {p && (
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <ClassificationBadge value={p.classification} />
            <span className="text-xs text-ink-3 hidden md:inline">
              Most likely <b className="font-semibold text-ink-2">{outcomeLabel(lead!, f.home_team.name, f.away_team.name)}</b>
            </span>
            <span className="ml-auto flex items-center gap-3">
              <ReliabilityBadge score={p.reliability_score} label={p.reliability_label} compact />
              <Freshness hours={p.odds_age_hours} label="Odds" />
            </span>
          </div>
        )}
      </div>
      <Icon name="chevronRight" size={18} className="hidden sm:block self-center shrink-0 text-ink-4 group-hover:text-ink-2 transition-colors" />
    </Link>
  );
}
