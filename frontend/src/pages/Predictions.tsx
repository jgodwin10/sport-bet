import { useState } from "react";
import { Link } from "react-router-dom";
import { usePredictions, type PredictionFilters } from "../api/hooks";
import type { SelectionRow } from "../api/types";
import { BetCard, BetStatus } from "../components/BetCard";
import { Icon } from "../components/icons";
import { Card, cx, Empty, ErrorState, Loading, PageHeader, Pager, SearchInput, Segmented } from "../components/ui";
import { signedPct } from "../lib/format";
import { friendlyReason } from "../lib/language";

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
      <Link to="/top" className="mb-4 inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink">
        <Icon name="chevronLeft" size={15} />Top picks
      </Link>
      <PageHeader title="All bets"
                  description={recommendedOnly
                    ? "Bets where a bookmaker's price beats our estimate and every safety check passes."
                    : "Every bet we priced, including the ones we rejected and why."}
                  actions={<Segmented label="Status" value={status} onChange={(v) => reset(() => setStatus(v))}
                                      options={[{ value: "upcoming", label: "Upcoming" }, { value: "settled", label: "Results" }]} />} />

      <div className="mb-6 space-y-2">
        <SearchInput value={search} onChange={(v) => reset(() => setSearch(v))} />
        <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
          <select className="input sm:w-48" aria-label="Market" value={market} onChange={(e) => reset(() => setMarket(e.target.value as typeof market))}>
            {MARKETS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <select className="input sm:w-40" aria-label="Sort by" value={sort} onChange={(e) => reset(() => setSort(e.target.value))}>
            {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          {status === "upcoming" && (
            <button role="switch" aria-checked={showAll} onClick={() => reset(() => setShowAll(!showAll))}
                    className={cx("btn col-span-2 sm:ml-auto", showAll && "bg-subtle")}>
              <Icon name={showAll ? "check" : "filter"} size={15} />Include rejected bets
            </button>
          )}
        </div>
      </div>

      {q.isLoading ? <Card><Loading rows={6} /></Card>
        : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} />
        : !q.data?.items.length ? (
          <Card>
            {recommendedOnly ? (
              <Empty title="No value picks right now" icon="ban"
                     action={<button className="btn btn-primary" onClick={() => reset(() => setShowAll(true))}>See every bet we checked</button>}>
                Our estimates are close to the bookmakers' prices, so nothing is worth recommending. That's normal: bookmakers are hard to beat.
              </Empty>
            ) : (
              <Empty title={status === "settled" ? "No results yet" : "No bets match these filters"} icon="target">
                {status === "settled" ? "Settled bets appear here after matches finish." : "Try a different market or clear the search."}
              </Empty>
            )}
          </Card>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {q.data.items.map((r) => <div key={r.selection_id} className="min-w-0"><BetCard r={r} highlight={r.qualifies && r.status !== "settled"} status={<RowStatus r={r} />} /></div>)}
            </div>
            <Pager page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onPage={setPage} />
          </>
        )}
    </>
  );
}

function RowStatus({ r }: { r: SelectionRow }) {
  if (r.status === "settled") {
    const tone = r.profit! > 0 ? "text-pos" : r.profit! < 0 ? "text-neg" : "text-ink-2";
    return (
      <span className="flex flex-wrap items-center gap-x-2">
        <span className={cx("font-medium capitalize", tone)}>{r.outcome?.replace("_", " ")} · {signedPct(r.profit)}</span>
        {r.clv !== null && <span className="num">CLV {signedPct(r.clv)}</span>}
      </span>
    );
  }
  return <BetStatus ok={r.qualifies} warnLabel="Not recommended" reason={r.rejection_reasons[0] && friendlyReason(r.rejection_reasons[0])} />;
}
