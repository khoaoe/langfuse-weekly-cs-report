import { z } from "zod";

const TraceStepSchema = z
  .object({
    key: z.string(),
    label: z.string(),
    outcome: z.enum(["ok", "chan", "bo_qua"]),
    summary: z.string(),
    evidence: z.record(z.string(), z.unknown()),
  })
  .strict();

const TraceTurnSchema = z
  .object({
    trace_id: z.string(),
    turn: z.number().int(),
    timestamp: z.string(),
    verdict: z.enum(["tra_loi", "chuyen_cs", "khong_tra_loi"]),
    verdict_reason: z.string(),
    skills_used: z.array(z.string()),
    tools_called: z.array(z.string()),
    steps: z.array(TraceStepSchema),
    user_input: z.string(),
    response: z.string(),
  })
  .strict();

export const TraceExplanationSchema = z
  .object({
    ticket_id: z.string(),
    turns: z.array(TraceTurnSchema),
    langfuse_url: z.string(),
  })
  .strict();

export type TraceStep = z.infer<typeof TraceStepSchema>;
export type TraceTurn = z.infer<typeof TraceTurnSchema>;
export type TraceExplanation = z.infer<typeof TraceExplanationSchema>;

export type SafeParseResult<T> =
  | { readonly ok: true; readonly data: T }
  | { readonly ok: false; readonly message: string };

export function parseTraceExplanation(
  value: unknown,
): SafeParseResult<TraceExplanation> {
  const parsed = TraceExplanationSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, message: "Không thể đọc dữ liệu giải thích trace." };
  }
  return { ok: true, data: parsed.data };
}
