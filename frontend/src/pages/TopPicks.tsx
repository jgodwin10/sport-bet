import { useState } from "react";
import { Link } from "react-router-dom";
import { useTopPickRecord, useTopPicks } from "../api/hooks";
import type { TopPick, TopPickRecord, TopPickResult, TopPickTally } from "../api/types";
import { Icon } from "../components/icons";
import {
  Card, cx, Empty, ErrorState, Freshness, InfoTip, Loading, PageHeader, Pill, ReliabilityBadge, Segmented, StatTile, TeamLogo,
} from "../components/ui";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { friendlyReason, GLOSSARY, selectionLabel } from "../lib/language";

const WINDOWS = [
  { value: "2", label: "Next 48 hours" },
  { value: "7", label: "Next 7 days" },
  { value: "14", label: "Next 14 days" },
];

const TRACKING = "Every match in the Top 10 at kickoff counts, staked 1 unit at the odds shown when it was last listed. Picks that dropped out before kickoff are shown but not counted.";

const RANKING = "Each match's best-priced bet, ranked by its value at the cautious end of our estimate and scaled by data reliability. Bets that pass every safety check come first.";

export default function TopPicks() {
  const [view, setView] = useState("upcoming");
  return (
    <>
      <PageHeader eyebrow="Ranked by the model" title="Top 10 picks"
                  description={view === "upcoming"
                    ? <>The strongest bet in each upcoming match, best first, with the AI's read on the team news. <InfoTip text={RANKING} /></>
                    : <>How the Top 10 has done, at 1 unit per pick. <InfoTip text={TRACKING} /></>}
                  actions={<Segmented label="View" value={view} onChange={setView}
                                      options={[{ value: "upcoming", label: "Upcoming" }, { value: "results", label: "Results" }]} />} />
      {view === "upcoming" ? <Upcoming /> : <Results />}
    </>
  );
}

function Upcoming() {
  const [days, setDays] = useState("7");
  const q = useTopPicks(Number(days));
  const items = q.data?.items ?? [];
  const recommended = items.filter((t) => t.tier === "recommended").length;

  return (
    <>
      <Segmented variant="chips" label="Window" value={days} onChange={setDays} options={WINDOWS} className="mb-4" />

      {q.isLoading ? <Card><Loading rows={6} /></Card>
        : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} />
        : !items.length ? (
          <Card>
            <Empty title="No picks in this window" icon="ban">
              None of the upcoming matches has a price that beats our estimate. Try a longer window, or check back after the next odds refresh.
            </Empty>
          </Card>
        ) : (
          <>
            {recommended < items.length && (
              <p className="mb-4 flex items-start gap-2 text-[13px] text-ink-3 leading-relaxed">
                <Icon name="info" size={15} className="mt-0.5 shrink-0" />
                {recommended
                  ? `${recommended} of these pass every safety check. The rest show value but failed a check, so treat them as a watchlist.`
                  : "None of these pass every safety check yet. They show value but are a watchlist, not recommendations."}
              </p>
            )}
            <ol className="grid gap-4 lg:grid-cols-2">
              {items.map((t, i) => <TopPickCard key={t.selection_id} t={t} delay={i} aiConfigured={q.data!.ai_configured} />)}
            </ol>
          </>
        )}
    </>
  );
}

