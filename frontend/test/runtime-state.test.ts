import { describe, expect, it } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import { initialDashboardRuntime, reduceDashboardRuntime } from "../src/lib/runtime-state";

describe("dashboard runtime state", () => {
  it("shows loading without inventing a snapshot", () => {
    expect(initialDashboardRuntime()).toEqual({ kind: "loading", snapshot: null, message: "Đang tải dữ liệu dashboard." });
  });

  it("retains last-good data during a refresh and stale error", () => {
    const ready = reduceDashboardRuntime(initialDashboardRuntime(), { type: "envelope", envelope: dashboardEnvelopeFixture });
    const refreshing = reduceDashboardRuntime(ready, { type: "refresh-start" });
    const stale = reduceDashboardRuntime(refreshing, { type: "request-failed", errorCode: "private_upstream_timeout" });

    expect(refreshing).toMatchObject({ kind: "refreshing", snapshot: dashboardEnvelopeFixture.snapshot });
    expect(stale).toMatchObject({ kind: "stale_error", snapshot: dashboardEnvelopeFixture.snapshot });
    expect(stale.message).toBe("Không thể tải dữ liệu mới. Đang hiển thị dữ liệu gần nhất.");
    expect(stale.message).not.toContain("private_upstream_timeout");
  });
});
