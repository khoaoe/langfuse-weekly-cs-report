import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchDashboardEnvelope, requestRefresh } from "../lib/api";
import {
  type DashboardRuntime,
  initialDashboardRuntime,
  reduceDashboardRuntime,
} from "../lib/runtime-state";

/** While a snapshot is being built the server state changes quickly. */
const ACTIVE_POLL_MS = 2_000;
/** A settled snapshot has a five-minute TTL, so polling faster buys nothing. */
const STABLE_POLL_MS = 5 * 60 * 1_000;
/** After a failed read, back off instead of hammering a struggling backend. */
const RECOVERY_POLL_MS = 30_000;
/** Mirrors the backend manual-refresh cooldown so the button tells the truth. */
export const REFRESH_COOLDOWN_MS = 60_000;

export interface DashboardRuntimeController {
  readonly state: DashboardRuntime;
  readonly refresh: () => void;
  readonly refreshDisabled: boolean;
  readonly refreshHint: string;
}

function pollInterval(state: DashboardRuntime): number {
  switch (state.kind) {
    case "loading":
    case "refreshing":
      return ACTIVE_POLL_MS;
    case "stale_error":
      return RECOVERY_POLL_MS;
    case "ready":
      return STABLE_POLL_MS;
  }
}

/**
 * Owns the dashboard read loop.
 *
 * The reducer, not the query cache, decides what the operator sees, so a
 * failing poll degrades to "last good data plus a plain warning" instead of
 * blanking the report or leaking a server error code into the interface.
 */
export function useDashboardRuntime(): DashboardRuntimeController {
  const [state, dispatch] = useReducer(
    reduceDashboardRuntime,
    undefined,
    initialDashboardRuntime,
  );
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const inFlight = useRef(false);
  const previousSnapshotRevision = useRef<string | null>(null);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => fetchDashboardEnvelope(signal),
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: pollInterval(state),
  });

  const { data, dataUpdatedAt, isError, errorUpdatedAt, refetch } = query;

  useEffect(() => {
    if (data !== undefined) {
      dispatch({ type: "envelope", envelope: data });
    }
  }, [data, dataUpdatedAt]);

  const snapshotRevision = state.snapshot?.generated_at ?? null;
  useEffect(() => {
    if (snapshotRevision === null) {
      return;
    }
    const previous = previousSnapshotRevision.current;
    previousSnapshotRevision.current = snapshotRevision;
    if (previous !== null && previous !== snapshotRevision) {
      // Ticket rows and dashboard metrics are projections of the same
      // snapshot. Invalidate only once the server confirms a new revision;
      // doing it when refresh merely starts can re-cache the old rows.
      void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    }
  }, [queryClient, snapshotRevision]);

  useEffect(() => {
    if (isError) {
      dispatch({ type: "request-failed" });
    }
  }, [isError, errorUpdatedAt]);

  useEffect(() => {
    if (cooldownUntil <= now) {
      return;
    }
    const timer = window.setTimeout(() => setNow(Date.now()), 1_000);
    return () => window.clearTimeout(timer);
  }, [cooldownUntil, now]);

  const refresh = useCallback(() => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setCooldownUntil(Date.now() + REFRESH_COOLDOWN_MS);
    setNow(Date.now());
    dispatch({ type: "refresh-start" });

    void (async () => {
      try {
        dispatch({ type: "envelope", envelope: await requestRefresh() });
      } catch {
        dispatch({ type: "request-failed" });
      } finally {
        inFlight.current = false;
      }
      await refetch();
    })();
  }, [refetch]);

  const remainingMs = Math.max(0, cooldownUntil - now);
  const cooling = remainingMs > 0;
  const refreshDisabled = cooling || state.kind === "refreshing";

  return {
    state,
    refresh,
    refreshDisabled,
    refreshHint: cooling
      ? `Có thể làm mới lại sau ${Math.ceil(remainingMs / 1_000)} giây.`
      : "Yêu cầu máy chủ đọc lại dữ liệu ngay.",
  };
}
