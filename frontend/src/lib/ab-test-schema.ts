import { z } from "zod";

const ArmMetricsSchema = z
  .object({
    arm: z.string(),
    ticket_count: z.number().int().nonnegative(),
    share: z.number().min(0).max(1),
    low_sample: z.boolean(),
    ai_end_to_end: z.number().int().nonnegative(),
    ai_then_cs: z.number().int().nonnegative(),
    direct_cs: z.number().int().nonnegative(),
    unclassified: z.number().int().nonnegative(),
    ai_first_count: z.number().int().nonnegative(),
    transferred_count: z.number().int().nonnegative(),
    reopen_count: z.number().int().nonnegative(),
    reopen_denominator: z.number().int().nonnegative(),
    turn_total: z.number().int().nonnegative(),
    latency_p50: z.number().nullable(),
    latency_p95: z.number().nullable(),
    llm_call_count: z.number().int().nonnegative(),
    input_tokens: z.number().int().nonnegative(),
    output_tokens: z.number().int().nonnegative(),
    total_tokens: z.number().int().nonnegative(),
    llm_latency_p50: z.number().nullable(),
    llm_latency_p95: z.number().nullable(),
    csat_response_count: z.number().int().nonnegative(),
    csat_positive_count: z.number().int().nonnegative(),
    csat_negative_count: z.number().int().nonnegative(),
  })
  .strict();

const DailyArmPointSchema = z
  .object({
    date: z.string(),
    arm: z.string(),
    ticket_count: z.number().int().nonnegative(),
    ai_end_to_end: z.number().int().nonnegative(),
  })
  .strict();

const DimensionArmCountSchema = z
  .object({
    value: z.string(),
    arm: z.string(),
    ticket_count: z.number().int().nonnegative(),
    ai_end_to_end: z.number().int().nonnegative(),
  })
  .strict();

export const AbTestSnapshotSchema = z
  .object({
    window_start: z.string(),
    window_end: z.string(),
    total_tickets: z.number().int().nonnegative(),
    unmatched_tickets: z.number().int().nonnegative(),
    csat_available: z.boolean(),
    arms: z.array(ArmMetricsSchema),
    daily: z.array(DailyArmPointSchema),
    dimensions: z.record(z.string(), z.array(DimensionArmCountSchema)),
  })
  .strict();

export type ArmMetrics = z.infer<typeof ArmMetricsSchema>;
export type DailyArmPoint = z.infer<typeof DailyArmPointSchema>;
export type DimensionArmCount = z.infer<typeof DimensionArmCountSchema>;
export type AbTestSnapshot = z.infer<typeof AbTestSnapshotSchema>;

export type SafeParseResult<T> =
  | { readonly ok: true; readonly data: T }
  | { readonly ok: false; readonly message: string };

export function parseAbTestSnapshot(
  value: unknown,
): SafeParseResult<AbTestSnapshot> {
  const parsed = AbTestSnapshotSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, message: "Không thể đọc dữ liệu AB test." };
  }
  return { ok: true, data: parsed.data };
}