function TopPickCard({ t, delay, aiConfigured }: { t: TopPick; delay: number; aiConfigured: boolean }) {
  const home = t.home_team?.name, away = t.away_team?.name;
  const recommended = t.tier === "recommended";
  return (
    <li style={{ animationDelay: `${Math.min(delay, 12) * 30}ms` }} className="animate-fade-up">
      <Link to={`/match/${t.fixture_id}`}
            className={cx("card group flex h-full flex-col p-5 transition-all hover:-translate-y-0.5 hover:bg-white/[0.08]",
                          recommended && "ring-1 ring-pos/35")}>
        <div className="flex items-start gap-3">
          <span className={cx("num grid place-items-center h-10 w-10 shrink-0 rounded-xl text-[17px] font-extrabold",
                              t.rank <= 3 ? "bg-brand-soft text-brand-strong ring-1 ring-brand/30" : "bg-white/[0.06] text-ink-2")}>
            {t.rank}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 min-w-0">
              <span className="flex -space-x-1.5 shrink-0">
                <TeamLogo name={home ?? ""} src={t.home_team?.logo_url} size={22} />
                <TeamLogo name={away ?? ""} src={t.away_team?.logo_url} size={22} />
              </span>
              <span className="truncate text-[13px] font-semibold text-ink-2">{t.match}</span>
            </div>
            <div className="mt-0.5 text-2xs text-ink-4">{t.competition} · {fmtDateTime(t.kickoff_utc)}</div>
          </div>
          {recommended
            ? <Pill tone="pos" icon="check">Recommended</Pill>
            : <Pill tone="warn" icon="alert" title={t.rejection_reasons.map(friendlyReason).join("\n")}>Watchlist</Pill>}
        </div>

        <div className="mt-4 flex items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="text-2xs font-semibold text-ink-3">Bet</div>
            <div className="text-[16px] font-extrabold leading-tight">{selectionLabel(t.market, t.selection, home, away)}</div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-2xs font-semibold text-ink-3">Odds</div>
            <div className="num text-[22px] font-extrabold leading-none">{odds(t.odds)}</div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          <Metric label="Our chance" value={pct(t.probability, 0)} />
          <Metric label="Bookmaker" value={pct(t.implied_probability, 0)} />
          <Metric label="Value" value={signedPct(t.expected_value)} tone={t.expected_value > 0 ? "pos" : undefined} info={GLOSSARY.value} />
        </div>

        {!recommended && t.rejection_reasons[0] && (
          <p className="mt-3 text-xs text-ink-4 line-clamp-1">Held back: {friendlyReason(t.rejection_reasons[0])}</p>
        )}

        <AiRead t={t} configured={aiConfigured} />

        <div className="mt-auto pt-3 flex items-center justify-end gap-3 border-t border-white/[0.06]">
          <ReliabilityBadge score={t.reliability_score} label={t.reliability_label} />
          <Freshness hours={t.odds_age_hours} label="" />
        </div>
      </Link>
    </li>
  );
}

function AiRead({ t, configured }: { t: TopPick; configured: boolean }) {
  const ai = t.ai;
  if (!ai) {
    return (
      <div className="mt-4 mb-3 flex items-center gap-2 text-xs text-ink-4">
        <Icon name="sparkle" size={14} />
        {configured ? "AI analysis runs within 48 hours of kickoff." : "AI analysis is not set up on this server."}
      </div>
    );
  }
  return (
    <div className="mt-4 mb-3 rounded-xl bg-white/[0.04] border border-white/[0.05] p-3">
      <div className="flex flex-wrap items-center gap-2 text-2xs font-semibold text-ink-3">
        <Icon name="sparkle" size={13} className="text-brand-strong" />AI read
        {ai.verdict === "supports" && <Pill tone="pos" icon="check">Still sees value{ai.probability !== null && ` · ${pct(ai.probability, 0)}`}</Pill>}
        {ai.verdict === "doubts" && <Pill tone="neg" icon="x">Doubts this bet{ai.probability !== null && ` · ${pct(ai.probability, 0)}`}</Pill>}
        {ai.confidence && <span className="text-ink-4 capitalize">{ai.confidence} confidence</span>}
        {!ai.current && <span className="text-ink-4">· written for an earlier prediction</span>}
      </div>
      <p className="mt-1.5 text-[13px] text-ink-2 leading-relaxed line-clamp-3">{ai.summary}</p>
    </div>
  );
}

