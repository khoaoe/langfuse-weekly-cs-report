import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { dashboardEnvelopeFixture } from "./fixtures/dashboard";
import {
  DashboardEnvelopeSchema,
  type DashboardSnapshot,
  type WeeklyReportRow,
} from "../src/lib/dashboard-schema";
import { DecisionLedger } from "../src/components/DecisionLedger";
import {
  ALL_WEEKS_SCOPE,
  isObservedWeek,
  selectAttentionItems,
  selectLedger,
  selectScope,
} from "../src/lib/selectors";

const baseSnapshot = DashboardEnvelopeSchema.parse(dashboardEnvelopeFixture)
  .snapshot as DashboardSnapshot;
const latest = baseSnapshot.views.mon_sun.weekly[0] as WeeklyReportRow;
const selected: WeeklyReportRow = {
  ...latest,
  cohort_week: "2026-07-13",
  total_tickets: 4,
  ai_first_count: 2,
  ai_first_rate: 0.5,
  ai_end_to_end_count: 1,
  ai_then_cs_count: 1,
  direct_cs_count: 1,
  reopen_lifetime_numerator: 0,
  reopen_lifetime_denominator: 2,
  reopen_lifetime_rate: 0,
  gt4_turn_without_cs: 0,
};
const snapshot: DashboardSnapshot = {
  ...baseSnapshot,
  views: {
    ...baseSnapshot.views,
    mon_sun: {
      ...baseSnapshot.views.mon_sun,
      weekly: [selected, latest],
    },
  },
};

