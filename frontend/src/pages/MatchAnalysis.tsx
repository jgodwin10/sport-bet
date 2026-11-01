import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getToken } from "../api/client";
import { useAdminAction, useAiAnalysis, useAnalysis, useGenerateAiAnalysis, useMe } from "../api/hooks";
import type { AiAnalysisContent, Analysis, FormSummary, PredictionDetail, PredictionSelection, RecentMatch } from "../api/types";
import { Icon } from "../components/icons";
import Lineups from "../components/Lineups";
import {
  Card, chart, ChartTooltip, cx, Disclosure, Empty, ErrorState, Figures, FormPills, Freshness, InfoTip,
  KeyValue, Legend, Loading, OutcomeBar, Pill, ReliabilityBadge, ResultLine, SectionTitle, Segmented, TeamLogo,
} from "../components/ui";
import { fmtDate, fmtDateTime, fmtTime, num, odds, pct, signedPct } from "../lib/format";
import { aiProviderName, bookmakerName, CONFIDENCE, friendlyReason, GLOSSARY, outcomeLabel, plainFacts, selectionLabel, verdict } from "../lib/language";

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "stats", label: "Stats" },
  { value: "lineups", label: "Lineups" },
  { value: "odds", label: "Odds" },
] as const;
type Tab = (typeof TABS)[number]["value"];

export default function MatchAnalysis() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.value === params.get("tab"))?.value ?? "overview") as Tab;
  const q = useAnalysis(id);

  if (q.isLoading) return <Card><Loading label="Loading match" rows={5} /></Card>;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const a = q.data!;
  const p = a.prediction;

  return (
    <>
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink mb-4">
        <Icon name="chevronLeft" size={15} />Matches
      </Link>
      <Hero a={a} />
      <div className="sticky top-[calc(3.5rem+env(safe-area-inset-top,0px))] z-20 -mx-4 sm:-mx-6 mt-6 mb-6 px-4 sm:px-6 bg-bg/90 backdrop-blur-md">
        <Segmented variant="tabs" label="Match sections" value={tab} options={[...TABS]}
                   onChange={(v) => setParams(v === "overview" ? {} : { tab: v }, { replace: true })} />
      </div>
      <div className="space-y-6" key={tab}>
        {tab === "overview" && (p ? <Overview a={a} p={p} /> : <NoPrediction />)}
        {tab === "stats" && <Stats a={a} />}
        {tab === "lineups" && <Lineups a={a} />}
        {tab === "odds" && (p ? <OddsValue a={a} p={p} /> : <NoPrediction />)}
      </div>
      <p className="mt-10 text-center text-xs text-ink-4">{a.disclaimer}</p>
    </>
  );
}

function NoPrediction() {
  return (
    <Card><Empty title="No prediction for this match yet" icon="clock">
      Predictions appear for matches in the next two weeks, once the league has enough history.
    </Empty></Card>
  );
}

