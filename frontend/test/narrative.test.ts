import { describe, expect, it } from "vitest";

import { buildDeterministicNarrative } from "../src/lib/narrative";

describe("deterministic narrative", () => {
  it("formats rates and deltas without calling an LLM", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 1_374, rate: 0.798 }, reopenRate: 0.262 },
      previous: { aiFirst: { count: 1_220, rate: 0.766 }, reopenRate: 0.266 },
      gt4TurnWithoutCs: 11,
      enrichmentStatus: "complete",
    });

    expect(narrative).toEqual([
      "AI First tăng 3,2 điểm so với tuần trước.",
      "Reopen sau AI First gần như không đổi so với tuần trước.",
      "11 ticket có hơn 3 lượt xử lý mà chưa chuyển CS — khách nhiều khả năng đang mắc kẹt.",
    ]);
  });

  it("test_narrative_has_no_methodological_advice_strings", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 8, rate: 0.8 }, reopenRate: null },
      previous: null,
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
      gt4TurnWithoutCs: 0,
      enrichmentStatus: "complete",
      isWtd: true,
      samePeriod: {
        cutoffWeekday: 3,
        weeksUsed: 4,
        aiFirstRate: 0.742,
        reopenRate: 0.215,
      },
    });

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
  });
});
