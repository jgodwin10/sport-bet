import { useState } from "react";
import { Link } from "react-router-dom";
import { useTopPickRecord, useTopPicks } from "../api/hooks";
import type { TopPick, TopPickRecord, TopPickResult, TopPickTally } from "../api/types";
import { Icon } from "../components/icons";
import {
  Card, cx, Empty, ErrorState, Freshness, InfoTip, Loading, MetricStrip, PageHeader, Pill, ReliabilityBadge, Segmented, StatTile, TeamLogo,
} from "../components/ui";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { friendlyReason, GLOSSARY, selectionLabel } from "../lib/language";

const WINDOWS = [
  { value: "today", label: "Today" },
  { value: "tomorrow", label: "Tomorrow" },
  { value: "7", label: "Next 7 days" },
];

const EMPTY: Record<string, string> = {
  today: "None of today's remaining matches has a price that beats our estimate. Try tomorrow, or check back after the next odds refresh.",
  tomorrow: "None of tomorrow's matches has a price that beats our estimate yet. Odds for many matches only arrive a day or two before kickoff.",
};

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
  const [span, setSpan] = useState("today");
  const q = useTopPicks(span);
  const items = q.data?.items ?? [];
  const recommended = items.filter((t) => t.tier === "recommended").length;

  return (
    <>
      <Segmented variant="chips" label="Window" value={span} onChange={setSpan} options={WINDOWS} className="mb-4" />

      {q.isLoading ? <Card><Loading rows={6} /></Card>
        : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} />
        : !items.length ? (
          <Card>
            <Empty title={span === "today" ? "No picks left today" : span === "tomorrow" ? "No picks for tomorrow yet" : "No picks in this window"} icon="ban">
              {EMPTY[span] ?? "None of the upcoming matches has a price that beats our estimate. Try a longer window, or check back after the next odds refresh."}
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
            <ol className="grid gap-3 lg:gap-4 lg:grid-cols-2">
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
            className={cx("card group relative flex h-full overflow-hidden transition-colors hover:border-line-strong",
                          recommended && "border-pos/40")}>
        {/* Rank rail */}
        <div className={cx("flex w-12 sm:w-14 shrink-0 items-start justify-center pt-4 border-r border-line",
                           t.rank <= 3 ? "bg-brand-soft text-brand" : "bg-night-3 text-ink-3")}>
          <span className="display num text-[30px] sm:text-[34px]">{t.rank}</span>
        </div>

        <div className="min-w-0 flex-1 flex flex-col p-3.5 sm:p-4">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="flex -space-x-1 shrink-0">
                  <TeamLogo name={home ?? ""} src={t.home_team?.logo_url} size={18} />
                  <TeamLogo name={away ?? ""} src={t.away_team?.logo_url} size={18} />
                </span>
                <span className="truncate text-[13px] font-semibold text-ink-2">{t.match}</span>
              </div>
              <div className="mt-0.5 truncate text-2xs text-ink-4">{t.competition} · {fmtDateTime(t.kickoff_utc)}</div>
            </div>
            {recommended
              ? <Pill tone="pos" icon="check">Recommended</Pill>
              : <Pill tone="warn" icon="alert" title={t.rejection_reasons.map(friendlyReason).join("\n")}>Watchlist</Pill>}
          </div>

          <div className="mt-3 flex items-end justify-between gap-3">
            <div className="min-w-0 text-[16px] sm:text-[17px] font-bold leading-tight">{selectionLabel(t.market, t.selection, home, away)}</div>
            <div className="shrink-0 text-right">
              <div className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink-4">Odds</div>
              <div className="display num text-[28px]">{odds(t.odds)}</div>
            </div>
          </div>

          <MetricStrip items={[
            ["Our chance", pct(t.probability, 0)],
            ["Bookmaker", pct(t.implied_probability, 0)],
            ["Value", signedPct(t.expected_value), t.expected_value > 0 ? "pos" : undefined, GLOSSARY.value],
          ]} />

          {!recommended && t.rejection_reasons[0] && (
            <p className="mt-2.5 text-xs text-ink-4 line-clamp-1">Held back: {friendlyReason(t.rejection_reasons[0])}</p>
          )}

          <AiRead t={t} configured={aiConfigured} />

          <div className="mt-auto pt-2.5 flex items-center justify-end gap-3 border-t border-line">
            <ReliabilityBadge score={t.reliability_score} label={t.reliability_label} />
            <Freshness hours={t.odds_age_hours} label="" />
          </div>
        </div>
      </Link>
    </li>
  );
}

function AiRead({ t, configured }: { t: TopPick; configured: boolean }) {
  const ai = t.ai;
  if (!ai) {
    return (
      <div className="mt-2.5 mb-2.5 flex items-center gap-2 text-xs text-ink-4">
        <Icon name="sparkle" size={13} />
        {configured ? "AI analysis runs within 48 hours of kickoff." : "AI analysis is not set up on this server."}
      </div>
    );
  }
  return (
    <div className="mt-3 mb-2.5 glass-inset p-3">
      <div className="flex flex-wrap items-center gap-2 text-2xs font-semibold text-ink-3">
        <Icon name="sparkle" size={13} className="text-brand" />AI read
        {ai.verdict === "supports" && <Pill tone="pos" icon="check">Still sees value{ai.probability !== null && ` · ${pct(ai.probability, 0)}`}</Pill>}
        {ai.verdict === "doubts" && <Pill tone="neg" icon="x">Doubts this bet{ai.probability !== null && ` · ${pct(ai.probability, 0)}`}</Pill>}
        {ai.confidence && <span className="text-ink-4 capitalize">{ai.confidence} confidence</span>}
        {!ai.current && <span className="text-ink-4">· written for an earlier prediction</span>}
      </div>
      <p className="mt-1.5 text-[13px] text-ink-2 leading-relaxed line-clamp-2 sm:line-clamp-3">{ai.summary}</p>
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 sm:gap-4">
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

      <Card title="Pick history" subtitle="Newest first" className="mt-6 bleed" flush>
        <ul className="divide-soft">
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
      <Link to={`/match/${h.fixture_id}`} className={cx("flex items-center gap-3 px-4 sm:px-5 py-3 hover:bg-white/[0.025] transition-colors", !h.counted && "opacity-60")}>
        <span className="display num grid place-items-center h-9 w-9 shrink-0 rounded-lg bg-night-3 text-[18px] text-ink-2">{h.rank}</span>
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
