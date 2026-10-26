import { useState } from "react";
import { Link } from "react-router-dom";
import { usePredictions, type PredictionFilters } from "../api/hooks";
import type { SelectionRow } from "../api/types";
import { Icon } from "../components/icons";
import {
  Card, cx, Empty, ErrorState, Freshness, InfoTip, Loading, PageHeader, Pager, Pill, ReliabilityBadge, Segmented, TeamLogo,
} from "../components/ui";
import { fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { friendlyReason, GLOSSARY, selectionLabel } from "../lib/language";

const MARKETS = [
  { value: "all", label: "All markets", api: undefined },
  { value: "1x2", label: "Match result", api: "1x2" },
  { value: "goals", label: "Over/under 2.5", api: "totals_2.5" },
  { value: "ah", label: "Handicap", api: "asian_handicap" },
] as const;
const SORTS = [
  { value: "expected_value", label: "Best value" },
  { value: "kickoff", label: "Kickoff" },
  { value: "probability", label: "Most likely" },
] as const;

export default function Predictions() {
  const [status, setStatus] = useState("upcoming");
  const [showAll, setShowAll] = useState(false);
  const [market, setMarket] = useState<(typeof MARKETS)[number]["value"]>("all");
  const [sort, setSort] = useState<string>("expected_value");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const filters: PredictionFilters = {
    status, qualifying_only: status === "upcoming" && !showAll ? true : undefined,
    market: MARKETS.find((m) => m.value === market)?.api, search: search || undefined,
    sort, order: sort === "kickoff" ? "asc" : "desc", page, page_size: 24,
  };
  const q = usePredictions(filters);
  const reset = (fn: () => void) => { fn(); setPage(1); };
  const recommendedOnly = status === "upcoming" && !showAll;

  return (
    <>
      <PageHeader title="Value picks"
                  description={recommendedOnly
                    ? "Bets where a bookmaker's price beats our estimated chance and every safety check passes."
                    : "Every bet we priced, including the ones we rejected and why."} />

      <div className="space-y-3 mb-6">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="Status" value={status} onChange={(v) => reset(() => setStatus(v))}
                     options={[{ value: "upcoming", label: "Upcoming" }, { value: "settled", label: "Results" }]} />
          {status === "upcoming" && (
            <button role="switch" aria-checked={showAll} onClick={() => reset(() => setShowAll(!showAll))}
                    className={cx("btn", showAll && "bg-white text-night hover:bg-white")}>
              <Icon name={showAll ? "check" : "filter"} size={15} />{showAll ? "Showing every bet checked" : "Show every bet checked"}
            </button>
          )}
          <div className="relative w-full sm:w-64 sm:ml-auto">
            <Icon name="search" size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-4" />
            <input className="input pl-11" placeholder="Find a team" aria-label="Find a team" value={search} onChange={(e) => reset(() => setSearch(e.target.value))} />
          </div>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:justify-between">
          <Segmented variant="chips" label="Market" value={market} onChange={(v) => reset(() => setMarket(v))} className="fade-edges -mx-4 px-4 sm:mx-0 sm:px-0"
                     options={MARKETS.map((m) => ({ value: m.value, label: m.label }))} />
          <label className="flex items-center gap-2 text-[13px] text-ink-3 shrink-0">
            Sort by
            <select className="input h-9 w-auto rounded-full text-[13px] font-semibold" value={sort} onChange={(e) => reset(() => setSort(e.target.value))}>
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
        </div>
      </div>

      {q.isLoading ? <Card><Loading rows={6} /></Card>
        : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} />
        : !q.data?.items.length ? (
          <Card>
            {recommendedOnly ? (
              <Empty title="No value picks right now" icon="ban"
                     action={<button className="btn btn-primary" onClick={() => reset(() => setShowAll(true))}>See every bet we checked</button>}>
                Our estimates are close to the bookmakers' prices, so nothing is worth recommending. That's normal — bookmakers are hard to beat, and holding back protects you.
              </Empty>
            ) : (
              <Empty title={status === "settled" ? "No results yet" : "No selections match these filters"} icon="target">
                {status === "settled" ? "Settled bets appear here after matches finish." : "Try a different market or clear the search."}
              </Empty>
            )}
          </Card>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {q.data.items.map((r, i) => <PickCard key={r.selection_id} r={r} delay={i} />)}
            </div>
            <Pager page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onPage={setPage} />
          </>
        )}
    </>
  );
}

function PickCard({ r, delay }: { r: SelectionRow; delay: number }) {
  const home = r.home_team?.name, away = r.away_team?.name;
  const settled = r.status === "settled";
  return (
    <Link to={`/match/${r.fixture_id}`} style={{ animationDelay: `${Math.min(delay, 12) * 30}ms` }}
          className={cx("card group flex flex-col p-5 transition-all hover:-translate-y-0.5 hover:bg-white/[0.08] animate-fade-up",
                        r.qualifies && !settled && "ring-1 ring-pos/35")}>
      <div className="flex items-center gap-2 text-xs text-ink-3 min-w-0">
        <span className="flex -space-x-1.5 shrink-0">
          <TeamLogo name={home ?? ""} src={r.home_team?.logo_url} size={22} />
          <TeamLogo name={away ?? ""} src={r.away_team?.logo_url} size={22} />
        </span>
        <span className="truncate font-semibold text-ink-2">{r.match}</span>
      </div>
      <div className="mt-1 text-2xs text-ink-4">{r.competition} · {fmtDateTime(r.kickoff_utc)}</div>

      <div className="mt-4 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-2xs font-semibold text-ink-3">Bet</div>
          <div className="text-[16px] font-extrabold leading-tight">{selectionLabel(r.market, r.selection, home, away)}</div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-2xs font-semibold text-ink-3">Odds</div>
          <div className="num text-[22px] font-extrabold leading-none">{odds(r.odds)}</div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 text-center">
        <Metric label="Our chance" value={pct(r.probability, 0)} />
        <Metric label="Bookmaker" value={pct(r.implied_probability, 0)} />
        <Metric label="Value" value={signedPct(r.expected_value)} tone={r.expected_value > 0 ? "pos" : undefined} info={GLOSSARY.value} />
      </div>

      <div className="mt-4 pt-3 border-t border-white/[0.06] flex flex-wrap items-center justify-between gap-2">
        {settled ? (
          <Pill tone={r.profit! > 0 ? "pos" : r.profit! < 0 ? "neg" : "neutral"}>{r.outcome} · {signedPct(r.profit)}</Pill>
        ) : r.qualifies ? (
          <Pill tone="pos" icon="check">Recommended</Pill>
        ) : (
          <span className="text-xs text-ink-4 line-clamp-1" title={r.rejection_reasons.map(friendlyReason).join("\n")}>{friendlyReason(r.rejection_reasons[0])}</span>
        )}
        <span className="flex items-center gap-3">
          <ReliabilityBadge score={r.reliability_score} label={r.reliability_label} />
          {!settled && <Freshness hours={r.odds_age_hours} label="" />}
          {settled && r.clv !== null && <span className="text-2xs text-ink-4 num">CLV {signedPct(r.clv)}</span>}
        </span>
      </div>
    </Link>
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
