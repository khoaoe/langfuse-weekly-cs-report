import { z } from "zod";

const ToolEvidenceSchema = z
  .object({
    step_key: z.string(),
    label: z.string(),
    value: z.string(),
    turn: z.number().int(),
    failed: z.boolean(),
  })
  .strict();

const TicketFactSchema = z
  .object({
    label: z.string(),
    value: z.string().nullable(),
    present: z.boolean(),
  })
  .strict();

const RuleCandidateSchema = z
  .object({
    anchor: z.string(),
    skill: z.string(),
    file_label: z.string(),
    case_id: z.string().nullable(),
    case_title: z.string(),
    body: z.string(),
    source: z.enum(["sub_skill", "skill_md", "tool_message"]),
  })
  .strict();

const CoverageCheckSchema = z
  .object({
    app_id: z.string().nullable(),
    expected_skill: z.string().nullable(),
    loaded_skills: z.array(z.string()),
    mismatch: z.boolean(),
  })
  .strict();

const TurnDeltaSchema = z
  .object({
    turn: z.number().int(),
    agent_asked_for: z.array(z.string()),
    facts_already_known: z.array(z.string()),
  })
  .strict();

const TimelineRowSchema = z
  .object({
    label: z.string(),
    value: z.string(),
    evidence: z.record(z.string(), z.unknown()),
  })
  .strict();

const TimelinePhaseSchema = z
  .object({
    key: z.enum(["tiep_nhan", "nhan_dien", "doc_quy_dinh", "tra_du_lieu", "ket_qua"]),
    title: z.string(),
    summary: z.string(),
    rows: z.array(TimelineRowSchema),
    state: z.enum(["dat", "thong_tin", "quyet_dinh", "chan"]),
    collapsed: z.boolean(),
  })
  .strict();

const EscalationDossierSchema = z
  .object({
    ticket_id: z.string(),
    escalation_class: z.enum([
      "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "NONE",
    ]),
    escalated_turn: z.number().int().nullable(),
    guardrail_reason: z.string().nullable(),
    blocking_rule: z.string().nullable(),
    skills_loaded: z.array(z.string()),
    sub_skills_read: z.array(z.string()),
    tool_evidence: z.array(ToolEvidenceSchema),
    ticket_facts: z.array(TicketFactSchema),
    rule_candidates: z.array(RuleCandidateSchema),
    coverage: CoverageCheckSchema,
    turn_deltas: z.array(TurnDeltaSchema),
    drift_changed: z.boolean(),
    phases: z.array(TimelinePhaseSchema),
    blocked_response_draft: z.string().nullable(),
    blocked_input_message: z.string().nullable(),
  })
  .strict();

const NarrationCanCuSchema = z
  .object({
    nguon: z.string(),
    case_id: z.string().nullable(),
    case_title: z.string(),
    file_label: z.string(),
    skill: z.string(),
    trich_dan: z.string().nullable(),
    trich_dan_dong: z.number().int().nullable(),
  })
  .strict();

const NarrationBangChungSchema = z
  .object({
    buoc: z.string(),
    nhan: z.string(),
    ket_qua: z.string(),
  })
  .strict();

const NarrationSchema = z
  .object({
    ket_luan: z.string(),
    can_cu: NarrationCanCuSchema.nullable(),
    bang_chung: z.array(NarrationBangChungSchema),
    do_tin_cay: z.enum(["cao", "trung_binh", "thap"]),
  })
  .strict();

// "pending" is /why-only -- it means "no LLM result attempted yet, call
// /why-narration for one"; every other value is a final, settled outcome.
const LLM_STATUS_ENUM = z.enum([
  "ok", "rejected", "unavailable", "disabled", "skipped", "pending",
]);

export const WhyExplanationSchema = z
  .object({
    ticket_id: z.string(),
    escalation_class: z.enum([
      "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "NONE",
    ]),
    dossier: EscalationDossierSchema,
    narration: NarrationSchema.nullable(),
    llm_status: LLM_STATUS_ENUM,
    drift: z.object({ changed: z.boolean() }).strict(),
  })
  .strict();

export const WhyNarrationSchema = z
  .object({
    narration: NarrationSchema.nullable(),
    llm_status: LLM_STATUS_ENUM,
  })
  .strict();

export type ToolEvidence = z.infer<typeof ToolEvidenceSchema>;
export type TicketFact = z.infer<typeof TicketFactSchema>;
export type RuleCandidate = z.infer<typeof RuleCandidateSchema>;
export type TimelineRow = z.infer<typeof TimelineRowSchema>;
export type TimelinePhase = z.infer<typeof TimelinePhaseSchema>;
export type EscalationDossier = z.infer<typeof EscalationDossierSchema>;
export type Narration = z.infer<typeof NarrationSchema>;
export type WhyExplanation = z.infer<typeof WhyExplanationSchema>;
export type WhyNarration = z.infer<typeof WhyNarrationSchema>;

export type SafeParseResult<T> =
  | { readonly ok: true; readonly data: T }
  | { readonly ok: false; readonly message: string };

export function parseWhyExplanation(
  value: unknown,
): SafeParseResult<WhyExplanation> {
  const parsed = WhyExplanationSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, message: "Không thể đọc dữ liệu giải thích." };
  }
  return { ok: true, data: parsed.data };
}

export function parseWhyNarration(
  value: unknown,
): SafeParseResult<WhyNarration> {
  const parsed = WhyNarrationSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, message: "Không thể đọc dữ liệu phân tích." };
  }
  return { ok: true, data: parsed.data };
}