/* -------------------------------------------------------------------- hero */
function Hero({ a }: { a: Analysis }) {
  const f = a.fixture;
  const p = a.prediction;
  const me = useMe(!!getToken());
  const action = useAdminAction();
  const r = p?.markets["1x2"];
  const lead = r ? (["home", "draw", "away"] as const).reduce((x, y) => (r[y] > r[x] ? y : x)) : null;
  const conf = p ? CONFIDENCE[p.reliability.label] : null;
  return (
    <section className="card relative overflow-hidden px-4 pt-5 pb-5 sm:px-8 sm:pt-7 text-center">
      <div aria-hidden className="pointer-events-none absolute inset-0"
           style={{ background: "radial-gradient(420px 220px at 0% 0%, rgb(var(--home) / 0.14), transparent 70%), radial-gradient(420px 220px at 100% 0%, rgb(var(--away) / 0.12), transparent 70%)" }} />
      <div className="relative">
      <div className="inline-flex items-center gap-2 rounded-full border border-line bg-bg/50 px-3 py-1 text-xs font-semibold text-ink-3">
        <span className="text-ink-2">{f.competition.name}</span><span className="text-ink-4">·</span>{fmtDateTime(f.kickoff_utc)}
      </div>

      <div className="mt-5 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-3 sm:gap-8">
        {[f.home_team, null, f.away_team].map((t) => t ? (
          <div key={t.id} className="flex flex-col items-center min-w-0">
            <span className="grid place-items-center rounded-full bg-bg/50 p-2 ring-1 ring-line">
              <TeamLogo name={t.name} src={t.logo_url} size={52} className="sm:!w-[68px] sm:!h-[68px]" />
            </span>
            <h1 className="mt-3 text-[15px] sm:text-xl font-extrabold leading-snug">{t.name}</h1>
          </div>
        ) : (
          <div key="mid" className="pt-3 sm:pt-5">
            {f.score ? (
              <div className="text-3xl sm:text-5xl font-extrabold num">{f.score.home}<span className="text-ink-4 mx-1.5">–</span>{f.score.away}</div>
            ) : (
              <div className="leading-tight">
                <div className="text-2xl sm:text-4xl font-extrabold num">{fmtTime(f.kickoff_utc).split(" ")[0]}</div>
                <div className="mt-1 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-4">{fmtTime(f.kickoff_utc).split(" ")[1] ?? "Kickoff"}</div>
              </div>
            )}
          </div>
        ))}
      </div>

      {p && r && lead && (
        <div className="mx-auto mt-6 max-w-md">
          <p className="text-sm text-ink-3">
            Most likely <span className="font-bold text-ink">{outcomeLabel(lead, f.home_team.name, f.away_team.name)}</span>{" "}
            <span className="ml-1 rounded-lg bg-brand/15 px-2 py-0.5 num font-extrabold text-brand">{pct(r[lead], 0)}</span>
          </p>
          <div className="mt-3 text-left"><OutcomeBar size="lg" p={r} labels={["Home", "Draw", "Away"]} /></div>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-ink-3">
        {p && <span className={cx("font-medium", p.classification === "consider" ? "text-pos" : p.classification === "high_uncertainty" ? "text-warn" : "text-ink-2")}>{verdict(p.classification).label}</span>}
        {p && conf && <span title={GLOSSARY.confidence}>Confidence {conf.label.toLowerCase()}</span>}
        <span>{p?.lineup_status === "confirmed" ? "Lineups confirmed" : "Lineups not out"}</span>
        <Freshness hours={a.odds.age_hours} />
        {me.data?.role === "admin" && (
          <button className="btn btn-sm" disabled={action.isPending} onClick={() => action.mutate({ path: `/admin/refresh-fixture/${f.id}` })}>
            <Icon name="refresh" size={13} />{action.isPending ? "Queuing…" : action.isSuccess ? "Queued" : "Refresh"}
          </button>
        )}
      </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- overview */
function Overview({ a, p }: { a: Analysis; p: PredictionDetail }) {
  const f = a.fixture;
  const m = p.markets;
  const v = verdict(p.classification);
  const qual = p.selections.filter((s) => s.qualifies);
  const best = [...p.selections].sort((x, y) => y.expected_value - x.expected_value)[0];
  const facts = plainFacts(p.explanations, f.home_team.name, f.away_team.name).slice(0, 5);
  const topScores = m.correct_score?.slice(0, 3) ?? [];
  const goals: [string, string][] = [];
  if (m.totals?.["2.5"]) goals.push(["Over 2.5 goals", pct(m.totals["2.5"].over, 0)]);
  if (m.btts) goals.push(["Both teams score", pct(m.btts.yes, 0)]);
  if (m.expected_goals) goals.push(["Expected goals", `${num(m.expected_goals.home, 1)} – ${num(m.expected_goals.away, 1)}`]);
  if (topScores[0]) goals.push(["Likeliest score", `${topScores[0].home}–${topScores[0].away}`]);
  goals.push([`${f.home_team.name} or draw`, pct(m.double_chance["1X"], 0)], [`${f.away_team.name} or draw`, pct(m.double_chance.X2, 0)]);

  return (
    <>
      <section className={cx("card relative overflow-hidden p-4 sm:p-6", qual.length && "!border-brand/35")}>
        {qual.length > 0 && <span aria-hidden className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-brand to-brand-2" />}
        <div className="eyebrow">Our verdict</div>
        <h2 className={cx("mt-1.5 text-xl font-extrabold", qual.length ? "text-pos" : v.tone === "warn" && "text-warn")}>{v.label}</h2>
        <p className="mt-1 text-sm text-ink-3">{v.explain}</p>
        {qual.length > 0 ? (
          <div className="mt-4 space-y-3">
            {qual.map((s) => <PickRow key={s.id} s={s} home={f.home_team.name} away={f.away_team.name} />)}
          </div>
        ) : best ? (
          <div className="mt-4 rounded-xl bg-subtle p-4">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 text-sm"><span className="text-ink-3">Closest bet: </span><span className="font-medium">{selectionLabel(best.market, best.selection, f.home_team.name, f.away_team.name)}</span></span>
              <span className="shrink-0 font-semibold num">{odds(best.odds)}</span>
            </div>
            <ul className="mt-2 space-y-1">
              {best.rejection_reasons.slice(0, 2).map((r) => <li key={r} className="text-[13px] text-ink-3">· {friendlyReason(r)}</li>)}
            </ul>
          </div>
        ) : null}
      </section>

      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <Card title="Why we think this">
          <ul className="space-y-3">
            {facts.map((e, i) => (
              <li key={i} className="flex gap-3 text-sm text-ink-2">
                <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-4" />{e.text}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Goals & more">
          <KeyValue className="-my-2.5" items={goals} />
        </Card>
      </div>

      <AiAnalysisCard a={a} p={p} />

      <div>
        <SectionTitle>Model details</SectionTitle>
        <div className="card overflow-hidden divide-soft">
          <ModelBreakdown a={a} p={p} />
          <Confidence p={p} />
          <AllReasons p={p} />
          <ScoreGrid a={a} p={p} />
          <AsianHandicap p={p} />
          <History a={a} />
          <DataSources a={a} />
        </div>
      </div>
    </>
  );
}

function PickRow({ s, home, away }: { s: PredictionSelection; home: string; away: string }) {
  return (
    <div className="rounded-xl border border-pos/30 bg-pos/5 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 font-semibold">{selectionLabel(s.market, s.selection, home, away)}</span>
        <span className="shrink-0 text-xl font-extrabold num">{odds(s.odds)}</span>
      </div>
      <Figures className="mt-3" items={[["Our chance", pct(s.probability, 0)], ["Bookmaker", pct(s.implied_probability, 0)], ["Value", signedPct(s.expected_value), "pos"]]} />
      <p className="mt-3 text-xs text-ink-3">Best price at {bookmakerName(s.bookmaker)}. Value is an estimate, not a promise.</p>
    </div>
  );
}

/* ------------------------------------------------------------- ai analysis */
const NEWS_TONE = { confirmed: "pos", reported: "warn", rumour: "neutral" } as const;

function AiAnalysisCard({ a, p }: { a: Analysis; p: PredictionDetail }) {
  const f = a.fixture;
  const q = useAiAnalysis(f.id);
  const gen = useGenerateAiAnalysis(f.id);
  const signedIn = !!getToken();
  if (!q.data?.configured) return null;
  const { analysis, available, note } = q.data;
  const c = analysis?.status === "ok" ? analysis.content : null;
  const stale = !!analysis && analysis.prediction_id !== p.id;
  const favours = (k: AiAnalysisContent["key_factors"][number]["favours"]) =>
    k === "home" ? f.home_team.name : k === "away" ? f.away_team.name : k === "draw" ? "Draw" : null;

  const button = available && signedIn && (
    <button className="btn btn-sm" disabled={gen.isPending} onClick={() => gen.mutate()}>
      <Icon name={gen.isPending ? "clock" : "sparkle"} size={13} />
      {gen.isPending ? "Analysing…" : c ? (stale ? "Update" : "Regenerate") : "Generate"}
    </button>
  );

  return (
    <Card title={<><Icon name="sparkle" size={15} />AI analysis</>} info={note}
          subtitle={analysis ? `${aiProviderName(analysis.provider)} · ${fmtDateTime(analysis.created_at)}${stale ? " · earlier prediction" : ""}`
                             : "Team news and context, written from a web search"}
          action={button}>
      {gen.isError && <p className="mb-3 text-[13px] text-neg">{(gen.error as Error).message}</p>}
      {!analysis ? (
        <p className="text-sm text-ink-3">
          {!available ? "AI analysis is only written before kickoff." : signedIn ? "No AI analysis yet. Generate one to add team news." : "No AI analysis yet. Sign in to generate one."}
        </p>
      ) : !c ? (
        <p className="text-sm text-ink-3">The last attempt failed: {analysis.error ?? "unknown error"}</p>
      ) : (
        <div className="space-y-5 text-sm">
          <p className="text-xs text-ink-3">Not validated, and it does not change our numbers. AI confidence: {c.confidence}.</p>
          {c.summary && <p className="text-[15px] text-ink-2 whitespace-pre-line">{c.summary}</p>}

          {c.probability_view && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div><div className="label mb-2">Our model</div><OutcomeBar p={p.markets["1x2"]} labels={["Home", "Draw", "Away"]} /></div>
              <div><div className="label mb-2">AI view</div><OutcomeBar p={c.probability_view} labels={["Home", "Draw", "Away"]} /></div>
            </div>
          )}
          {c.model_assessment && <p className="rounded-xl bg-subtle p-3.5 text-ink-2">{c.model_assessment}</p>}

          {c.key_factors.length > 0 && (
            <div>
              <div className="label mb-2">Key factors</div>
              <ul className="space-y-3">
                {c.key_factors.map((k, i) => (
                  <li key={i}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{k.title}</span>
                      {favours(k.favours) && <Pill>Favours {favours(k.favours)}</Pill>}
                      {k.basis !== "model" && <Pill>from news</Pill>}
                    </div>
                    <p className="mt-0.5 text-ink-3">{k.detail}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {c.team_news.length > 0 && (
            <div>
              <div className="label mb-2">Team news</div>
              <ul className="space-y-2">
                {c.team_news.map((n, i) => (
                  <li key={i} className="flex items-start gap-2 text-ink-2">
                    <Pill tone={NEWS_TONE[n.status]} className="shrink-0">{n.status}</Pill>
                    <span className="min-w-0"><span className="font-medium text-ink">{n.team}:</span> {n.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {c.risks.length > 0 && (
            <div>
              <div className="label mb-2">What could make this wrong</div>
              <ul className="space-y-1">{c.risks.map((r, i) => <li key={i} className="text-ink-3">· {r}</li>)}</ul>
            </div>
          )}

          {analysis.sources.length > 0 && (
            <div>
              <div className="label mb-2">Sources</div>
              <ul className="space-y-1.5">
                {analysis.sources.map((s) => (
                  <li key={s.uri} className="min-w-0">
                    <a href={s.uri} target="_blank" rel="noopener noreferrer nofollow"
                       className="inline-flex items-start gap-1.5 text-[13px] text-ink-2 underline-offset-2 hover:underline break-all">
                      <Icon name="external" size={12} className="mt-1 shrink-0" />{s.title}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------- stats */
const FORM_ROWS: [string, keyof FormSummary, "last_5" | "last_10" | "last_15", number][] = [
  ["Points per game, last 5", "points_per_game", "last_5", 2],
  ["Points per game, last 10", "points_per_game", "last_10", 2],
  ["Goals scored, last 10", "goals_for", "last_10", 0],
  ["Goals conceded, last 10", "goals_against", "last_10", 0],
  ["xG created per game", "xg_for", "last_10", 2],
  ["xG allowed per game", "xg_against", "last_10", 2],
  ["Shots on target per game", "sot_for", "last_10", 1],
  ["Clean sheets, last 10", "clean_sheets", "last_10", 0],
];

function Stats({ a }: { a: Analysis }) {
  const c = chart();
  const f = a.fixture;
  const hs = a.form.home.summary, as = a.form.away.summary;
  const fmt = (s: FormSummary | null, key: keyof FormSummary, d: number) => (typeof s?.[key] === "number" ? num(s[key] as number, d) : "—");
  const usesXg = (hs.last_10?.xg_coverage ?? 0) > 0.5;
  const data = Array.from({ length: 10 }, (_, i) => {
    const hm = a.form.home.matches[9 - i], am = a.form.away.matches[9 - i];
    const val = (m?: RecentMatch) => (m ? (usesXg ? m.xg_for ?? m.goals_for : m.goals_for) : null);
    return { n: `${10 - i}`, home: val(hm), away: val(am) };
  });
  const ctx = a.standings_context;
  return (
    <>
      <Card title="Form" flush>
        <table className="table table-fixed">
          <colgroup><col /><col className="w-[84px] sm:w-[120px]" /><col className="w-[84px] sm:w-[120px]" /></colgroup>
          <thead>
            <tr>
              <th className="pl-4 sm:pl-5">Last 5</th>
              {[[f.home_team, hs.sequence], [f.away_team, as.sequence]].map(([t, seq]: any, i) => (
                <th key={t.id} className={cx("!px-1 text-center", i === 1 && "!pr-3 sm:!pr-5")}>
                  <div className="flex flex-col items-center gap-1.5">
                    <TeamLogo name={t.name} src={t.logo_url} size={22} />
                    <FormPills seq={seq} size={12} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {FORM_ROWS.map(([label, key, w, d]) => {
              const h = hs[w]?.[key], aw = as[w]?.[key];
              const better = typeof h === "number" && typeof aw === "number" && h !== aw
                ? ((key === "goals_against" || key === "xg_against") ? (h < aw ? "h" : "a") : (h > aw ? "h" : "a")) : null;
              return (
                <tr key={label}>
                  <td className="pl-4 sm:pl-5 text-ink-3">{label}</td>
                  <td className={cx("num text-center", better === "h" ? "font-semibold text-ink" : "text-ink-3")}>{fmt(hs[w], key, d)}</td>
                  <td className={cx("num text-center pr-4 sm:pr-5", better === "a" ? "font-semibold text-ink" : "text-ink-3")}>{fmt(as[w], key, d)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <Card title={usesXg ? "Chances created (xG)" : "Goals scored"} subtitle="Last 10 matches, oldest to newest">
          <Legend items={[[f.home_team.name, c.series[0]], [f.away_team.name, c.series[1]]]} />
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={data} barGap={2} margin={{ left: -24, right: 0, top: 4 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="n" stroke={c.axis} fontSize={c.fontSize} tickLine={false} axisLine={false} />
                <YAxis stroke={c.axis} fontSize={c.fontSize} tickLine={false} axisLine={false} />
                <Tooltip content={<ChartTooltip fmt={(v) => num(v)} />} cursor={{ fill: color0(c.grid) }} />
                <Bar isAnimationActive={false} dataKey="home" name={f.home_team.name} fill={c.series[0]} radius={[3, 3, 0, 0]} maxBarSize={12} />
                <Bar isAnimationActive={false} dataKey="away" name={f.away_team.name} fill={c.series[1]} radius={[3, 3, 0, 0]} maxBarSize={12} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Head-to-head" subtitle="Background only, not used by the model" flush>
          {a.head_to_head.length === 0 ? <p className="px-4 sm:px-5 pb-5 text-sm text-ink-3">These teams haven't met in our records.</p> : (
            <ul className="divide-soft">
              {a.head_to_head.slice(0, 6).map((m, i) => (
                <li key={i} className={cx("grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 px-4 sm:px-5 py-2.5 text-sm", m.age_days > 1095 && "opacity-50")}>
                  <span className="truncate text-right">{m.home}</span>
                  <span className="text-center">
                    <span className="block font-semibold num">{m.home_goals}–{m.away_goals}</span>
                    <span className="block text-[10px] text-ink-4">{fmtDate(m.date)}</span>
                  </span>
                  <span className="truncate">{m.away}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2 items-start">
        <RecentList team={f.home_team} matches={a.form.home.matches.slice(0, 6)} position={ctx.home} />
        <RecentList team={f.away_team} matches={a.form.away.matches.slice(0, 6)} position={ctx.away} />
      </div>

      <TeamNews a={a} />
    </>
  );
}

const color0 = (grid: string) => grid.replace("rgb(", "rgba(").replace(")", ", 0.5)");

function RecentList({ team, matches, position }: { team: { name: string; logo_url?: string | null }; matches: RecentMatch[]; position: Record<string, number | string> | null }) {
  return (
    <Card title={<span className="flex items-center gap-2 min-w-0"><TeamLogo name={team.name} src={team.logo_url} size={20} /><span className="truncate">{team.name}</span></span>}
          action={position ? <span className="text-xs text-ink-3 num">{String(position.position)}{ordinal(Number(position.position))} · {String(position.points)} pts</span> : undefined}
          flush>
      <ul className="divide-soft">
        {matches.map((m) => <ResultLine key={m.fixture_id} m={m} />)}
      </ul>
    </Card>
  );
}

const ordinal = (n: number) => (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th");

function TeamNews({ a }: { a: Analysis }) {
  return (
    <Card title="Team news" subtitle="Injuries, suspensions and lineups">
      {a.availability.length === 0 && a.lineups.length === 0 ? (
        <p className="text-sm text-ink-3">No team news yet. Lineups usually appear about an hour before kickoff. Missing news lowers data confidence.</p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="min-w-0">
            <div className="label mb-2">Unavailable or doubtful</div>
            {a.availability.length === 0 ? <p className="text-sm text-ink-3">None reported.</p> : (
              <ul className="space-y-2">
                {a.availability.map((r, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 text-sm">
                    <span className="min-w-0"><span className="block truncate">{r.player}</span><span className="block text-xs text-ink-4 truncate">{r.team}{r.reason ? ` · ${r.reason}` : ""}</span></span>
                    <Pill tone={r.kind === "doubtful" ? "warn" : "neg"}>{r.kind}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="grid sm:grid-cols-2 gap-5 min-w-0">
            {a.lineups.map((l) => (
              <div key={l.team} className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-sm"><span className="font-medium">{l.team}</span><span className="text-xs text-ink-3">{l.status}{l.formation && ` · ${l.formation}`}</span></div>
                <ul className="mt-2 space-y-1 text-[13px] text-ink-2">
                  {l.players.filter((x) => x.starter).map((x) => <li key={x.name} className="flex gap-2"><span className="num text-ink-4 w-5 text-right shrink-0">{x.number}</span><span className="truncate">{x.name}</span></li>)}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

/* -------------------------------------------------------------- odds/value */
function OddsValue({ a, p }: { a: Analysis; p: PredictionDetail }) {
  const f = a.fixture;
  const r = p.markets["1x2"];
  const rows = a.odds.latest.filter((x) => x.market === "1x2");
  const fairRow = (sel: string) => p.selections.find((s) => s.market === "1x2" && s.selection === sel);
  const isPseudo = (bk: string) => ["avg", "max"].includes(bk);
  const books = [...new Set(rows.map((x) => x.bookmaker))].sort((x, y) => Number(isPseudo(x)) - Number(isPseudo(y)));
  const get = (bk: string, sel: string) => rows.find((x) => x.bookmaker === bk && x.selection === sel);
  const best = Object.fromEntries((["home", "draw", "away"] as const).map((s) => [s, Math.max(0, ...rows.filter((x) => x.selection === s && !isPseudo(x.bookmaker)).map((x) => x.odds))]));

  return (
    <>
      <Card title="Our chances vs the bookmakers" info={GLOSSARY.implied}
            subtitle="Where our bar is longer, the bookmaker's price may be generous">
        <div className="space-y-5">
          {(["home", "draw", "away"] as const).map((k) => {
            const sel = fairRow(k);
            return (
              <div key={k}>
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="min-w-0 font-medium">{outcomeLabel(k, f.home_team.name, f.away_team.name)}</span>
                  {sel && <span className="shrink-0 text-xs text-ink-3">best price <span className="num font-semibold text-ink">{odds(sel.odds)}</span></span>}
                </div>
                <div className="mt-2 space-y-1.5">
                  <Bar2 label="Us" value={r[k]} className={k === "home" ? "bg-home" : k === "away" ? "bg-away" : "bg-draw"} />
                  <Bar2 label="Bookmakers" value={sel?.fair_probability ?? null} className="bg-ink-4/60" />
                </div>
              </div>
            );
          })}
        </div>
        <p className="mt-5 text-xs text-ink-4">Bookmaker chances have their margin removed so they compare fairly.</p>
      </Card>

      <Card title="Every bet we checked" info={GLOSSARY.value} flush>
        <ul className="divide-soft">
          {p.selections.map((s) => (
            <li key={s.id} className="px-4 sm:px-5 py-3.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium">{selectionLabel(s.market, s.selection, f.home_team.name, f.away_team.name)}</div>
                  <div className="mt-0.5 text-xs text-ink-3">Us <span className="num">{pct(s.probability, 0)}</span> · bookmaker <span className="num">{pct(s.implied_probability, 0)}</span> · {bookmakerName(s.bookmaker)}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-semibold num">{odds(s.odds)}</div>
                  <div className={cx("num text-xs", s.expected_value > 0 ? "text-pos" : "text-ink-4")}>{signedPct(s.expected_value)}</div>
                </div>
              </div>
              <div className="mt-1.5 text-xs">
                {s.qualifies ? <span className="font-medium text-pos">Recommended</span>
                  : <span className="text-ink-4">{friendlyReason(s.rejection_reasons[0])}{s.rejection_reasons.length > 1 && ` (+${s.rejection_reasons.length - 1} more)`}</span>}
              </div>
            </li>
          ))}
          {p.selections.length === 0 && <li className="px-5 py-8 text-center text-sm text-ink-3">No bookmaker prices available for this match.</li>}
        </ul>
      </Card>

      <Card title="Bookmaker odds" subtitle={`Match result · ${fmtDateTime(a.odds.latest_observed)}`} flush>
        {books.length === 0 ? <Empty title="No odds available" icon="target" /> : (
          <div className="scroll-x">
            <table className="table min-w-[320px]">
              <thead><tr><th className="pl-4 sm:pl-5">Bookmaker</th><th className="text-right">Home</th><th className="text-right">Draw</th><th className="text-right pr-4 sm:pr-5">Away</th></tr></thead>
              <tbody>
                {books.map((bk) => (
                  <tr key={bk}>
                    <td className={cx("pl-4 sm:pl-5", isPseudo(bk) ? "text-ink-4" : "text-ink-2")}>{get(bk, "home")?.bookmaker_name ?? bk}</td>
                    {(["home", "draw", "away"] as const).map((s, i) => {
                      const c = get(bk, s);
                      const top = !isPseudo(bk) && c && c.odds === best[s];
                      return <td key={s} className={cx("text-right num", i === 2 && "pr-4 sm:pr-5", top ? "font-semibold text-pos" : "text-ink-2")}>{odds(c?.odds)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="px-4 sm:px-5 py-3 text-xs text-ink-4 border-t border-line">Green is the best price. Average and maximum rows are aggregates.</p>
      </Card>
    </>
  );
}

function Bar2({ label, value, className }: { label: string; value: number | null; className: string }) {
  return (
    <div className="grid grid-cols-[76px_minmax(0,1fr)_40px] items-center gap-3 text-xs">
      <span className="text-ink-3">{label}</span>
      <div className="h-1.5 rounded-full bg-subtle overflow-hidden">
        {value !== null && <div className={cx("h-full rounded-full", className)} style={{ width: `${value * 100}%` }} />}
      </div>
      <span className="num text-right font-medium">{value === null ? "—" : pct(value, 0)}</span>
    </div>
  );
}

/* ----------------------------------------------------------- model details */
function ModelBreakdown({ a, p }: { a: Analysis; p: PredictionDetail }) {
  const r = p.markets["1x2"];
  const iv = p.intervals ?? {};
  return (
    <Disclosure title="How each model sees it">
      <p className="text-sm text-ink-3">
        Each model and the bookmaker market estimate the result; they are blended with weights learned from past seasons ({p.components.weights_source}).
      </p>
      <div className="scroll-x mt-3">
        <table className="table min-w-[300px] [&_td]:px-2 [&_th]:px-2">
          <thead><tr><th className="!pl-0">Model</th><th className="text-right">Home</th><th className="text-right">Draw</th><th className="text-right">Away</th><th className="text-right !pr-0">Weight</th></tr></thead>
          <tbody>
            {Object.entries(p.components.one_x_two).map(([name, v]) => (
              <tr key={name}>
                <td className="!pl-0 capitalize text-ink-2">{name.replace(/_/g, " ")}</td>
                {v.map((x, i) => <td key={i} className="num text-right text-ink-3">{pct(x, 0)}</td>)}
                <td className="num text-right !pr-0 text-ink-4">{num(p.components.weights[name] ?? 0)}</td>
              </tr>
            ))}
            <tr>
              <td className="!pl-0 font-semibold">Blended</td>
              {(["home", "draw", "away"] as const).map((k) => (
                <td key={k} className="num text-right font-semibold">{pct(r[k], 0)}
                  {Array.isArray(iv[k]) && <div className="text-[10px] font-normal text-ink-4 whitespace-nowrap">{pct(iv[k][0], 0)}–{pct(iv[k][1], 0)}</div>}
                </td>
              ))}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-ink-4">Ranges under the blend are the plausible range <InfoTip text={GLOSSARY.interval} />. Models disagree by {p.components.disagreement === null ? "n/a" : num(p.components.disagreement)} (0 = full agreement). {a.fixture.home_team.name} at home.</p>
    </Disclosure>
  );
}

function Confidence({ p }: { p: PredictionDetail }) {
  const c = CONFIDENCE[p.reliability.label];
  const bar = c?.tone === "pos" ? "bg-pos" : c?.tone === "warn" ? "bg-warn" : "bg-neg";
  return (
    <Disclosure title={<span className="flex items-center gap-2">Data confidence <ReliabilityBadge score={p.reliability.score} label={p.reliability.label} compact /></span>}>
      <p className="text-sm text-ink-3">{GLOSSARY.confidence}</p>
      <div className="mt-4 h-1.5 rounded-full bg-subtle overflow-hidden"><div className={cx("h-full rounded-full", bar)} style={{ width: `${p.reliability.score}%` }} /></div>
      <ul className="mt-4 space-y-2">
        {p.reliability.factors.map((f) => (
          <li key={f.factor} className="flex gap-3 text-[13px]"><span className="num text-neg w-8 text-right shrink-0">−{f.penalty}</span><span className="min-w-0 text-ink-2">{f.detail}</span></li>
        ))}
        {p.reliability.factors.length === 0 && <li className="text-[13px] text-ink-3">Nothing reduced confidence.</li>}
      </ul>
    </Disclosure>
  );
}

function AllReasons({ p }: { p: PredictionDetail }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Disclosure title="Every reason, with the numbers">
      <ol className="divide-soft">
        {p.explanations.map((e, i) => (
          <li key={i} className="min-w-0">
            <button className="w-full flex gap-3 py-3 text-left" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
              <span className="min-w-0 flex-1">
                <span className="block text-xs text-ink-4 capitalize">{e.category.replace(/_/g, " ")}</span>
                <span className="block text-sm text-ink-2">{e.text}</span>
              </span>
              <Icon name="chevronDown" size={15} className={cx("text-ink-4 mt-1 shrink-0 transition-transform", open === i && "rotate-180")} />
            </button>
            {open === i && <pre className="mb-3 scroll-x rounded-xl bg-subtle p-3 text-xs text-ink-3 font-mono">{JSON.stringify(e.evidence, null, 2)}</pre>}
          </li>
        ))}
      </ol>
    </Disclosure>
  );
}

function ScoreGrid({ a, p }: { a: Analysis; p: PredictionDetail }) {
  const g = p.markets.score_grid;
  if (!g) return null;
  const max = Math.max(...g.matrix.flat());
  return (
    <Disclosure title="Chance of every scoreline">
      <p className="text-xs text-ink-3 mb-3">Rows: {a.fixture.home_team.name} goals · columns: {a.fixture.away_team.name} goals · %</p>
      <div className="grid grid-cols-[18px_repeat(6,minmax(0,1fr))] gap-1 text-center">
        <span />
        {g.matrix[0].map((_, j) => <span key={j} className="text-xs text-ink-4 pb-1">{j}</span>)}
        {g.matrix.map((row, i) => (
          <div key={i} className="contents">
            <span className="text-xs text-ink-4 grid place-items-center">{i}</span>
            {row.map((v, j) => (
              <span key={j} title={`${i}–${j}: ${pct(v)}`} className="relative h-9 grid place-items-center rounded-md num text-[11px] sm:text-xs overflow-hidden bg-subtle">
                <span aria-hidden className="absolute inset-0 bg-home" style={{ opacity: (v / max) * 0.55 }} />
                <span className={cx("relative", v / max > 0.6 ? "font-semibold text-ink" : "text-ink-2")}>{(v * 100).toFixed(1)}</span>
              </span>
            ))}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-ink-4">Any other score: {pct(g.other)}.</p>
    </Disclosure>
  );
}

function AsianHandicap({ p }: { p: PredictionDetail }) {
  const ah = p.markets.asian_handicap ?? {};
  const lines = ["-1.50", "-1.00", "-0.75", "-0.50", "-0.25", "+0.00", "+0.25", "+0.50", "+1.00"].filter((k) => ah[k]);
  if (!lines.length) return null;
  return (
    <Disclosure title="Asian handicap outcomes (home side)">
      <div className="scroll-x">
        <table className="table min-w-[300px] [&_td]:px-1.5 [&_th]:px-1.5">
          <thead><tr><th className="!pl-0">Line</th><th className="text-right">Win</th><th className="text-right">½ win</th><th className="text-right">Push</th><th className="text-right">½ loss</th><th className="text-right !pr-0">Loss</th></tr></thead>
          <tbody>
            {lines.map((k) => (
              <tr key={k}>
                <td className="num font-medium !pl-0">{k}</td>
                {(["win", "half_win", "push", "half_loss", "loss"] as const).map((o) => (
                  <td key={o} className={cx("num text-right last:!pr-0", ah[k].home[o] < 0.005 ? "text-ink-4" : "text-ink-2")}>{pct(ah[k].home[o], 0)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Disclosure>
  );
}

function History({ a }: { a: Analysis }) {
  return (
    <Disclosure title={`Prediction history (${a.prediction_history.length})`}>
      <p className="text-[13px] text-ink-3 mb-4">Every update is saved; old predictions are never edited.</p>
      <ol className="space-y-4">
        {a.prediction_history.map((h, i) => (
          <li key={h.id} className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 text-xs"><span className="font-medium">{fmtDateTime(h.created_at)}</span><span className="text-ink-4">{h.trigger}{i === 0 && " · latest"}</span></div>
            {h.one_x_two && <div className="mt-2 max-w-xs"><OutcomeBar p={h.one_x_two} /></div>}
            <div className="mt-1 text-xs text-ink-4">{verdict(h.classification).label} · confidence {Math.round(h.reliability)}</div>
          </li>
        ))}
      </ol>
    </Disclosure>
  );
}

function DataSources({ a }: { a: Analysis }) {
  const dq = a.data_quality as Record<string, any>;
  const warnings: string[] = [...(dq.missing_components ?? []), ...(dq.stale_inputs ?? []), ...(dq.conflicts ?? []).map((c: any) => `Conflict on ${c.field}: ${c.resolution}`)];
  return (
    <Disclosure title="Data quality & sources">
      {warnings.length > 0 && (
        <ul className="mb-4 space-y-1.5">
          {warnings.map((w) => <li key={w} className="flex gap-2 text-xs text-ink-2"><Icon name="alert" size={13} className="text-warn shrink-0 mt-0.5" /><span className="min-w-0">{w}</span></li>)}
        </ul>
      )}
      <KeyValue items={[
        ["Matches the models learned from", String(dq.training_matches ?? "—")],
        ["Team sample sizes (home / away)", dq.sample_sizes ? `${dq.sample_sizes.home} / ${dq.sample_sizes.away}` : "—"],
        ["Bookmakers priced", String(dq.odds_bookmakers?.length ?? 0)],
        ["Model version", <span key="v" className="font-mono text-xs whitespace-normal break-all">{String(dq.model_version ?? "unvalidated")}</span>],
      ]} />
      <ul className="mt-4 divide-soft">
        {a.sources.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
            <span className="min-w-0"><span className="block capitalize">{s.provider.replace(/_/g, " ")}</span><span className="block text-xs text-ink-4 font-mono truncate">{s.resource}</span></span>
            <span className="text-right text-xs text-ink-3 shrink-0">{fmtDateTime(s.retrieved_at)}</span>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}
