import { z } from "zod";

const nonNegativeInteger = z.number().int().nonnegative();
const positiveInteger = z.number().int().positive();
const nonNegativeNumber = z.number().finite().nonnegative();
const rate = z.number().finite().min(0).max(1);
const safeLabel = z.string().min(1).max(256);
const nullableSafeLabel = safeLabel.nullable();
const TicketIdSchema = z.string().regex(/^[1-9]\d{0,19}$/);
const tpeToken = z.string().refine(
  (value) => {
    const digits = value.startsWith("-") ? value.slice(1) : value;
    return (
      digits.length >= 1 &&
      digits.length <= 6 &&
      [...digits].every((character) => character >= "0" && character <= "9")
    );
  },
  { message: "Invalid exact-source TPE token." },
);
const labelKey = z.string().regex(/^[a-z0-9_-]{1,64}$/);

/**
 * `data_quality.counts` and the reopen maps are sparse on the wire:
 * `_validate_quality` and `_validate_reopen_reason` only reject *unknown*
 * labels, they never require the full label set. Zod 4 treats
 * `z.record(z.enum(...))` as exhaustive, so partial records are required here.
 */
const QualityLabelSchema = z.enum([
  "valid",
  "empty_or_technical",
  "malformed_output",
  "invalid_timestamp",
  "missing_trace_id",
  "missing_session_id",
  "missing_turn",
  "invalid_turn",
  "session_freshdesk_mismatch",
  "empty_session",
  "session_id_mismatch",
  "duplicate_turn",
  "missing_turn0",
  "no_turn_zero",
  "unknown_quality_issue",
]);
export type QualityLabel = z.infer<typeof QualityLabelSchema>;

function isMondayIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === (month ?? 1) - 1 &&
    parsed.getUTCDate() === day &&
    parsed.getUTCDay() === 1
  );
}

function isoWeekday(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }

  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== (month ?? 1) - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null;
  }

  const weekday = parsed.getUTCDay();
  return weekday === 0 ? 7 : weekday;
}

const WeekStringSchema = z.string().refine(isMondayIsoDate, {
  message: "Expected an ISO Monday cohort date.",
});

const IsoDateSchema = z.string().refine((value) => isoWeekday(value) !== null, {
  message: "Expected an ISO date.",
});

const UTC_DATE_TIME_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?Z$/;

function daysInMonth(year: number, month: number): number {
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return days[month - 1] ?? 0;
}

function isValidUtcDateTime(value: string): boolean {
  const match = UTC_DATE_TIME_PATTERN.exec(value);
  if (match === null) {
    return false;
  }
  const [, yearText, monthText, dayText, hourText, minuteText, secondText] =
    match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  return (
    year >= 1 &&
    year <= 9999 &&
    month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= daysInMonth(year, month) &&
    hour >= 0 &&
    hour <= 23 &&
    minute >= 0 &&
    minute <= 59 &&
    second >= 0 &&
    second <= 59
  );
}

const UtcDateTimeSchema = z
  .string()
  .regex(
    UTC_DATE_TIME_PATTERN,
    "Expected a UTC ISO timestamp.",
  )
  .refine(isValidUtcDateTime, {
    message: "Expected a valid UTC timestamp.",
  });

export const WeekDefinitionSchema = z.enum(["mon_sun", "mon_fri"]);
export type WeekDefinition = z.infer<typeof WeekDefinitionSchema>;

export const CohortStatusSchema = z.enum(["complete", "wtd"]);
export type CohortStatus = z.infer<typeof CohortStatusSchema>;

export const OutcomeSchema = z.enum([
  "ai_end_to_end",
  "ai_then_cs",
  "direct_cs",
  "unclassified",
]);
export type Outcome = z.infer<typeof OutcomeSchema>;

const ReopenOutcomeCountsSchema = z
  .object({
    ai_end_to_end: positiveInteger.optional(),
    ai_then_cs: positiveInteger.optional(),
  })
  .strict()
  .refine((value) => Object.keys(value).length > 0, {
    message: "A labeled reopen reason must contain at least one outcome.",
  });

const ReopenReasonSchema = z
  .object({
    // `null` is retained as a compatibility input for an early safe browser
    // payload. Current v4 snapshots normally provide a value such as "v1".
    labels_version: z.union([z.string().regex(/^v\d+$/), z.null()]),
    status: z.enum(["pending", "labeled", "unavailable"]),
    counts: z.record(labelKey, ReopenOutcomeCountsSchema),
    by_business: z.record(safeLabel, z.record(labelKey, positiveInteger)),
    coverage: z
      .object({
        population: nonNegativeInteger,
        labeled: nonNegativeInteger,
        abstained: nonNegativeInteger,
        failed: nonNegativeInteger,
        invalid: nonNegativeInteger,
      })
      .strict(),
    control: z
      .object({
        direct_cs_reopen_7d_rate: rate.nullable(),
        direct_cs_denominator: nonNegativeInteger,
      })
      .strict(),
  })
  .strict();

