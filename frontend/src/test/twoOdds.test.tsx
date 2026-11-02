import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import TwoOdds from "../pages/TwoOdds";

const team = (id: number, name: string) => ({ id, name, logo_url: null });
const leg = {
  selection_id: 1, prediction_id: 1, fixture_id: 7, match: "Alpha v Beta", home_team: team(1, "Alpha"), away_team: team(2, "Beta"),
  competition: "ENG-1", kickoff_utc: "2026-11-02T20:00:00Z", market: "1x2", selection: "home", probability: 0.68,
  probability_lower: 0.65, odds: 1.46, bookmaker: "b365", implied_probability: 0.68, fair_probability: 0.67, edge: 0, expected_value: -0.01,
  qualifies: false, rejection_reasons: [], reliability_score: 80, reliability_label: "high", odds_age_hours: 3,
  predicted_at: "2026-11-02T08:00:00Z", status: "upcoming", outcome: null, profit: null, clv: null, score: null,
  checks: [{ key: "market", label: "Bookmakers agree", status: "pass", detail: "bookmakers imply 67%" },
           { key: "form", label: "Recent form", status: "note", detail: "Alpha has the worse form" }],
};
const slip = {
  date: "2026-11-02", status: "pending", built: true, locked: false, legs: [leg, { ...leg, selection_id: 2, fixture_id: 8 }],
  combined_odds: 2.13, combined_probability: 0.46, paid_odds: null, analysed: 5, spare: 0, changes: [],
  rejected: [{ fixture_id: 9, match: "Gamma v Delta", home: "Gamma", away: "Delta", selection: "away", probability: 0.61, odds: 1.6, reasons: ["reliability 50/100; the minimum is 60"] }],
  updated_at: "2026-11-02T08:00:00Z", ai_configured: true, min_combined_odds: 2, max_combined_odds: 2.4, min_leg_probability: 0.6,
};

function show(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true, status: 200, text: async () => JSON.stringify(url.includes("/competitions") ? [] : body),
  }) as Response));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><TwoOdds /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("Daily 2 odds", () => {
  it("shows the total, the chance of losing and each game's analysis", async () => {
    show(slip);
    await waitFor(() => expect(screen.getByText("2.13")).toBeInTheDocument());
    expect(screen.getByRole("note")).toHaveTextContent("This is not a sure bet");
    expect(screen.getByRole("note")).toHaveTextContent("loses about 5 days in 10");
    fireEvent.click(screen.getAllByRole("button", { name: "Why this game" })[0]);
    expect(screen.getByText("bookmakers imply 67%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Games we ruled out (1)" }));
    expect(screen.getByText("reliability 50/100; the minimum is 60")).toBeInTheDocument();
  });

  it("says when no slip qualifies instead of forcing one", async () => {
    show({ ...slip, status: "none", legs: [], combined_odds: null, combined_probability: null, rejected: [] });
    await waitFor(() => expect(screen.getByText("No slip today")).toBeInTheDocument());
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("says when the first analysis has not run", async () => {
    show({ ...slip, status: "none", built: false, legs: [], combined_odds: null, combined_probability: null, rejected: [], updated_at: null });
    await waitFor(() => expect(screen.getByText("Today's slip isn't ready")).toBeInTheDocument());
  });
});
