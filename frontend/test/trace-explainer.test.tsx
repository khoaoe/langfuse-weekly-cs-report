import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TraceExplainer,
  buildSummaryMarkdown,
  renderSafeResponse,
} from "../src/components/TraceExplainer";
import type { TraceExplanation } from "../src/lib/trace-explain-schema";
import { server } from "./msw/server";

const WHY_EXPLANATION = {
  ticket_id: "7068785",
  escalation_class: "NONE",
  dossier: {
    ticket_id: "7068785",
    escalation_class: "NONE",
    escalated_turn: null,
    guardrail_reason: null,
    blocking_rule: null,
    skills_loaded: ["withdraw"],
    sub_skills_read: [],
    tool_evidence: [],
    ticket_facts: [],
    rule_candidates: [],
    coverage: { app_id: null, expected_skill: null, loaded_skills: ["withdraw"], mismatch: false },
    turn_deltas: [],
    drift_changed: false,
    phases: [
      {
        key: "tiep_nhan",
        title: "Tiếp nhận câu hỏi",
        summary: "2 bước kiểm tra · đạt",
        rows: [],
        state: "dat",
        collapsed: true,
      },
      {
        key: "nhan_dien",
        title: "Nhận diện vấn đề",
        summary: "1 bước kiểm tra · đạt",
        rows: [],
        state: "dat",
        collapsed: true,
      },
      {
        key: "doc_quy_dinh",
        title: "Đọc quy định",
        summary: "Không có bước nào",
        rows: [],
        state: "dat",
        collapsed: true,
      },
      {
        key: "tra_du_lieu",
        title: "Tra dữ liệu",
        summary: "",
        rows: [
          { label: "Ngân hàng", value: "VCB", evidence: { bank: "VCB" } },
        ],
        state: "thong_tin",
        collapsed: false,
      },
      {
        key: "ket_qua",
        title: "TRẢ LỜI KHÁCH",
        summary: "",
        rows: [],
        state: "quyet_dinh",
        collapsed: false,
      },
    ],
    blocked_response_draft: null,
    blocked_input_message: null,
  },
  narration: null,
  llm_status: "disabled",
  drift: { changed: false },
};

function renderExplainer(ticketId: string | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <TraceExplainer ticketId={ticketId} />
    </QueryClientProvider>,
  );
}

const EXPLANATION: TraceExplanation = {
  ticket_id: "7068785",
  turns: [
    {
      trace_id: "trace-0",
      turn: 0,
      timestamp: "2026-08-01T02:00:00.000Z",
      verdict: "chuyen_cs",
      verdict_reason: "Câu hỏi vướng rule off_topic",
      skills_used: [],
      tools_called: [],
      steps: [
        {
          key: "input_guardrail",
          label: "Kiểm tra câu hỏi của khách",
          outcome: "chan",
          summary: "Câu hỏi vướng rule off_topic",
          evidence: { output: { blocked: true, rule: "off_topic" } },
        },
      ],
      user_input: "asdkjaslkdj",
      response: "<p>chuyen CS</p>",
    },
    {
      trace_id: "trace-1",
      turn: 1,
      timestamp: "2026-08-02T02:00:00.000Z",
      verdict: "tra_loi",
      verdict_reason: "Agent đã trả lời khách",
      skills_used: ["withdraw"],
      tools_called: ["get_bank_info"],
      steps: [
        {
          key: "idempotency_guard",
          label: "Kiểm tra trùng lặp",
          outcome: "ok",
          summary: "Chưa xử lý trước đó, agent tiếp tục xử lý",
          evidence: { output: { blocked: false } },
        },
        {
          key: "tool:get_bank_info",
          label: "Tra dữ liệu: get_bank_info",
          outcome: "ok",
          summary: "Agent tra cứu dữ liệu qua get_bank_info",
          evidence: { input: {}, output: { bank: "VCB" } },
        },
      ],
      user_input: "cam on, con giao dich khac",
      response: "<p>da xu ly giao dich thu hai</p>",
    },
  ],
  langfuse_url:
    "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces?filter=x&dateRange=1-2",
};

afterEach(() => {
  window.location.hash = "";
});