function Results() {
  const q = useTopPickRecord();
  if (q.isLoading) return <Card><Loading rows={6} /></Card>;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const rec = q.data as TopPickRecord;
  if (!rec.history.length) {
    return (
      <Card>
        <Empty title="No results yet" icon="clock">
          The Top 10 is recorded every time predictions update. Results appear here once those matches have been played.
        </Empty>
      </Card>
    );
  }
  const all = rec.summary.all;
  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <StatTile label="Profit" value={units(all.profit)} tone={all.profit > 0 ? "pos" : all.profit < 0 ? "neg" : undefined}
                  hint={`from ${all.settled} settled pick${all.settled === 1 ? "" : "s"}`} />
        <StatTile label="Return per pick" value={all.roi === null ? "—" : signedPct(all.roi)}
                  tone={all.roi === null ? undefined : all.roi > 0 ? "pos" : all.roi < 0 ? "neg" : undefined} hint="ROI at 1 unit each" />
        <StatTile label="Won · lost" value={`${all.won} · ${all.lost}`} hint={all.void ? `${all.void} void or push` : undefined} />
        <StatTile label="Awaiting result" value={all.pending} hint={rec.dropped ? `${rec.dropped} dropped before kickoff, not counted` : undefined} />
      </div>

      {all.settled > 0 && all.settled < 50 && (
        <p className="mt-3 flex items-start gap-2 text-[13px] text-ink-3 leading-relaxed">
          <Icon name="info" size={15} className="mt-0.5 shrink-0" />
          {all.settled} results is a small sample: profit this early is mostly luck, in either direction.
        </p>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <TierLine label="Recommended" tone="pos" t={rec.summary.recommended} />
        <TierLine label="Watchlist" tone="warn" t={rec.summary.watchlist} />
      </div>

      <Card title="Pick history" subtitle="Newest first" className="mt-6" flush>
        <ul className="divide-y divide-white/[0.06]">
          {rec.history.map((h) => <ResultRow key={h.fixture_id} h={h} />)}
        </ul>
      </Card>
    </>
  );
}

const units = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(2)}u`;

function TierLine({ label, tone, t }: { label: string; tone: "pos" | "warn"; t: TopPickTally }) {
  return (
    <div className="card flex items-center justify-between gap-3 px-4 py-3">
      <Pill tone={tone}>{label}</Pill>
      <span className="text-[13px] text-ink-3 num">
        {t.settled ? <>{t.won}–{t.lost} · <span className={cx("font-bold", t.profit > 0 ? "text-pos" : t.profit < 0 ? "text-neg" : "text-ink")}>{units(t.profit)}</span></>
          : "no results yet"}
        {t.pending > 0 && ` · ${t.pending} pending`}
      </span>
    </div>
  );
}

function ResultRow({ h }: { h: TopPickResult }) {
  const home = h.home_team?.name, away = h.away_team?.name;
  const win = h.outcome === "win" || h.outcome === "half_win", loss = h.outcome === "loss" || h.outcome === "half_loss";
  return (
    <li>
      <Link to={`/match/${h.fixture_id}`} className={cx("flex items-center gap-3 px-4 sm:px-6 py-3 hover:bg-white/[0.04] transition-colors", !h.counted && "opacity-60")}>
        <span className="num grid place-items-center h-8 w-8 shrink-0 rounded-lg bg-white/[0.06] text-[13px] font-bold text-ink-2">{h.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-semibold">{selectionLabel(h.market, h.selection, home, away)} <span className="num text-ink-3">@ {odds(h.odds)}</span></div>
          <div className="truncate text-2xs text-ink-4">
            {h.match}{h.score && <span className="num"> · {h.score.home}–{h.score.away}</span>} · {fmtDateTime(h.kickoff_utc)}
            {!h.counted && " · dropped before kickoff"}
          </div>
        </div>
        <div className="text-right shrink-0">
          {h.outcome
            ? <Pill tone={win ? "pos" : loss ? "neg" : "neutral"}>{h.outcome.replace("_", " ")}{h.counted && h.profit !== null && ` · ${units(h.profit)}`}</Pill>
            : <Pill icon="clock">pending</Pill>}
          {h.counted && <div className="mt-1 text-2xs text-ink-4 num">total {units(h.running_profit)}</div>}
        </div>
      </Link>
    </li>
  );
}

function Metric({ label, value, tone, info }: { label: string; value: string; tone?: "pos"; info?: string }) {
  return (
    <div className="rounded-xl bg-white/[0.04] border border-white/[0.05] py-2 px-1">
      <div className="flex items-center justify-center gap-0.5 text-2xs text-ink-3">{label}{info && <InfoTip text={info} />}</div>
      <div className={cx("num text-[14px] font-extrabold mt-0.5", tone === "pos" ? "text-pos" : "text-ink")}>{value}</div>
    </div>
  );
}
