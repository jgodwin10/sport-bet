import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useCompetitions, useTeamStats } from "../api/hooks";
import { Icon } from "../components/icons";
import {
  Card, chart, ChartTooltip, Empty, ErrorState, FormPills, Legend, Loading, PageHeader, Pill, ResultLine, SearchInput, StatTile,
  TeamLogo,
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
      <PageHeader title="Teams" description="Form, ratings and results for every club we track." />
      <div className="mb-6 flex gap-2">
        <SearchInput value={search} onChange={setSearch} placeholder="Search all teams" className="flex-1" />
        {!search && (
          <select className="input w-auto max-w-[45%] sm:max-w-[240px]" aria-label="League" value={league} onChange={(e) => setLeague(e.target.value)}>
            {(comps.data ?? []).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        )}
      </div>
      {teams.isLoading ? <Card><Loading rows={4} /></Card> : teams.isError ? <ErrorState error={teams.error} onRetry={teams.refetch} /> : !teams.data?.length ? (
        <Card><Empty title="No teams found" icon="shield">Try a different search or league.</Empty></Card>
      ) : (
        <ul className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-2">
          {teams.data.map((t) => (
            <li key={t.id} className="min-w-0">
              <button onClick={() => onSelect(t.id)}
                      className="w-full h-full flex flex-col items-center gap-2 rounded-2xl px-2 py-4 text-center transition-colors hover:bg-surface hover:shadow-sm">
                <TeamLogo name={t.name} src={t.logo_url} size={44} />
                <span className="w-full text-[13px] font-medium leading-tight line-clamp-2 break-words">{t.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function TeamDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const c = chart();
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
      <button onClick={onBack} className="mb-5 inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <Icon name="chevronLeft" size={15} />All teams
      </button>

      <header className="mb-6 flex items-center gap-4 min-w-0">
        <TeamLogo name={d.team.name} src={d.team.logo_url} size={60} />
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight leading-tight">{d.team.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <FormPills seq={d.form.sequence} max={10} size={18} />
            <span className="text-xs text-ink-4">newest first</span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <StatTile label="Points per game" value={num(l10?.points_per_game)} hint={l10 ? `${l10.wins}W ${l10.draws}D ${l10.losses}L, last 10` : undefined} />
        <StatTile label="Goals, last 10" value={l10 ? `${l10.goals_for}–${l10.goals_against}` : "—"} hint={`${l10?.clean_sheets ?? 0} clean sheets`} />
        <StatTile label="Home / away PPG" value={`${num(d.form.home?.points_per_game, 1)} / ${num(d.form.away?.points_per_game, 1)}`} />
        <StatTile label="Strength rating" value={elo ? num(elo, 0) : "—"} tone={elo && eloPrev ? (elo >= eloPrev ? "pos" : "neg") : undefined}
                  hint={elo && eloPrev ? `${elo >= eloPrev ? "+" : "−"}${num(Math.abs(elo - eloPrev), 0)} over 10 matches` : "Elo rating"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2 mb-6">
        <Card title={hasXg ? "Chances created vs allowed (xG)" : "Goals scored vs conceded"} subtitle={`Last ${trend.length} matches`}>
          <Legend items={[[hasXg ? "Created" : "Scored", c.series[0]], [hasXg ? "Allowed" : "Conceded", c.series[1]]]} />
          <div className="h-48">
            <ResponsiveContainer>
              <LineChart data={trend.map((x: any) => ({ date: fmtDate(x.date), for: hasXg ? x.xg_for : x.goals_for, against: hasXg ? x.xg_against : x.goals_against }))} margin={{ left: -24, right: 4, top: 4 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="date" stroke={c.axis} fontSize={10} tickLine={false} axisLine={false} minTickGap={32} />
                <YAxis stroke={c.axis} fontSize={c.fontSize} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip fmt={(v) => num(v)} />} />
                <Line isAnimationActive={false} dataKey="for" name={hasXg ? "Created" : "Scored"} stroke={c.series[0]} strokeWidth={2} dot={false} connectNulls />
                <Line isAnimationActive={false} dataKey="against" name={hasXg ? "Allowed" : "Conceded"} stroke={c.series[1]} strokeWidth={2} dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Strength over time" subtitle="Elo rating within its league; higher is stronger">
          <div className="h-[212px]">
            <ResponsiveContainer>
              <LineChart data={d.elo_history} margin={{ left: 0, right: 4, top: 4 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="date" stroke={c.axis} fontSize={10} tickLine={false} axisLine={false} minTickGap={48} tickFormatter={(v) => fmtDate(v)} />
                <YAxis stroke={c.axis} fontSize={c.fontSize} axisLine={false} tickLine={false} domain={["auto", "auto"]} width={36} tickFormatter={(v) => num(v, 0)} />
                <Tooltip content={<ChartTooltip fmt={(v) => num(v, 0)} />} />
                <Line isAnimationActive={false} dataKey="rating" name="Rating" stroke={c.series[2]} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] items-start">
        <Card title="Results" subtitle="Most recent first" flush>
          <ul className="divide-soft max-h-[520px] overflow-y-auto">
            {d.matches.map((m: any) => (
              <ResultLine key={m.fixture_id} m={m} extra={m.xg_for !== null ? ` · xG ${num(m.xg_for, 1)}–${num(m.xg_against, 1)}` : undefined} />
            ))}
          </ul>
        </Card>
        <div className="space-y-6 min-w-0">
          <Card title="Next matches" flush>
            {d.upcoming.length === 0 ? <p className="px-4 sm:px-5 pb-5 text-sm text-ink-3">No upcoming fixtures yet.</p> : (
              <ul className="divide-soft">
                {d.upcoming.map((u: any) => (
                  <li key={u.fixture_id}>
                    <Link to={`/match/${u.fixture_id}`} className="flex items-center gap-3 px-4 sm:px-5 py-3 hover:bg-subtle/60 transition-colors">
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm truncate">{u.home_team} v {u.away_team}</span>
                        <span className="block text-xs text-ink-4">{fmtDateTime(u.kickoff_utc)}</span>
                      </span>
                      <Icon name="chevronRight" size={15} className="text-ink-4 shrink-0" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Availability">
            {d.availability.length === 0 ? <p className="text-sm text-ink-3">No injury or suspension reports.</p> : (
              <ul className="space-y-2">
                {d.availability.map((a: any, i: number) => (
                  <li key={i} className="flex items-center justify-between gap-3 text-sm">
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
