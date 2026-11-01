import { useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { getToken } from "../api/client";
import { useAdminAction, useBacktest, useBacktests, useCompetitions, useMe, useModels, usePerformance } from "../api/hooks";
import { Icon } from "../components/icons";
import {
  Card, chart, ChartTooltip, cx, Disclosure, Empty, ErrorState, Field, Legend, Loading, PageHeader, Pill, SectionTitle, Sheet,
  StatTile, useColorScheme,
} from "../components/ui";
import { fmtDate, fmtDateTime, marketLabel, num, pct, signedPct } from "../lib/format";
import { GLOSSARY } from "../lib/language";

export default function Performance() {
  const perf = usePerformance();
  const backtests = useBacktests();
  const models = useModels();
  const [selected, setSelected] = useState<number | null>(null);
  const btId = selected ?? backtests.data?.items.find((b) => b.status === "completed")?.id ?? null;
  const bt = useBacktest(btId);

  if (perf.isLoading) return <Card><Loading rows={5} /></Card>;
  if (perf.isError) return <ErrorState error={perf.error} onRetry={perf.refetch} />;
  const p = perf.data!;
  const m = bt.data?.metrics;
  const live = p.prospective.overall;

  return (
    <>
      <PageHeader title="Track record" description="How our predictions did on past seasons they never saw, losses included."
                  actions={<NewBacktest />} />

      {bt.isLoading && btId !== null ? <Card><Loading rows={4} /></Card> : m?.matches ? <Verdict m={m} /> : (
        <Card><Empty title="No track record yet" icon="chart">An administrator needs to run a backtest on historical seasons.</Empty></Card>
      )}

      <div className="mt-8 space-y-8">
        {m?.matches ? <Evidence m={m} /> : null}

        <section>
          <SectionTitle>Live record</SectionTitle>
          {live.selections ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatTile label="Bets" value={live.selections} hint={live.sample_warning ?? undefined} />
              <StatTile label="Return" value={signedPct(live.roi)} tone={live.roi > 0 ? "pos" : "neg"} />
              <StatTile label="Profit" value={`${num(live.profit, 1)}u`} />
              <StatTile label="Beat closing price" value={signedPct(live.clv_mean)} info={GLOSSARY.clv} />
            </div>
          ) : (
            <Card><p className="text-sm text-ink-3">No live bets settled yet. This fills in as recommended bets are made and matches finish.</p></Card>
          )}
        </section>

        <section>
          <SectionTitle>Technical details</SectionTitle>
          <div className="card overflow-hidden divide-soft">
            {m?.matches ? <Calibration m={m} /> : null}
            <Disclosure title={`Backtest runs (${backtests.data?.items.length ?? 0})`}>
              {!backtests.data?.items.length ? <p className="text-sm text-ink-3">None yet.</p> : (
                <ul className="space-y-2">
                  {backtests.data.items.map((b) => (
                    <li key={b.id}>
                      <button onClick={() => setSelected(b.id)}
                              className={cx("w-full text-left rounded-xl border px-3.5 py-3 transition-colors",
                                b.id === btId ? "border-ink/40 bg-subtle" : "border-line hover:bg-subtle/60")}>
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-sm font-medium shrink-0">#{b.id}</span>
                          <span className="text-[13px] text-ink-3 truncate">{b.params.competitions.join(", ")}</span>
                          <Pill tone={b.status === "completed" ? "pos" : b.status === "failed" ? "neg" : "warn"} className="ml-auto">{b.status}</Pill>
                        </div>
                        <div className="mt-1 text-xs text-ink-4">{b.params.date_from} → {b.params.date_to} · {b.metrics?.matches?.toLocaleString() ?? "—"} matches · {fmtDateTime(b.created_at)}</div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Disclosure>
            <Disclosure title={`Model versions (${models.data?.length ?? 0})`}>
              {!models.data?.length ? <p className="text-sm text-ink-3">None registered.</p> : (
                <ul className="divide-soft">
                  {models.data.map((v) => (
                    <li key={v.id} className="py-3 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs break-all">{v.version}</span>
                        {v.status === "deployed" ? <Pill tone="pos">deployed</Pill> : <Pill>{v.status}</Pill>}
                      </div>
                      <div className="mt-1.5 text-xs text-ink-3">
                        Weights: {Object.entries(v.ensemble_weights).filter(([k]) => !k.startsWith("_")).map(([k, w]: any) => `${k.replace(/_/g, " ")} ${num(w)}`).join(" · ")}
                      </div>
                      <div className="mt-0.5 text-xs text-ink-3">Calibrated: {v.validated_markets.map(marketLabel).join(", ") || "none"}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Disclosure>
            {m?.notes && (
              <Disclosure title="How the test works">
                <ul className="space-y-1.5">{m.notes.map((n: string) => <li key={n} className="text-[13px] text-ink-2">· {n}</li>)}</ul>
              </Disclosure>
            )}
          </div>
        </section>
      </div>
    </>
  );
}

function Verdict({ m }: { m: any }) {
  const comp = m.one_x_two.comparison_common_subset ?? {};
  const ens = comp.ensemble?.log_loss, mkt = comp.market?.log_loss;
  const beats = ens !== undefined && mkt !== undefined && ens < mkt;
  const b = m.betting?.overall ?? {};
  const edge = !!b.edge_demonstrated;
  const calibrated = m.validated_markets ?? [];
  const headline = edge
    ? "The model has shown a real edge on past seasons."
    : beats ? "The model predicts slightly better than bookmakers, but not by enough to profit."
    : "The model does not beat the bookmakers yet.";
  const checks = [
    { ok: beats, title: beats ? "More accurate than bookmakers" : "Less accurate than bookmakers",
      text: `Forecast score ${num(ens, 3)} vs ${num(mkt, 3)} (lower is better)`, info: GLOSSARY.logloss },
    { ok: calibrated.length > 0, title: calibrated.length ? "Probabilities are honest" : "Probabilities need work",
      text: calibrated.length ? `Honest for: ${calibrated.map(marketLabel).join(", ")}` : "No market passed the calibration test", info: GLOSSARY.calibrated },
    { ok: edge, title: edge ? "Profitable on history" : "Not profitable on history",
      text: b.roi_interval_90 ? `Return ${signedPct(b.roi)} on ${b.bets} bets (likely ${signedPct(b.roi_interval_90[0])} to ${signedPct(b.roi_interval_90[1])})` : "Too few bets to judge", info: GLOSSARY.value },
  ];
  return (
    <section className="card p-5 sm:p-6">
      <div className="text-xs text-ink-3">{m.matches.toLocaleString()} past matches · {fmtDate(m.date_from)} – {fmtDate(m.date_to)}</div>
      <h2 className="mt-2 text-xl sm:text-2xl font-semibold tracking-tight max-w-2xl">{headline}</h2>
      <p className="mt-2 text-sm text-ink-3 max-w-2xl">
        {edge ? "Results still carry risk; past performance does not guarantee future returns."
          : "That's why most matches show “No value bet”. We'd rather say so than invent picks."}
      </p>
      <ul className="mt-5 grid gap-4 md:grid-cols-3">
        {checks.map((c) => (
          <li key={c.title} className="flex gap-3 min-w-0">
            <span className={cx("grid place-items-center h-6 w-6 rounded-full shrink-0", c.ok ? "bg-pos/15 text-pos" : "bg-subtle text-ink-3")}>
              <Icon name={c.ok ? "check" : "x"} size={13} />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-medium">{c.title}</div>
              <div className="mt-0.5 text-xs text-ink-3">{c.text}</div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

const NAMES: Record<string, string> = { market: "Bookmakers", ensemble: "Our blend", dixon_coles: "Goals model", elo: "Ratings model", feature_model: "Form model", base_rates: "Guessing base rates" };

function Evidence({ m }: { m: any }) {
  useColorScheme();
  const c = chart();
  const b = m.betting ?? {};
  const comp = m.one_x_two.comparison_common_subset ?? {};
  const ranked = Object.entries(comp).sort((x: any, y: any) => x[1].log_loss - y[1].log_loss) as [string, any][];
  const best = ranked[0]?.[1].log_loss ?? 0, worst = ranked[ranked.length - 1]?.[1].log_loss ?? 1;
  return (
    <>
      <section>
        <SectionTitle>If you had followed every pick</SectionTitle>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile label="Return" value={signedPct(b.overall?.roi)} tone={b.overall?.roi > 0 ? "pos" : "neg"}
                    hint={b.overall?.roi_interval_90 ? `likely ${signedPct(b.overall.roi_interval_90[0])} to ${signedPct(b.overall.roi_interval_90[1])}` : `${b.overall?.bets ?? 0} bets`} />
          <StatTile label="Profit" value={`${num(b.overall?.profit, 1)}u`} tone={b.overall?.profit > 0 ? "pos" : "neg"} hint="1 unit per bet" />
          <StatTile label="Win rate" value={pct(b.overall?.hit_rate, 0)} hint={`average odds ${num(b.overall?.avg_odds)}`} />
          <StatTile label="Worst run" value={`${num(b.overall?.max_drawdown, 1)}u`} hint="peak-to-trough drop" />
        </div>
        {b.equity_curve?.length > 0 && (
          <Card className="mt-3" title="Running profit">
            <div className="h-56 sm:h-64">
              <ResponsiveContainer>
                <LineChart data={b.equity_curve} margin={{ left: -20, right: 4, top: 8 }}>
                  <CartesianGrid stroke={c.grid} vertical={false} />
                  <XAxis dataKey="date" stroke={c.axis} fontSize={10} minTickGap={60} tickLine={false} axisLine={false} />
                  <YAxis stroke={c.axis} fontSize={c.fontSize} axisLine={false} tickLine={false} />
                  <ReferenceLine y={0} stroke={c.axis} strokeDasharray="3 3" />
                  <Tooltip content={<ChartTooltip fmt={(v) => `${num(v, 1)} units`} />} />
                  <Line isAnimationActive={false} dataKey="cumulative_profit" name="Running profit" stroke={c.series[0]} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
      </section>

      <Card title="Who forecasts best?" subtitle="Forecast score on the same matches; longer bar is better" info={GLOSSARY.logloss}>
        <ul className="space-y-3.5">
          {ranked.map(([k, v], i) => (
            <li key={k}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className={cx("min-w-0 truncate", k === "ensemble" ? "font-semibold" : "text-ink-2")}>{i + 1}. {NAMES[k] ?? k}</span>
                <span className="shrink-0 num text-xs text-ink-3">{num(v.log_loss, 3)} · {pct(v.accuracy, 0)} right</span>
              </div>
              <div className="mt-1.5 h-1.5 rounded-full bg-subtle overflow-hidden">
                <div className={cx("h-full rounded-full", k === "ensemble" ? "bg-ink" : "bg-ink-4/60")}
                     style={{ width: `${100 - ((v.log_loss - best) / (worst - best || 1)) * 75}%` }} />
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}

function Calibration({ m }: { m: any }) {
  useColorScheme();
  const c = chart();
  const calib = (["home", "draw", "away"] as const).map((k) => ({ k, points: (m.calibration?.[k] ?? []).map((x: any) => ({ predicted: x.predicted, observed: x.observed, count: x.count })) }));
  return (
    <Disclosure title={<span className="flex items-center gap-1.5">Are our percentages honest?</span>}>
      <p className="mb-3 text-[13px] text-ink-3">Dots on the dashed line mean “when we say 40%, it happens 40% of the time”. {GLOSSARY.calibrated}</p>
      <Legend items={calib.map(({ k }) => [k === "draw" ? "Draw" : `${k[0].toUpperCase()}${k.slice(1)} win`, c.outcome[k]])} />
      <div className="h-64">
        <ResponsiveContainer>
          <ScatterChart margin={{ left: -20, right: 8, top: 8 }}>
            <CartesianGrid stroke={c.grid} />
            <XAxis type="number" dataKey="predicted" domain={[0, 1]} stroke={c.axis} fontSize={c.fontSize} tickFormatter={(v) => pct(v, 0)} tickLine={false} name="We said" />
            <YAxis type="number" dataKey="observed" domain={[0, 1]} stroke={c.axis} fontSize={c.fontSize} tickFormatter={(v) => pct(v, 0)} tickLine={false} axisLine={false} name="Happened" />
            <ZAxis type="number" dataKey="count" range={[24, 160]} />
            <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke={c.axis} strokeDasharray="3 3" />
            <Tooltip cursor={false} content={({ active, payload }) => active && payload?.length ? (
              <div className="rounded-xl border border-line bg-surface shadow-pop px-3 py-2 text-xs num">
                <div>We said {pct(payload[0].payload.predicted, 0)}</div><div>Happened {pct(payload[0].payload.observed, 0)}</div>
                <div className="text-ink-3">{payload[0].payload.count} matches</div>
              </div>) : null} />
            {calib.map(({ k, points }) => <Scatter isAnimationActive={false} key={k} name={k} data={points} fill={c.outcome[k]} />)}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </Disclosure>
  );
}

function NewBacktest() {
  const me = useMe(!!getToken());
  const comps = useCompetitions();
  const action = useAdminAction();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ competitions: ["ENG-1"], date_from: "2023-08-01", date_to: new Date().toISOString().slice(0, 10), deploy: false });
  if (me.data?.role !== "admin") return null;
  const toggle = (code: string) => setForm((f) => ({ ...f, competitions: f.competitions.includes(code) ? f.competitions.filter((c) => c !== code) : [...f.competitions, code] }));
  return (
    <>
      <button className="btn btn-primary" onClick={() => setOpen(true)}>New backtest</button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Test on past seasons"
             footer={
               <div className="flex flex-wrap items-center gap-2">
                 {action.isError && <span className="text-xs text-neg flex-1 min-w-0">{(action.error as Error).message}</span>}
                 <button className="btn ml-auto" onClick={() => setOpen(false)}>Cancel</button>
                 <button className="btn btn-primary" disabled={!form.competitions.length || action.isPending}
                         onClick={() => action.mutate({ path: "/backtests", body: form }, { onSuccess: () => setOpen(false) })}>Start test</button>
               </div>
             }>
        <div className="space-y-5">
          <div>
            <div className="text-[13px] font-medium text-ink-2 mb-2">Leagues</div>
            <div className="flex flex-wrap gap-1.5">
              {(comps.data ?? []).map((c) => (
                <button key={c.code} onClick={() => toggle(c.code)} aria-pressed={form.competitions.includes(c.code)} className="chip h-8 border border-line">{c.name}</button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="From"><input className="input" type="date" value={form.date_from} onChange={(e) => setForm({ ...form, date_from: e.target.value })} /></Field>
            <Field label="To"><input className="input" type="date" value={form.date_to} onChange={(e) => setForm({ ...form, date_to: e.target.value })} /></Field>
          </div>
          <label className="flex items-start gap-3 text-sm text-ink-2">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-current" checked={form.deploy} onChange={(e) => setForm({ ...form, deploy: e.target.checked })} />
            Use the result for live predictions
          </label>
        </div>
      </Sheet>
    </>
  );
}
