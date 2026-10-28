import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { Competition, Fixture, pageOf, SelectionRow, TopPicks } from "./types";
import type { AiAnalysis, AiAnalysisState, Analysis, Page } from "./types";
import { z } from "zod";

// Predictions refresh in the background; polling is how the UI learns that a
// new snapshot (odds move, lineup confirmation) exists.
const LIVE = { refetchInterval: 60_000, staleTime: 30_000 };

export type FixtureFilters = {
  date_from?: string; date_to?: string; competition?: string[]; team?: string; status?: string;
  classification?: string; page?: number; page_size?: number;
};

export const useFixtures = (f: FixtureFilters) =>
  useQuery({
    queryKey: ["fixtures", f],
    queryFn: () => api<Page<Fixture>>("/fixtures", { query: f, schema: pageOf(Fixture) }),
    ...LIVE,
  });

export const useAnalysis = (id: number) =>
  useQuery({ queryKey: ["analysis", id], queryFn: () => api<Analysis>(`/fixtures/${id}/analysis`), ...LIVE });

export const useAiAnalysis = (id: number) =>
  useQuery({ queryKey: ["ai-analysis", id], queryFn: () => api<AiAnalysisState>(`/fixtures/${id}/ai-analysis`), staleTime: 60_000 });

export function useGenerateAiAnalysis(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<AiAnalysis>(`/fixtures/${id}/ai-analysis`, { method: "POST", body: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai-analysis", id] }),
  });
}

export type PredictionFilters = {
  status?: string; qualifying_only?: boolean; market?: string; competition?: string[]; search?: string;
  min_probability?: number; min_edge?: number; min_ev?: number; min_odds?: number; max_odds?: number;
  sort?: string; order?: string; page?: number; page_size?: number;
};

export const usePredictions = (f: PredictionFilters) =>
  useQuery({
    queryKey: ["predictions", f],
    queryFn: () => api<Page<SelectionRow>>("/predictions", { query: f, schema: pageOf(SelectionRow) }),
    ...LIVE,
  });

export const useTopPicks = (days: number) =>
  useQuery({
    queryKey: ["top-picks", days],
    queryFn: () => api<TopPicks>("/predictions/top", { query: { days }, schema: TopPicks }),
    ...LIVE,
  });

export const useCompetitions = () =>
  useQuery({
    queryKey: ["competitions"],
    queryFn: () => api("/competitions", { schema: z.array(Competition) }),
    staleTime: 600_000,
  });

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => api<Record<string, any>>("/system/health"), refetchInterval: 60_000 });

export const usePerformance = () =>
  useQuery({ queryKey: ["performance"], queryFn: () => api<Record<string, any>>("/performance/summary") });

export const usePerformanceMarkets = () =>
  useQuery({ queryKey: ["performance-markets"], queryFn: () => api<Record<string, any>>("/performance/markets") });

export const useBacktests = () =>
  useQuery({
    queryKey: ["backtests"],
    queryFn: () => api<Page<Record<string, any>>>("/backtests"),
    refetchInterval: (q) => (q.state.data?.items.some((b) => ["queued", "running"].includes(b.status)) ? 5000 : false),
  });

export const useBacktest = (id: number | null) =>
  useQuery({
    queryKey: ["backtest", id],
    queryFn: () => api<Record<string, any>>(`/backtests/${id}`),
    enabled: id !== null,
  });

export const useModels = () => useQuery({ queryKey: ["models"], queryFn: () => api<Record<string, any>[]>("/models") });

export const useTeams = (search: string) =>
  useQuery({
    queryKey: ["teams", search],
    queryFn: () => api<{ id: number; name: string }[]>("/teams", { query: { search, limit: 50 } }),
  });

export const useTeamStats = (id: number | null) =>
  useQuery({
    queryKey: ["team", id],
    queryFn: () => api<Record<string, any>>(`/teams/${id}/statistics`),
    enabled: id !== null,
  });

export const useDataQuality = () =>
  useQuery({ queryKey: ["data-quality"], queryFn: () => api<Record<string, any>>("/data-quality") });

export const useSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: () => api<Record<string, any>>("/settings") });

export const useMe = (enabled: boolean) =>
  useQuery({
    queryKey: ["me"],
    queryFn: () => api<{ id: number; email: string; role: string }>("/auth/me"),
    enabled,
    retry: false,
  });

export function useAdminAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { path: string; body?: unknown; method?: string }) =>
      api<Record<string, any>>(args.path, { method: args.method ?? "POST", body: args.body ?? {} }),
    onSuccess: () => qc.invalidateQueries(),
  });
}
