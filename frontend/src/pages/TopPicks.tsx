import { useState } from "react";
import { Link } from "react-router-dom";
import { useTopPicks } from "../api/hooks";
import type { TopPick } from "../api/types";
import { Icon } from "../components/icons";
import {
  Card, cx, Empty, ErrorState, Freshness, InfoTip, Loading, PageHeader, Pill, ReliabilityBadge, Segmented, TeamLogo,
} from "../components/ui";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { friendlyReason, GLOSSARY, selectionLabel } from "../lib/language";

const WINDOWS = [
  { value: "2", label: "Next 48 hours" },
  { value: "7", label: "Next 7 days" },
  { value: "14", label: "Next 14 days" },
];

const RANKING = "Each match's best-priced bet, ranked by its value at the cautious end of our estimate and scaled by data reliability. Bets that pass every safety check come first.";

export default function TopPicks() {
  const [days, setDays] = useState("7");
  const q = useTopPicks(Number(days));
  const items = q.data?.items ?? [];
  const recommended = items.filter((t) => t.tier === "recommended").length;

  return (
    <>
      <PageHeader eyebrow="Ranked by the model" title="Top 10 picks"
                  description={<>The strongest bet in each upcoming match, best first, with the AI's read on the team news. <InfoTip text={RANKING} /></>}
                  actions={<Segmented label="Window" value={days} onChange={setDays} options={WINDOWS} />} />

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

function Metric({ label, value, tone, info }: { label: string; value: string; tone?: "pos"; info?: string }) {
  return (
    <div className="rounded-xl bg-white/[0.04] border border-white/[0.05] py-2 px-1">
      <div className="flex items-center justify-center gap-0.5 text-2xs text-ink-3">{label}{info && <InfoTip text={info} />}</div>
      <div className={cx("num text-[14px] font-extrabold mt-0.5", tone === "pos" ? "text-pos" : "text-ink")}>{value}</div>
    </div>
  );
}
