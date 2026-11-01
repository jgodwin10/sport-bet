import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useFixtures, useStandings, useTopPicks } from "../api/hooks";
import type { Fixture } from "../api/types";
import { BetCard, BetStatus } from "../components/BetCard";
import { Icon } from "../components/icons";
import { MATCH_GRID, MatchRow } from "../components/MatchRow";
import { Card, Countdown, cx, Empty, ErrorState, FormPills, Hex, Loading, SearchInput, TeamLogo } from "../components/ui";
import { dayKey, fmtDateTime, fmtTime, pct } from "../lib/format";
import { friendlyReason, verdict } from "../lib/language";
import { inLeague, useLeague } from "../lib/league";

const isoDay = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

function dayParts(key: string): [string, string] {
  const d = new Date(`${key}T12:00:00`);
  const today = dayKey(new Date().toISOString()), tomorrow = dayKey(new Date(Date.now() + 86_400_000).toISOString());
  const top = key === today ? "Today" : key === tomorrow ? "Tomorrow" : new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(d);
  return [top, new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(d)];
}

/** The match to feature: a value bet if there is one, else the next match still to kick off. */
function featured(list: Fixture[]): Fixture | undefined {
  const upcoming = list.filter((f) => new Date(f.kickoff_utc).getTime() > Date.now());
  return list.find((f) => f.latest_prediction?.classification === "consider") ?? upcoming[0] ?? list[0];
}