export const WeeklyReportRowSchema = z
  .object({
    cohort_week: WeekStringSchema,
    cohort_status: CohortStatusSchema,
    week_definition: WeekDefinitionSchema,
    has_data: z.boolean(),
    total_tickets: nonNegativeInteger,
    ai_first_count: nonNegativeInteger,
    ai_first_rate: rate,
    ai_end_to_end_count: nonNegativeInteger,
    ai_then_cs_count: nonNegativeInteger,
    direct_cs_count: nonNegativeInteger,
    unclassified_count: nonNegativeInteger,
    reopen_7d_rate: rate.nullable(),
    reopen_7d_denominator: nonNegativeInteger.nullable(),
    reopen_lifetime_rate: rate.nullable(),
    reopen_lifetime_numerator: nonNegativeInteger,
    reopen_lifetime_denominator: nonNegativeInteger,
    ai_reply_mean_ai_first: nonNegativeNumber.nullable(),
    ai_reply_p50: nonNegativeInteger.nullable(),
    ai_reply_p90: nonNegativeInteger.nullable(),
    ai_reply_max: nonNegativeInteger.nullable(),
    gt4_turn_with_cs: nonNegativeInteger,
    gt4_turn_without_cs: nonNegativeInteger,
    max_replies_rule_fired: nonNegativeInteger,
    as_of: UtcDateTimeSchema,
    reopen_reason: ReopenReasonSchema,
  })
  .strict();
export type WeeklyReportRow = z.infer<typeof WeeklyReportRowSchema>;

const SegmentCountsSchema = z
  .object({
    total: nonNegativeInteger,
    ai_first: nonNegativeInteger,
    transferred: nonNegativeInteger,
    reopen: nonNegativeInteger,
  })
  .strict();

const SegmentBucketsSchema = z.record(safeLabel, SegmentCountsSchema);

export const SegmentsSchema = z
  .object({
    issue_category: SegmentBucketsSchema,
    app: SegmentBucketsSchema,
    product_code: SegmentBucketsSchema,
    skill: SegmentBucketsSchema,
    intent: SegmentBucketsSchema,
    tpe: SegmentBucketsSchema,
    guardrail_rule: SegmentBucketsSchema,
    entry_point: SegmentBucketsSchema,
    model_core: SegmentBucketsSchema,
  })
  .strict();
export type Segments = z.infer<typeof SegmentsSchema>;

const GuardrailRuleSchema = z.enum([
  "cs_escalation",
  "empty_input",
  "empty_message_marker",
  "max_replies_exceeded",
  "missing_transaction_id",
  "off_topic_llm",
  "prompt_injection",
  "prompt_injection_llm",
  "off_topic",
  "system_prompt_leak",
  "tone_check_error",
]);

export const TransferTriggerReasonSchema = z.enum([
  "skill_suggested_transfer",
  "ai_response_requires_transfer",
  "missing_transaction_id",
  "max_replies_exceeded",
  "out_of_scope",
  "empty_message",
  "prompt_injection",
  "output_check_error",
  "other_guardrail",
  "unknown",
]);
export type TransferTriggerReason = z.infer<typeof TransferTriggerReasonSchema>;

const TransferTriggerSourceSchema = z.enum([
  "input_guardrail",
  "skill_guardrail_checked",
  "output_guardrail",
]);

function expectedTransferReason(
  rule: z.infer<typeof GuardrailRuleSchema>,
  source: z.infer<typeof TransferTriggerSourceSchema>,
  stage: "input" | "output" | null,
): z.infer<typeof TransferTriggerReasonSchema> {
  if (
    rule === "cs_escalation" &&
    source === "skill_guardrail_checked" &&
    stage === "output"
  ) {
    return "skill_suggested_transfer";
  }
  if (rule === "cs_escalation" && source === "output_guardrail") {
    return "ai_response_requires_transfer";
  }
  if (rule === "missing_transaction_id") return "missing_transaction_id";
  if (rule === "max_replies_exceeded") return "max_replies_exceeded";
  if (rule === "off_topic" || rule === "off_topic_llm") return "out_of_scope";
  if (rule === "empty_input" || rule === "empty_message_marker") {
    return "empty_message";
  }
  if (
    rule === "prompt_injection" ||
    rule === "prompt_injection_llm" ||
    rule === "system_prompt_leak"
  ) {
    return "prompt_injection";
  }
  if (rule === "tone_check_error") return "output_check_error";
  return "other_guardrail";
}

