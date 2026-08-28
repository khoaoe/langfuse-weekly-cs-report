import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { ReactNode } from "react";

import { server } from "./msw/server";
import { useDayRangeAggregates } from "../src/hooks/useDayRangeAggregates";

function wrapper({ children }: { readonly children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("useDayRangeAggregates", () => {
  it("requests a 6-day lookback before `from` while keeping the plotted domain from...to", async () => {
    let requestedFrom: string | null = null;
    let requestedTo: string | null = null;
    server.use(
      http.get("/api/tickets", ({ request }) => {
        const url = new URL(request.url);
        requestedFrom = url.searchParams.get("opened_from");
        requestedTo = url.searchParams.get("opened_to");
        return HttpResponse.json({ days: [] });
      }),
    );

    const { result } = renderHook(
      () =>
        useDayRangeAggregates({
          from: "2026-08-10",
          to: "2026-08-14",
          weekDefinition: "mon_sun",
          enabled: true,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(requestedFrom).toBe("2026-08-04");
    expect(requestedTo).toBe("2026-08-14");
  });

  it("splits fetched days into a lookback window and the plotted range", async () => {
    const days = [
      "2026-08-04",
      "2026-08-05",
      "2026-08-06",
      "2026-08-07",
      "2026-08-08",
      "2026-08-09",
      "2026-08-10",
      "2026-08-11",
    ].map((day) => ({
      day,
      total_tickets: 1,
      ai_first_count: 1,
      transferred_count: 0,
      direct_cs_count: 0,
      outcomes: { ai_end_to_end: 1, ai_then_cs: 0, direct_cs: 0, unclassified: 0 },
      reopen_lifetime_numerator: 0,
      reopen_lifetime_denominator: 1,
      gt4_turn_with_cs: 0,
      gt4_turn_without_cs: 0,
      resolved_first_reply_count: 1,
      ai_reply_sum_ai_first: 1,
      segments: { skill: {}, app: {}, issue_category: {} },
      transfer_reasons: {},
    }));
    server.use(
      http.get("/api/tickets", () => HttpResponse.json({ days })),
    );

    const { result } = renderHook(
      () =>
        useDayRangeAggregates({
          from: "2026-08-10",
          to: "2026-08-11",
          weekDefinition: "mon_sun",
          enabled: true,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.data?.allDays.map((d) => d.day)).toEqual(
      days.map((d) => d.day),
    );
    expect(result.current.data?.plottedDays.map((d) => d.day)).toEqual([
      "2026-08-10",
      "2026-08-11",
    ]);
  });

  it("does not fetch when disabled", async () => {
    let requested = false;
    server.use(
      http.get("/api/tickets", () => {
        requested = true;
        return HttpResponse.json({ days: [] });
      }),
    );

    const { result } = renderHook(
      () =>
        useDayRangeAggregates({
          from: "2026-08-10",
          to: "2026-08-11",
          weekDefinition: "mon_sun",
          enabled: false,
        }),
      { wrapper },
    );

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(requested).toBe(false);
    expect(result.current.isLoading).toBe(false);
  });
});
