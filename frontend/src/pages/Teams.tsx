import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useCompetitions, useTeamStats } from "../api/hooks";
import { Icon } from "../components/icons";
import {
  AXIS, Card, ChartTooltip, cx, Empty, ErrorState, FormPills, Loading, PageHeader, Pill, Segmented, SERIES, StatTile, TeamLogo,
} from "../components/ui";
import { fmtDate, fmtDateTime, num } from "../lib/format";

type TeamItem = { id: number; name: string; logo_url: string | null };

export default function Teams() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("team") ? Number(params.get("team")) : null;
  if (selected !== null) return <TeamDetail id={selected} onBack={() => setParams({})} />;
  return <TeamGrid onSelect={(id) => setParams({ team: String(id) })} />;
}

function TeamGrid({ onSelect }: { onSelect: (id: number) => void }) {
  const comps = useCompetitions();
  const [league, setLeague] = useState("ENG-1");
  const [search, setSearch] = useState("");
  const teams = useQuery({
    queryKey: ["teams", league, search],
    queryFn: () => api<TeamItem[]>("/teams", { query: { competition: search ? undefined : league, search: search || undefined, limit: 60 } }),
  });
  return (
    <>
      <PageHeader title="Teams" description="Form, ratings and results for every club we track. Tap a crest to open the team." />
      <div className="space-y-3 mb-6">
        <div className="relative sm:w-80">
          <Icon name="search" size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-4" />
          <input className="input pl-11" placeholder="Search all teams" aria-label="Search all teams" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {!search && (
          <Segmented variant="chips" label="League" value={league} onChange={setLeague} className="fade-edges -mx-4 px-4 sm:mx-0 sm:px-0"
                     options={(comps.data ?? []).map((c) => ({ value: c.code, label: c.name }))} />
        )}
      </div>
      {teams.isLoading ? <Card><Loading rows={4} /></Card> : teams.isError ? <ErrorState error={teams.error} onRetry={teams.refetch} /> : !teams.data?.length ? (
        <Card><Empty title="No teams found" icon="shield">Try a different search or league.</Empty></Card>
      ) : (
        <ul className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-3 sm:gap-4">
          {teams.data.map((t, i) => (
            <li key={t.id} className="animate-fade-up" style={{ animationDelay: `${Math.min(i, 20) * 20}ms` }}>
              <button onClick={() => onSelect(t.id)}
                      className="card w-full flex flex-col items-center gap-3 px-3 py-5 text-center transition-all hover:-translate-y-0.5 hover:bg-white/[0.08]">
                <TeamLogo name={t.name} src={t.logo_url} size={56} />
                <span className="text-[14px] font-bold leading-tight line-clamp-2">{t.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function TeamDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const q = useTeamStats(id);
  if (q.isLoading) return <Card><Loading rows={5} /></Card>;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data!;
  const l10 = d.form.last_10;
  const withXg = d.xg_trend.filter((x: any) => x.xg_for !== null).slice(-20);
  const hasXg = withXg.length >= 5;
  const trend = hasXg ? withXg : d.xg_trend.slice(-20);
  const elo = d.elo_history.length ? d.elo_history[d.elo_history.length - 1].rating : null;
  const eloPrev = d.elo_history.length > 10 ? d.elo_history[d.elo_history.length - 11].rating : null;
  return (
    <>
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink-3 hover:text-ink mb-4">
        <Icon name="chevronLeft" size={16} />All teams
      </button>

      <section className="card relative overflow-hidden p-6 sm:p-8 mb-6">
        <div aria-hidden className="absolute inset-0 bg-[radial-gradient(50%_90%_at_0%_0%,rgba(34,197,94,0.16),transparent_60%)]" />
        <div className="relative flex flex-col sm:flex-row items-center sm:items-center gap-5 text-center sm:text-left">
          <TeamLogo name={d.team.name} src={d.team.logo_url} size={96} />
          <div className="min-w-0">
            <h1 className="h-page">{d.team.name}</h1>
            <div className="mt-3 flex flex-wrap items-center justify-center sm:justify-start gap-3">
              <FormPills seq={d.form.sequence} max={10} size={22} />
              <span className="text-xs text-ink-3">last 10, newest first</span>
            </div>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <StatTile label="Points per game" value={num(l10?.points_per_game)} hint={l10 ? `${l10.wins} won · ${l10.draws} drawn · ${l10.losses} lost` : undefined} />
        <StatTile label="Goals (last 10)" value={l10 ? `${l10.goals_for}–${l10.goals_against}` : "—"} hint={`${l10?.clean_sheets ?? 0} clean sheets`} />
        <StatTile label="Home / away PPG" value={`${num(d.form.home?.points_per_game, 1)} / ${num(d.form.away?.points_per_game, 1)}`} hint="last 10 at each venue" />
        <StatTile label="Strength rating" value={elo ? num(elo, 0) : "—"} tone={elo && eloPrev ? (elo >= eloPrev ? "pos" : "neg") : undefined}
                  hint={elo && eloPrev ? `${elo >= eloPrev ? "▲" : "▼"} ${num(Math.abs(elo - eloPrev), 0)} over 10 matches` : "Elo rating"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2 mb-6">
        <Card title={hasXg ? "Chances created vs allowed (xG)" : "Goals scored vs conceded"} subtitle={`Last ${trend.length} matches`}>
          <div className="flex gap-4 text-xs text-ink-2 mb-3">
            <span className="flex items-center gap-1.5"><span className="h-1 w-4 rounded-full" style={{ background: SERIES[0] }} />{hasXg ? "Created" : "Scored"}</span>
            <span className="flex items-center gap-1.5"><span className="h-1 w-4 rounded-full" style={{ background: SERIES[1] }} />{hasXg ? "Allowed" : "Conceded"}</span>
          </div>
          <div className="h-52">
            <ResponsiveContainer>
              <LineChart data={trend.map((x: any) => ({ date: fmtDate(x.date), for: hasXg ? x.xg_for : x.goals_for, against: hasXg ? x.xg_against : x.goals_against }))} margin={{ left: -18, right: 8, top: 4 }}>
                <CartesianGrid stroke={AXIS.grid} vertical={false} />
                <XAxis dataKey="date" stroke={AXIS.stroke} fontSize={10} tickLine={false} axisLine={false} minTickGap={28} />
                <YAxis stroke={AXIS.stroke} fontSize={AXIS.fontSize} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip fmt={(v) => num(v)} />} />
                <Line isAnimationActive={false} dataKey="for" name={hasXg ? "Created" : "Scored"} stroke={SERIES[0]} strokeWidth={2.5} dot={{ r: 3, strokeWidth: 0, fill: SERIES[0] }} connectNulls />
                <Line isAnimationActive={false} dataKey="against" name={hasXg ? "Allowed" : "Conceded"} stroke={SERIES[1]} strokeWidth={2.5} dot={{ r: 3, strokeWidth: 0, fill: SERIES[1] }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Strength over time" subtitle="Elo rating within its league — higher is stronger">
          <div className="h-[236px]">
            <ResponsiveContainer>
              <LineChart data={d.elo_history} margin={{ left: -6, right: 8, top: 4 }}>
                <CartesianGrid stroke={AXIS.grid} vertical={false} />
                <XAxis dataKey="date" stroke={AXIS.stroke} fontSize={10} tickLine={false} axisLine={false} minTickGap={48} />
                <YAxis stroke={AXIS.stroke} fontSize={AXIS.fontSize} axisLine={false} tickLine={false} domain={["auto", "auto"]} width={42} />
                <Tooltip content={<ChartTooltip fmt={(v) => num(v, 0)} />} />
                <Line isAnimationActive={false} dataKey="rating" name="Rating" stroke={SERIES[2]} strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] items-start">
        <Card title="Results" subtitle="Most recent first" flush>
          <ul className="divide-soft max-h-[520px] overflow-y-auto">
            {d.matches.map((m: any) => (
              <li key={m.fixture_id} className="flex items-center gap-3 px-5 sm:px-6 py-3 text-[13.5px]">
                <FormPills seq={m.result} max={1} size={24} />
                <TeamLogo name={m.opponent} src={m.opponent_logo} size={24} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{m.venue === "H" ? "vs" : "at"} {m.opponent}</span>
                  <span className="block text-2xs text-ink-4">{fmtDate(m.date)}{m.xg_for !== null && ` · xG ${num(m.xg_for, 1)}–${num(m.xg_against, 1)}`}</span>
                </span>
                <span className="num font-extrabold">{m.goals_for}–{m.goals_against}</span>
              </li>
            ))}
          </ul>
        </Card>
        <div className="space-y-6">
          <Card title="Next matches">
            {d.upcoming.length === 0 ? <p className="text-[14px] text-ink-3">No upcoming fixtures yet.</p> : (
              <ul className="space-y-2">
                {d.upcoming.map((u: any) => (
                  <li key={u.fixture_id}>
                    <Link to={`/match/${u.fixture_id}`} className="flex items-center gap-3 rounded-2xl bg-white/[0.04] border border-white/[0.06] px-3.5 py-3 hover:bg-white/[0.08] transition-colors">
                      <span className="flex -space-x-1.5 shrink-0"><TeamLogo name={u.home_team} src={u.home_logo} size={24} /><TeamLogo name={u.away_team} src={u.away_logo} size={24} /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13.5px] font-semibold truncate">{u.home_team} v {u.away_team}</span>
                        <span className="block text-2xs text-ink-4">{fmtDateTime(u.kickoff_utc)}</span>
                      </span>
                      <Icon name="chevronRight" size={16} className="text-ink-4 shrink-0" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Availability">
            {d.availability.length === 0 ? <p className="text-[14px] text-ink-3">No injury or suspension reports stored.</p> : (
              <ul className="space-y-2">
                {d.availability.map((a: any, i: number) => (
                  <li key={i} className={cx("flex items-center justify-between gap-3 text-[13.5px]")}>
                    <span className="truncate">{a.player}</span><Pill tone={a.kind === "doubtful" ? "warn" : "neg"}>{a.kind}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
