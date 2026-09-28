import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { dashboardEnvelopeFixture } from "../fixtures/dashboard";

export const dashboardHandler = http.get("/api/dashboard", () =>
  HttpResponse.json(dashboardEnvelopeFixture),
);

export const server = setupServer(
  dashboardHandler,
  http.post("/api/refresh", () => HttpResponse.json({ ...dashboardEnvelopeFixture, status: "refreshing", refreshing: true })),
  http.get("/api/tickets", () => HttpResponse.json({ items: [], page: 1, page_size: 50, total: 0 })),
  http.get("/api/freshdesk-cookie", () =>
    HttpResponse.json({ state: "missing", updated_at: null, last_verified_at: null }),
  ),
  http.post("/api/freshdesk-cookie", () =>
    HttpResponse.json(
      { state: "ok", updated_at: "2026-08-12T00:00:00Z", last_verified_at: "2026-08-12T00:00:00Z" },
      { status: 202 },
    ),
  ),
);