export default function Dashboard() {
  const fixtures = useFixtures({ date_from: isoDay(0), date_to: isoDay(14), page_size: 200 });
  const { league } = useLeague();
  const [day, setDay] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const all = (fixtures.data?.items ?? []).filter((f) => league === "all" || f.competition.code === league);
  const days = useMemo(() => [...new Set(all.map((f) => dayKey(f.kickoff_utc)))].sort(), [all]);
  useEffect(() => { if (days.length && (day === null || !days.includes(day))) setDay(days[0]); }, [days, day]);

  const ofDay = all.filter((f) => !day || dayKey(f.kickoff_utc) === day);
  const q = search.trim().toLowerCase();
  const visible = ofDay.filter((f) => !q || f.home_team.name.toLowerCase().includes(q) || f.away_team.name.toLowerCase().includes(q));
  const hero = featured(ofDay);
  const tableLeague = league !== "all" ? league : hero?.competition.code ?? null;

  if (fixtures.isLoading) return <Card><Loading rows={6} /></Card>;
  if (fixtures.isError) return <ErrorState error={fixtures.error} onRetry={fixtures.refetch} />;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px] items-start">
      <div className="min-w-0 space-y-5">
        {hero ? <Hero f={hero} days={days} day={day} onDay={setDay} /> : (
          <Card><Empty title="No upcoming matches" icon="clock">New fixtures appear automatically once they are published.</Empty></Card>
        )}

        {hero && (
          <section className="card overflow-hidden">
            <header className="flex flex-col gap-3 px-4 sm:px-6 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <h2 className="text-[17px] font-bold">Fixtures</h2>
                <p className="text-[13px] text-ink-3">{visible.length} {visible.length === 1 ? "match" : "matches"} · {day ? dayParts(day).join(", ") : ""}</p>
              </div>
              <SearchInput value={search} onChange={setSearch} className="sm:w-60" />
            </header>
            <div className={cx(MATCH_GRID, "mt-4 px-4 sm:px-6 pb-2.5 border-b border-white/[0.06] text-xs font-medium text-ink-3")}>
              <span className="text-center">Time</span><span>Match</span>
              <span className="grid grid-cols-3 text-center"><span>1</span><span>X</span><span>2</span></span>
            </div>
            {visible.length ? (
              <div className="divide-soft">{visible.map((f) => <MatchRow key={f.id} f={f} showLeague={league === "all"} />)}</div>
            ) : <Empty title="No matches found" icon="search">Try another team name.</Empty>}
          </section>
        )}
      </div>

      <aside className="min-w-0 space-y-5">
        <TopPicksPanel />
        {tableLeague && <StandingsPanel code={tableLeague} name={all.find((f) => f.competition.code === tableLeague)?.competition.name ?? tableLeague} />}
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------- hero */
function Hero({ f, days, day, onDay }: { f: Fixture; days: string[]; day: string | null; onDay: (d: string) => void }) {
  const p = f.latest_prediction;
  const live = f.status === "scheduled" && new Date(f.kickoff_utc).getTime() <= Date.now();
  const r = p?.one_x_two;
  const v = p ? verdict(p.classification) : null;
  return (
    <section className="card relative overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute inset-0"
           style={{ background: "radial-gradient(520px 300px at 18% 55%, rgb(var(--home) / 0.16), transparent 70%), radial-gradient(520px 300px at 82% 55%, rgb(var(--brand-2) / 0.10), transparent 70%)" }} />
      <div className="relative">
        <div className="flex items-center gap-3 px-4 sm:px-6 pt-5">
          <span className={cx("shrink-0 rounded-full px-3 py-1 text-xs font-bold",
                              live ? "bg-neg text-white" : p?.classification === "consider" ? "bg-pos/15 text-pos ring-1 ring-inset ring-pos/30" : "bg-brand/20 text-brand-2 ring-1 ring-inset ring-brand/30")}>
            {live ? "Live" : p?.classification === "consider" ? "Value spotted" : "Featured"}
          </span>
          <div role="tablist" aria-label="Day" className="flex flex-1 gap-1 scroll-x sm:justify-center">
            {days.slice(0, 10).map((k) => {
              const [top, date] = dayParts(k);
              return (
                <button key={k} role="tab" aria-selected={k === day} onClick={() => onDay(k)}
                        className={cx("shrink-0 rounded-2xl px-3 py-1.5 text-center leading-tight transition-colors",
                                      k === day ? "bg-white/[0.07] text-ink" : "text-ink-4 hover:text-ink-2")}>
                  <span className={cx("block text-[13px]", k === day ? "font-bold" : "font-medium")}>{top}</span>
                  <span className="block text-xs">{date}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 sm:gap-6 px-3 sm:px-8 pt-6 pb-2">
          {[f.home_team, null, f.away_team].map((t, i) => t ? (
            <Link key={i} to={`/teams?team=${t.id}`} className="flex min-w-0 flex-col items-center text-center">
              <TeamLogo name={t.name} src={t.logo_url} size={64} className="sm:!w-[104px] sm:!h-[104px]" />
              <span className="mt-3 text-base sm:text-[26px] font-extrabold leading-tight">{t.name}</span>
            </Link>
          ) : (
            <div key="mid" className="flex flex-col items-center gap-2 sm:gap-3 text-center">
              <div className="text-[13px] sm:text-lg font-bold leading-tight">{f.competition.name}</div>
              <div className="text-[11px] sm:text-xs text-ink-3">{fmtDateTime(f.kickoff_utc)}</div>
              <Countdown to={f.kickoff_utc} className="hidden sm:inline-flex" />
              <Hex className="h-12 sm:h-14">
                <span className="text-xl sm:text-[26px] font-extrabold num">
                  {f.score ? `${f.score.home} - ${f.score.away}` : fmtTime(f.kickoff_utc).split(" ")[0]}
                </span>
              </Hex>
            </div>
          ))}
        </div>
        <div className="flex justify-center sm:hidden"><Countdown to={f.kickoff_utc} className="mt-3" /></div>

        {r && (
          <div className="px-4 sm:px-8 pt-6 pb-5">
            <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full" role="img"
                 aria-label={`Home ${pct(r.home, 0)}, draw ${pct(r.draw, 0)}, away ${pct(r.away, 0)}`}>
              <span className="bg-home" style={{ width: `${(r.home ?? 0) * 100}%` }} />
              <span className="bg-draw/70" style={{ width: `${(r.draw ?? 0) * 100}%` }} />
              <span className="bg-away" style={{ width: `${(r.away ?? 0) * 100}%` }} />
            </div>
            <div className="mt-4 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
              <div className="min-w-0">
                <div className="text-xl sm:text-2xl font-extrabold num">{pct(r.home, 0)}</div>
                <div className="truncate text-xs text-ink-3">Home win</div>
              </div>
              <div className="flex flex-col items-center gap-1.5">
                <Link to={`/match/${f.id}`} className="btn btn-primary px-6">Match details</Link>
                <span className="text-xs text-ink-3">Draw <b className="text-ink-2 num">{pct(r.draw, 0)}</b></span>
              </div>
              <div className="min-w-0 text-right">
                <div className="text-xl sm:text-2xl font-extrabold num">{pct(r.away, 0)}</div>
                <div className="truncate text-xs text-ink-3">Away win</div>
              </div>
            </div>
            {v && <p className="mt-4 text-center text-xs text-ink-4">{v.label} · {v.explain}</p>}
          </div>
        )}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- right side */
function TopPicksPanel() {
  const { league } = useLeague();
  const today = useTopPicks("today", 25);
  const week = useTopPicks("7", 25);
  const todays = inLeague(today.data?.items ?? [], league, 3);
  const picks = todays.length ? todays : inLeague(week.data?.items ?? [], league, 3);
  return (
    <section className="card p-4 sm:p-5">
      <header className="mb-4 flex items-center justify-between gap-3 px-1">
        <div className="min-w-0">
          <h2 className="text-[17px] font-bold">Top picks</h2>
          <p className="text-[13px] text-ink-3">{todays.length ? "Today" : "Next 7 days"}</p>
        </div>
        <Link to="/top" className="icon-btn !h-9 !w-9" aria-label="All top picks"><Icon name="chevronRight" size={16} /></Link>
      </header>
      {today.isLoading || week.isLoading ? <Loading rows={3} /> : !picks.length ? (
        <Empty title="No value right now" icon="ban">No price beats our estimate by enough. Holding back is part of the system.</Empty>
      ) : (
        <div className="space-y-4">
          {picks.map((t) => (
            <BetCard key={t.selection_id} r={t} rank={t.rank} highlight={t.tier === "recommended"}
                     status={<BetStatus ok={t.tier === "recommended"} warnLabel="Watchlist" reason={t.rejection_reasons[0] && friendlyReason(t.rejection_reasons[0])} />} />
          ))}
        </div>
      )}
    </section>
  );
}

function StandingsPanel({ code, name }: { code: string; name: string }) {
  const q = useStandings(code);
  const rows = q.data?.rows ?? [];
  if (q.isLoading) return <Card><Loading rows={4} /></Card>;
  if (!rows.length) return null;
  return (
    <section className="card overflow-hidden">
      <header className="px-5 pt-5">
        <h2 className="text-[17px] font-bold truncate">{name} table</h2>
        <p className="text-[13px] text-ink-3">Current season</p>
      </header>
      <table className="table mt-3 table-fixed">
        <colgroup><col className="w-[52px]" /><col /><col className="w-[40px]" /><col className="w-[150px]" /></colgroup>
        <thead><tr><th className="pl-5">#</th><th>Team</th><th className="text-right">Pts</th><th className="pr-5 text-right">Last 5</th></tr></thead>
        <tbody>
          {rows.slice(0, 10).map((r) => (
            <tr key={r.team.id}>
              <td className="pl-5">
                <span className="flex items-center gap-1 num">
                  <span className="font-semibold">{r.position}</span>
                  {r.movement !== 0 && <span className={cx("text-[10px] font-bold", r.movement > 0 ? "text-pos" : "text-neg")}
                                             aria-label={r.movement > 0 ? "up" : "down"}>{r.movement > 0 ? "↑" : "↓"}</span>}
                </span>
              </td>
              <td>
                <Link to={`/teams?team=${r.team.id}`} className="flex items-center gap-2 min-w-0 hover:text-brand-2">
                  <TeamLogo name={r.team.name} src={r.team.logo_url} size={22} />
                  <span className="truncate text-[13px] font-medium">{r.team.name}</span>
                </Link>
              </td>
              <td className="text-right font-bold num">{r.points}</td>
              <td className="pr-5"><span className="flex justify-end"><FormPills seq={r.form} size={20} /></span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