export const TransferReasonsSchema = z
  .object({
    observed_transfer_denominator: nonNegativeInteger,
    triggers: z.array(
      z
        .object({
          reason: TransferTriggerReasonSchema,
          rule: GuardrailRuleSchema.nullable(),
          source: TransferTriggerSourceSchema.nullable(),
          stage: z.enum(["input", "output"]).nullable(),
          skill: labelKey.nullable(),
          count: positiveInteger,
        })
        .strict(),
    ),
    step_result_missing: z
      .object({
        count: nonNegativeInteger,
        denominator: nonNegativeInteger,
      })
      .strict(),
    tpe: z.array(
      z
        .object({
          transstatus: tpeToken,
          step_result: tpeToken.nullable(),
          count: positiveInteger,
          // null = cap chua co trong taxonomy TPE.
          status: z.string().min(1).nullable(),
        })
        .strict(),
    ),
    guardrail: z.array(
      z
        .object({
          rule: GuardrailRuleSchema,
          count: positiveInteger,
        })
        .strict(),
    ),
    escalation_guard_blocked: z
      .object({
        count: nonNegativeInteger,
        denominator: nonNegativeInteger,
      })
      .strict(),
  })
  .strict()
  .superRefine((value, context) => {
    if (
      value.triggers.reduce((total, row) => total + row.count, 0) !==
      value.observed_transfer_denominator
    ) {
      context.addIssue({
        code: "custom",
        path: ["triggers"],
        message: "Transfer triggers must partition transferred tickets.",
      });
    }
    const seenTriggers = new Set<string>();
    value.triggers.forEach((row, index) => {
      const grain = JSON.stringify([
        row.reason,
        row.rule,
        row.source,
        row.stage,
        row.skill,
      ]);
      if (seenTriggers.has(grain)) {
        context.addIssue({
          code: "custom",
          path: ["triggers", index],
          message: "Duplicate transfer-trigger grain.",
        });
      }
      seenTriggers.add(grain);
      if (row.reason === "unknown") {
        if (
          row.rule !== null ||
          row.source !== null ||
          row.stage !== null ||
          row.skill !== null
        ) {
          context.addIssue({
            code: "custom",
            path: ["triggers", index],
            message: "Unknown transfer trigger cannot carry source metadata.",
          });
        }
        return;
      }
      if (row.rule === null || row.source === null) {
        context.addIssue({
          code: "custom",
          path: ["triggers", index],
          message: "Known transfer trigger requires rule and source.",
        });
        return;
      }
      if (
        row.source === "skill_guardrail_checked"
          ? row.stage === null
          : row.stage !== null || row.skill !== null
      ) {
        context.addIssue({
          code: "custom",
          path: ["triggers", index],
          message: "Transfer-trigger source metadata is inconsistent.",
        });
      }
      if (row.reason !== expectedTransferReason(row.rule, row.source, row.stage)) {
        context.addIssue({
          code: "custom",
          path: ["triggers", index, "reason"],
          message: "Transfer-trigger reason does not match its source.",
        });
      }
    });
    if (
      value.step_result_missing.denominator !==
      value.observed_transfer_denominator
    ) {
      context.addIssue({
        code: "custom",
        path: ["step_result_missing", "denominator"],
        message: "Step result denominator must match transferred tickets.",
      });
    }
    if (
      value.step_result_missing.count >
      value.step_result_missing.denominator
    ) {
      context.addIssue({
        code: "custom",
        path: ["step_result_missing", "count"],
        message: "Missing Step result count exceeds its denominator.",
      });
    }
    const seenTpeGrains = new Set<string>();
    value.tpe.forEach((row, index) => {
      const grain = JSON.stringify([row.transstatus, row.step_result]);
      if (seenTpeGrains.has(grain)) {
        context.addIssue({
          code: "custom",
          path: ["tpe", index],
          message: "Duplicate Transstatus and Step result grain.",
        });
      }
      seenTpeGrains.add(grain);
      if (row.count > value.observed_transfer_denominator) {
        context.addIssue({
          code: "custom",
          path: ["tpe", index, "count"],
          message: "TPE count exceeds transferred tickets.",
        });
      }
    });
    const seenGuardrailRules = new Set<string>();
    value.guardrail.forEach((row, index) => {
      if (seenGuardrailRules.has(row.rule)) {
        context.addIssue({
          code: "custom",
          path: ["guardrail", index, "rule"],
          message: "Duplicate guardrail rule.",
        });
      }
      seenGuardrailRules.add(row.rule);
      if (row.count > value.observed_transfer_denominator) {
        context.addIssue({
          code: "custom",
          path: ["guardrail", index, "count"],
          message: "Guardrail count exceeds transferred tickets.",
        });
      }
    });
    if (
      value.escalation_guard_blocked.denominator !==
      value.observed_transfer_denominator
    ) {
      context.addIssue({
        code: "custom",
        path: ["escalation_guard_blocked", "denominator"],
        message: "Escalation denominator must match transferred tickets.",
      });
    }
    if (
      value.escalation_guard_blocked.count >
      value.escalation_guard_blocked.denominator
    ) {
      context.addIssue({
        code: "custom",
        path: ["escalation_guard_blocked", "count"],
        message: "Escalation count exceeds its denominator.",
      });
    }
  });
export type TransferReasons = z.infer<typeof TransferReasonsSchema>;

function segmentTransferTotalsMatch(
  segments: Segments,
  denominator: number,
): boolean {
  return Object.values(segments).every(
    (buckets) =>
      Object.values(buckets).reduce(
        (total, row) => total + row.transferred,
        0,
      ) === denominator,
  );
}

const ByWeekDetailSchema = z
  .object({
    segments: SegmentsSchema,
    transfer_reasons: TransferReasonsSchema,
  })
  .strict()
  .superRefine((value, context) => {
    if (
      !segmentTransferTotalsMatch(
        value.segments,
        value.transfer_reasons.observed_transfer_denominator,
      )
    ) {
      context.addIssue({
        code: "custom",
        path: ["transfer_reasons", "observed_transfer_denominator"],
        message: "Transfer denominator does not reconcile with segments.",
      });
    }
  });

const SamePeriodWeekSchema = z
  .object({
    cohort_week: WeekStringSchema,
    total_tickets: nonNegativeInteger,
    ai_first_count: nonNegativeInteger,
    ai_first_rate: rate,
    reopen_lifetime_rate: rate.nullable(),
    reopen_lifetime_numerator: nonNegativeInteger,
    reopen_lifetime_denominator: nonNegativeInteger,
  })
  .strict()
  .superRefine((value, context) => {
    if (value.ai_first_count > value.total_tickets) {
      context.addIssue({
        code: "custom",
        path: ["ai_first_count"],
        message: "AI First count exceeds total tickets.",
      });
    }
    const expectedAiRate =
      value.total_tickets === 0 ? 0 : value.ai_first_count / value.total_tickets;
    if (Math.abs(value.ai_first_rate - expectedAiRate) > 1e-12) {
      context.addIssue({
        code: "custom",
        path: ["ai_first_rate"],
        message: "AI First rate must match count divided by total.",
      });
    }
    if (value.reopen_lifetime_numerator > value.reopen_lifetime_denominator) {
      context.addIssue({
        code: "custom",
        path: ["reopen_lifetime_numerator"],
        message: "Reopen numerator exceeds denominator.",
      });
    }
    const expectedReopenRate =
      value.reopen_lifetime_denominator === 0
        ? null
        : value.reopen_lifetime_numerator / value.reopen_lifetime_denominator;
    if (
      (expectedReopenRate === null) !== (value.reopen_lifetime_rate === null) ||
      (expectedReopenRate !== null &&
        value.reopen_lifetime_rate !== null &&
        Math.abs(value.reopen_lifetime_rate - expectedReopenRate) > 1e-12)
    ) {
      context.addIssue({
        code: "custom",
        path: ["reopen_lifetime_rate"],
        message: "Reopen lifetime rate must match numerator divided by denominator.",
      });
    }
  });
