import { describe, expect, it } from "vitest";

import { buildDeterministicNarrative } from "../src/lib/narrative";
import { selectTransferSignals } from "../src/lib/selectors";

describe("deterministic narrative", () => {
  it("formats rates and deltas without calling an LLM", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 1_374, rate: 0.798 }, reopenRate: 0.262 },
      previous: { aiFirst: { count: 1_220, rate: 0.766 }, reopenRate: 0.266 },
      transferSignals: [
        { label: "Transstatus -365 / Step result -1013", count: 622 },
      ],
      transferDenominator: 1_000,
      gt4TurnWithoutCs: 11,
      enrichmentStatus: "complete",
    });

    expect(narrative).toEqual([
      "AI First tăng 3,2 điểm so với tuần trước.",
      "Reopen sau AI First gần như không đổi so với tuần trước.",
      "Tín hiệu chuyển CS nổi bật: Transstatus -365 / Step result -1013 62,2% — tính trên 1.000 ticket đã chuyển CS.",
      "11 ticket có hơn 3 lượt xử lý mà chưa chuyển CS — khách nhiều khả năng đang mắc kẹt.",
    ]);
  });

  it("test_transfer_signals_show_share_not_only_count", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 591, rate: 0.79 }, reopenRate: 0.196 },
      previous: null,
      transferSignals: [
        { label: "Transstatus -365 / Step result -1013", count: 838 },
        { label: "Transstatus -217", count: 547 },
        { label: "Transstatus 1 / Step result 1", count: 46 },
      ],
      transferDenominator: 1_599,
      gt4TurnWithoutCs: 0,
      enrichmentStatus: "complete",
    } as Parameters<typeof buildDeterministicNarrative>[0]);

    // The reader is weighing reasons against each other, so the comparable
    // quantity is the share. A bare count made them divide by a denominator
    // the sentence never gave them.
    const signalLine = narrative.find((line) =>
      line.startsWith("Tín hiệu chuyển CS"),
    );
    expect(signalLine).toBe(
      "Tín hiệu chuyển CS nổi bật: Transstatus -365 / Step result -1013 52,4%, " +
        "Transstatus -217 34,2%, Transstatus 1 / Step result 1 2,9% — " +
        "tính trên 1.599 ticket đã chuyển CS.",
    );
  });

  it("omits the transfer line when no ticket was transferred", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 10, rate: 1 }, reopenRate: 0 },
      previous: null,
      transferSignals: [{ label: "missing_transaction_id", count: 3 }],
      transferDenominator: 0,
      gt4TurnWithoutCs: 0,
      enrichmentStatus: "complete",
    } as Parameters<typeof buildDeterministicNarrative>[0]);

    // A share needs a denominator. Rather than print an undefined percentage,
    // the sentence is dropped.
    expect(narrative.join(" ")).not.toContain("Tín hiệu chuyển CS");
  });

  it("test_narrative_has_no_methodological_advice_strings", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 8, rate: 0.8 }, reopenRate: null },
      previous: null,
      transferSignals: [],
      transferDenominator: 0,
      gt4TurnWithoutCs: 0,
      enrichmentStatus: "partial",
      isWtd: true,
    });

    expect(narrative.join(" ")).not.toMatch(/80,0%|8 ticket|Reopen sau AI First —/);
    expect(narrative).toContain(
      "Lần đọc này chưa lấy đủ dữ liệu phụ từ Langfuse, nên Intent, Skill, Transstatus và Step result còn thiếu.",
    );
    expect(narrative.join(" ")).not.toMatch(
      /Cần lưu ý|đừng suy rộng|không tự suy luận nguyên nhân|chỉ chẩn đoán trên phần dữ liệu quan sát được|tuần đang chạy nên chưa so với tuần đủ/i,
    );
  });

  it("uses same-period baselines for a running week when they are available", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 627, rate: 0.78 }, reopenRate: 0.188 },
      previous: { aiFirst: { count: 900, rate: 0.82 }, reopenRate: 0.19 },
      transferSignals: [],
      transferDenominator: 0,
      gt4TurnWithoutCs: 0,
      enrichmentStatus: "complete",
      isWtd: true,
      samePeriod: {
        cutoffWeekday: 3,
        weeksUsed: 4,
        aiFirstRate: 0.742,
        reopenRate: 0.215,
      },
    } as Parameters<typeof buildDeterministicNarrative>[0]);

    expect(narrative[0]).toBe(
      "AI First tăng 3,8 điểm so với trung bình cùng kỳ 4 tuần trước.",
    );
    expect(narrative[1]).toBe(
      "Reopen sau AI First giảm 2,7 điểm so với trung bình cùng kỳ 4 tuần trước.",
    );
  });

  it("caps the first-viewport narrative at four sentences and keeps action warnings", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 987, rate: 0.712 }, reopenRate: 0.318 },
      previous: { aiFirst: { count: 1_104, rate: 0.776 }, reopenRate: 0.241 },
      transferSignals: [
        { label: "missing_transaction_id", count: 220 },
        { label: "max_replies_exceeded", count: 90 },
      ],
      transferDenominator: 400,
      gt4TurnWithoutCs: 7,
      enrichmentStatus: "partial",
    });

    expect(narrative.length).toBeGreaterThanOrEqual(2);
    expect(narrative.length).toBeLessThanOrEqual(4);
    expect(narrative).toContain(
      "7 ticket có hơn 3 lượt xử lý mà chưa chuyển CS — khách nhiều khả năng đang mắc kẹt.",
    );
    expect(narrative).toContain(
      "Lần đọc này chưa lấy đủ dữ liệu phụ từ Langfuse, nên Intent, Skill, Transstatus và Step result còn thiếu.",
    );
    expect(
      narrative.some((line) => line.startsWith("Tín hiệu chuyển CS nổi bật")),
    ).toBe(false);
  });

  it("khong bao gio in ma TPE tho trong cau insight", () => {
    const signals = selectTransferSignals({
      transfer_reasons: {
        observed_transfer_denominator: 21,
        triggers: [],
        step_result_missing: { count: 0, denominator: 21 },
        tpe: [
          { transstatus: "1", step_result: "1", count: 19, status: "SUCCESSFUL" },
          { transstatus: "-217", step_result: "-5025", count: 2, status: null },
        ],
        guardrail: [],
        escalation_guard_blocked: { count: 0, denominator: 21 },
      },
    });
    const labels = signals.map((s) => s.label).join(" | ");
    expect(labels).toContain("SUCCESSFUL");
    expect(labels).not.toMatch(/-217|-5025|Transstatus|Step result/);
  });

  it("aggregates tpe rows that share the same status instead of listing them twice", () => {
    // Many distinct (transstatus, step_result) pairs can resolve to the same
    // status — e.g. PENDING here comes from three different rows. Without
    // grouping by status first, PENDING would occupy two or three slots in
    // the top-3 signal list, understating its true share and potentially
    // evicting a genuinely distinct signal.
    const signals = selectTransferSignals({
      transfer_reasons: {
        observed_transfer_denominator: 30,
        triggers: [],
        step_result_missing: { count: 0, denominator: 30 },
        tpe: [
          { transstatus: "1", step_result: "1", count: 5, status: "PENDING" },
          { transstatus: "1", step_result: "2", count: 3, status: "PENDING" },
          { transstatus: "2", step_result: "1", count: 2, status: "PENDING" },
          { transstatus: "-217", step_result: "-5025", count: 4, status: "SUCCESSFUL" },
        ],
        guardrail: [],
        escalation_guard_blocked: { count: 0, denominator: 30 },
      },
    });

    const pendingEntries = signals.filter((signal) => signal.label === "PENDING");
    expect(pendingEntries).toHaveLength(1);
    expect(pendingEntries[0]?.count).toBe(10);
    expect(signals).toEqual([
      { label: "PENDING", count: 10 },
      { label: "SUCCESSFUL", count: 4 },
    ]);
  });
});
