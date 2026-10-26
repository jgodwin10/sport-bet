import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useFixtures, useHealth, usePredictions } from "../api/hooks";
import type { Fixture } from "../api/types";
import { Icon } from "../components/icons";
import { MatchRow } from "../components/MatchRow";
import { Card, cx, Empty, ErrorState, Loading, PageHeader, Pill, Segmented, Sheet, TeamLogo } from "../components/ui";
import { age, dayKey, fmtTime, odds, signedPct } from "../lib/format";
import { providerName, selectionLabel } from "../lib/language";

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
  const top = usePredictions({ qualifying_only: true, sort: "expected_value", page_size: 4 });
  const [day, setDay] = useState<string | null>(null);
  const [league, setLeague] = useState("all");
  const [search, setSearch] = useState("");
  const [help, setHelp] = useState(false);

  const all = fixtures.data?.items ?? [];
  const days = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of all) m.set(dayKey(f.kickoff_utc), (m.get(dayKey(f.kickoff_utc)) ?? 0) + 1);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [all]);
  useEffect(() => { if (day === null && days.length) setDay(days[0][0]); }, [days, day]);

  const ofDay = all.filter((f) => !day || dayKey(f.kickoff_utc) === day);
  const leagues = useMemo(() => {
    const m = new Map<string, { name: string; count: number }>();
    for (const f of ofDay) m.set(f.competition.code, { name: f.competition.name, count: (m.get(f.competition.code)?.count ?? 0) + 1 });
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

  const withPred = all.filter((f) => f.latest_prediction && f.status === "scheduled");
  const freshest = withPred.reduce<number | null>((acc, f) => {
    const h = f.latest_prediction!.odds_age_hours;
    return h === null ? acc : acc === null ? h : Math.min(acc, h);
  }, null);
  const lineupsSoon = withPred.filter((f) => f.latest_prediction!.lineup_status !== "confirmed"
    && new Date(f.kickoff_utc).getTime() - Date.now() < 3 * 3_600_000 && new Date(f.kickoff_utc).getTime() > Date.now());
  const valueCount = top.data?.total ?? 0;

  return (
    <>
      <PageHeader
        eyebrow={new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long" }).format(new Date())}
        title="Matches"
        description="Pick a day and a league, then tap a match to see our prediction and the reasons behind it."
        actions={<button className="btn" onClick={() => setHelp(true)}><Icon name="info" size={15} />How it works</button>}
      />

      {/* At-a-glance summary in plain words */}
      <div className="flex sm:grid sm:grid-cols-3 gap-3 mb-6 -mx-4 px-4 sm:mx-0 sm:px-0 scroll-x no-scrollbar snap-x snap-mandatory animate-fade-up [&>*]:snap-start [&>*]:min-w-[78%] sm:[&>*]:min-w-0">
        <SummaryTile icon="dashboard" title={`${all.length} upcoming matches`} text="in the next two weeks across tracked leagues" />
        <SummaryTile icon="sparkle" tone={valueCount ? "pos" : undefined}
                     title={valueCount ? `${valueCount} value ${valueCount === 1 ? "pick" : "picks"}` : "No value picks right now"}
                     text={valueCount ? "prices that beat our estimate and pass every check" : "our odds are close to the bookmakers' — that's normal"} />
        <SummaryTile icon="clock" tone={freshest !== null && freshest > 12 ? "warn" : undefined}
                     title={freshest === null ? "No odds yet" : `Odds updated ${age(freshest)}`}
                     text={freshest !== null && freshest > 12 ? "add a live odds key for fresher prices" : "prices refresh automatically"} />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_330px] items-start">
        <div className="min-w-0 space-y-5">
          {/* Day + league + search */}
          <div className="space-y-3">
            {days.length > 0 && (
              <Segmented variant="chips" label="Day" value={day ?? ""} onChange={(d) => { setDay(d); setLeague("all"); }} className="fade-edges -mx-4 px-4 sm:mx-0 sm:px-0"
                         options={days.map(([k, n]) => ({ value: k, label: dayChipLabel(k), count: n }))} />
            )}
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative sm:w-64 shrink-0">
                <Icon name="search" size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-4" />
                <input className="input pl-11" placeholder="Find a team" aria-label="Find a team" value={search} onChange={(e) => setSearch(e.target.value)} />
              </div>
              {leagues.length > 1 && (
                <Segmented variant="chips" label="League" value={league} onChange={setLeague} className="fade-edges -mx-4 px-4 sm:mx-0 sm:px-0 min-w-0"
                           options={[{ value: "all", label: "All leagues", count: ofDay.length }, ...leagues.map(([code, l]) => ({ value: code, label: l.name, count: l.count }))]} />
              )}
            </div>
          </div>

          {fixtures.isLoading ? <Card><Loading rows={6} /></Card>
            : fixtures.isError ? <ErrorState error={fixtures.error} onRetry={fixtures.refetch} />
            : visible.length === 0 ? (
              <Card><Empty title={all.length ? "No matches match your filters" : "No upcoming matches"} icon="search"
                           action={all.length ? <button className="btn" onClick={() => { setSearch(""); setLeague("all"); }}>Clear filters</button> : undefined}>
                {all.length ? "Try another day or league." : "New fixtures appear automatically once they are published."}
              </Empty></Card>
            ) : groups.map((list, gi) => (
              <section key={list[0].competition.code} className="card overflow-hidden animate-fade-up" style={{ animationDelay: `${gi * 40}ms` }}>
                <header className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3.5 border-b border-white/[0.06] bg-white/[0.02]">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="grid place-items-center h-7 w-7 rounded-lg bg-white/[0.07] text-ink-2"><Icon name="shield" size={14} /></span>
                    <div className="min-w-0">
                      <div className="text-[14px] font-bold truncate">{list[0].competition.name}</div>
                      <div className="text-2xs text-ink-3">{list[0].competition.country}</div>
                    </div>
                  </div>
                  <span className="text-xs text-ink-3 num">{list.length} {list.length === 1 ? "match" : "matches"}</span>
                </header>
                <div className="divide-soft">{list.map((f) => <MatchRow key={f.id} f={f} />)}</div>
              </section>
            ))}
        </div>

        <aside className="space-y-6 lg:sticky lg:top-24">
          <Card title="Value picks" subtitle="Bets where the price beats our estimate"
                action={<Link to="/predictions" className="btn btn-ghost btn-sm">See all<Icon name="chevronRight" size={14} /></Link>}>
            {top.isLoading ? <Loading rows={2} /> : top.isError ? <ErrorState error={top.error} /> : !top.data?.items.length ? (
              <div className="rounded-2xl bg-white/[0.04] border border-white/[0.06] p-4">
                <div className="flex items-center gap-2 font-semibold text-[14px]"><Icon name="ban" size={16} className="text-ink-3" />Nothing worth betting on</div>
                <p className="mt-1.5 text-[13px] text-ink-3 leading-relaxed">
                  No price currently beats our estimate by enough while passing every safety check. Holding back is part of the system.
                </p>
              </div>
            ) : (
              <ul className="space-y-2.5">
                {top.data.items.map((s) => (
                  <li key={s.selection_id}>
                    <Link to={`/match/${s.fixture_id}`} className="block rounded-2xl bg-white/[0.04] border border-white/[0.06] p-3.5 hover:bg-white/[0.07] transition-colors">
                      <div className="flex items-center gap-2 text-xs text-ink-3">
                        <TeamLogo name={s.home_team?.name ?? ""} src={s.home_team?.logo_url} size={16} />
                        <TeamLogo name={s.away_team?.name ?? ""} src={s.away_team?.logo_url} size={16} />
                        <span className="truncate">{s.match}</span>
                      </div>
                      <div className="mt-1.5 flex items-center justify-between gap-2">
                        <span className="text-[14px] font-bold truncate">{selectionLabel(s.market, s.selection, s.home_team?.name, s.away_team?.name)}</span>
                        <span className="num text-[15px] font-extrabold">{odds(s.odds)}</span>
                      </div>
                      <div className="mt-1 text-xs text-pos num">Value {signedPct(s.expected_value)}</div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Good to know">
            <ul className="space-y-4 text-[13.5px]">
              <li className="flex gap-3">
                <span className={cx("grid place-items-center h-9 w-9 rounded-xl shrink-0", lineupsSoon.length ? "bg-warn-soft text-warn" : "bg-white/[0.06] text-ink-3")}><Icon name="users" size={16} /></span>
                <div className="min-w-0">
                  <div className="font-semibold">{lineupsSoon.length ? `${lineupsSoon.length} kick off soon without lineups` : "No lineups pending"}</div>
                  <div className="text-xs text-ink-3 truncate">
                    {lineupsSoon.length ? lineupsSoon.slice(0, 2).map((f) => `${f.home_team.name}–${f.away_team.name} ${fmtTime(f.kickoff_utc)}`).join(" · ") : "Predictions update when official lineups arrive."}
                  </div>
                </div>
              </li>
              <li className="flex gap-3">
                <span className="grid place-items-center h-9 w-9 rounded-xl shrink-0 bg-white/[0.06] text-ink-3"><Icon name="shield" size={16} /></span>
                <div>
                  <div className="font-semibold">We often say “no bet”</div>
                  <div className="text-xs text-ink-3 leading-relaxed">Bookmakers are hard to beat. A recommendation only appears when the evidence is strong.</div>
                </div>
              </li>
            </ul>
          </Card>
          <SourcesCard />
        </aside>
      </div>

      <Sheet open={help} onClose={() => setHelp(false)} title="How Matchline works"
             footer={<button className="btn btn-primary w-full" onClick={() => setHelp(false)}>Got it</button>}>
        <ol className="space-y-5">
          {[
            ["Estimate the chances", "Three statistical models (goals, team ratings, recent form) plus the bookmaker market are blended into one probability for each result."],
            ["Compare with the price", "If a bookmaker's odds imply a lower chance than ours, the bet may have value. We show how much."],
            ["Check the evidence", "Data confidence drops when information is old, thin or missing (like lineups). Low confidence means no recommendation."],
            ["Prove it on history", "Every model is tested on past seasons it has never seen. The Track record page shows the honest result — including losses."],
          ].map(([t, d], i) => (
            <li key={t} className="flex gap-4">
              <span className="grid place-items-center h-8 w-8 rounded-full bg-brand-soft text-brand-strong text-sm font-extrabold shrink-0">{i + 1}</span>
              <div><div className="font-bold text-[15px]">{t}</div><p className="mt-1 text-[13.5px] text-ink-2 leading-relaxed">{d}</p></div>
            </li>
          ))}
        </ol>
      </Sheet>
    </>
  );
}

function SummaryTile({ icon, title, text, tone }: { icon: Parameters<typeof Icon>[0]["name"]; title: string; text: string; tone?: "pos" | "warn" }) {
  return (
    <div className="card flex items-center gap-3.5 px-4 py-4 min-w-0">
      <span className={cx("grid place-items-center h-11 w-11 rounded-2xl shrink-0",
        tone === "pos" ? "bg-pos-soft text-pos" : tone === "warn" ? "bg-warn-soft text-warn" : "bg-white/[0.07] text-ink-2")}>
        <Icon name={icon} size={19} />
      </span>
      <div className="min-w-0">
        <div className="text-[15px] font-bold leading-tight">{title}</div>
        <div className="mt-0.5 text-xs text-ink-3 leading-snug">{text}</div>
      </div>
    </div>
  );
}

function SourcesCard() {
  const h = useHealth();
  if (!h.data) return null;
  return (
    <Card title="Data sources">
      <ul className="space-y-2.5 text-[13px]">
        {h.data.providers.map((p: any) => (
          <li key={p.name} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 min-w-0 text-ink-2">
              <span className={cx("h-2 w-2 rounded-full shrink-0", p.configured ? "bg-pos" : "bg-white/20")} />
              <span className="truncate">{providerName(p.name)}</span>
            </span>
            <Pill tone={p.configured ? "pos" : "neutral"}>{p.configured ? "Active" : "Needs key"}</Pill>
          </li>
        ))}
      </ul>
    </Card>
  );
}
