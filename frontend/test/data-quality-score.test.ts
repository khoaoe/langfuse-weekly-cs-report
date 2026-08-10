import { describe, expect, it } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
} from "../src/lib/dashboard-schema";
import {
  DATA_QUALITY_FRESHNESS_WINDOW_MS,
  calculateDataQualityScore,
} from "../src/lib/data-quality-score";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;
const now = Date.parse("2026-07-30T00:00:00Z");

describe("data quality score", () => {
  it("uses the governed 40/20/20/10/10 weighting and the seven-minute boundary", () => {
    const snapshot: DashboardSnapshot = {
      ...baseSnapshot,
      generated_at: new Date(now - DATA_QUALITY_FRESHNESS_WINDOW_MS).toISOString(),
      coverage: {
        ...baseSnapshot.coverage,
        issue_category: 1,
        tpe: 1,
        skill: 1,
      },
      gate_status: {
        ...baseSnapshot.gate_status,
        structural_invalid_rate: 0.02,
      },
    };

    expect(calculateDataQualityScore(snapshot, now)).toMatchObject({
      score: 99,
      tone: "good",
      freshnessOk: true,
    });

    expect(
      calculateDataQualityScore(
        {
          ...snapshot,
          generated_at: new Date(
            now - DATA_QUALITY_FRESHNESS_WINDOW_MS - 1,
          ).toISOString(),
        },
        now,
      ),
    ).toMatchObject({
      score: 89,
      tone: "warning",
      freshnessOk: false,
    });
  });

  it("marks a low combined score critical without conflating it with the gate", () => {
    const snapshot: DashboardSnapshot = {
      ...baseSnapshot,
      generated_at: new Date(now - 60 * 60 * 1_000).toISOString(),
      coverage: {
        ...baseSnapshot.coverage,
        issue_category: 0.5,
        tpe: 0.5,
        skill: 0.5,
      },
      gate_status: {
        allowed: true,
        structural_invalid_rate: 0.05,
        reasons: [],
      },
    };

    expect(calculateDataQualityScore(snapshot, now)).toMatchObject({
      score: 63,
      tone: "critical",
      freshnessOk: false,
      structuralValidRate: 0.95,
    });
  });
});