export type SamePeriodWeek = z.infer<typeof SamePeriodWeekSchema>;

const SamePeriodSchema = z
  .object({
    cutoff_date: IsoDateSchema,
    cutoff_weekday: z.number().int().min(1).max(7),
    current: SamePeriodWeekSchema,
    baseline: z
      .object({
        weeks_used: z.number().int().min(2).max(4),
        ai_first_rate: rate,
        reopen_lifetime_rate: rate.nullable(),
      })
      .strict(),
    by_week: z.record(WeekStringSchema, SamePeriodWeekSchema),
  })
  .strict()
  .superRefine((value, context) => {
    if (isoWeekday(value.cutoff_date) !== value.cutoff_weekday) {
      context.addIssue({
        code: "custom",
        path: ["cutoff_weekday"],
        message: "Cutoff weekday must match cutoff date.",
      });
    }
    if (!Object.hasOwn(value.by_week, value.current.cohort_week)) {
      context.addIssue({
        code: "custom",
        path: ["by_week", value.current.cohort_week],
        message: "same_period.by_week must include the running week.",
      });
    } else {
      const currentRow = value.by_week[value.current.cohort_week];
      if (
        currentRow !== undefined &&
        (
          [
            "cohort_week",
            "total_tickets",
            "ai_first_count",
            "ai_first_rate",
            "reopen_lifetime_rate",
            "reopen_lifetime_numerator",
            "reopen_lifetime_denominator",
          ] as const
        ).some((field) => currentRow[field] !== value.current[field])
      ) {
        context.addIssue({
          code: "custom",
          path: ["current"],
          message: "same_period.current must match its by_week row.",
        });
      }
    }
    for (const [cohortWeek, summary] of Object.entries(value.by_week)) {
      if (summary.cohort_week !== cohortWeek) {
        context.addIssue({
          code: "custom",
          path: ["by_week", cohortWeek],
          message: "same_period.by_week key must match its summary cohort_week.",
        });
      }
      if (cohortWeek > value.current.cohort_week) {
        context.addIssue({
          code: "custom",
          path: ["by_week", cohortWeek],
          message: "same_period.by_week cannot extend past the running week.",
        });
      }
    }

    const contributors = Object.entries(value.by_week)
      .filter(
        ([cohortWeek, summary]) =>
          cohortWeek < value.current.cohort_week && summary.total_tickets > 0,
      )
      .sort(([left], [right]) => left.localeCompare(right))
      .slice(-4)
      .map(([, summary]) => summary);
    if (contributors.length !== value.baseline.weeks_used) {
      context.addIssue({
        code: "custom",
        path: ["baseline", "weeks_used"],
        message: "same_period baseline contributor count is inconsistent.",
      });
      return;
    }

    const expectedAiRate =
      contributors.reduce((sum, summary) => sum + summary.ai_first_rate, 0) /
      contributors.length;
    if (Math.abs(value.baseline.ai_first_rate - expectedAiRate) > 1e-12) {
      context.addIssue({
        code: "custom",
        path: ["baseline", "ai_first_rate"],
        message: "same_period baseline AI First rate is inconsistent.",
      });
    }
    const reopenRates = contributors.flatMap((summary) =>
      summary.reopen_lifetime_rate === null
        ? []
        : [summary.reopen_lifetime_rate],
    );
    const expectedReopenRate =
      reopenRates.length === 0
        ? null
        : reopenRates.reduce((sum, current) => sum + current, 0) /
          reopenRates.length;
    if (
      (value.baseline.reopen_lifetime_rate === null) !==
        (expectedReopenRate === null) ||
      (value.baseline.reopen_lifetime_rate !== null &&
        expectedReopenRate !== null &&
        Math.abs(
          value.baseline.reopen_lifetime_rate - expectedReopenRate,
        ) > 1e-12)
    ) {
      context.addIssue({
        code: "custom",
        path: ["baseline", "reopen_lifetime_rate"],
        message: "same_period baseline reopen rate is inconsistent.",
      });
    }
  });
export type SamePeriod = z.infer<typeof SamePeriodSchema>;

