import { useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { getToken } from "../api/client";
import { useAdminAction, useBacktest, useBacktests, useCompetitions, useMe, useModels, usePerformance } from "../api/hooks";
import { Icon } from "../components/icons";
import {
  AXIS, Card, ChartTooltip, cx, Disclosure, Empty, ErrorState, Field, Loading, OUTCOME_COLORS, PageHeader, Pill, SERIES, Sheet, StatTile,
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
      <PageHeader title="Track record" description="How our predictions would have done on past seasons they never saw — wins and losses included."
                  actions={<NewBacktest />} />

      {bt.isLoading && btId !== null ? <Card><Loading rows={4} /></Card> : m?.matches ? <Verdict m={m} /> : (
        <Card><Empty title="No track record yet" icon="chart">An administrator needs to run a backtest on historical seasons.</Empty></Card>
      )}

      <div className="space-y-6 mt-6">
        {m?.matches ? <Evidence m={m} /> : null}

        <Card title="Live record" subtitle="Real predictions made before kickoff, settled after the final whistle">
          {live.selections ? (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatTile label="Bets" value={live.selections} hint={live.sample_warning ?? undefined} />
              <StatTile label="Return on stake" value={signedPct(live.roi)} tone={live.roi > 0 ? "pos" : "neg"} />
              <StatTile label="Profit" value={`${num(live.profit, 1)} u`} />
              <StatTile label="Beat closing price" value={signedPct(live.clv_mean)} info={GLOSSARY.clv} />
            </div>
          ) : (
            <div className="flex gap-3 rounded-2xl bg-white/[0.04] border border-white/[0.06] p-4 text-[14px] text-ink-2">
              <Icon name="clock" size={18} className="text-ink-3 shrink-0 mt-0.5" />
              No live bets settled yet. This fills in automatically as recommended bets are made and matches finish.
            </div>
          )}
        </Card>

        <Disclosure title="Technical details">
          <div className="space-y-6">
            <div>
              <div className="field-label mb-2">Backtest runs</div>
              {!backtests.data?.items.length ? <p className="text-[13px] text-ink-3">None yet.</p> : (
                <ul className="space-y-2">
                  {backtests.data.items.map((b) => (
                    <li key={b.id}>
                      <button onClick={() => setSelected(b.id)}
                              className={cx("w-full text-left rounded-2xl border px-4 py-3 transition-colors",
                                b.id === btId ? "bg-white/[0.08] border-white/20" : "bg-white/[0.03] border-white/[0.06] hover:bg-white/[0.06]")}>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-bold text-[13.5px]">#{b.id}</span>
                          <span className="text-[13px] text-ink-2 truncate">{b.params.competitions.join(", ")}</span>
                          <Pill tone={b.status === "completed" ? "pos" : b.status === "failed" ? "neg" : "warn"} className="ml-auto">{b.status}</Pill>
                        </div>
                        <div className="mt-1 text-xs text-ink-3">{b.params.date_from} → {b.params.date_to} · {b.metrics?.matches?.toLocaleString() ?? "—"} matches · run {fmtDateTime(b.created_at)}</div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="field-label mb-2">Model versions</div>
              {!models.data?.length ? <p className="text-[13px] text-ink-3">None registered.</p> : (
                <ul className="space-y-2">
                  {models.data.map((v) => (
                    <li key={v.id} className="rounded-2xl bg-white/[0.03] border border-white/[0.06] px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs break-all">{v.version}</span>
                        <Pill tone={v.status === "deployed" ? "brand" : "neutral"}>{v.status}</Pill>
                      </div>
                      <div className="mt-2 text-xs text-ink-3">
                        Blend weights: {Object.entries(v.ensemble_weights).filter(([k]) => !k.startsWith("_")).map(([k, w]: any) => `${k.replace(/_/g, " ")} ${num(w)}`).join(" · ")}
                      </div>
                      <div className="mt-1 text-xs text-ink-3">Calibrated markets: {v.validated_markets.map(marketLabel).join(", ") || "none"}</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {m?.notes && (
              <div>
                <div className="field-label mb-2">How the test works</div>
                <ul className="space-y-1.5">{m.notes.map((n: string) => <li key={n} className="flex gap-2 text-[13px] text-ink-2"><Icon name="check" size={14} className="text-ink-4 mt-1 shrink-0" />{n}</li>)}</ul>
              </div>
            )}
          </div>
        </Disclosure>
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
      text: `Forecast score ${num(ens, 3)} vs bookmakers ${num(mkt, 3)} (lower is better)`, info: GLOSSARY.logloss },
    { ok: calibrated.length > 0, title: calibrated.length ? "Probabilities are honest" : "Probabilities need work",
      text: calibrated.length ? `Checked and honest for: ${calibrated.map(marketLabel).join(", ")}` : "No market passed the calibration test", info: GLOSSARY.calibrated },
    { ok: edge, title: edge ? "Profitable on history" : "Not profitable on history",
      text: b.roi_interval_90 ? `Return ${signedPct(b.roi)} on ${b.bets} bets (likely range ${signedPct(b.roi_interval_90[0])} to ${signedPct(b.roi_interval_90[1])})` : "Too few bets to judge", info: GLOSSARY.value },
  ];
  return (
    <section className="card relative overflow-hidden p-6 sm:p-8 animate-fade-up">
      <div aria-hidden className={cx("absolute inset-0", edge ? "bg-[radial-gradient(60%_100%_at_0%_0%,rgba(52,211,153,0.18),transparent_60%)]" : "bg-[radial-gradient(60%_100%_at_0%_0%,rgba(251,191,36,0.12),transparent_60%)]")} />
      <div className="relative">
        <div className="eyebrow">Tested on {m.matches.toLocaleString()} past matches · {fmtDate(m.date_from)} – {fmtDate(m.date_to)}</div>
        <h2 className="mt-3 text-[22px] sm:text-[28px] font-extrabold tracking-[-0.03em] leading-tight max-w-3xl">{headline}</h2>
        <p className="mt-2 text-[14.5px] text-ink-2 max-w-3xl leading-relaxed">
          {edge ? "Results still carry risk — past performance does not guarantee future returns."
            : "That's why most matches show “No value bet”. We'd rather tell you that than invent picks."}
        </p>
        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {checks.map((c) => (
            <div key={c.title} className={cx("flex gap-3 rounded-2xl border p-4", c.ok ? "border-pos/30 bg-pos-soft" : "border-white/[0.07] bg-white/[0.04]")}>
              <span className={cx("grid place-items-center h-9 w-9 rounded-full shrink-0", c.ok ? "bg-pos/25 text-pos" : "bg-white/10 text-ink-2")}>
                <Icon name={c.ok ? "check" : "x"} size={16} />
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-1 text-[14px] font-bold">{c.title}</div>
                <div className="mt-1 text-xs text-ink-3 leading-snug">{c.text}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Evidence({ m }: { m: any }) {
  const b = m.betting ?? {};
  const comp = m.one_x_two.comparison_common_subset ?? {};
  const ranked = Object.entries(comp).sort((x: any, y: any) => x[1].log_loss - y[1].log_loss) as [string, any][];
  const best = ranked[0]?.[1].log_loss ?? 0, worst = ranked[ranked.length - 1]?.[1].log_loss ?? 1;
  const calib = (["home", "draw", "away"] as const).map((k) => ({ k, points: (m.calibration?.[k] ?? []).map((x: any) => ({ predicted: x.predicted, observed: x.observed, count: x.count })) }));
  const NAMES: Record<string, string> = { market: "Bookmakers", ensemble: "Our blend", dixon_coles: "Goals model", elo: "Ratings model", feature_model: "Form model", base_rates: "Guessing base rates" };
  return (
    <>
      <Card title="If you had followed every pick" subtitle={`Flat 1-unit bets under the default rules · ${b.overall?.bets ?? 0} bets`}>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <StatTile label="Return on stake" value={signedPct(b.overall?.roi)} tone={b.overall?.roi > 0 ? "pos" : "neg"}
                    hint={b.overall?.roi_interval_90 ? `likely ${signedPct(b.overall.roi_interval_90[0])} to ${signedPct(b.overall.roi_interval_90[1])}` : undefined} />
          <StatTile label="Profit" value={`${num(b.overall?.profit, 1)} u`} tone={b.overall?.profit > 0 ? "pos" : "neg"} hint="units staked: 1 per bet" />
          <StatTile label="Win rate" value={pct(b.overall?.hit_rate, 0)} hint={`average odds ${num(b.overall?.avg_odds)}`} />
          <StatTile label="Worst losing run" value={`${num(b.overall?.max_drawdown, 1)} u`} hint="largest peak-to-trough drop" />
        </div>
        {b.equity_curve?.length > 0 && (
          <div className="mt-6 h-60 sm:h-72">
            <ResponsiveContainer>
              <LineChart data={b.equity_curve} margin={{ left: -14, right: 8, top: 8 }}>
                <CartesianGrid stroke={AXIS.grid} vertical={false} />
                <XAxis dataKey="date" stroke={AXIS.stroke} fontSize={10} minTickGap={60} tickLine={false} axisLine={false} />
                <YAxis stroke={AXIS.stroke} fontSize={AXIS.fontSize} axisLine={false} tickLine={false} />
                <ReferenceLine y={0} stroke="rgba(255,255,255,0.25)" strokeDasharray="4 4" />
                <Tooltip content={<ChartTooltip fmt={(v) => `${num(v, 1)} units`} />} />
                <Line isAnimationActive={false} dataKey="cumulative_profit" name="Running profit" stroke={SERIES[0]} strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <Card title="Who forecasts best?" subtitle="Forecast score on the same matches — shorter bar = worse" info={GLOSSARY.logloss}>
          <ul className="space-y-3.5">
            {ranked.map(([k, v], i) => (
              <li key={k}>
                <div className="flex items-center justify-between gap-3 text-[13.5px]">
                  <span className={cx("font-semibold", k === "ensemble" && "text-brand-strong")}>{i + 1}. {NAMES[k] ?? k}</span>
                  <span className="num text-ink-3">{num(v.log_loss, 3)} · {pct(v.accuracy, 0)} right</span>
                </div>
                <div className="mt-1.5 h-2 rounded-full bg-white/[0.06] overflow-hidden">
                  <div className={cx("h-full rounded-full", k === "ensemble" ? "bg-brand" : k === "market" ? "bg-white/50" : "bg-white/20")}
                       style={{ width: `${100 - ((v.log_loss - best) / (worst - best || 1)) * 75}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Are our percentages honest?" subtitle="Dots on the dashed line mean “when we say 40%, it happens 40% of the time”" info={GLOSSARY.calibrated}>
          <div className="flex gap-4 text-xs text-ink-2 mb-2">
            {calib.map(({ k }) => <span key={k} className="flex items-center gap-1.5 capitalize"><span className="h-2.5 w-2.5 rounded-full" style={{ background: OUTCOME_COLORS[k] }} />{k} win{k === "draw" ? "" : ""}</span>)}
          </div>
          <div className="h-64">
            <ResponsiveContainer>
              <ScatterChart margin={{ left: -14, right: 8, top: 8 }}>
                <CartesianGrid stroke={AXIS.grid} />
                <XAxis type="number" dataKey="predicted" domain={[0, 1]} stroke={AXIS.stroke} fontSize={AXIS.fontSize} tickFormatter={(v) => pct(v, 0)} tickLine={false} name="We said" />
                <YAxis type="number" dataKey="observed" domain={[0, 1]} stroke={AXIS.stroke} fontSize={AXIS.fontSize} tickFormatter={(v) => pct(v, 0)} tickLine={false} axisLine={false} name="Happened" />
                <ZAxis type="number" dataKey="count" range={[30, 200]} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="rgba(255,255,255,0.3)" strokeDasharray="4 4" />
                <Tooltip cursor={false} content={({ active, payload }) => active && payload?.length ? (
                  <div className="glass-strong rounded-xl px-3 py-2 text-xs num">
                    <div>We said {pct(payload[0].payload.predicted, 0)}</div><div>Happened {pct(payload[0].payload.observed, 0)}</div>
                    <div className="text-ink-3">{payload[0].payload.count} matches</div>
                  </div>) : null} />
                {calib.map(({ k, points }) => <Scatter isAnimationActive={false} key={k} name={k} data={points} fill={OUTCOME_COLORS[k]} />)}
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
    </>
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
      <button className="btn btn-primary" onClick={() => setOpen(true)}><Icon name="activity" size={15} />New backtest</button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Test on past seasons"
             footer={
               <div className="flex items-center gap-2">
                 {action.isError && <span className="text-xs text-neg flex-1">{(action.error as Error).message}</span>}
                 <button className="btn ml-auto" onClick={() => setOpen(false)}>Cancel</button>
                 <button className="btn btn-primary" disabled={!form.competitions.length || action.isPending}
                         onClick={() => action.mutate({ path: "/backtests", body: form }, { onSuccess: () => setOpen(false) })}>Start test</button>
               </div>
             }>
        <div className="space-y-5">
          <div>
            <div className="field-label mb-2">Leagues</div>
            <div className="flex flex-wrap gap-2">
              {(comps.data ?? []).map((c) => (
                <button key={c.code} onClick={() => toggle(c.code)} aria-pressed={form.competitions.includes(c.code)} className="chip-btn h-8">{c.name}</button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="From"><input className="input" type="date" value={form.date_from} onChange={(e) => setForm({ ...form, date_from: e.target.value })} /></Field>
            <Field label="To"><input className="input" type="date" value={form.date_to} onChange={(e) => setForm({ ...form, date_to: e.target.value })} /></Field>
          </div>
          <label className="flex items-start gap-3 text-[13.5px] text-ink-2">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-[#22c55e]" checked={form.deploy} onChange={(e) => setForm({ ...form, deploy: e.target.checked })} />
            Use the result for live predictions
          </label>
        </div>
      </Sheet>
    </>
  );
}
