import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { DashboardRequestError, fetchWhyExplanation } from "../lib/api";
import {
  parseWhyExplanation,
  type EscalationDossier,
  type Narration,
} from "../lib/why-schema";
import { MarkdownLite } from "./MarkdownLite";
import { WhyTimeline } from "./WhyTimeline";
import styles from "./why-drawer.module.css";

const DRAWER_TITLE: Record<string, string> = {
  NONE: "Trợ lý đã xử lý thế nào",
};
const DEFAULT_TITLE = "Vì sao ticket này chuyển CS";

const BRANCH_TEMPLATE: Record<string, string> = {
  E1: "Trợ lý xác định tình huống thuộc kịch bản {case_title}, và quy định của kịch bản này yêu cầu chuyển cho bộ phận chăm sóc khách hàng.",
  E2: "Nội dung trợ lý định trả lời mang nghĩa chuyển tiếp cho người hỗ trợ, nên ticket được chuyển cho bộ phận chăm sóc khách hàng.",
  E3: "Câu hỏi của khách không nằm trong phạm vi trợ lý tự động xử lý, nên được chuyển thẳng cho bộ phận chăm sóc khách hàng.",
  E4: "Ticket này đã được chuyển cho bộ phận chăm sóc khách hàng ở lượt trước, nên trợ lý không trả lời các lượt sau.",
  E5: "Ticket này đã được xử lý trước đó nên trợ lý không trả lời lại.",
  E6: "Nhóm dịch vụ của ticket này chưa có kịch bản nghiệp vụ nào phủ, nên trợ lý chuyển cho bộ phận chăm sóc khách hàng.",
  E7: "Trợ lý tra dữ liệu nhưng hệ thống không trả về thông tin cần thiết, nên theo hướng dẫn phải chuyển cho bộ phận chăm sóc khách hàng.",
  E8: "Câu trả lời trợ lý soạn ra chưa đạt yêu cầu về nội dung, nên chuyển cho người xử lý.",
  E9: "Bước kiểm duyệt giọng điệu câu trả lời gặp lỗi kỹ thuật, không phải do nội dung câu trả lời có vấn đề.",
};

// spec 17.9 -- rule-specific sentences that stand in for the generic E3
// template whenever the exact rule is known.
const RULE_TEMPLATE: Record<string, string> = {
  missing_transaction_id:
    "Khách chưa cung cấp mã giao dịch nên trợ lý không tra cứu được, phải chuyển cho bộ phận chăm sóc khách hàng.",
  max_replies_exceeded:
    "Khách đã trao đổi qua nhiều lượt mà chưa xong, nên ticket được chuyển cho người xử lý.",
  off_topic: "Nội dung khách hỏi nằm ngoài phạm vi trợ lý tự động xử lý.",
  off_topic_llm: "Nội dung khách hỏi nằm ngoài phạm vi trợ lý tự động xử lý.",
  prompt_injection_llm:
    "Nội dung khách gửi có dấu hiệu bất thường về mặt an toàn, nên được chuyển cho người kiểm tra.",
  multilingual_jailbreak:
    "Nội dung khách gửi có dấu hiệu bất thường về mặt an toàn, nên được chuyển cho người kiểm tra.",
  empty_input: "Ticket không có nội dung để trợ lý xử lý.",
  empty_message_marker: "Ticket không có nội dung để trợ lý xử lý.",
  // profanity/customer_insult/foreign_language/inappropriate_tone_llm only
  // ever fire from the OUTPUT guardrail (checking the bot's own draft, not
  // the customer's message) -- cs-agent-master's input side uses different
  // rule names (multilingual_jailbreak, off_topic...) for the same idea.
  profanity:
    "Câu trả lời trợ lý soạn ra chứa từ ngữ không phù hợp, nên chuyển cho người xử lý.",
  customer_insult:
    "Câu trả lời trợ lý soạn ra có lời lẽ không phù hợp với khách, nên chuyển cho người xử lý.",
  foreign_language:
    "Câu trả lời trợ lý soạn ra dùng ngôn ngữ chưa được hỗ trợ, nên chuyển cho người xử lý.",
  inappropriate_tone_llm:
    "Câu trả lời trợ lý soạn ra chưa đạt yêu cầu về nội dung, nên chuyển cho người xử lý.",
  tone_check_error:
    "Bước kiểm duyệt giọng điệu câu trả lời gặp lỗi kỹ thuật, không phải do nội dung câu trả lời có vấn đề.",
};

