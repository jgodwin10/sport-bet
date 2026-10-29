import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getToken } from "../api/client";
import { useAdminAction, useAiAnalysis, useAnalysis, useGenerateAiAnalysis, useMe } from "../api/hooks";
import type { AiAnalysisContent, Analysis, FormSummary, PredictionDetail, PredictionSelection, RecentMatch } from "../api/types";
import { Icon, type IconName } from "../components/icons";
import Lineups from "../components/Lineups";
import {
  AXIS, Card, ChartTooltip, ClassificationBadge, cx, Disclosure, Empty, ErrorState, FormPills, Freshness, InfoTip,
  KeyValue, Loading, MetricStrip, OUTCOME_COLORS, OutcomeBar, Pill, ReliabilityBadge, Segmented, SERIES, StatTile, TeamLogo,
} from "../components/ui";
import { fmtDate, fmtDateTime, fmtTime, num, odds, pct, signedPct } from "../lib/format";
import { aiProviderName, bookmakerName, CONFIDENCE, friendlyReason, GLOSSARY, outcomeLabel, plainFacts, selectionLabel, verdict } from "../lib/language";

const TABS = [
  { value: "summary", label: "Summary" },
  { value: "lineups", label: "Lineups" },
  { value: "stats", label: "Stats" },
  { value: "odds", label: "Odds" },
  { value: "details", label: "Details" },
] as const;
type Tab = (typeof TABS)[number]["value"];

