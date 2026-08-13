import {
  Fragment,
  createElement,
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";

import { DashboardRequestError, fetchTraceExplanation } from "../lib/api";
import {
  parseTraceExplanation,
  type TraceExplanation,
  type TraceTurn,
} from "../lib/trace-explain-schema";
import { formatUpdatedAt } from "../lib/format";
import { isValidFreshdeskTicketId } from "./FreshdeskTicketLink";
import styles from "./dashboard.module.css";
import traceStyles from "./trace-explainer.module.css";

const VERDICT_BADGE_LABEL: Record<TraceTurn["verdict"], string> = {
  tra_loi: "Đã trả lời",
  chuyen_cs: "Chuyển CS",
  khong_tra_loi: "Không trả lời",
};

const VERDICT_BADGE_CLASS: Record<TraceTurn["verdict"], string | undefined> = {
  tra_loi: traceStyles.badgeAnswered,
  chuyen_cs: traceStyles.badgeTransferred,
  khong_tra_loi: traceStyles.badgeUnanswered,
};

const VERDICT_DOT_CLASS: Record<TraceTurn["verdict"], string | undefined> = {
  tra_loi: traceStyles.dotAnswered,
  chuyen_cs: traceStyles.dotTransferred,
  khong_tra_loi: traceStyles.dotUnanswered,
};

function traceExplainErrorMessage(error: unknown): string {
  if (error instanceof DashboardRequestError) {
    if (error.status === 400) {
      return "Mã ticket không hợp lệ.";
    }
    if (error.status === 404) {
      return "Không tìm thấy trace nào cho ticket này.";
    }
    if (error.status === 503) {
      return "Không đọc được Langfuse lúc này. Thử lại sau.";
    }
  }
  return "Không đọc được dữ liệu giải thích trace.";
}

export function buildSummaryMarkdown(
  ticketId: string,
  turn: TraceTurn,
  pageUrl: string,
): string {
  const lines = [
    `Ticket ${ticketId} — Lượt ${turn.turn + 1}`,
    `Kết luận: ${turn.verdict_reason}`,
    "",
    "Các bước:",
    ...turn.steps.map((step) => `- ${step.label}: ${step.summary}`),
    "",
    `Link: ${pageUrl}`,
  ];
  return lines.join("\n");
}

function navigateToTicket(rawValue: string): void {
  const value = rawValue.trim();
  if (!isValidFreshdeskTicketId(value)) {
    return;
  }
  window.location.hash = `trace/${value}`;
}

const SAFE_RESPONSE_TAGS: Readonly<Record<string, string>> = {
  P: "p",
  STRONG: "strong",
  B: "strong",
  EM: "em",
  I: "em",
  UL: "ul",
  OL: "ol",
  LI: "li",
  BR: "br",
};

function renderSafeNode(node: ChildNode, key: number): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }
  const element = node as Element;
  const children = Array.from(element.childNodes).map((child, index) =>
    renderSafeNode(child, index),
  );
  const tag = SAFE_RESPONSE_TAGS[element.tagName];
  if (tag === undefined) {
    return <Fragment key={key}>{children}</Fragment>;
  }
  if (tag === "br") {
    return <br key={key} />;
  }
  return createElement(tag, { key }, children);
}

/** The agent response is real HTML sent to a customer, but it is LLM output
 * over customer-controlled input -- a prompt injection could make the agent
 * emit a malicious tag. Never render it with dangerouslySetInnerHTML: parse
 * with DOMParser (its document is inert, scripts/onerror never fire), then
 * rebuild only an allowlisted set of formatting tags as real React elements.
 * No attribute is ever copied over -- href/src/style/onerror all vanish --
 * so an injected <img onerror=...> or <a href="javascript:..."> can only
 * ever contribute its own text, never execute or link anywhere. */
export function renderSafeResponse(html: string): ReactNode {
  if (typeof DOMParser === "undefined") {
    return html;
  }
  const parsed = new DOMParser().parseFromString(html, "text/html");
  return Array.from(parsed.body.childNodes).map((node, index) =>
    renderSafeNode(node, index),
  );
}

function TraceStepItem({ step }: { readonly step: TraceExplanation["turns"][number]["steps"][number] }) {
  const [expanded, setExpanded] = useState(false);
  const blocked = step.outcome === "chan";
  return (
    <li className={blocked ? traceStyles.stepBlocked : traceStyles.step}>
      <span
        className={blocked ? traceStyles.stepDotBlocked : traceStyles.stepDot}
        aria-hidden="true"
      />
      <div className={traceStyles.stepBody}>
        <p className={traceStyles.stepSummary}>{step.summary}</p>
        <p className={traceStyles.stepLabel}>{step.label}</p>
        <button
          type="button"
          className={traceStyles.evidenceToggle}
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "Ẩn chi tiết" : "Xem chi tiết"}
        </button>
        {expanded ? (
          <pre className={traceStyles.evidence}>
            {JSON.stringify(step.evidence, null, 2)}
          </pre>
        ) : null}
      </div>
    </li>
  );
}