describe("TraceExplainer", () => {
  it("shows a placeholder and makes no request when no ticket is selected", () => {
    renderExplainer(null);

    expect(
      screen.getByText("Dán mã ticket ở trên để xem."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Mã ticket")).toHaveValue("");
  });

  it("renders the latest turn by default: badge, conclusion sentence and timeline", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
      http.get("/api/trace-explain/:ticketId/why", () =>
        HttpResponse.json(WHY_EXPLANATION),
      ),
    );

    renderExplainer("7068785");

    expect(await screen.findByText("Đã trả lời")).toBeInTheDocument();
    expect(screen.getByText("Agent đã trả lời khách")).toBeInTheDocument();
    // Timeline now comes from the separate /why dossier (spec 11.1).
    expect(await screen.findByText("Ngân hàng")).toBeInTheDocument();
    expect(screen.getByText("VCB")).toBeInTheDocument();
    // The blocked first turn must not be shown until selected.
    expect(screen.queryByText("Câu hỏi vướng rule off_topic")).not.toBeInTheDocument();
  });

  it("switches turns via the turn selector without losing the shared timeline", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
      http.get("/api/trace-explain/:ticketId/why", () =>
        HttpResponse.json(WHY_EXPLANATION),
      ),
    );
    const user = userEvent.setup();
    renderExplainer("7068785");
    await screen.findByText("Đã trả lời");

    await user.click(screen.getByRole("tab", { name: "Lượt 1" }));

    expect(screen.getByText("Chuyển CS")).toBeInTheDocument();
    expect(screen.getByText("Câu hỏi vướng rule off_topic")).toBeInTheDocument();
    // The timeline reflects the session's dossier, not the selected tab --
    // it must not disappear when switching to an earlier turn.
    expect(screen.getByText("Ngân hàng")).toBeInTheDocument();
  });

  it("expands a timeline row to show its raw evidence", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
      http.get("/api/trace-explain/:ticketId/why", () =>
        HttpResponse.json(WHY_EXPLANATION),
      ),
    );
    const user = userEvent.setup();
    renderExplainer("7068785");
    await screen.findByText("Đã trả lời");

    expect(screen.queryByText(/"bank": "VCB"/)).not.toBeInTheDocument();
    await user.click(await screen.findByText("Xem bằng chứng"));

    expect(screen.getByText(/"bank": "VCB"/)).toBeInTheDocument();
  });

  it("shows a Vietnamese not-found message on 404, not a blank screen", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json({ detail: { code: "trace_not_found" } }, { status: 404 }),
      ),
    );

    renderExplainer("9999999");

    expect(
      await screen.findByText("Không tìm thấy trace nào cho ticket này."),
    ).toBeInTheDocument();
  });

  it("shows a Vietnamese unavailable message on 503", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json({ detail: { code: "langfuse_unavailable" } }, { status: 503 }),
      ),
    );

    renderExplainer("7068785");

    expect(
      await screen.findByText("Không đọc được Langfuse lúc này. Thử lại sau."),
    ).toBeInTheDocument();
  });

  it("navigates by setting the #trace/<id> hash when the paste box is submitted", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
    );
    const user = userEvent.setup();
    renderExplainer(null);

    await user.type(screen.getByLabelText("Mã ticket"), "12345");
    await user.click(screen.getByRole("button", { name: "Xem" }));

    expect(window.location.hash).toBe("#trace/12345");
  });

  it("copies the explainer page link, not the raw Langfuse link", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
    );
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    renderExplainer("7068785");
    await screen.findByText("Đã trả lời");

    await user.click(screen.getByRole("button", { name: "Copy link" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const [copiedText] = writeText.mock.calls[0]!;
    expect(copiedText).toContain(window.location.pathname);
    expect(copiedText).not.toContain("langfuse.zalopay.vn");
  });

  it("offers a way back to the dashboard, not just the browser Back button", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
    );
    const user = userEvent.setup();
    renderExplainer("7068785");
    await screen.findByText("Đã trả lời");
    window.location.hash = "#trace/7068785";

    await user.click(screen.getByRole("button", { name: "Quay lại dashboard" }));

    expect(window.location.hash).not.toContain("trace");
  });

  it("shows the back button even before any ticket is loaded", () => {
    renderExplainer(null);

    expect(screen.getByRole("button", { name: "Quay lại dashboard" })).toBeInTheDocument();
  });

  it("renders the agent response as separate paragraphs, not raw HTML tags", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
    );
    renderExplainer("7068785");

    expect(await screen.findByText("da xu ly giao dich thu hai")).toBeInTheDocument();
    expect(screen.queryByText(/<p>/)).not.toBeInTheDocument();
  });

  it("still links out to the original Langfuse trace for the AI team", async () => {
    server.use(
      http.get("/api/trace-explain/:ticketId", () =>
        HttpResponse.json(EXPLANATION),
      ),
    );
    renderExplainer("7068785");
    await screen.findByText("Đã trả lời");

    const link = screen.getByRole("link", { name: "Mở trace gốc trên Langfuse" });
    expect(link).toHaveAttribute("href", EXPLANATION.langfuse_url);
  });
});

describe("buildSummaryMarkdown", () => {
  it("renders a markdown summary of one turn including every step", () => {
    const markdown = buildSummaryMarkdown("7068785", EXPLANATION.turns[1]!, "https://x/y#trace/7068785");

    expect(markdown).toContain("Ticket 7068785");
    expect(markdown).toContain("Lượt 2");
    expect(markdown).toContain("Agent đã trả lời khách");
    expect(markdown).toContain("Tra dữ liệu: get_bank_info");
    expect(markdown).toContain("https://x/y#trace/7068785");
  });
});

describe("renderSafeResponse", () => {
  it("preserves bold and list formatting as real elements, not stripped text", () => {
    const html =
      "<p>Xin chao</p><p><strong>Thong tin giao dich</strong></p>" +
      "<ul><li>Ma GD: 123</li><li>So tien: 5.000d</li></ul>";

    render(<>{renderSafeResponse(html)}</>);

    expect(screen.getByText("Thong tin giao dich").tagName).toBe("STRONG");
    expect(screen.getByText("Ma GD: 123").closest("li")).not.toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("falls back to the raw text when there are no recognised tags", () => {
    render(<>{renderSafeResponse("plain text reply")}</>);

    expect(screen.getByText("plain text reply")).toBeInTheDocument();
  });

  it("never executes embedded markup and drops every attribute -- only allowlisted tags and text survive", () => {
    const malicious =
      '<p>hello<img src="x" onerror="window.__pwned = true">world' +
      '<a href="javascript:alert(1)">click</a></p>';

    const { container } = render(<>{renderSafeResponse(malicious)}</>);

    expect(container).toHaveTextContent("hello");
    expect(container).toHaveTextContent("world");
    expect(container).toHaveTextContent("click");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect((window as { __pwned?: boolean }).__pwned).toBeUndefined();
  });
});