const VIETNAMESE_FAMILY_NAMES = new Set([
  "nguyễn", "nguyen", "trần", "tran", "lê", "le", "phạm", "pham",
  "hoàng", "hoang", "huỳnh", "huynh", "vũ", "vu", "võ", "vo",
  "đặng", "dang", "bùi", "bui", "đỗ", "do", "hồ", "ho", "ngô",
  "ngo", "dương", "duong", "lý", "ly",
]);
const VIETNAMESE_NAME_MIDDLES = new Set(["văn", "van", "thị", "thi"]);
const UNSAFE_FEEDBACK_PHONE = /(?:^|\D)(?:0|84|\+84)[0-9]{8,10}(?:$|\D)/u;
const UNSAFE_FEEDBACK_UUID =
  /[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/iu;
const UNSAFE_FEEDBACK_EMAIL = /[^\s@]+@[^\s@]+\.[^\s@]+/u;
const UNSAFE_FEEDBACK_URL =
  /(?:https?:\/\/|www\.)\S+|(?:mailto|tel|sms|data|javascript|geo|urn):\S+|(?:^|[^\w@])(?:[^\W_](?:[\w-]{0,61}[^\W_])?\.)+[^\W\d_]{2,63}(?::\d{1,5})?(?:[/?#]\S*)?/iu;
const UNSAFE_FEEDBACK_CONTROL = /\p{C}/u;
const UNSAFE_FEEDBACK_LONG_NUMBER = /\p{Nd}{6}/u;

function looksLikeVietnamesePersonalName(value: string): boolean {
  const parts = value
    .normalize("NFC")
    .trim()
    .toLocaleLowerCase("vi")
    .split(/\s+/u);
  return (
    parts.length === 3 &&
    VIETNAMESE_FAMILY_NAMES.has(parts[0] ?? "") &&
    VIETNAMESE_NAME_MIDDLES.has(parts[1] ?? "") &&
    /^\p{L}{1,32}$/u.test(parts[2] ?? "")
  );
}

function containsUnsafeFeedbackText(value: string): boolean {
  const normalized = value.normalize("NFC").trim();
  return (
    normalized.length === 0 ||
    UNSAFE_FEEDBACK_PHONE.test(normalized) ||
    UNSAFE_FEEDBACK_UUID.test(normalized) ||
    UNSAFE_FEEDBACK_EMAIL.test(normalized) ||
    UNSAFE_FEEDBACK_URL.test(normalized) ||
    UNSAFE_FEEDBACK_CONTROL.test(normalized) ||
    UNSAFE_FEEDBACK_LONG_NUMBER.test(normalized) ||
    looksLikeVietnamesePersonalName(normalized)
  );
}

const safeFeedbackText = z
  .string()
  .min(1)
  .max(200)
  .refine(
    (value) => !containsUnsafeFeedbackText(value),
    { message: "CSAT feedback text contains unsafe identifying content." },
  );

const CsatOutcomeCountsSchema = z
  .object({
    ticket_count: nonNegativeInteger,
    positive: nonNegativeInteger,
    neutral: nonNegativeInteger,
    negative: nonNegativeInteger,
  })
  .strict()
  .refine(
    (value) =>
      value.ticket_count === value.positive + value.neutral + value.negative,
    { message: "CSAT outcome buckets must reconcile." },
  );

const CsatDimensionCountsSchema = z
  .object({
    value: safeLabel,
    ticket_count: nonNegativeInteger,
    positive: nonNegativeInteger,
    neutral: nonNegativeInteger,
    negative: nonNegativeInteger,
  })
  .strict()
  .refine(
    (value) =>
      value.ticket_count === value.positive + value.neutral + value.negative,
    { message: "CSAT dimension buckets must reconcile." },
  );

export const CsatFeedbackEntrySchema = z
  .object({
    ticket_id: TicketIdSchema,
    responded_at: UtcDateTimeSchema,
    satisfaction_bucket: z.enum(["positive", "neutral", "negative"]),
    outcome: OutcomeSchema,
    skill: safeLabel,
    issue_category: safeLabel,
    text: safeFeedbackText,
    response_number: positiveInteger,
    response_total: positiveInteger,
    is_latest_for_ticket: z.boolean(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.response_number > value.response_total) {
      context.addIssue({
        code: "custom",
        path: ["response_number"],
        message: "CSAT response number exceeds total.",
      });
    }
    if (
      value.is_latest_for_ticket !==
      (value.response_number === value.response_total)
    ) {
      context.addIssue({
        code: "custom",
        path: ["is_latest_for_ticket"],
        message: "CSAT latest marker is inconsistent.",
      });
    }
  });
export type CsatFeedbackEntry = z.infer<typeof CsatFeedbackEntrySchema>;

export const CsatWeekSchema = z
  .object({
    response_count: nonNegativeInteger,
    ticket_count: nonNegativeInteger,
    positive: nonNegativeInteger,
    neutral: nonNegativeInteger,
    negative: nonNegativeInteger,
    by_outcome: z
      .object({
        ai_end_to_end: CsatOutcomeCountsSchema,
        ai_then_cs: CsatOutcomeCountsSchema,
        direct_cs: CsatOutcomeCountsSchema,
        unclassified: CsatOutcomeCountsSchema,
      })
      .strict(),
    by_dimension: z
      .object({
        skill: z.array(CsatDimensionCountsSchema),
        issue_category: z.array(CsatDimensionCountsSchema),
      })
      .strict(),
    response_by_outcome: z
      .object({
        ai_end_to_end: CsatOutcomeCountsSchema,
        ai_then_cs: CsatOutcomeCountsSchema,
        direct_cs: CsatOutcomeCountsSchema,
        unclassified: CsatOutcomeCountsSchema,
      })
      .strict()
      .optional(),
    response_by_dimension: z
      .object({
        skill: z.array(CsatDimensionCountsSchema),
        issue_category: z.array(CsatDimensionCountsSchema),
      })
      .strict()
      .optional(),
    feedback_entries: z.array(CsatFeedbackEntrySchema),
  })
  .strict()
  .superRefine((value, context) => {
    if (
      value.ticket_count !== value.positive + value.neutral + value.negative
    ) {
      context.addIssue({
        code: "custom",
        path: ["ticket_count"],
        message: "CSAT ticket buckets must reconcile to the ticket count.",
      });
    }
    if (value.ticket_count > value.response_count) {
      context.addIssue({
        code: "custom",
        path: ["ticket_count"],
        message: "CSAT ticket count exceeds the response count.",
      });
    }
    if (value.feedback_entries.length > value.response_count) {
      context.addIssue({
        code: "custom",
        path: ["feedback_entries"],
        message: "CSAT feedback count exceeds the response count.",
      });
    }
    const countKeys = ["ticket_count", "positive", "neutral", "negative"] as const;
    for (const key of countKeys) {
      const outcomeTotal = Object.values(value.by_outcome).reduce(
        (total, row) => total + row[key],
        0,
      );
      if (outcomeTotal !== value[key]) {
        context.addIssue({
          code: "custom",
          path: ["by_outcome"],
          message: `CSAT outcome ${key} does not reconcile.`,
        });
      }
    }
    for (const dimension of ["skill", "issue_category"] as const) {
      const rows = value.by_dimension[dimension];
      const labels = new Set(rows.map((row) => row.value));
      if (labels.size !== rows.length) {
        context.addIssue({
          code: "custom",
          path: ["by_dimension", dimension],
          message: "CSAT dimension values must be unique.",
        });
      }
      for (const key of countKeys) {
        if (rows.reduce((total, row) => total + row[key], 0) !== value[key]) {
          context.addIssue({
            code: "custom",
            path: ["by_dimension", dimension],
            message: `CSAT dimension ${key} does not reconcile.`,
          });
        }
      }
    }
    const metadataByTicket = new Map<string, string>();
    const numbersByTicket = new Map<string, Set<number>>();
    for (const entry of value.feedback_entries) {
      const metadata = JSON.stringify([
        entry.response_total,
        entry.outcome,
        entry.skill,
        entry.issue_category,
      ]);
      const existing = metadataByTicket.get(entry.ticket_id);
      if (existing !== undefined && existing !== metadata) {
        context.addIssue({
          code: "custom",
          path: ["feedback_entries"],
          message: "CSAT feedback ticket metadata is inconsistent.",
        });
      }
      metadataByTicket.set(entry.ticket_id, metadata);
      const numbers = numbersByTicket.get(entry.ticket_id) ?? new Set<number>();
      if (numbers.has(entry.response_number)) {
        context.addIssue({
          code: "custom",
          path: ["feedback_entries"],
          message: "CSAT response number is duplicated.",
        });
      }
      numbers.add(entry.response_number);
      numbersByTicket.set(entry.ticket_id, numbers);
    }
  });
export type CsatWeek = z.infer<typeof CsatWeekSchema>;

export const CsatSchema = z
  .object({
    source: z.literal("freshdesk"),
    fetched_at: UtcDateTimeSchema,
    by_week: z.record(WeekStringSchema, CsatWeekSchema),
  })
  .strict();
export type Csat = z.infer<typeof CsatSchema>;

const OutcomeReconciliationWeekSchema = z
  .object({
    langfuse_ai_end_to_end: nonNegativeInteger,
    checked_ticket_count: nonNegativeInteger,
    human_replied_after_ai: nonNegativeInteger,
    unresolved_ticket_count: nonNegativeInteger,
    mismatch_rate: rate.nullable(),
  })
  .strict()
  .superRefine((value, context) => {
    if (
      value.checked_ticket_count + value.unresolved_ticket_count >
        value.langfuse_ai_end_to_end ||
      value.human_replied_after_ai > value.checked_ticket_count
    ) {
      context.addIssue({
        code: "custom",
        message: "Outcome reconciliation counts do not reconcile.",
      });
    }
    const expectedRate =
      value.checked_ticket_count === 0
        ? null
        : value.human_replied_after_ai / value.checked_ticket_count;
    if (
      (expectedRate === null && value.mismatch_rate !== null) ||
      (expectedRate !== null &&
        (value.mismatch_rate === null ||
          Math.abs(value.mismatch_rate - expectedRate) > 1e-12))
    ) {
      context.addIssue({
        code: "custom",
        path: ["mismatch_rate"],
        message: "Outcome reconciliation rate does not reconcile.",
      });
    }
  });
export type OutcomeReconciliationWeek = z.infer<
  typeof OutcomeReconciliationWeekSchema
>;

export const OutcomeReconciliationSchema = z
  .object({
    source: z.literal("freshdesk"),
    fetched_at: UtcDateTimeSchema,
    by_week: z.record(WeekStringSchema, OutcomeReconciliationWeekSchema),
  })
  .strict();
export type OutcomeReconciliation = z.infer<
  typeof OutcomeReconciliationSchema
>;

export const EntryCoverageStatusSchema = z.enum([
  "ai_replied_only",
  "ai_replied_then_transferred",
  "transferred_without_ai_reply",
  "invoked_no_result",
  "not_observed_invoked",
  "unresolved",
]);
export type EntryCoverageStatus = z.infer<typeof EntryCoverageStatusSchema>;

const EntryCoverageWeekSchema = z
  .object({
    freshdesk_ticket_count: nonNegativeInteger,
    ai_replied_only: nonNegativeInteger,
    ai_replied_then_transferred: nonNegativeInteger,
    transferred_without_ai_reply: nonNegativeInteger,
    invoked_no_result: nonNegativeInteger,
    not_observed_invoked: nonNegativeInteger,
    not_observed_human_replied: nonNegativeInteger,
    not_observed_no_human_reply: nonNegativeInteger,
    unresolved: nonNegativeInteger,
  })
  .strict()
  .superRefine((value, context) => {
    const statusTotal =
      value.ai_replied_only +
      value.ai_replied_then_transferred +
      value.transferred_without_ai_reply +
      value.invoked_no_result +
      value.not_observed_invoked +
      value.unresolved;
    if (statusTotal !== value.freshdesk_ticket_count) {
      context.addIssue({
        code: "custom",
        path: ["freshdesk_ticket_count"],
        message: "Freshdesk entry statuses must reconcile.",
      });
    }
    if (
      value.not_observed_invoked !==
      value.not_observed_human_replied + value.not_observed_no_human_reply
    ) {
      context.addIssue({
        code: "custom",
        path: ["not_observed_invoked"],
        message: "Freshdesk no-call subcounts must reconcile.",
      });
    }
  });

export const EntryCoverageSchema = z
  .object({
    source: z.literal("freshdesk"),
    source_start_week: z.literal("2026-07-06"),
    fetched_at: UtcDateTimeSchema,
    by_week: z.record(WeekStringSchema, EntryCoverageWeekSchema),
  })
  .strict();
export type EntryCoverage = z.infer<typeof EntryCoverageSchema>;

export const DashboardViewSchema = z
  .object({
    totals: z
      .object({
        eligible_ticket_count: nonNegativeInteger,
        transfer_total: nonNegativeInteger,
        gt4_turn_total: nonNegativeInteger,
        weekend_start_count: nonNegativeInteger,
      })
      .strict(),
    outcomes: z
      .object({
        ai_end_to_end: nonNegativeInteger,
        ai_then_cs: nonNegativeInteger,
        direct_cs: nonNegativeInteger,
        unclassified: nonNegativeInteger,
      })
      .strict(),
    ai_first: z
      .object({
        count: nonNegativeInteger,
        rate,
      })
      .strict(),
    reopen: z
      .object({
        lifetime: z
          .object({
            numerator: nonNegativeInteger,
            denominator: nonNegativeInteger,
          })
          .strict(),
        within_7d: z
          .object({
            numerator: nonNegativeInteger,
            denominator: nonNegativeInteger,
          })
          .strict(),
      })
      .strict(),
    weekly: z.array(WeeklyReportRowSchema),
    segments: SegmentsSchema,
    transfer_reasons: TransferReasonsSchema,
    by_week: z.record(WeekStringSchema, ByWeekDetailSchema),
    same_period: SamePeriodSchema.nullable(),
    csat: CsatSchema.nullable(),
    outcome_reconciliation: OutcomeReconciliationSchema.nullable(),
    entry_coverage: EntryCoverageSchema.nullable(),
    rule_gt4: z
      .object({
        gt4_turn_total: nonNegativeInteger,
        gt4_turn_with_cs: nonNegativeInteger,
        gt4_turn_without_cs: nonNegativeInteger,
        max_replies_rule_fired: nonNegativeInteger,
      })
      .strict(),
  })
  .strict()
  .superRefine((view, context) => {
    if (
      !segmentTransferTotalsMatch(
        view.segments,
        view.transfer_reasons.observed_transfer_denominator,
      )
    ) {
      context.addIssue({
        code: "custom",
        message: "Transfer denominator does not reconcile with segments.",
        path: ["transfer_reasons", "observed_transfer_denominator"],
      });
    }
    const weeklyKeys = new Set(view.weekly.map((row) => row.cohort_week));
    const byWeekKeys = new Set(Object.keys(view.by_week));

    for (const cohortWeek of weeklyKeys) {
      if (!byWeekKeys.has(cohortWeek)) {
        context.addIssue({
          code: "custom",
          message: "Missing detail for weekly cohort.",
          path: ["by_week", cohortWeek],
        });
      }
    }
    for (const cohortWeek of byWeekKeys) {
      if (!weeklyKeys.has(cohortWeek)) {
        context.addIssue({
          code: "custom",
          message: "Unexpected detail outside weekly cohorts.",
          path: ["by_week", cohortWeek],
        });
      }
    }
    if (view.same_period !== null) {
      const currentWeek = view.weekly.find(
        (row) => row.cohort_week === view.same_period?.current.cohort_week,
      );
      if (currentWeek?.cohort_status !== "wtd") {
        context.addIssue({
          code: "custom",
          message: "same_period.current must identify the running weekly cohort.",
          path: ["same_period", "current", "cohort_week"],
        });
      }
      for (const cohortWeek of Object.keys(view.same_period.by_week)) {
        if (!byWeekKeys.has(cohortWeek)) {
          context.addIssue({
            code: "custom",
            message: "same_period.by_week must stay inside the view by_week map.",
            path: ["same_period", "by_week", cohortWeek],
          });
        }
      }
    }
    if (view.csat !== null) {
      for (const cohortWeek of Object.keys(view.csat.by_week)) {
        if (!weeklyKeys.has(cohortWeek)) {
          context.addIssue({
            code: "custom",
            message: "CSAT weeks must stay inside the dashboard view.",
            path: ["csat", "by_week", cohortWeek],
          });
        }
      }
    }
    if (view.outcome_reconciliation !== null) {
      for (const [cohortWeek, row] of Object.entries(
        view.outcome_reconciliation.by_week,
      )) {
        if (!weeklyKeys.has(cohortWeek)) {
          context.addIssue({
            code: "custom",
            message: "Outcome reconciliation weeks must stay inside the dashboard view.",
            path: ["outcome_reconciliation", "by_week", cohortWeek],
          });
          continue;
        }
        const weekly = view.weekly.find(
          (item) => item.cohort_week === cohortWeek,
        );
        if (
          weekly === undefined ||
          row.langfuse_ai_end_to_end > weekly.ai_end_to_end_count
        ) {
          context.addIssue({
            code: "custom",
            message: "Outcome reconciliation population does not reconcile.",
            path: ["outcome_reconciliation", "by_week", cohortWeek],
          });
        }
      }
    }
  });
export type DashboardView = z.infer<typeof DashboardViewSchema>;

export const DashboardSnapshotSchema = z
  .object({
    generated_at: UtcDateTimeSchema,
    source: z
      .object({
        traces_fetched: nonNegativeInteger,
        traces_deduplicated: nonNegativeInteger,
        observations_fetched: nonNegativeInteger,
      })
      .strict(),
    enrichment_status: z.enum(["complete", "partial"]),
    data_range: z
      .object({
        first_week_with_data: WeekStringSchema.nullable(),
        weeks_without_data: z.array(WeekStringSchema),
      })
      .strict(),
    views: z
      .object({
        mon_sun: DashboardViewSchema,
        mon_fri: DashboardViewSchema,
      })
      .strict(),
    coverage: z
      .object({
        issue_category: rate,
        app: rate,
        tpe: rate,
        intent: rate,
        skill: rate,
      })
      .strict(),
    unmapped_tpe_codes: z.array(
      z
        .object({
          code: safeLabel,
          status: z.string().max(256),
          count: nonNegativeInteger,
        })
        .strict(),
    ).max(0),
    gate_status: z
      .object({
        allowed: z.boolean(),
        structural_invalid_rate: rate,
        reasons: z.array(z.enum(["structural_invalid_rate_gt_5pct"])),
      })
      .strict(),
    data_quality: z
      .object({
        counts: z.partialRecord(QualityLabelSchema, nonNegativeInteger),
        weekend_start_count: nonNegativeInteger,
        left_censored_count: nonNegativeInteger,
        pre_window_start_count: nonNegativeInteger,
        invalid_keyed_session_count: nonNegativeInteger,
        unkeyed_trace_count: nonNegativeInteger,
      })
      .strict(),
  })
  .strict();
export type DashboardSnapshot = z.infer<typeof DashboardSnapshotSchema>;

export const DashboardEnvelopeSchema = z
  .object({
    status: z.enum(["loading", "refreshing", "ready", "stale_error"]),
    refreshing: z.boolean(),
    last_error_code: z.string().max(128).nullable(),
    last_error_at: UtcDateTimeSchema.nullable(),
    snapshot: DashboardSnapshotSchema.nullable(),
  })
  .strict();
export type DashboardEnvelope = z.infer<typeof DashboardEnvelopeSchema>;

export const TicketRowSchema = z
  .object({
    ticket_id: TicketIdSchema,
    opened_at: UtcDateTimeSchema,
    cohort_week: WeekStringSchema,
    cohort_status: CohortStatusSchema,
    is_weekend_start: z.boolean(),
    outcome: OutcomeSchema,
    ai_first: z.boolean(),
    transferred: z.boolean(),
    reopen_lifetime: z.union([z.literal(0), z.literal(1), z.null()]),
    reopen_within_7d: z.union([z.literal(0), z.literal(1), z.null()]),
    ai_reply_count: nonNegativeInteger,
    turn_count: positiveInteger,
    gt4_turn: z.boolean(),
    issue_category: safeLabel,
    app: safeLabel,
    product_code: safeLabel,
    skill: nullableSafeLabel,
    intent: z.union([labelKey, z.literal("khác")]).nullable(),
    tpe_code: tpeToken.nullable(),
    tpe_status: z.null(),
    guardrail_rule: nullableSafeLabel,
    transfer_reason: TransferTriggerReasonSchema.nullable(),
    escalation_guard_blocked: z.boolean(),
    csat_satisfaction: z
      .enum(["positive", "neutral", "negative", "unrated"])
      .nullable(),
    data_quality: QualityLabelSchema,
    model_core: nullableSafeLabel,
  })
  .strict()
  .superRefine((row, context) => {
    if (row.transferred && row.transfer_reason === null) {
      context.addIssue({
        code: "custom",
        path: ["transfer_reason"],
        message: "Transferred tickets require a transfer reason.",
      });
    }
    if (!row.transferred && row.transfer_reason !== null) {
      context.addIssue({
        code: "custom",
        path: ["transfer_reason"],
        message: "Tickets not transferred cannot have a transfer reason.",
      });
    }
  });
export type TicketRow = z.infer<typeof TicketRowSchema>;

export const TicketPageSchema = z
  .object({
    items: z.array(TicketRowSchema),
    page: positiveInteger,
    page_size: positiveInteger.max(100),
    total: nonNegativeInteger,
  })
  .strict();
export type TicketPage = z.infer<typeof TicketPageSchema>;

export const EntryCoverageTicketSchema = z
  .object({
    ticket_id: TicketIdSchema,
    opened_at: UtcDateTimeSchema,
    cohort_week: WeekStringSchema,
    status: EntryCoverageStatusSchema,
    human_replied: z.boolean().nullable(),
  })
  .strict();
export type EntryCoverageTicket = z.infer<typeof EntryCoverageTicketSchema>;

export const EntryCoverageTicketPageSchema = z
  .object({
    items: z.array(EntryCoverageTicketSchema),
    page: positiveInteger,
    page_size: positiveInteger.max(100),
    total: nonNegativeInteger,
  })
  .strict();
export type EntryCoverageTicketPage = z.infer<
  typeof EntryCoverageTicketPageSchema
>;

export type SafeParseResult<T> =
  | { readonly ok: true; readonly data: T }
  | { readonly ok: false; readonly message: string };

export function parseDashboardEnvelope(value: unknown): SafeParseResult<DashboardEnvelope> {
  const parsed = DashboardEnvelopeSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, message: "Không thể đọc dữ liệu dashboard." };
  }
  return { ok: true, data: parsed.data };
}

export function parseTicketPage(value: unknown): SafeParseResult<TicketPage> {
  const parsed = TicketPageSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, message: "Không thể đọc dữ liệu Ticket Explorer." };
  }
  return { ok: true, data: parsed.data };
}

export function parseEntryCoverageTicketPage(
  value: unknown,
): SafeParseResult<EntryCoverageTicketPage> {
  const parsed = EntryCoverageTicketPageSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, message: "Không thể đọc dữ liệu độ phủ Freshdesk." };
  }
  return { ok: true, data: parsed.data };
}