/** Ô ① when llm_status != "ok": a real guardrail_reason (system-generated
 * text, not a guess) wins; otherwise fall back to the fixed sentence for the
 * rule, then the branch, per spec 17.6/17.9. Tầng 2 (LLM) is not wired up
 * yet -- every ticket is served this way until then. */
function conclusionFor(dossier: EscalationDossier): string {
  if (dossier.guardrail_reason) {
    return dossier.guardrail_reason;
  }
  if (dossier.blocking_rule) {
    const ruleTemplate = RULE_TEMPLATE[dossier.blocking_rule];
    if (ruleTemplate) {
      return ruleTemplate;
    }
  }
  const caseTitle = dossier.rule_candidates[0]?.case_title;
  const template = BRANCH_TEMPLATE[dossier.escalation_class];
  if (!template) {
    return "Chưa xác định được lý do cụ thể từ dữ liệu trợ lý.";
  }
  return template.replace("{case_title}", caseTitle ?? "đã áp dụng");
}

function WhyCard({
  dossier,
  narration,
}: {
  readonly dossier: EscalationDossier;
  readonly narration: Narration | null;
}) {
  const ketLuan = narration?.ket_luan ?? conclusionFor(dossier);
  const canCu = narration?.can_cu ?? null;
  const fallbackCandidate = dossier.rule_candidates[0] ?? null;
  // narration.can_cu === null with narration present means stage A returned
  // "khong_xac_dinh" -- a valid outcome, distinct from "no narration at all".
  const stageAWasUndetermined = narration !== null && canCu === null;

  const quoteBody =
    canCu !== null
      ? (canCu.trich_dan ??
        dossier.rule_candidates.find((c) => c.anchor === canCu.nguon)?.body ??
        canCu.case_title)
      : (fallbackCandidate?.body ?? null);
  const caseMeta =
    canCu !== null
      ? { caseId: canCu.case_id, caseTitle: canCu.case_title, skill: canCu.skill, fileLabel: canCu.file_label }
      : fallbackCandidate !== null
        ? {
            caseId: fallbackCandidate.case_id,
            caseTitle: fallbackCandidate.case_title,
            skill: fallbackCandidate.skill,
            fileLabel: fallbackCandidate.file_label,
          }
        : null;

  const evidenceRows =
    narration && narration.bang_chung.length > 0
      ? narration.bang_chung.map((item) => ({
          key: item.buoc,
          label: item.nhan,
          value: item.ket_qua,
        }))
      : dossier.tool_evidence.map((ev, index) => ({
          key: `${ev.step_key}-${index}`,
          label: ev.label,
          value: ev.value,
        }));

  const ticketFactRows = dossier.ticket_facts.map((fact, index) => ({
    key: `${fact.label}-${index}`,
    label: fact.label,
    value: fact.value ?? (fact.present ? "Có" : "Không có"),
  }));

  return (
    <div className={styles.card}>
      {ticketFactRows.length > 0 ? (
        <div className={styles.cardSection}>
          <p className={styles.cardLabel}>THÔNG TIN TICKET</p>
          <ul className={styles.evidenceList}>
            {ticketFactRows.map((row) => (
              <li key={row.key} className={styles.evidenceRow}>
                <span className={styles.evidenceRowLabel}>{row.label}</span>
                <span className={styles.evidenceRowValue}>{row.value}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={styles.cardSection}>
        <p className={styles.cardLabel}>VÌ SAO</p>
        <p className={styles.cardConclusion}>{ketLuan}</p>
      </div>

      <div className={styles.cardSection}>
        <p className={styles.cardLabel}>CĂN CỨ</p>
        {stageAWasUndetermined ? (
          <p className={styles.caseMeta}>Không xác định được kịch bản cụ thể</p>
        ) : caseMeta !== null ? (
          <>
            <p className={styles.caseMeta}>
              {caseMeta.caseId ? `Kịch bản ${caseMeta.caseId} — ` : ""}
              {caseMeta.caseTitle}
              {" · "}
              {caseMeta.skill}/{caseMeta.fileLabel}
            </p>
            <blockquote className={styles.quote}>
              <MarkdownLite text={quoteBody ?? ""} />
            </blockquote>
          </>
        ) : (
          <p className={styles.caseMeta}>Không áp dụng kịch bản nghiệp vụ nào</p>
        )}
      </div>

      {dossier.blocked_response_draft ? (
        <div className={styles.cardSection}>
          <p className={styles.cardLabel}>NỘI DUNG AI ĐỊNH TRẢ LỜI</p>
          <blockquote className={styles.quote}>
            <MarkdownLite text={dossier.blocked_response_draft} />
          </blockquote>
        </div>
      ) : dossier.blocked_input_message ? (
        <div className={styles.cardSection}>
          <p className={styles.cardLabel}>NỘI DUNG KHÁCH GỬI</p>
          <blockquote className={styles.quote}>
            <MarkdownLite text={dossier.blocked_input_message} />
          </blockquote>
        </div>
      ) : null}

      <div className={styles.cardSection}>
        <p className={styles.cardLabel}>BẰNG CHỨNG</p>
        {evidenceRows.length > 0 ? (
          <ul className={styles.evidenceList}>
            {evidenceRows.map((row) => (
              <li key={row.key} className={styles.evidenceRow}>
                <span className={styles.evidenceRowLabel}>{row.label}</span>
                <span className={styles.evidenceRowValue}>{row.value}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.caseMeta}>Không có dữ liệu tra cứu</p>
        )}
      </div>

      {dossier.drift_changed ? (
        <p className={styles.driftNote}>Skill đã thay đổi sau khi ticket này chạy</p>
      ) : null}
    </div>
  );
}

function whyErrorMessage(error: unknown): string {
  if (error instanceof DashboardRequestError) {
    if (error.status === 404) {
      return "Ticket này không có dữ liệu xử lý của trợ lý.";
    }
    if (error.status === 503) {
      return "Không đọc được Langfuse lúc này. Thử lại sau.";
    }
  }
  return "Không đọc được dữ liệu giải thích.";
}

export function WhyDrawer({
  ticketId,
  onClose,
}: {
  readonly ticketId: string | null;
  readonly onClose: () => void;
}) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const query = useQuery({
    queryKey: ["trace-why", ticketId],
    enabled: ticketId !== null,
    retry: false,
    queryFn: async ({ signal }) => {
      const parsed = parseWhyExplanation(
        await fetchWhyExplanation(ticketId as string, signal),
      );
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      return parsed.data;
    },
  });

  useEffect(() => {
    if (ticketId === null) {
      return;
    }
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    drawerRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || drawerRef.current === null) {
        return;
      }
      const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
        'button, a[href], input, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) {
        return;
      }
      const first = focusable.item(0);
      const last = focusable.item(focusable.length - 1);
      if (first === null || last === null) {
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [ticketId, onClose]);

  if (ticketId === null) {
    return null;
  }

  const dossier = query.data?.dossier ?? null;
  const title =
    dossier !== null
      ? (DRAWER_TITLE[dossier.escalation_class] ?? DEFAULT_TITLE)
      : DEFAULT_TITLE;

  return (
    <>
      <div className={styles.overlay} onClick={onClose} aria-hidden="true" />
      <div
        ref={drawerRef}
        className={styles.drawer}
        role="dialog"
        aria-modal="true"
        aria-labelledby="why-drawer-title"
        tabIndex={-1}
      >
        <div className={styles.drawerHead}>
          <h2 id="why-drawer-title" className={styles.drawerTitle}>
            {title}
          </h2>
          <button
            type="button"
            className={styles.closeButton}
            onClick={onClose}
            aria-label="Đóng"
          >
            ×
          </button>
        </div>

        {query.isLoading ? (
          <p role="status">Đang tải…</p>
        ) : query.isError ? (
          <p role="alert">{whyErrorMessage(query.error)}</p>
        ) : dossier !== null ? (
          <>
            {query.data?.llm_status !== "ok" ? (
              <p className={styles.caseMeta}>
                Phần diễn giải tự động chưa sẵn sàng. Nội dung dưới đây lấy trực tiếp từ hệ thống.
              </p>
            ) : null}
            {dossier.escalation_class !== "NONE" ? (
              <WhyCard
                dossier={dossier}
                narration={query.data?.llm_status === "ok" ? (query.data.narration ?? null) : null}
              />
            ) : null}
            <WhyTimeline phases={dossier.phases} />
          </>
        ) : null}
      </div>
    </>
  );
}
