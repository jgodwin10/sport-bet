import { useState } from "react";
import { Link } from "react-router-dom";
import { useTwoOdds, useTwoOddsRecord } from "../api/hooks";
import type { TwoOddsCheck, TwoOddsLeg, TwoOddsRecord, TwoOddsResult, TwoOddsSlip } from "../api/types";
import { BetCard } from "../components/BetCard";
import { Icon, type IconName } from "../components/icons";
import { Card, cx, Disclosure, Empty, ErrorState, InfoTip, Loading, PageHeader, Pill, Segmented, StatTile } from "../components/ui";
import { fmtDate, fmtDateTime, odds, pct, signedPct } from "../lib/format";
import { selectionLabel } from "../lib/language";

const METHOD = "We take today's favourites and check each one against the bookmakers, our models, its data, form, venue record, head to head, the table, rest, reported absences and current news. From the games that pass, we pick the combination with the highest chance of winning at total odds of about 2.";

const units = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(2)}u`;

export default function TwoOdds() {
  const [view, setView] = useState("today");
  return (
    <>
      <PageHeader eyebrow="Slip of the day" title="Daily 2 odds"
                  description={<>One slip a day, built from the games that pass every check. <InfoTip text={METHOD} /></>}
                  actions={<Segmented label="View" value={view} onChange={setView}
                                      options={[{ value: "today", label: "Today" }, { value: "results", label: "Results" }]} />} />
      {view === "today" ? <Today /> : <Results />}
    </>
  );
}

function Today() {
  const q = useTwoOdds();
  if (q.isLoading) return <Card><Loading rows={6} /></Card>;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const slip = q.data as TwoOddsSlip;
  return (
    <>
      {slip.legs.length ? <SlipView slip={slip} /> : <NoSlip slip={slip} />}
      <Rejected slip={slip} />
    </>
  );
}

function NoSlip({ slip }: { slip: TwoOddsSlip }) {
  if (!slip.built) {
    return <Card><Empty title="Today's slip isn't ready" icon="clock">The analysis runs with each prediction update. Check back soon.</Empty></Card>;
  }
  const waitingForAi = slip.rejected.some((r) => r.reasons.some((x) => x.startsWith("waiting for an analysis")));
  return (
    <Card>
      <Empty title="No slip today" icon="ban">
        {slip.analysed === 0
          ? "None of today's remaining games has a priced favourite strong enough to analyse."
          : waitingForAi
            ? `${slip.analysed} ${slip.analysed === 1 ? "game is" : "games are"} waiting for the news check. The slip will appear here if they pass.`
            : `We analysed ${slip.analysed} ${slip.analysed === 1 ? "game" : "games"} and could not make about ${odds(slip.min_combined_odds)} odds from the ones that passed. Passing on a day is part of the method.`}
      </Empty>
      {slip.changes.length > 0 && <p className="px-4 pb-4 text-center text-sm text-ink-3">{slip.changes[slip.changes.length - 1].reason}</p>}
    </Card>
  );
}

function SlipView({ slip }: { slip: TwoOddsSlip }) {
  const chance = slip.combined_probability ?? 0;
  const lastChange = slip.changes[slip.changes.length - 1];
  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile label="Total odds" value={odds(slip.combined_odds)} hint="at the best price found" />
        <StatTile label="Chance it wins" value={pct(chance, 0)} hint={`${slip.legs.length} ${slip.legs.length === 1 ? "game" : "games"}, all must win`} />
        <StatTile label="Games analysed" value={slip.analysed} hint={`${slip.rejected.length} ruled out`} />
        <StatusTile slip={slip} />
      </div>

      <div role="note" className="mt-3 flex gap-2.5 rounded-2xl bg-warn/10 px-4 py-3 text-sm text-ink-2 ring-1 ring-inset ring-warn/25">
        <Icon name="alert" size={17} className="mt-0.5 shrink-0 text-warn" />
        <p>
          <b className="text-ink">This is not a sure bet.</b> No slip at these odds can be. On our estimate it loses about {Math.round((1 - chance) * 10)} days in 10,
          and losing runs of a week or more are normal. Bookmakers' prices vary, so check yours before staking, and only stake what you can afford to lose.
        </p>
      </div>

      {lastChange && <p className="mt-3 text-sm text-ink-3">{lastChange.reason} Updated {fmtDateTime(lastChange.at)}.</p>}

      <ol className="mt-5 grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {slip.legs.map((leg, i) => (
          <li key={leg.selection_id} className="min-w-0">
            <BetCard r={leg} rank={i + 1} status={<LegStatus leg={leg} />}><Analysis checks={leg.checks} /></BetCard>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-xs text-ink-4">
        Updated {fmtDateTime(slip.updated_at)}. {slip.locked ? "The first game has started, so this slip is locked." : "The slip stays the same while every game keeps passing, and locks when the first game starts."}
      </p>
    </>
  );
}

const STATUS: Record<string, { label: string; tone?: "pos" | "neg" }> = {
  pending: { label: "In play or to come" }, won: { label: "Won", tone: "pos" }, lost: { label: "Lost", tone: "neg" },
  void: { label: "Void" }, none: { label: "—" },
};

function StatusTile({ slip }: { slip: TwoOddsSlip }) {
  const s = STATUS[slip.status];
  return <StatTile label="Status" value={s.label} tone={s.tone}
                   hint={slip.paid_odds !== null ? `paid ${odds(slip.paid_odds)}` : slip.locked ? "locked" : "can still change"} />;
}

function LegStatus({ leg }: { leg: TwoOddsLeg }) {
  if (leg.outcome) {
    const win = leg.outcome === "win", loss = leg.outcome === "loss";
    return <div className="text-center"><Pill tone={win ? "pos" : loss ? "neg" : "neutral"}>{leg.outcome}{leg.score && ` · ${leg.score.home}–${leg.score.away}`}</Pill></div>;
  }
  const passed = leg.checks.filter((c) => c.status === "pass").length;
  return <div className="text-center"><b className="text-pos">{passed} checks passed</b> of {leg.checks.length}</div>;
}

const CHECK_LOOK: Record<TwoOddsCheck["status"], { icon: IconName; className: string; label: string }> = {
  pass: { icon: "check", className: "text-pos", label: "Passed" },
  note: { icon: "alert", className: "text-warn", label: "Caution" },
  fail: { icon: "x", className: "text-neg", label: "Failed" },
  unchecked: { icon: "info", className: "text-ink-4", label: "Not checked" },
};

function Analysis({ checks }: { checks: TwoOddsCheck[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 rounded-xl bg-subtle text-[13px]">
      <button className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left font-medium text-ink-2" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="flex items-center gap-1.5"><Icon name="target" size={13} />Why this game</span>
        <Icon name="chevronDown" size={15} className={cx("text-ink-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="space-y-2 px-3 pb-3">
          {checks.map((c) => {
            const look = CHECK_LOOK[c.status];
            return (
              <li key={c.key} className="flex gap-2">
                <Icon name={look.icon} size={14} className={cx("mt-0.5 shrink-0", look.className)} aria-label={look.label} />
                <div className="min-w-0"><div className="font-medium text-ink">{c.label}</div><p className="text-xs text-ink-3">{c.detail}</p></div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function Rejected({ slip }: { slip: TwoOddsSlip }) {
  if (!slip.rejected.length) return null;
  return (
    <div className="card mt-6">
      <Disclosure title={`Games we ruled out (${slip.rejected.length})`}>
        <ul className="divide-soft">
          {slip.rejected.map((r) => (
            <li key={`${r.fixture_id}-${r.selection}`} className="py-3">
              <Link to={`/match/${r.fixture_id}`} className="text-sm font-medium hover:underline">
                {selectionLabel("1x2", r.selection, r.home, r.away)} <span className="num font-normal text-ink-3">@ {odds(r.odds)} · {pct(r.probability, 0)}</span>
              </Link>
              <div className="truncate text-xs text-ink-4">{r.match}</div>
              <p className="mt-1 text-xs text-ink-3">{r.reasons[0]}</p>
            </li>
          ))}
        </ul>
      </Disclosure>
    </div>
  );
}

function Results() {
  const q = useTwoOddsRecord();
  if (q.isLoading) return <Card><Loading rows={6} /></Card>;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const rec = q.data as TwoOddsRecord;
  const s = rec.summary;
  return (
    <>
      {rec.backtest?.slips ? <BacktestLine b={rec.backtest} /> : null}
      {!rec.history.length ? (
        <Card className="mt-4"><Empty title="No results yet" icon="clock">Each published slip is recorded here and scored once its games are played.</Empty></Card>
      ) : (
        <>
          <div className="mt-4 grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatTile label="Profit" value={units(s.profit ?? 0)} tone={(s.profit ?? 0) > 0 ? "pos" : (s.profit ?? 0) < 0 ? "neg" : undefined} hint="1 unit on each slip" />
            <StatTile label="Won · lost" value={`${s.won} · ${s.lost}`} hint={s.void ? `${s.void} void` : undefined} />
            <StatTile label="Hit rate" value={s.hit_rate === null ? "—" : pct(s.hit_rate, 0)} hint={s.expected_hit_rate === null ? undefined : `we estimated ${pct(s.expected_hit_rate, 0)}`} />
            <StatTile label="Return per slip" value={s.roi === null ? "—" : signedPct(s.roi)} hint={`${s.days_without_slip} days without a slip`} />
          </div>
          {(s.settled ?? 0) < 50 && (s.settled ?? 0) > 0 && (
            <p className="mt-3 text-sm text-ink-3">{s.settled} results is a small sample: profit this early is mostly luck, either way.</p>
          )}
          <Card title="History" subtitle="Newest first" className="mt-6" flush>
            <ul className="divide-soft">{rec.history.map((h) => <ResultRow key={h.date} h={h} />)}</ul>
          </Card>
        </>
      )}
    </>
  );
}

function BacktestLine({ b }: { b: Record<string, any> }) {
  return (
    <p className="rounded-2xl bg-subtle px-4 py-3 text-sm text-ink-2">
      <b className="text-ink">Tested on past seasons:</b> {b.slips} slips on {b.days_with_matches} match days won {pct(b.hit_rate, 0)} of the time at average odds of {odds(b.avg_odds)},
      a return of {signedPct(b.roi_at_average_odds)} at average bookmaker prices, with a worst losing run of {b.longest_losing_run}. Form, news and the other context checks are not part of this test.
    </p>
  );
}

function ResultRow({ h }: { h: TwoOddsResult }) {
  return (
    <li className="px-4 sm:px-5 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium">{fmtDate(h.date)} <span className="num font-normal text-ink-3">@ {odds(h.combined_odds)}</span></div>
        <div className="text-right shrink-0">
          <Pill tone={h.status === "won" ? "pos" : h.status === "lost" ? "neg" : "neutral"}>{h.status}{h.profit !== null && ` ${units(h.profit)}`}</Pill>
          <div className="mt-1 text-xs text-ink-4 num">{units(h.running_profit)}</div>
        </div>
      </div>
      <ul className="mt-1 space-y-0.5">
        {h.legs.map((leg) => (
          <li key={leg.selection_id} className="truncate text-xs text-ink-3">
            <Link to={`/match/${leg.fixture_id}`} className="hover:underline">
              {selectionLabel(leg.market, leg.selection, leg.home_team?.name, leg.away_team?.name)} <span className="num">@ {odds(leg.odds)}</span>
              {leg.score && <span className="num text-ink-4"> · {leg.score.home}–{leg.score.away}</span>}
              {leg.outcome && <span className={leg.outcome === "win" ? "text-pos" : leg.outcome === "loss" ? "text-neg" : ""}> · {leg.outcome}</span>}
            </Link>
          </li>
        ))}
      </ul>
    </li>
  );
}
