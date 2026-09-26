import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import { server } from "./msw/server";
import { useDashboardRuntime } from "../src/hooks/useDashboardRuntime";
import {
  DashboardEnvelopeSchema,
  type DashboardEnvelope,
} from "../src/lib/dashboard-schema";

function RuntimeHarness() {
  const runtime = useDashboardRuntime();
  return (
    <>
      <output>{runtime.state.kind}</output>
      <button type="button" onClick={runtime.refresh}>
        Làm mới runtime
      </button>
    </>
  );
}

describe("dashboard and ticket snapshot consistency", () => {
  it("invalidates ticket queries only after a confirmed snapshot revision", async () => {
    const initialEnvelope = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture);
    if (initialEnvelope.snapshot === null) {
      throw new Error("fixture must contain a snapshot");
    }
    const nextEnvelope: DashboardEnvelope = {
      ...initialEnvelope,
      snapshot: {
        ...initialEnvelope.snapshot,
        generated_at: "2026-07-30T11:27:00Z",
      },
    };
    let currentEnvelope: DashboardEnvelope = initialEnvelope;
    let dashboardReads = 0;

    server.use(
      http.get("/api/dashboard", () => {
        dashboardReads += 1;
        return HttpResponse.json(currentEnvelope);
      }),
      http.post("/api/refresh", () =>
        HttpResponse.json({
          ...dashboardEnvelopeFixture,
          status: "refreshing",
          refreshing: true,
        }),
      ),
    );

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={client}>
        <RuntimeHarness />
      </QueryClientProvider>,
    );

    await screen.findByText("ready");
    await user.click(screen.getByRole("button", { name: "Làm mới runtime" }));
    await waitFor(() => expect(dashboardReads).toBeGreaterThanOrEqual(2));

    expect(invalidate).not.toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["tickets"] }),
    );

    currentEnvelope = nextEnvelope;
    await act(async () => {
      await client.refetchQueries({ queryKey: ["dashboard"] });
    });

    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["tickets"] }),
    );
  });
});

describe("dashboard conditional polling", () => {
  it("keeps the held snapshot when the server answers an unchanged poll with 304", async () => {
    const seenTags: (string | null)[] = [];
    server.use(
      http.get("/api/dashboard", ({ request }) => {
        const tag = request.headers.get("If-None-Match");
        seenTags.push(tag);
        return tag === '"v1"'
          ? new HttpResponse(null, { status: 304, headers: { ETag: '"v1"' } })
          : HttpResponse.json(dashboardEnvelopeFixture, { headers: { ETag: '"v1"' } });
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <RuntimeHarness />
      </QueryClientProvider>,
    );
    await screen.findByText("ready");
    await act(async () => {
      await client.refetchQueries({ queryKey: ["dashboard"] });
    });

    expect(seenTags.at(-1)).toBe('"v1"');
    expect(screen.getByText("ready")).toBeVisible();
  });
});
