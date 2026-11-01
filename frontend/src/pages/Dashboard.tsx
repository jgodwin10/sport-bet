import { useEffect, useMemo, useState } from "react";
import { useFixtures } from "../api/hooks";
import type { Fixture } from "../api/types";
import { MatchRow } from "../components/MatchRow";
import { Card, Empty, ErrorState, Loading, PageHeader, SearchInput, Segmented } from "../components/ui";
import { dayKey } from "../lib/format";

const isoDay = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

function dayChipLabel(key: string): string {
  const today = dayKey(new Date().toISOString());
  const tomorrow = dayKey(new Date(Date.now() + 86_400_000).toISOString());
  if (key === today) return "Today";
  if (key === tomorrow) return "Tomorrow";
  const d = new Date(`${key}T12:00:00`);
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" }).format(d);
}

export default function Dashboard() {
  const fixtures = useFixtures({ date_from: isoDay(0), date_to: isoDay(14), page_size: 200 });
  const [day, setDay] = useState<string | null>(null);
  const [league, setLeague] = useState("all");
  const [search, setSearch] = useState("");

  const all = fixtures.data?.items ?? [];
  const days = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of all) m.set(dayKey(f.kickoff_utc), (m.get(dayKey(f.kickoff_utc)) ?? 0) + 1);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [all]);
  useEffect(() => { if (day === null && days.length) setDay(days[0][0]); }, [days, day]);

  const ofDay = all.filter((f) => !day || dayKey(f.kickoff_utc) === day);
  const leagues = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of ofDay) m.set(f.competition.code, f.competition.name);
    return [...m.entries()];
  }, [ofDay]);
  const q = search.trim().toLowerCase();
  const visible = ofDay.filter((f) => (league === "all" || f.competition.code === league)
    && (!q || f.home_team.name.toLowerCase().includes(q) || f.away_team.name.toLowerCase().includes(q)));
  const groups = useMemo(() => {
    const m = new Map<string, Fixture[]>();
    for (const f of visible) m.set(f.competition.code, [...(m.get(f.competition.code) ?? []), f]);
    return [...m.values()];
  }, [visible]);

  return (
    <>
      <PageHeader title="Matches" description="Our chances for every upcoming match. Tap one for the full picture." />

      <div className="space-y-3 mb-6">
        {days.length > 0 && (
          <Segmented variant="chips" label="Day" value={day ?? ""} onChange={(d) => { setDay(d); setLeague("all"); }}
                     className="-mx-4 px-4 sm:mx-0 sm:px-0"
                     options={days.map(([k, n]) => ({ value: k, label: dayChipLabel(k), count: n }))} />
        )}
        <div className="flex gap-2">
          <SearchInput value={search} onChange={setSearch} className="flex-1" />
          {leagues.length > 1 && (
            <select className="input w-auto max-w-[45%] sm:max-w-[240px]" aria-label="League" value={league} onChange={(e) => setLeague(e.target.value)}>
              <option value="all">All leagues</option>
              {leagues.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          )}
        </div>
      </div>

      {fixtures.isLoading ? <Card><Loading rows={6} /></Card>
        : fixtures.isError ? <ErrorState error={fixtures.error} onRetry={fixtures.refetch} />
        : visible.length === 0 ? (
          <Card><Empty title={all.length ? "No matches found" : "No upcoming matches"} icon="search"
                       action={all.length ? <button className="btn" onClick={() => { setSearch(""); setLeague("all"); }}>Clear filters</button> : undefined}>
            {all.length ? "Try another day or league." : "New fixtures appear automatically once they are published."}
          </Empty></Card>
        ) : (
          <div className="space-y-6">
            {groups.map((list) => (
              <section key={list[0].competition.code}>
                <h2 className="mb-2 flex items-baseline gap-2 px-1 min-w-0">
                  <span className="text-sm font-semibold truncate">{list[0].competition.name}</span>
                  <span className="text-xs text-ink-4 truncate">{list[0].competition.country}</span>
                </h2>
                <div className="card overflow-hidden divide-soft">{list.map((f) => <MatchRow key={f.id} f={f} />)}</div>
              </section>
            ))}
          </div>
        )}
    </>
  );
}