export default function MatchAnalysis() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.value === params.get("tab"))?.value ?? "summary") as Tab;
  const q = useAnalysis(id);

  if (q.isLoading) return <Card><Loading label="Loading match" rows={5} /></Card>;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const a = q.data!;
  const p = a.prediction;

  return (
    <>
      <Link to="/" className="inline-flex items-center gap-1 text-[13px] font-semibold text-ink-3 hover:text-ink mb-3 sm:mb-4">
        <Icon name="chevronLeft" size={16} />Matches
      </Link>
      <Hero a={a} />
      <div className="sticky top-14 lg:top-0 z-20 -mx-4 sm:-mx-6 lg:mx-0 mt-3 mb-4 sm:mb-6 px-2 sm:px-4 lg:px-0 bg-night/95 backdrop-blur-md">
        <Segmented variant="tabs" label="Match sections" value={tab} options={[...TABS]}
                   onChange={(v) => setParams(v === "summary" ? {} : { tab: v }, { replace: true })} />
      </div>
      <div className="space-y-4 sm:space-y-6 animate-fade-up" key={tab}>
        {tab === "summary" && (p ? <Summary a={a} p={p} /> : <NoPrediction />)}
        {tab === "lineups" && <Lineups a={a} />}
        {tab === "stats" && <Stats a={a} />}
        {tab === "odds" && (p ? <OddsValue a={a} p={p} /> : <NoPrediction />)}
        {tab === "details" && <Details a={a} />}
      </div>
      <p className="mt-8 text-center text-xs text-ink-4">{a.disclaimer}</p>
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
    <section className="card relative overflow-hidden">
      {/* Home / away colour bar */}
      <div aria-hidden className="flex h-1"><span className="flex-1 bg-home" /><span className="flex-1 bg-away" /></div>
      <div className="relative">
        <div className="flex flex-wrap items-center justify-center gap-x-2.5 gap-y-1 px-4 pt-4 sm:pt-5 text-2xs font-bold uppercase tracking-[0.08em] text-ink-3">
          <span>{f.competition.name}</span><span className="text-ink-4">·</span>
          <span>{fmtDateTime(f.kickoff_utc)}</span>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2 sm:gap-8 px-3 sm:px-10 pt-4 sm:pt-6 pb-4">
          {[f.home_team, null, f.away_team].map((t, i) => t ? (
            <div key={t.id} className="flex flex-col items-center text-center min-w-0">
              <TeamLogo name={t.name} src={t.logo_url} size={60} className="sm:!w-[84px] sm:!h-[84px]" />
              <h1 className="mt-2.5 display uppercase text-[20px] sm:text-[28px] leading-[1.05] break-words">{t.name}</h1>
              <span className="mt-1 text-[10px] font-bold uppercase tracking-[0.1em] text-ink-4">{i === 0 ? "Home" : "Away"}</span>
            </div>
          ) : (
            <div key="mid" className="pt-4 sm:pt-6 text-center">
              {f.score ? (
                <div className="display num text-[44px] sm:text-[60px]">{f.score.home}<span className="text-ink-4 mx-1">–</span>{f.score.away}</div>
              ) : (
                <div>
                  <div className="display num text-[30px] sm:text-[40px]">{fmtTime(f.kickoff_utc).split(" ")[0]}</div>
                  <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.1em] text-ink-4">Kickoff</div>
                </div>
              )}
            </div>
          ))}
        </div>

        {p && r && lead && (
          <div className="px-4 sm:px-10 pb-5">
            <p className="text-center text-[14px] sm:text-[16px] text-ink-3">
              Most likely <b className="text-ink font-bold">{outcomeLabel(lead, f.home_team.name, f.away_team.name)}</b>{" "}
              <span className="display num text-[20px] text-brand">{pct(r[lead], 0)}</span>
            </p>
            <div className="mt-3 max-w-xl mx-auto"><OutcomeBar size="lg" p={r} labels={["Home", "Draw", "Away"]} /></div>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-center gap-2 px-3 py-3 border-t border-line bg-night/40">
          {p && <ClassificationBadge value={p.classification} />}
          {p && conf && <Pill tone={conf.tone} icon="shield" title={GLOSSARY.confidence}>Data confidence: {conf.label}</Pill>}
          <Pill tone={p?.lineup_status === "confirmed" ? "pos" : "neutral"} icon="users">
            {p?.lineup_status === "confirmed" ? "Lineups confirmed" : "Lineups not out yet"}
          </Pill>
          <Freshness hours={a.odds.age_hours} />
          {me.data?.role === "admin" && (
            <button className="btn btn-sm" disabled={action.isPending} onClick={() => action.mutate({ path: `/admin/refresh-fixture/${f.id}` })}>
              <Icon name="refresh" size={13} />{action.isPending ? "Queuing…" : action.isSuccess ? "Refresh queued" : "Refresh"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- summary */
function Summary({ a, p }: { a: Analysis; p: PredictionDetail }) {
  const f = a.fixture;
  const m = p.markets;
  const v = verdict(p.classification);
  const qual = p.selections.filter((s) => s.qualifies);
  const best = [...p.selections].sort((x, y) => y.expected_value - x.expected_value)[0];
  const facts = plainFacts(p.explanations, f.home_team.name, f.away_team.name).slice(0, 5);
  const topScores = m.correct_score?.slice(0, 3) ?? [];
  return (
    <>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-start">
        {/* Verdict */}
        <section className={cx("card p-4 sm:p-5", qual.length && "border-pos/40")}>
          <div className="eyebrow">Our verdict</div>
          <div className="mt-3 flex items-start gap-4">
            <span className={cx("grid place-items-center h-11 w-11 rounded-xl shrink-0",
              v.tone === "pos" ? "bg-pos-soft text-pos" : v.tone === "warn" ? "bg-warn-soft text-warn" : "bg-night-3 text-ink-2")}>
              <Icon name={qual.length ? "sparkle" : v.tone === "warn" ? "alert" : "ban"} size={22} />
            </span>
            <div className="min-w-0">
              <h2 className="display uppercase text-[26px]">{v.label}</h2>
              <p className="mt-1 text-[14px] text-ink-2 leading-relaxed">{v.explain}</p>
            </div>
          </div>
          {qual.length > 0 ? (
            <div className="mt-5 space-y-3">
              {qual.map((s) => <PickCard key={s.id} s={s} home={f.home_team.name} away={f.away_team.name} />)}
            </div>
          ) : best ? (
            <div className="mt-4 glass-inset p-4">
              <div className="text-xs font-semibold text-ink-3">Closest bet we looked at</div>
              <div className="mt-1 flex items-center justify-between gap-3">
                <span className="text-[15px] font-bold">{selectionLabel(best.market, best.selection, f.home_team.name, f.away_team.name)}</span>
                <span className="display num text-[22px]">{odds(best.odds)}</span>
              </div>
              <div className="mt-2 text-xs text-ink-3">Why we passed:</div>
              <ul className="mt-1.5 space-y-1">
                {best.rejection_reasons.slice(0, 3).map((r) => (
                  <li key={r} className="flex gap-2 text-[13px] text-ink-2"><Icon name="x" size={13} className="text-neg mt-1 shrink-0" />{friendlyReason(r)}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        {/* Key facts */}
        <Card title="Why we think this" subtitle="The main evidence behind the prediction">
          <ul className="space-y-3.5">
            {facts.map((e, i) => (
              <li key={i} className="flex gap-3">
                <span className="grid place-items-center h-8 w-8 rounded-lg bg-night-3 text-brand shrink-0"><Icon name={e.icon as IconName} size={15} /></span>
                <p className="text-[14px] text-ink-2 leading-relaxed pt-1">{e.text}</p>
              </li>
            ))}
          </ul>
          <Link to="?tab=details" className="mt-4 inline-flex items-center gap-1 text-[13px] font-semibold text-brand hover:underline">
            See the full breakdown<Icon name="chevronRight" size={14} />
          </Link>
        </Card>
      </div>

      <AiAnalysisCard a={a} p={p} />

      {/* Goals at a glance */}
      <div>
        <h2 className="eyebrow mb-2.5">Goals at a glance</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 sm:gap-3">
          {m.totals?.["2.5"] && <StatTile label="Over 2.5 goals" value={pct(m.totals["2.5"].over, 0)} hint={`Under: ${pct(m.totals["2.5"].under, 0)}`} />}
          {m.btts && <StatTile label="Both teams score" value={pct(m.btts.yes, 0)} hint={`No: ${pct(m.btts.no, 0)}`} />}
          {m.expected_goals && <StatTile label="Expected goals" value={`${num(m.expected_goals.home, 1)} – ${num(m.expected_goals.away, 1)}`} hint="home – away" />}
          {topScores[0] && <StatTile label="Likeliest score" value={`${topScores[0].home}–${topScores[0].away}`}
                                     hint={topScores.slice(1).map((s) => `${s.home}–${s.away}`).join(", ") + " next"} />}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 sm:gap-3">
        <StatTile label={`${f.home_team.name} or draw`} value={pct(m.double_chance["1X"], 0)} hint="Double chance 1X" />
        <StatTile label={`${f.away_team.name} or draw`} value={pct(m.double_chance.X2, 0)} hint="Double chance X2" />
        <StatTile label="Either team wins" value={pct(m.double_chance["12"], 0)} hint="No draw" />
      </div>
    </>
  );
}

/* ------------------------------------------------------------- ai analysis */
const NEWS_TONE = { confirmed: "pos", reported: "warn", rumour: "neutral" } as const;
const WEIGHT_TONE = { high: "brand", medium: "neutral", low: "neutral" } as const;

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
      {gen.isPending ? "Analysing… (up to a minute)" : c ? (stale ? "Update" : "Regenerate") : "Generate"}
    </button>
  );

  return (
    <Card title={<><Icon name="sparkle" size={16} />AI analysis</>} info={note}
          subtitle={analysis ? `${aiProviderName(analysis.provider)}${analysis.model ? ` (${analysis.model})` : ""} · ${fmtDateTime(analysis.created_at)}${stale ? " · based on an earlier prediction" : ""}`
                             : "Written by AI from our model's evidence plus a web search for team news"}
          action={button}>
      {gen.isError && <p className="mb-3 text-[13px] text-neg">{(gen.error as Error).message}</p>}
      {!analysis ? (
        <p className="text-[14px] text-ink-3">
          {!available ? "AI analysis is only written before kickoff." : signedIn ? "No AI analysis yet. Generate one to add current team news and context." : "No AI analysis yet. Sign in to generate one."}
        </p>
      ) : !c ? (
        <p className="text-[14px] text-ink-3">The last attempt failed: {analysis.error ?? "unknown error"}</p>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            <Pill tone="warn" icon="alert" title={note}>Not validated: does not change our numbers</Pill>
            <Pill tone={c.confidence === "high" ? "pos" : c.confidence === "medium" ? "neutral" : "warn"}>AI confidence: {c.confidence}</Pill>
          </div>
          {c.summary && <p className="text-[15px] text-ink-2 leading-relaxed whitespace-pre-line">{c.summary}</p>}

          {c.probability_view && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div><div className="text-xs font-semibold text-ink-3 mb-2">Our model</div>
                <OutcomeBar p={p.markets["1x2"]} labels={["Home", "Draw", "Away"]} /></div>
              <div><div className="text-xs font-semibold text-ink-3 mb-2">AI view (unvalidated)</div>
                <OutcomeBar p={c.probability_view} labels={["Home", "Draw", "Away"]} /></div>
            </div>
          )}
          {c.model_assessment && (
            <div className="glass-inset p-4">
              <div className="text-xs font-semibold text-ink-3">Does the news change the picture?</div>
              <p className="mt-1 text-[14px] text-ink-2 leading-relaxed">{c.model_assessment}</p>
            </div>
          )}

          {c.key_factors.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-ink-3 mb-2">Key factors</div>
              <ul className="space-y-3">
                {c.key_factors.map((k, i) => (
                  <li key={i} className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[14px] font-bold">{k.title}</span>
                      {favours(k.favours) && <Pill tone={WEIGHT_TONE[k.weight]}>Favours {favours(k.favours)}</Pill>}
                      {k.basis !== "model" && <Pill tone="neutral" icon="search">from news</Pill>}
                    </div>
                    <p className="text-[13.5px] text-ink-2 leading-relaxed">{k.detail}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {c.team_news.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-ink-3 mb-2">Team news found online</div>
              <ul className="space-y-2">
                {c.team_news.map((n, i) => (
                  <li key={i} className="flex gap-2 text-[13.5px] text-ink-2">
                    <Pill tone={NEWS_TONE[n.status]} className="shrink-0">{n.status}</Pill>
                    <span><b className="text-ink">{n.team}:</b> {n.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {c.risks.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-ink-3 mb-2">What could make this wrong</div>
              <ul className="space-y-1.5">
                {c.risks.map((r, i) => (
                  <li key={i} className="flex gap-2 text-[13.5px] text-ink-2"><Icon name="alert" size={13} className="text-warn mt-1 shrink-0" />{r}</li>
                ))}
              </ul>
            </div>
          )}

          {analysis.sources.length > 0 && (
            <Disclosure title={`Sources (${analysis.sources.length})`}>
              <ul className="space-y-1.5">
                {analysis.sources.map((s) => (
                  <li key={s.uri}>
                    <a href={s.uri} target="_blank" rel="noopener noreferrer nofollow"
                       className="inline-flex items-center gap-1.5 text-[13px] text-brand hover:underline break-all">
                      <Icon name="external" size={12} className="shrink-0" />{s.title}
                    </a>
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}
        </div>
      )}
    </Card>
  );
}

function PickCard({ s, home, away }: { s: PredictionSelection; home: string; away: string }) {
  return (
    <div className="rounded-xl border border-pos/40 bg-pos-soft p-3.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[15px] font-bold">{selectionLabel(s.market, s.selection, home, away)}</span>
        <span className="display num text-[26px]">{odds(s.odds)}</span>
      </div>
      <MetricStrip items={[["Our chance", pct(s.probability, 0)], ["Bookmaker", pct(s.implied_probability, 0)], ["Value", signedPct(s.expected_value), "pos"]]} />
      <p className="mt-2.5 text-2xs text-ink-3">Best price at {bookmakerName(s.bookmaker)}. Value is an estimate, not a promise.</p>
    </div>
  );
}

/* ------------------------------------------------------------------- stats */
const FORM_ROWS: [string, keyof FormSummary, "last_5" | "last_10" | "last_15", number][] = [
  ["Points per game (last 5)", "points_per_game", "last_5", 2],
  ["Points per game (last 10)", "points_per_game", "last_10", 2],
  ["Goals scored (last 10)", "goals_for", "last_10", 0],
  ["Goals conceded (last 10)", "goals_against", "last_10", 0],
  ["xG created per game", "xg_for", "last_10", 2],
  ["xG allowed per game", "xg_against", "last_10", 2],
  ["Shots on target per game", "sot_for", "last_10", 1],
  ["Clean sheets (last 10)", "clean_sheets", "last_10", 0],
];

function Stats({ a }: { a: Analysis }) {
  const f = a.fixture;
  const hs = a.form.home.summary, as = a.form.away.summary;
  const fmt = (s: FormSummary | null, key: keyof FormSummary, d: number) => (typeof s?.[key] === "number" ? num(s[key] as number, d) : "—");
  const usesXg = (hs.last_10?.xg_coverage ?? 0) > 0.5;
  const chart = Array.from({ length: 10 }, (_, i) => {
    const hm = a.form.home.matches[9 - i], am = a.form.away.matches[9 - i];
    const val = (m?: RecentMatch) => (m ? (usesXg ? m.xg_for ?? m.goals_for : m.goals_for) : null);
    return { n: `${10 - i}`, home: val(hm), away: val(am) };
  });
  const ctx = a.standings_context;
  return (
    <>
      <Card title="Form side by side" flush>
        <div className="grid grid-cols-[minmax(0,1fr)_100px_100px] sm:grid-cols-[minmax(0,1fr)_150px_150px] items-end gap-x-2 px-5 sm:px-6 pb-4 border-b border-line">
          <span className="eyebrow pb-1">Last 5</span>
          {[[f.home_team, hs.sequence], [f.away_team, as.sequence]].map(([t, seq]: any) => (
            <div key={t.id} className="flex flex-col items-center gap-2 min-w-0">
              <TeamLogo name={t.name} src={t.logo_url} size={30} />
              <FormPills seq={seq} size={15} />
            </div>
          ))}
        </div>
        <table className="table table-fixed">
          <colgroup><col /><col className="w-[100px] sm:w-[150px]" /><col className="w-[100px] sm:w-[150px]" /></colgroup>
          <tbody>
            {FORM_ROWS.map(([label, key, w, d]) => {
              const h = hs[w]?.[key], aw = as[w]?.[key];
              const better = typeof h === "number" && typeof aw === "number" && h !== aw
                ? ((key === "goals_against" || key === "xg_against") ? (h < aw ? "h" : "a") : (h > aw ? "h" : "a")) : null;
              return (
                <tr key={label}>
                  <td className="pl-5 sm:pl-6 text-ink-2">{label}</td>
                  <td className={cx("num text-center", better === "h" ? "font-extrabold text-ink" : "text-ink-2")}>{fmt(hs[w], key, d)}</td>
                  <td className={cx("num text-center pr-5 sm:pr-6", better === "a" ? "font-extrabold text-ink" : "text-ink-2")}>{fmt(as[w], key, d)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="px-5 sm:px-6 py-4 text-xs text-ink-4 border-t border-line">The better figure in each row is in bold.</p>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <Card title={usesXg ? "Chances created (xG)" : "Goals scored"} subtitle="Last 10 matches, oldest to newest">
          <div className="flex flex-wrap gap-4 text-xs text-ink-2 mb-3">
            {[f.home_team.name, f.away_team.name].map((n, i) => (
              <span key={n} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[i] }} />{n}</span>
            ))}
          </div>
          <div className="h-52">
            <ResponsiveContainer>
              <BarChart data={chart} barGap={3} margin={{ left: -18, right: 4, top: 4 }}>
                <CartesianGrid stroke={AXIS.grid} vertical={false} />
                <XAxis dataKey="n" stroke={AXIS.stroke} fontSize={AXIS.fontSize} tickLine={false} axisLine={false} />
                <YAxis stroke={AXIS.stroke} fontSize={AXIS.fontSize} tickLine={false} axisLine={false} />
                <Tooltip content={<ChartTooltip fmt={(v) => num(v)} />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                <Bar isAnimationActive={false} dataKey="home" name={f.home_team.name} fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={14} />
                <Bar isAnimationActive={false} dataKey="away" name={f.away_team.name} fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={14} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Head-to-head" subtitle="Past meetings — background only, not used by the model">
          {a.head_to_head.length === 0 ? <p className="text-[14px] text-ink-3">These teams haven't met in our records.</p> : (
            <ul className="space-y-2">
              {a.head_to_head.slice(0, 6).map((m, i) => (
                <li key={i} className={cx("glass-inset px-3 py-2.5", m.age_days > 1095 && "opacity-50")}>
                  <div className="text-2xs text-ink-4 text-center">{fmtDate(m.date)}</div>
                  <div className="mt-1 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-3 items-center text-[13.5px]">
                    <span className="flex items-center justify-end gap-2 min-w-0"><span className="truncate">{m.home}</span><TeamLogo name={m.home} src={m.home_logo} size={20} /></span>
                    <span className="num font-extrabold px-2.5 py-1 rounded-lg bg-white/[0.07]">{m.home_goals}–{m.away_goals}</span>
                    <span className="flex items-center gap-2 min-w-0"><TeamLogo name={m.away} src={m.away_logo} size={20} /><span className="truncate">{m.away}</span></span>
                  </div>
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

function RecentList({ team, matches, position }: { team: { name: string; logo_url?: string | null }; matches: RecentMatch[]; position: Record<string, number | string> | null }) {
  return (
    <Card title={<span className="flex items-center gap-2.5"><TeamLogo name={team.name} src={team.logo_url} size={26} />{team.name}</span>}
          action={position ? <Pill>{String(position.position)}{ordinal(Number(position.position))} · {String(position.points)} pts</Pill> : undefined}
          subtitle="Recent results">
      <ul className="divide-soft -my-2">
        {matches.map((m) => (
          <li key={m.fixture_id} className="flex items-center gap-3 py-2.5 text-[13.5px]">
            <FormPills seq={m.result} max={1} size={24} />
            <TeamLogo name={m.opponent} src={m.opponent_logo} size={22} />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{m.venue === "H" ? "vs" : "at"} {m.opponent}</span>
              <span className="block text-2xs text-ink-4">{fmtDate(m.date)}</span>
            </span>
            <span className="num font-extrabold">{m.goals_for}–{m.goals_against}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

const ordinal = (n: number) => (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th");

function TeamNews({ a }: { a: Analysis }) {
  return (
    <Card title="Team news" subtitle="Injuries, suspensions and lineups">
      {a.availability.length === 0 && a.lineups.length === 0 ? (
        <div className="flex gap-3 glass-inset p-4 text-[13.5px] text-ink-2">
          <Icon name="users" size={18} className="text-ink-3 shrink-0 mt-0.5" />
          <span>No team news yet. Lineups usually appear about an hour before kickoff (requires the API-Football data source). Missing news lowers data confidence.</span>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <div className="field-label mb-2">Unavailable or doubtful</div>
            {a.availability.length === 0 ? <p className="text-[13px] text-ink-3">None reported.</p> : (
              <ul className="space-y-2">
                {a.availability.map((r, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 text-[13.5px]">
                    <span className="min-w-0"><span className="block font-medium truncate">{r.player}</span><span className="block text-2xs text-ink-4">{r.team}{r.reason ? ` · ${r.reason}` : ""}</span></span>
                    <Pill tone={r.kind === "doubtful" ? "warn" : "neg"}>{r.kind}</Pill>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="grid sm:grid-cols-2 gap-5">
            {a.lineups.map((l) => (
              <div key={l.team}>
                <div className="flex items-center gap-2 flex-wrap"><span className="font-bold text-[13.5px]">{l.team}</span><Pill tone={l.status === "confirmed" ? "pos" : "neutral"}>{l.status}</Pill>{l.formation && <span className="text-xs text-ink-3">{l.formation}</span>}</div>
                <ul className="mt-2 space-y-1 text-[13px]">
                  {l.players.filter((x) => x.starter).map((x) => <li key={x.name} className="flex gap-2"><span className="num text-ink-4 w-5 text-right">{x.number}</span>{x.name}</li>)}
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
            subtitle="If our bar is longer than the bookmaker's, their price may be generous">
        <div className="space-y-5">
          {(["home", "draw", "away"] as const).map((k) => {
            const sel = fairRow(k);
            const bookie = sel?.fair_probability ?? null;
            return (
              <div key={k}>
                <div className="flex items-center justify-between gap-3 text-[14px]">
                  <span className="font-bold">{outcomeLabel(k, f.home_team.name, f.away_team.name)}</span>
                  {sel && <span className="text-xs text-ink-3">best price <b className="num text-ink text-[14px]">{odds(sel.odds)}</b></span>}
                </div>
                <div className="mt-2 space-y-1.5">
                  <Bar2 label="Us" value={r[k]} color={OUTCOME_COLORS[k]} />
                  <Bar2 label="Bookmakers" value={bookie} color="rgba(255,255,255,0.35)" />
                </div>
              </div>
            );
          })}
        </div>
        <p className="mt-5 text-xs text-ink-4">Bookmaker chances have their margin removed so they can be compared fairly.</p>
      </Card>

      <Card title="Every bet we checked" subtitle="Value = what a 1-unit bet returns on average if our chance is right" info={GLOSSARY.value} flush>
        <ul className="divide-soft">
          {p.selections.map((s) => (
            <li key={s.id} className="px-5 sm:px-6 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[14.5px] font-bold">{selectionLabel(s.market, s.selection, f.home_team.name, f.away_team.name)}</div>
                  <div className="mt-0.5 text-xs text-ink-3">Our chance <b className="num text-ink-2">{pct(s.probability, 0)}</b> · bookmaker <b className="num text-ink-2">{pct(s.implied_probability, 0)}</b> · {bookmakerName(s.bookmaker)}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="display num text-[22px]">{odds(s.odds)}</div>
                  <div className={cx("num text-xs font-bold", s.expected_value > 0 ? "text-pos" : "text-ink-4")}>{signedPct(s.expected_value)}</div>
                </div>
              </div>
              <div className="mt-2">
                {s.qualifies ? <Pill tone="pos" icon="check">Recommended</Pill> : (
                  <span className="text-xs text-ink-4">Not recommended: {friendlyReason(s.rejection_reasons[0])}{s.rejection_reasons.length > 1 && ` (+${s.rejection_reasons.length - 1} more)`}</span>
                )}
              </div>
            </li>
          ))}
          {p.selections.length === 0 && <li className="px-6 py-8 text-center text-[14px] text-ink-3">No bookmaker prices available for this match.</li>}
        </ul>
      </Card>

      <Card title="Bookmaker odds" subtitle={`Match result · updated ${fmtDateTime(a.odds.latest_observed)}`} action={<Freshness hours={a.odds.age_hours} label="" />} flush>
        {books.length === 0 ? <Empty title="No odds available" icon="target" /> : (
          <div className="scroll-x"><table className="table min-w-[340px]">
            <thead><tr><th className="pl-5 sm:pl-6">Bookmaker</th><th className="text-center">Home</th><th className="text-center">Draw</th><th className="text-center pr-5 sm:pr-6">Away</th></tr></thead>
            <tbody>
              {books.map((bk) => (
                <tr key={bk}>
                  <td className={cx("pl-5 sm:pl-6", isPseudo(bk) ? "text-ink-3 italic" : "font-medium")}>{get(bk, "home")?.bookmaker_name ?? bk}</td>
                  {(["home", "draw", "away"] as const).map((s, i) => {
                    const c = get(bk, s);
                    const top = !isPseudo(bk) && c && c.odds === best[s];
                    return (
                      <td key={s} className={cx("text-center", i === 2 && "pr-5 sm:pr-6")}>
                        <span className={cx("num inline-block min-w-[52px] rounded-lg px-2 py-1", top ? "bg-pos-soft text-pos font-extrabold" : "text-ink-2")}>{odds(c?.odds)}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
        <p className="px-5 sm:px-6 py-4 text-xs text-ink-4 border-t border-line">Highlighted = best price. “Market average/maximum” rows are aggregates.</p>
      </Card>
    </>
  );
}

function Bar2({ label, value, color }: { label: string; value: number | null; color: string }) {
  return (
    <div className="grid grid-cols-[84px_minmax(0,1fr)_48px] items-center gap-3 text-xs">
      <span className="text-ink-3">{label}</span>
      <div className="h-2.5 rounded-full bg-white/[0.06] overflow-hidden">
        {value !== null && <div className="h-full rounded-full" style={{ width: `${value * 100}%`, background: color }} />}
      </div>
      <span className="num text-right font-bold text-ink">{value === null ? "—" : pct(value, 0)}</span>
    </div>
  );
}

/* ----------------------------------------------------------------- details */
function Details({ a }: { a: Analysis }) {
  const p = a.prediction;
  return (
    <>
      {p && <ModelBreakdown a={a} p={p} />}
      {p && <Confidence p={p} />}
      {p && <AllReasons p={p} />}
      {p && <ScoreGrid a={a} p={p} />}
      {p && <AsianHandicap p={p} />}
      <History a={a} />
      <DataSources a={a} />
    </>
  );
}

function ModelBreakdown({ a, p }: { a: Analysis; p: PredictionDetail }) {
  const r = p.markets["1x2"];
  const iv = p.intervals ?? {};
  return (
    <Disclosure title="How each model sees it" defaultOpen>
      <p className="text-[13.5px] text-ink-2 leading-relaxed">
        Three statistical models and the bookmaker market each estimate the result. They are blended using weights learned
        from past seasons ({p.components.weights_source}).
      </p>
      <div className="scroll-x"><table className="table mt-3 min-w-[320px] [&_td]:px-2 [&_th]:px-2 sm:[&_td]:px-3 sm:[&_th]:px-3">
        <thead><tr><th className="!pl-0">Model</th><th className="text-right">Home</th><th className="text-right">Draw</th><th className="text-right">Away</th><th className="text-right !pr-0">Weight</th></tr></thead>
        <tbody>
          {Object.entries(p.components.one_x_two).map(([name, v]) => (
            <tr key={name}>
              <td className="!pl-0 capitalize font-medium">{name.replace(/_/g, " ")}</td>
              {v.map((x, i) => <td key={i} className="num text-right text-ink-2">{pct(x, 0)}</td>)}
              <td className="num text-right !pr-0 text-ink-3">{num(p.components.weights[name] ?? 0)}</td>
            </tr>
          ))}
          <tr>
            <td className="!pl-0 font-extrabold">Blended</td>
            {(["home", "draw", "away"] as const).map((k) => (
              <td key={k} className="num text-right font-extrabold">{pct(r[k], 0)}
                {Array.isArray(iv[k]) && <div className="text-2xs font-normal text-ink-4">{pct(iv[k][0], 0)}–{pct(iv[k][1], 0)}</div>}
              </td>
            ))}
            <td />
          </tr>
        </tbody>
      </table></div>
      <p className="mt-3 text-xs text-ink-4">Small numbers under the blend are the plausible range <InfoTip text={GLOSSARY.interval} />. Models disagree by {p.components.disagreement === null ? "n/a" : num(p.components.disagreement)} (0 = perfect agreement). {a.fixture.home_team.name} at home.</p>
    </Disclosure>
  );
}

function Confidence({ p }: { p: PredictionDetail }) {
  const c = CONFIDENCE[p.reliability.label];
  const color = c?.tone === "pos" ? "bg-pos" : c?.tone === "warn" ? "bg-warn" : "bg-neg";
  return (
    <Disclosure title={<span className="flex items-center gap-2">Data confidence <ReliabilityBadge score={p.reliability.score} label={p.reliability.label} compact /></span>}>
      <p className="text-[13.5px] text-ink-2 leading-relaxed">{GLOSSARY.confidence}</p>
      <div className="mt-4 flex items-end gap-2"><span className="text-[34px] font-extrabold num leading-none">{Math.round(p.reliability.score)}</span><span className="pb-1 text-ink-3">/ 100 · {c?.label}</span></div>
      <div className="mt-3 h-2 rounded-full bg-white/[0.07] overflow-hidden"><div className={cx("h-full rounded-full", color)} style={{ width: `${p.reliability.score}%` }} /></div>
      <ul className="mt-4 space-y-2">
        {p.reliability.factors.map((f) => (
          <li key={f.factor} className="flex gap-3 text-[13px]"><span className="num text-neg font-bold w-8 text-right shrink-0">−{f.penalty}</span><span className="text-ink-2">{f.detail}</span></li>
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
          <li key={i}>
            <button className="w-full flex gap-3 py-3 text-left" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
              <span className="min-w-0 flex-1">
                <span className="block text-2xs font-bold uppercase tracking-wider text-ink-4">{e.category.replace(/_/g, " ")}</span>
                <span className="block text-[13.5px] text-ink-2 leading-relaxed">{e.text}</span>
              </span>
              <Icon name="chevronDown" size={15} className={cx("text-ink-4 mt-1 shrink-0 transition-transform", open === i && "rotate-180")} />
            </button>
            {open === i && <pre className="mb-3 scroll-x rounded-xl bg-black/30 border border-line p-3 text-2xs text-ink-3 font-mono">{JSON.stringify(e.evidence, null, 2)}</pre>}
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
      <p className="text-xs text-ink-3 mb-3">Rows: {a.fixture.home_team.name} goals · Columns: {a.fixture.away_team.name} goals · values in %</p>
      <div className="grid grid-cols-[22px_repeat(6,minmax(0,1fr))] gap-1 text-center">
        <span />
        {g.matrix[0].map((_, j) => <span key={j} className="text-2xs text-ink-4 pb-1">{j}</span>)}
        {g.matrix.map((row, i) => (
          <div key={i} className="contents">
            <span className="text-2xs text-ink-4 grid place-items-center">{i}</span>
            {row.map((v, j) => (
              <span key={j} title={`${i}–${j}: ${pct(v)}`} className={cx("h-10 grid place-items-center rounded-lg num text-xs", v / max > 0.55 ? "text-white font-bold" : "text-ink-2")}
                    style={{ background: `rgba(57,135,229,${0.06 + (v / max) * 0.7})` }}>{(v * 100).toFixed(1)}</span>
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
  return (
    <Disclosure title="Asian handicap outcomes (home side)">
      <div className="scroll-x"><table className="table min-w-[320px] [&_td]:px-1.5 [&_th]:px-1.5 sm:[&_td]:px-3 sm:[&_th]:px-3">
        <thead><tr><th className="!pl-0">Line</th><th className="text-right">Win</th><th className="text-right">½ win</th><th className="text-right">Push</th><th className="text-right">½ loss</th><th className="text-right !pr-0">Loss</th></tr></thead>
        <tbody>
          {lines.map((k) => (
            <tr key={k}>
              <td className="num font-bold !pl-0">{k}</td>
              {(["win", "half_win", "push", "half_loss", "loss"] as const).map((o) => (
                <td key={o} className={cx("num text-right last:!pr-0", ah[k].home[o] < 0.005 ? "text-ink-4" : "text-ink-2")}>{pct(ah[k].home[o], 0)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table></div>
    </Disclosure>
  );
}

function History({ a }: { a: Analysis }) {
  return (
    <Disclosure title={`Prediction history (${a.prediction_history.length})`}>
      <p className="text-[13px] text-ink-3 mb-4">Every update is saved; old predictions are never edited.</p>
      <ol className="relative ml-1.5 border-l border-line-strong space-y-5">
        {a.prediction_history.map((h, i) => (
          <li key={h.id} className="pl-5 relative">
            <span className={cx("absolute -left-[6px] top-1.5 h-3 w-3 rounded-full ring-4 ring-night-2", i === 0 ? "bg-brand" : "bg-white/25")} />
            <div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-bold text-ink">{fmtDateTime(h.created_at)}</span><Pill>{h.trigger}</Pill>{i === 0 && <Pill tone="brand">Latest</Pill>}</div>
            {h.one_x_two && <div className="mt-2 max-w-xs"><OutcomeBar p={h.one_x_two} /></div>}
            <div className="mt-1.5 text-2xs text-ink-3">{verdict(h.classification).label} · confidence {Math.round(h.reliability)}</div>
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
        <ul className="mb-4 space-y-2">
          {warnings.map((w) => <li key={w} className="flex gap-2 rounded-xl bg-warn-soft border border-warn/20 px-3 py-2 text-xs text-ink-2"><Icon name="alert" size={13} className="text-warn shrink-0 mt-0.5" />{w}</li>)}
        </ul>
      )}
      <KeyValue items={[
        ["Matches the models learned from", String(dq.training_matches ?? "—")],
        ["Team sample sizes (home / away)", dq.sample_sizes ? `${dq.sample_sizes.home} / ${dq.sample_sizes.away}` : "—"],
        ["Bookmakers priced", String(dq.odds_bookmakers?.length ?? 0)],
        ["Model version", <span key="v" className="font-mono text-2xs break-all">{String(dq.model_version ?? "unvalidated")}</span>],
      ]} />
      <ul className="mt-4 space-y-2">
        {a.sources.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-3 glass-inset px-3 py-2.5 text-[13px]">
            <span className="min-w-0"><span className="block capitalize font-medium">{s.provider.replace(/_/g, " ")}</span><span className="block text-2xs text-ink-4 font-mono truncate">{s.resource}</span></span>
            <span className="text-right text-xs text-ink-3 shrink-0">{fmtDateTime(s.retrieved_at)}</span>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}
