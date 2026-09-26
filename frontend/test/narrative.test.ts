import { describe, expect, it } from "vitest";

import { buildDeterministicNarrative } from "../src/lib/narrative";
import { hideImmatureReopen, isReopenMature } from "../src/lib/selectors";
import { DashboardEnvelopeSchema } from "../src/lib/dashboard-schema";
import { dashboardEnvelopeFixture } from "./fixtures/dashboard";

describe("deterministic narrative", () => {
  it("formats rates and deltas without calling an LLM", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 1_374, rate: 0.798 }, reopenRate: 0.262 },
      previous: { aiFirst: { count: 1_220, rate: 0.766 }, reopenRate: 0.266 },
      enrichmentStatus: "complete",
    });

    expect(narrative).toEqual([
      "AI First tăng 3,2 điểm so với tuần trước.",
      "Reopen sau AI First gần như không đổi so với tuần trước.",
    ]);
  });

  it("never mentions the retired >3-turn warning, even though the action rail still shows it", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 1_374, rate: 0.798 }, reopenRate: 0.262 },
      previous: { aiFirst: { count: 1_220, rate: 0.766 }, reopenRate: 0.266 },
      enrichmentStatus: "complete",
    });

    expect(narrative.join(" ")).not.toMatch(/lượt xử lý|mắc kẹt/);
  });

  it("test_narrative_has_no_methodological_advice_strings", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 8, rate: 0.8 }, reopenRate: null },
      previous: null,
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

  it("caps the first-viewport narrative at four sentences and keeps the enrichment warning", () => {
    const narrative = buildDeterministicNarrative({
      current: { aiFirst: { count: 987, rate: 0.712 }, reopenRate: 0.318 },
      previous: { aiFirst: { count: 1_104, rate: 0.776 }, reopenRate: 0.241 },
      enrichmentStatus: "partial",
    });

    expect(narrative.length).toBeGreaterThanOrEqual(1);
    expect(narrative.length).toBeLessThanOrEqual(4);
    expect(narrative).toContain(
      "Lần đọc này chưa lấy đủ dữ liệu phụ từ Langfuse, nên Intent, Skill, Transstatus và Step result còn thiếu.",
    );
  });
});

describe("reopen maturity", () => {
  it("matches cohort.is_week_fully_mature: week end + 168 h, Vietnam time", () => {
    // mon_sun week of 2026-07-20 ends 2026-07-27 00:00 +07; mature from 2026-08-03 00:00 +07.
    expect(isReopenMature("2026-07-20", 7, "2026-08-02T16:59:59Z")).toBe(false);
    expect(isReopenMature("2026-07-20", 7, "2026-08-02T17:00:00Z")).toBe(true);
    // mon_fri ends two days earlier.
    expect(isReopenMature("2026-07-20", 5, "2026-07-31T17:00:00Z")).toBe(true);
  });

  it("blanks only the immature weeks' lifetime rate", () => {
    const snapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture).snapshot;
    if (snapshot === null) throw new Error("fixture must carry a snapshot");
    const immature = hideImmatureReopen({ ...snapshot, generated_at: "2026-07-29T11:27:00Z" });
    expect(immature.views.mon_sun.weekly.every((row) => row.reopen_lifetime_rate === null)).toBe(true);
    // Counts stay: only the censored rate is hidden.
    expect(immature.views.mon_sun.weekly[0]?.reopen_lifetime_numerator).toBe(
      snapshot.views.mon_sun.weekly[0]?.reopen_lifetime_numerator,
    );
    const mature = { ...snapshot, generated_at: "2026-12-01T00:00:00Z" };
    expect(hideImmatureReopen(mature)).toBe(mature);
  });
});