function TraceTurnView({
  ticketId,
  turn,
  onCopyStatus,
}: {
  readonly ticketId: string;
  readonly turn: TraceTurn;
  readonly onCopyStatus: (message: string) => void;
}) {
  const copyLink = useCallback(() => {
    void navigator.clipboard.writeText(window.location.href).then(
      () => onCopyStatus("Đã copy link."),
      () => onCopyStatus("Không copy được link."),
    );
  }, [onCopyStatus]);

  const copySummary = useCallback(() => {
    const markdown = buildSummaryMarkdown(ticketId, turn, window.location.href);
    void navigator.clipboard.writeText(markdown).then(
      () => onCopyStatus("Đã copy tóm tắt."),
      () => onCopyStatus("Không copy được tóm tắt."),
    );
  }, [ticketId, turn, onCopyStatus]);

  return (
    <div>
      <div className={traceStyles.conclusionCard}>
        <p className={traceStyles.conclusion}>
          <span className={VERDICT_BADGE_CLASS[turn.verdict]}>
            {VERDICT_BADGE_LABEL[turn.verdict]}
          </span>
          {turn.verdict_reason}
        </p>
        <p className={traceStyles.turnMeta}>
          {formatUpdatedAt(turn.timestamp)}
          {turn.skills_used.length > 0 ? ` · Skill: ${turn.skills_used.join(", ")}` : ""}
        </p>
      </div>

      <div className={traceStyles.conversation}>
        <div className={traceStyles.customerBubble}>
          <span className={traceStyles.bubbleLabel}>Khách hỏi</span>
          <p>{turn.user_input}</p>
        </div>
        {turn.response ? (
          <div className={traceStyles.agentBubble}>
            <span className={traceStyles.bubbleLabel}>Agent trả lời</span>
            <div className={traceStyles.agentBubbleContent}>
              {renderSafeResponse(turn.response)}
            </div>
          </div>
        ) : null}
      </div>

      <h3 className={traceStyles.timelineTitle}>Diễn biến xử lý</h3>
      <ol className={traceStyles.timeline}>
        {turn.steps.map((step, index) => (
          <TraceStepItem key={`${step.key}-${index}`} step={step} />
        ))}
      </ol>

      <div className={traceStyles.actions}>
        <button type="button" className={styles.action} onClick={copyLink}>
          Copy link
        </button>
        <button type="button" className={styles.action} onClick={copySummary}>
          Copy tóm tắt
        </button>
      </div>
    </div>
  );
}

export function TraceExplainer({
  ticketId,
}: {
  readonly ticketId: string | null;
}) {
  const [pastedTicketId, setPastedTicketId] = useState(ticketId ?? "");
  const [selectedTurnIndex, setSelectedTurnIndex] = useState<number | null>(null);
  const [copyStatus, setCopyStatus] = useState("");

  const query = useQuery({
    queryKey: ["trace-explain", ticketId],
    enabled: ticketId !== null,
    retry: false,
    queryFn: async ({ signal }) => {
      const parsed = parseTraceExplanation(
        await fetchTraceExplanation(ticketId as string, signal),
      );
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      return parsed.data;
    },
  });

  const turns = query.data?.turns ?? [];
  const activeIndex = useMemo(() => {
    if (turns.length === 0) {
      return 0;
    }
    if (selectedTurnIndex !== null && selectedTurnIndex < turns.length) {
      return selectedTurnIndex;
    }
    return turns.length - 1;
  }, [turns.length, selectedTurnIndex]);
  const activeTurn = turns[activeIndex];

  return (
    <section
      id="trace-explainer"
      className={styles.section}
      aria-labelledby="trace-explainer-title"
    >
      <div className={styles.sectionHead}>
        <h2 id="trace-explainer-title" className={styles.sectionTitle}>
          Vì sao agent làm vậy
        </h2>
        <button
          type="button"
          className={styles.action}
          onClick={() => {
            window.location.hash = "weekly";
          }}
        >
          <span aria-hidden="true">← </span>Quay lại dashboard
        </button>
      </div>

      <form
        className={traceStyles.pasteForm}
        onSubmit={(event) => {
          event.preventDefault();
          navigateToTicket(pastedTicketId);
        }}
      >
        <label className={traceStyles.field}>
          Mã ticket
          <input
            type="text"
            inputMode="numeric"
            value={pastedTicketId}
            onChange={(event) => setPastedTicketId(event.target.value)}
          />
        </label>
        <button type="submit" className={styles.action}>
          Xem
        </button>
      </form>

      {ticketId === null ? (
        <p>Dán mã ticket ở trên để xem.</p>
      ) : query.isLoading ? (
        <p role="status">Đang tải…</p>
      ) : query.isError ? (
        <p role="alert">{traceExplainErrorMessage(query.error)}</p>
      ) : query.data && activeTurn ? (
        <>
          {turns.length > 1 ? (
            <div
              className={traceStyles.turnTabs}
              role="tablist"
              aria-label="Chọn lượt"
            >
              {turns.map((turn, index) => (
                <button
                  key={turn.trace_id}
                  type="button"
                  role="tab"
                  className={traceStyles.turnTab}
                  aria-selected={index === activeIndex}
                  onClick={() => setSelectedTurnIndex(index)}
                >
                  <span
                    className={VERDICT_DOT_CLASS[turn.verdict]}
                    aria-hidden="true"
                  />
                  {`Lượt ${turn.turn + 1}`}
                </button>
              ))}
            </div>
          ) : null}

          <TraceTurnView
            ticketId={query.data.ticket_id}
            turn={activeTurn}
            onCopyStatus={setCopyStatus}
          />

          <p aria-live="polite" className={traceStyles.copyStatus}>
            {copyStatus}
          </p>

          <p>
            <a
              className={traceStyles.langfuseLink}
              href={query.data.langfuse_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Mở trace gốc trên Langfuse
            </a>
          </p>
        </>
      ) : null}
    </section>
  );
}
