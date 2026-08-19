import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { dashboardEnvelopeFixture } from "../fixtures/dashboard";

export const dashboardHandler = http.get("/api/dashboard", () =>
  HttpResponse.json(dashboardEnvelopeFixture),
);

// TraceExplainer/WhyDrawer always fire a second, independent request for the
// deterministic dossier (spec 11.2) alongside /api/trace-explain/:ticketId --
// a harmless default here means tests that don't care about /why content
// (most of them) don't have to mock it themselves.
export const whyExplanationHandler = http.get(
  "/api/trace-explain/:ticketId/why",
  ({ params }) =>
    HttpResponse.json({
      ticket_id: String(params.ticketId),
      escalation_class: "NONE",
      dossier: {
        ticket_id: String(params.ticketId),
        escalation_class: "NONE",
        escalated_turn: null,
        guardrail_reason: null,
        blocking_rule: null,
        skills_loaded: [],
        sub_skills_read: [],
        tool_evidence: [],
        ticket_facts: [],
        rule_candidates: [],
        coverage: { app_id: null, expected_skill: null, loaded_skills: [], mismatch: false },
        turn_deltas: [],
        drift_changed: false,
        phases: [],
      },
      narration: null,
      llm_status: "disabled",
      drift: { changed: false },
    }),
);

export const server = setupServer(
  dashboardHandler,
  whyExplanationHandler,
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
