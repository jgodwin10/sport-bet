import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Predictions from "../pages/Predictions";
import { ClassificationBadge, ErrorState, OutcomeBar, ReliabilityBadge } from "../components/ui";
import { ApiError } from "../api/client";

function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

function mockFetch(handler: (url: string) => { status: number; body: unknown }) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const r = handler(url);
    return { ok: r.status < 400, status: r.status, text: async () => JSON.stringify(r.body) } as Response;
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("UI states", () => {
  it("shows loading then the empty state when there are no selections", async () => {
    mockFetch((url) => url.includes("/competitions") ? { status: 200, body: [] }
      : { status: 200, body: { items: [], total: 0, page: 1, page_size: 50 } });
    renderWithClient(<Predictions />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    // Default view shows recommended bets only; an empty result explains why and offers to show everything.
    await waitFor(() => expect(screen.getByText("No value picks right now")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "See every bet we checked" })).toBeInTheDocument();
  });

  it("shows an error state with the API message", async () => {
    mockFetch((url) => url.includes("/competitions") ? { status: 200, body: [] }
      : { status: 503, body: { detail: "database unavailable" } });
    renderWithClient(<Predictions />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("database unavailable"));
  });

  it("rejects malformed API responses instead of rendering them", async () => {
    mockFetch((url) => url.includes("/competitions") ? { status: 200, body: [] }
      : { status: 200, body: { items: [{ nonsense: true }], total: 1, page: 1, page_size: 50 } });
    renderWithClient(<Predictions />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Unexpected response shape"));
  });

  it("renders a settled row with outcome and CLV", async () => {
    const row = { selection_id: 1, prediction_id: 1, fixture_id: 7, match: "A v B", competition: "ENG-1",
      kickoff_utc: "2026-10-01T15:00:00Z", market: "1x2", selection: "home", probability: 0.5, probability_lower: null,
      odds: 2.2, bookmaker: "b365", implied_probability: 0.4545, fair_probability: 0.44, edge: 0.045, expected_value: 0.1,
      qualifies: true, rejection_reasons: [], reliability_score: 80, reliability_label: "high", odds_age_hours: 1,
      predicted_at: "2026-10-01T10:00:00Z", status: "settled", outcome: "loss", profit: -1, clv: 0.02 };
    mockFetch((url) => url.includes("/competitions") ? { status: 200, body: [] }
      : { status: 200, body: { items: [row], total: 1, page: 1, page_size: 50 } });
    renderWithClient(<Predictions />);
    await waitFor(() => expect(screen.getByText("A v B")).toBeInTheDocument());
    expect(screen.getByText(/loss/)).toBeInTheDocument();
    expect(screen.getByText(/CLV \+2\.0%/)).toBeInTheDocument();
    expect(screen.getByText("Home win")).toBeInTheDocument(); // plain-language selection label
  });
});

describe("components", () => {
  it("labels no-bet and reliability without relying on colour", () => {
    render(<><ClassificationBadge value="no_bet" /><ReliabilityBadge score={42} label="low" /></>);
    expect(screen.getByText("No value bet")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
    expect(screen.getByText("low")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("outcome bar exposes an accessible summary", () => {
    render(<OutcomeBar p={{ home: 0.5, draw: 0.3, away: 0.2 }} />);
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "1 50%, X 30%, 2 20%");
  });

  it("error state shows retry", () => {
    const retry = vi.fn();
    render(<ErrorState error={new ApiError(500, "boom")} onRetry={retry} />);
    screen.getByText("Retry").click();
    expect(retry).toHaveBeenCalled();
  });
});
