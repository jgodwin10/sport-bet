import { useState } from "react";
import { Link } from "react-router-dom";
import { useTopPickRecord, useTopPicks } from "../api/hooks";
import type { TopPick, TopPickRecord, TopPickResult, TopPickTally } from "../api/types";
import { BetCard, BetStatus } from "../components/BetCard";
import { Icon } from "../components/icons";
import { Card, cx, Empty, ErrorState, InfoTip, Loading, PageHeader, Pill, Segmented, StatTile } from "../components/ui";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { friendlyReason, selectionLabel } from "../lib/language";
import { inLeague, useLeague } from "../lib/league";

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
      <PageHeader eyebrow="Ranked by the model" title="Top picks"
                  description={view === "upcoming"
                    ? <>The strongest bet in each match, best first. <InfoTip text={RANKING} /></>
                    : <>How the Top 10 has done, at 1 unit per pick. <InfoTip text={TRACKING} /></>}
                  actions={<Segmented label="View" value={view} onChange={setView}
                                      options={[{ value: "upcoming", label: "Upcoming" }, { value: "results", label: "Results" }]} />} />
      {view === "upcoming" ? <Upcoming /> : <Results />}
    </>
  );
}

function Upcoming() {
  const [span, setSpan] = useState("today");
  const { league } = useLeague();
  const q = useTopPicks(span, 25);
  const items = inLeague(q.data?.items ?? [], league);
  const recommended = items.filter((t) => t.tier === "recommended").length;

  return (
    <>
      <Segmented variant="chips" label="Window" value={span} onChange={setSpan} options={WINDOWS} className="mb-5 -mx-4 px-4 sm:mx-0 sm:px-0" />

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
              <p className="mb-4 text-sm text-ink-3">
                {recommended
                  ? `${recommended} of ${items.length} pass every safety check. The rest are a watchlist.`
                  : "None of these pass every safety check yet, so treat them as a watchlist."}
              </p>
            )}
            <ol className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
              {items.map((t) => (
                <li key={t.selection_id} className="min-w-0">
                  <BetCard r={t} rank={t.rank} highlight={t.tier === "recommended"}
                           status={<BetStatus ok={t.tier === "recommended"} warnLabel="Watchlist" reason={t.rejection_reasons[0] && friendlyReason(t.rejection_reasons[0])} />}>
                    <AiRead t={t} />
                  </BetCard>
                </li>
              ))}
            </ol>
          </>
        )}

      <Link to="/predictions" className="mt-6 inline-flex items-center gap-1 text-sm font-medium text-ink-3 hover:text-ink">
        Every bet we priced<Icon name="chevronRight" size={15} />
      </Link>
    </>
  );
}

function AiRead({ t }: { t: TopPick }) {
  const ai = t.ai;
  if (!ai) return null;
  return (
    <div className="mt-3 rounded-xl bg-subtle px-3 py-2.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
        <span className="flex items-center gap-1 font-medium text-ink-2"><Icon name="sparkle" size={12} />AI read</span>
        {ai.verdict === "supports" && <span className="text-pos">still sees value{ai.probability !== null && ` · ${pct(ai.probability, 0)}`}</span>}
        {ai.verdict === "doubts" && <span className="text-neg">doubts this bet{ai.probability !== null && ` · ${pct(ai.probability, 0)}`}</span>}
        {!ai.current && <span>· earlier prediction</span>}
      </div>
      <p className="mt-1 text-ink-2 line-clamp-2">{ai.summary}</p>
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile label="Profit" value={units(all.profit)} tone={all.profit > 0 ? "pos" : all.profit < 0 ? "neg" : undefined}
                  hint={`${all.settled} settled pick${all.settled === 1 ? "" : "s"}`} />
        <StatTile label="Return per pick" value={all.roi === null ? "—" : signedPct(all.roi)}
                  tone={all.roi === null ? undefined : all.roi > 0 ? "pos" : all.roi < 0 ? "neg" : undefined} />
        <StatTile label="Won · lost" value={`${all.won} · ${all.lost}`} hint={all.void ? `${all.void} void` : undefined} />
        <StatTile label="Pending" value={all.pending} hint={rec.dropped ? `${rec.dropped} dropped, not counted` : undefined} />
      </div>

      {all.settled > 0 && all.settled < 50 && (
        <p className="mt-3 text-sm text-ink-3">{all.settled} results is a small sample: profit this early is mostly luck, either way.</p>
      )}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <TierLine label="Recommended" t={rec.summary.recommended} />
        <TierLine label="Watchlist" t={rec.summary.watchlist} />
      </div>

      <Card title="History" subtitle="Newest first" className="mt-6" flush>
        <ul className="divide-soft">
          {rec.history.map((h) => <ResultRow key={h.fixture_id} h={h} />)}
        </ul>
      </Card>
    </>
  );
}

const units = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(2)}u`;

function TierLine({ label, t }: { label: string; t: TopPickTally }) {
  return (
    <div className="card flex items-center justify-between gap-3 px-4 py-3 text-sm">
      <span className="font-medium">{label}</span>
      <span className="text-ink-3 num text-right">
        {t.settled ? <>{t.won}–{t.lost} · <span className={cx("font-semibold", t.profit > 0 ? "text-pos" : t.profit < 0 ? "text-neg" : "text-ink")}>{units(t.profit)}</span></>
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
      <Link to={`/match/${h.fixture_id}`} className={cx("flex items-center gap-3 px-4 sm:px-5 py-3 hover:bg-subtle/60 transition-colors", !h.counted && "opacity-60")}>
        <span className="w-5 shrink-0 text-sm text-ink-4 num">{h.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{selectionLabel(h.market, h.selection, home, away)} <span className="num text-ink-3 font-normal">@ {odds(h.odds)}</span></div>
          <div className="truncate text-xs text-ink-4">
            {h.match}{h.score && <span className="num"> · {h.score.home}–{h.score.away}</span>} · {fmtDateTime(h.kickoff_utc)}
            {!h.counted && " · dropped before kickoff"}
          </div>
        </div>
        <div className="text-right shrink-0">
          {h.outcome
            ? <Pill tone={win ? "pos" : loss ? "neg" : "neutral"}>{h.outcome.replace("_", " ")}{h.counted && h.profit !== null && ` ${units(h.profit)}`}</Pill>
            : <Pill>pending</Pill>}
          {h.counted && <div className="mt-1 text-xs text-ink-4 num">{units(h.running_profit)}</div>}
        </div>
      </Link>
    </li>
  );
}
