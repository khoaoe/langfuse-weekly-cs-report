import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { it, expect } from "vitest";

import { WhyDrawer } from "../src/components/WhyDrawer";
import { server } from "./msw/server";

function renderDrawer(ticketId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WhyDrawer ticketId={ticketId} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

// Real case candidates (only their shape matters here), same as would come
// from a loaded sub-skill file -- deliberately NOT the ticket's real case.
const RULE_CANDIDATES = [
  {
    anchor: "withdraw/references/sub-skill-C.md#L1",
    skill: "withdraw",
    file_label: "sub-skill-C",
    case_id: "C1",
    case_title: "Đã hoàn tiền thành công",
    body: "- Xác nhận đã hoàn tiền.",
    source: "sub_skill",
  },
  {
    anchor: "withdraw/references/sub-skill-C.md#L10",
    skill: "withdraw",
    file_label: "sub-skill-C",
    case_id: "D1",
    case_title: "Đang xử lý hoàn tiền",
    body: "- Nếu đã quá 3 ngày: Chuyển bộ phận CSKH.",
    source: "sub_skill",
  },
];

it("does not guess a case from rule_candidates[0] when there is no real narration", async () => {
  // Regression for the bug reported on ticket 7090152: with no LLM
  // narration, CĂN CỨ used to silently show rule_candidates[0] (whichever
  // case happens to be first in the skill file) as if it were confirmed --
  // there it showed "đã hoàn tiền thành công" for a refund that was still
  // processing. Must show "chưa xác định", never guess.
  server.use(
    http.get("/api/trace-explain/:ticketId/why", () =>
      HttpResponse.json({
        ticket_id: "9009001",
        escalation_class: "E1",
        dossier: {
          ticket_id: "9009001",
          escalation_class: "E1",
          escalated_turn: 0,
          guardrail_reason: "Phản hồi thông báo chuyển yêu cầu lên bộ phận Chăm sóc Khách hàng.",
          blocking_rule: "cs_escalation",
          skills_loaded: ["withdraw"],
          sub_skills_read: ["sub-skill-C.md"],
          tool_evidence: [],
          ticket_facts: [],
          rule_candidates: RULE_CANDIDATES,
          coverage: { app_id: "452", expected_skill: "withdraw", loaded_skills: ["withdraw"], mismatch: false },
          turn_deltas: [],
          drift_changed: false,
          phases: [],
          blocked_response_draft: null,
          blocked_input_message: null,
        },
        // No LLM available -- this is exactly the "unavailable" state
        // production is in right now (vllm.zalopay.vn network issue).
        narration: null,
        llm_status: "unavailable",
        drift: { changed: false },
      }),
    ),
  );

  renderDrawer("9009001");

  expect(await screen.findByText("Chưa xác định được kịch bản cụ thể")).toBeInTheDocument();
  expect(screen.queryByText("Đã hoàn tiền thành công")).not.toBeInTheDocument();
  expect(screen.queryByText("Đang xử lý hoàn tiền")).not.toBeInTheDocument();
  expect(screen.queryByText(/Chuyển bộ phận CSKH/)).not.toBeInTheDocument();
});