describe("selected-week decision scope", () => {
  it("identifies a selected week that must be cleared after snapshot rollover", () => {
    expect(
      isObservedWeek(snapshot.views.mon_sun, "2026-07-13"),
    ).toBe(true);
    expect(
      isObservedWeek(snapshot.views.mon_sun, "2026-06-29"),
    ).toBe(false);
  });

  it("uses the chart-selected week for the title, ledger and warning", () => {
    expect(selectScope(snapshot, "mon_sun", "2026-07-13")).toMatchObject({
      eligible: 4,
      aiFirstCount: 2,
      gt4WithoutCs: 0,
      week: { cohort_week: "2026-07-13" },
    });
    expect(
      selectAttentionItems(snapshot, "mon_sun", "2026-07-13").map(
        (item) => item.id,
      ),
    ).not.toContain("attention-gt4");

    render(
      <DecisionLedger
        snapshot={snapshot}
        weekDefinition="mon_sun"
        activeWeek="2026-07-13"
      />,
    );

    expect(
      screen.getByRole("heading", { level: 1, name: /13\/07–19\/07.*4 ticket/ }),
    ).toBeVisible();
    expect(screen.getByRole("group", { name: "Tóm tắt quyết định" })).toBeVisible();
    // The denominator is stated once on the group caption, not repeated in
    // each of the three cells that divide by it.
    expect(document.getElementById("ledger-ai-first")).toHaveTextContent(
      "250,0%",
    );
    expect(screen.getByText("4 ticket tuần này")).toBeVisible();
    expect(
      screen.queryByText(/ticket có hơn 3 lượt xử lý nhưng chưa chuyển CS/),
    ).toBeNull();
  });

  it("moves partial-enrichment context onto the rail as a warning", () => {
    const partial: DashboardSnapshot = {
      ...baseSnapshot,
      enrichment_status: "partial",
    };

    render(
      <DecisionLedger snapshot={partial} weekDefinition="mon_sun" />,
    );

    expect(
      screen.getByText(
        "Lần đọc này chưa lấy đủ dữ liệu phụ từ Langfuse, nên Intent, Skill, Transstatus và Step result còn thiếu.",
      ),
    ).toBeVisible();
    expect(document.getElementById("narrativeSummary")).toBeNull();
    expect(screen.queryByText(/Chờ lần làm mới kế tiếp/)).toBeNull();
    expect(screen.queryByText(/Cần lưu ý/i)).toBeNull();
  });

  it("keeps the share line on a neutral count cell that measured nothing", () => {
    const zeroed: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [
            { ...latest, direct_cs_count: 0 },
            ...baseSnapshot.views.mon_sun.weekly.slice(1),
          ],
        },
      },
    };

    const cells = selectLedger(zeroed, "mon_sun").flatMap((group) => group.cells);
    const directCs = cells.find((cell) => cell.id === "ledger-direct-cs");

    // Unlike the old warning cell, "0 ticket" is still an informative share
    // for a neutral cell — only an empty population (eligible === 0) hides it.
    expect(directCs?.value).toBe("0");
    expect(directCs?.support).not.toBeNull();
  });

  it("leads each KPI cell with the number that compares across weeks, and only prints a group denominator the whole group shares", () => {
    const reportingWeek: WeeklyReportRow = {
      ...latest,
      total_tickets: 935,
      ai_first_count: 727,
      ai_first_rate: 727 / 935,
      ai_end_to_end_count: 406,
      ai_then_cs_count: 180,
      direct_cs_count: 28,
      reopen_lifetime_numerator: 152,
      reopen_lifetime_denominator: 727,
      reopen_lifetime_rate: 152 / 727,
      gt4_turn_without_cs: 0,
      resolved_first_reply: 322,
      // Exact, not rounded: the pipeline asserts sum == mean * ai_first_count
      // before serialising, so a fixture that violates it would pass here and
      // never occur in production. 923 / 727 renders as 1,27.
      ai_reply_sum_ai_first: 923,
      ai_reply_mean_ai_first: 923 / 727,
    };
    const reportingSnapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [reportingWeek],
        },
      },
    };

    const groups = selectLedger(reportingSnapshot, "mon_sun");
    expect(groups.map((group) => group.id)).toEqual([
      "ledger-group-ticket",
      "ledger-group-secondary",
    ]);

    const ticketGroup = groups.find(
      (group) => group.id === "ledger-group-ticket",
    );
    expect(ticketGroup?.denominator).toBe("935 ticket tuần này");
    // "AI xử lý trọn" is the outcome the whole product is judged on, and it
    // used to exist only as the caption of the collapsed group below -- a
    // ticket count worn as a per-response denominator. It belongs here, in the
    // group whose denominator really is tickets, reading as a funnel:
    // AI First -> đóng trọn -> chuyển CS -> phần chuyển ngay từ đầu (CS First).
    // AI First and CS First do not sum to the population: `unclassified`
    // tickets have no classifiable trace and belong to neither side, which is
    // why CS First reads `direct_cs` and never `eligible - aiFirst`.
    expect(ticketGroup?.cells).toMatchObject([
      {
        id: "ledger-ai-first",
        value: "727",
        unit: null,
        support: "77,8%",
        filterPatch: { outcome: "ai_end_to_end,ai_then_cs" },
      },
      {
        id: "ledger-ai-end-to-end",
        value: "406",
        unit: null,
        support: "43,4%",
      },
      { id: "ledger-transfer", value: "208", unit: null, support: "22,2%" },
      {
        // Rate leads, count supports. The absolute count rises with volume by
        // construction, so it cannot be read across weeks; lần/ticket can.
        id: "ledger-reopen",
        value: "0,21",
        unit: "lần/ticket",
        support: "152 lần trên 727 ticket AI First",
      },
    ]);

    const secondaryGroup = groups.find(
      (group) => group.id === "ledger-group-secondary",
    );
    // No group-level denominator: these cells divide by the eligible
    // population, ai_first (727) and ai_end_to_end (406), so any single
    // number in the heading is wrong for most of them.
    expect(secondaryGroup?.denominator).toBeNull();
    expect(secondaryGroup?.cells).toMatchObject([
      // AI First and CS First do not sum to the population: `unclassified`
      // tickets belong to neither side, so CS First reads `direct_cs`.
      { id: "ledger-direct-cs", value: "28", unit: null, support: "3,0%" },
      { id: "ledger-gt4-turn", value: "1", unit: null, support: "0,1%" },
      {
        // 923 / 727 = 1,27: the total and the mean beside it read as one
        // division, so only the first spells out the base.
        id: "ledger-ai-reply-total",
        value: "923",
        unit: "lượt",
        support: "trên 727 ticket AI First",
      },
      {
        id: "ledger-replies-per-ticket",
        value: "1,27",
        unit: "lượt",
        support: null,
      },
      {
        id: "ledger-first-reply-resolved",
        value: "79,3%",
        unit: null,
        support: "322 trong 406 ticket AI xử lý trọn",
      },
    ]);
  });

  it("fills resolvedFirstReply/aiEndToEndCount/aiReplyMeanAiFirst on the week branch of selectScope()", () => {
    expect(
      selectScope(snapshot, "mon_sun", "2026-07-13"),
    ).toMatchObject({
      resolvedFirstReply: selected.resolved_first_reply,
      aiEndToEndCount: selected.ai_end_to_end_count,
      aiReplyMeanAiFirst: selected.ai_reply_mean_ai_first,
    });
  });

  it("fills resolvedFirstReply/aiEndToEndCount/aiReplyMeanAiFirst on the no-week branch of selectScope(), summed/weighted across observed weeks", () => {
    const scope = selectScope(snapshot, "mon_sun", ALL_WEEKS_SCOPE);

    const observedWeeks = snapshot.views.mon_sun.weekly.filter(
      (week) => week.has_data,
    );
    const expectedResolved = observedWeeks.reduce(
      (total, week) => total + week.resolved_first_reply,
      0,
    );
    expect(scope.resolvedFirstReply).toBe(expectedResolved);
    expect(scope.aiEndToEndCount).toBe(
      snapshot.views.mon_sun.outcomes.ai_end_to_end,
    );
  });

  it("shows — instead of NaN when ai_reply_mean_ai_first is null for the scoped week", () => {
    const noAiFirst: WeeklyReportRow = {
      ...latest,
      ai_first_count: 0,
      ai_reply_sum_ai_first: 0,
      ai_reply_mean_ai_first: null,
    };
    const noAiFirstSnapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        ...baseSnapshot.views,
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [noAiFirst],
        },
      },
    };

    const groups = selectLedger(noAiFirstSnapshot, "mon_sun");
    const repliesPerTicket = groups
      .flatMap((group) => group.cells)
      .find((cell) => cell.id === "ledger-replies-per-ticket");

    expect(repliesPerTicket?.value).toBe("—");
    expect(repliesPerTicket?.support).toBeNull();
  });

  it("renders critical rail items with a direct ticket filter", () => {
    const onCellSelect = vi.fn();
    render(
      <DecisionLedger
        snapshot={baseSnapshot}
        weekDefinition="mon_sun"
        onCellSelect={onCellSelect}
      />,
    );

    const rail = screen.getByRole("list", {
      name: "Cần xem trong phạm vi này",
    });
    // Critical items carry their severity as text, not only as colour, and
    // drop the written instruction the "Xem ticket" button already gives.
    expect(within(rail).getByText("Cần xử lý")).toBeVisible();
    expect(within(rail).queryByText(/Mở Ticket Explorer/)).toBeNull();
    expect(
      within(rail).getByText(/ticket có hơn 3 lượt xử lý mà chưa chuyển CS/),
    ).toBeVisible();
    fireEvent.click(within(rail).getByRole("button", { name: "Xem ticket" }));
    expect(onCellSelect).toHaveBeenCalledWith({
      gt4_turn: "true",
      transferred: "false",
    });
  });
});
