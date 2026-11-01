import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { lines } from "../components/Lineups";
import { MatchRow } from "../components/MatchRow";
import { Segmented, Sheet, TeamLogo } from "../components/ui";
import { friendlyReason, plainFacts, selectionLabel } from "../lib/language";
import type { Fixture } from "../api/types";

const fixture: Fixture = {
  id: 7, season: "2026-2027", kickoff_utc: new Date(Date.now() + 3_600_000).toISOString(), status: "scheduled",
  neutral: false, venue: null, score: null,
  competition: { id: 1, code: "ENG-1", name: "Premier League", country: "England", tier: 1 },
  home_team: { id: 1, name: "Alpha Town" }, away_team: { id: 2, name: "Beta City" },
  latest_prediction: {
    id: 3, created_at: new Date().toISOString(), classification: "high_uncertainty",
    one_x_two: { home: 0.5, draw: 0.3, away: 0.2 }, reliability_score: 30, reliability_label: "low",
    lineup_status: "unavailable", best_selection: null, odds_age_hours: 40,
  },
};

describe("MatchRow", () => {
  it("links to the match and shows teams and probabilities, without a value marker by default", () => {
    render(<MemoryRouter><MatchRow f={fixture} /></MemoryRouter>);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/match/7");
    expect(screen.getByText("Alpha Town")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "1 50%, X 30%, 2 20%");
    expect(screen.queryByText("Value bet")).toBeNull();
  });

  it("marks matches with a value bet", () => {
    const value = { ...fixture, latest_prediction: { ...fixture.latest_prediction!, classification: "consider" as const } };
    render(<MemoryRouter><MatchRow f={value} /></MemoryRouter>);
    expect(screen.getByText("Value bet")).toBeInTheDocument();
  });
});

describe("Segmented", () => {
  it("marks the active option and reports changes", () => {
    const onChange = vi.fn();
    render(<Segmented label="Window" value="7" onChange={onChange}
                      options={[{ value: "1", label: "1d" }, { value: "7", label: "7d" }]} />);
    expect(screen.getByRole("tab", { name: "7d" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "1d" }));
    expect(onChange).toHaveBeenCalledWith("1");
  });
});

describe("Sheet", () => {
  it("renders as a modal dialog and closes on Escape", () => {
    const onClose = vi.fn();
    render(<Sheet open title="Filters" onClose={onClose}><p>content</p></Sheet>);
    expect(screen.getByRole("dialog", { name: "Filters" })).toHaveAttribute("aria-modal", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing when closed", () => {
    render(<Sheet open={false} title="Filters" onClose={() => {}}><p>content</p></Sheet>);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("TeamLogo", () => {
  it("shows initials until the crest loads, and keeps them if the image fails", () => {
    const { container } = render(<TeamLogo name="Crystal Palace" src="/api/v1/teams/1/crest" size={72} />);
    expect(screen.getByText("CP")).toBeInTheDocument();
    const img = container.querySelector("img")!;
    expect(img.getAttribute("src")).toBe("/api/v1/teams/1/crest?size=small"); // large crests use the 200px rendition
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("CP")).toBeInTheDocument();
  });
});

describe("plain language", () => {
  it("translates rule-engine reasons and selections", () => {
    expect(friendlyReason("edge +0.2% below minimum 2%")).toBe("The price isn't generous enough (edge +0.2%, we need 2%)");
    expect(friendlyReason("odds missing or stale")).toBe("The odds are too old to trust");
    expect(selectionLabel("totals_2.5", "over")).toBe("Over 2.5 goals");
    expect(selectionLabel("1x2", "away", "Alpha", "Beta")).toBe("Beta to win");
    expect(selectionLabel("asian_handicap", "home -0.75", "Alpha", "Beta")).toBe("Alpha -0.75");
  });

  it("builds readable facts from model evidence", () => {
    const facts = plainFacts([
      { category: "goal_model", text: "", evidence: { expected_goals: { home: 1.53, away: 1.04 }, home_attack: 1.2, away_defence: 0.98 } },
      { category: "market", text: "", evidence: { market_1x2: {}, difference: { home: 0.01 } } },
    ], "Alpha", "Beta");
    expect(facts[0].text).toBe("We expect about 1.5 goals from Alpha and 1.0 from Beta.");
    expect(facts[1].text).toContain("20% stronger than the league average");
    expect(facts[2].text).toContain("almost exactly as we do");
  });
});

describe("lineup lines", () => {
  const xi = (positions: (string | null)[]) => positions.map((position, i) => ({ name: `P${i}`, position }));

  it("splits starters by the formation, goalkeeper first", () => {
    const rows = lines(xi(Array(11).fill(null)), "4-2-3-1")!;
    expect(rows.map((r) => r.length)).toEqual([1, 4, 2, 3, 1]);
    expect(rows[0][0].name).toBe("P0");
  });

  it("falls back to positions when the formation does not add up", () => {
    const rows = lines(xi(["G", "D", "D", "D", "M", "M", "F"]), "4-4-2")!;
    expect(rows.map((r) => r.length)).toEqual([1, 3, 2, 1]);
  });

  it("gives up when neither the formation nor positions are usable", () => {
    expect(lines(xi([null, "DF"]), null)).toBeNull();
  });
});
