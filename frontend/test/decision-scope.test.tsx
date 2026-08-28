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
  buildNarrativeInput,
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

  it("uses the chart-selected week for the title, ledger, narrative and warning", () => {
    expect(selectScope(snapshot, "mon_sun", "2026-07-13")).toMatchObject({
      eligible: 4,
      aiFirstCount: 2,
      gt4WithoutCs: 0,
      week: { cohort_week: "2026-07-13" },
    });
    expect(
      buildNarrativeInput(snapshot, "mon_sun", "2026-07-13").current.aiFirst,
    ).toEqual({ count: 2, rate: 0.5 });
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
    expect(document.getElementById("ledger-ai-first")).toHaveTextContent(
      "250,0% trong 4 ticket tuần này",
    );
    expect(
      screen.queryByText(/ticket có hơn 3 lượt xử lý nhưng chưa chuyển CS/),
    ).toBeNull();
  });

  it("uses the same-period block from the selected cohort view", () => {
    const runningSun = {
      ...latest,
      cohort_status: "wtd" as const,
    };
    const runningFri = {
      ...baseSnapshot.views.mon_fri.weekly[0]!,
      cohort_status: "wtd" as const,
    };
    const comparisonSnapshot: DashboardSnapshot = {
      ...baseSnapshot,
      views: {
        mon_sun: {
          ...baseSnapshot.views.mon_sun,
          weekly: [runningSun],
          same_period: {
            cutoff_date: "2026-07-23",
            cutoff_weekday: 4,
            current: {
              cohort_week: runningSun.cohort_week,
              total_tickets: 10,
              ai_first_count: 5,
              ai_first_rate: 0.5,
              reopen_lifetime_rate: 0.2,
              reopen_lifetime_numerator: 1,
              reopen_lifetime_denominator: 5,
            },
            baseline: {
              weeks_used: 4,
              ai_first_rate: 0.6,
              reopen_lifetime_rate: 0.25,
            },
            by_week: {},
          },
        },
        mon_fri: {
          ...baseSnapshot.views.mon_fri,
          weekly: [runningFri],
          same_period: {
            cutoff_date: "2026-07-23",
            cutoff_weekday: 4,
            current: {
              cohort_week: runningFri.cohort_week,
              total_tickets: 5,
              ai_first_count: 2,
              ai_first_rate: 0.4,
              reopen_lifetime_rate: 0.5,
              reopen_lifetime_numerator: 1,
              reopen_lifetime_denominator: 2,
            },
            baseline: {
              weeks_used: 2,
              ai_first_rate: 0.3,
              reopen_lifetime_rate: 0.4,
            },
            by_week: {},
          },
        },
      },
    };

    expect(buildNarrativeInput(comparisonSnapshot, "mon_sun")).toMatchObject({
      current: { aiFirst: { count: 5, rate: 0.5 }, reopenRate: 0.2 },
      samePeriod: { weeksUsed: 4, aiFirstRate: 0.6, reopenRate: 0.25 },
    });
    expect(buildNarrativeInput(comparisonSnapshot, "mon_fri")).toMatchObject({
      current: { aiFirst: { count: 2, rate: 0.4 }, reopenRate: 0.5 },
      samePeriod: { weeksUsed: 2, aiFirstRate: 0.3, reopenRate: 0.4 },
    });
  });

  it("keeps partial-enrichment context in the narrative without a separate alert card", () => {
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

  it("uses a count as the primary value in every KPI cell, grouped by denominator tier", () => {
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
      ai_reply_mean_ai_first: 1.27,
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
      "ledger-group-response",
    ]);

    const ticketGroup = groups.find(
      (group) => group.id === "ledger-group-ticket",
    );
    expect(ticketGroup?.cells).toMatchObject([
      {
        id: "ledger-ai-first",
        value: "727",
        support: "77,8% trong 935 ticket tuần này",
      },
      {
        id: "ledger-transfer",
        value: "208",
        support: "22,2% trong 935 ticket tuần này",
      },
      {
        id: "ledger-direct-cs",
        value: "28",
        support: "3,0% trong 935 ticket tuần này",
      },
    ]);

    const responseGroup = groups.find(
      (group) => group.id === "ledger-group-response",
    );
    expect(responseGroup?.cells).toMatchObject([
      {
        id: "ledger-first-reply-resolved",
        value: "79,3%",
        support: "322 trong 406 ticket AI xử lý trọn",
      },
      {
        id: "ledger-replies-per-ticket",
        value: "1,27 lượt",
        support: "trên 727 ticket AI First",
      },
      {
        id: "ledger-reopen",
        value: "152 lần",
        support: "0,21 lần/ticket · 727 ticket AI First",
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
    expect(within(rail).queryByText("Cần xử lý")).toBeNull();
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
