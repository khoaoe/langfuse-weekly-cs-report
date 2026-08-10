import { describe, expect, it } from "vitest";

import {
  EMPTY_TICKET_FILTERS,
  activeTicketFilterChips,
  updateTicketFilters,
} from "../src/lib/dashboard-filters";

describe("dashboard filter state", () => {
  it("describes every active filter in Vietnamese without mutating the input", () => {
    const current = {
      ...EMPTY_TICKET_FILTERS,
      cohort_week: "2026-07-20",
      product_code: "IBFT",
      transfer_reason: "skill_suggested_transfer",
      gt4_turn: "true",
      transferred: "false",
    } as const;

    expect(activeTicketFilterChips(current, "mon_sun")).toEqual([
      { key: "cohort_week", label: "Tuần: 20/07–26/07" },
      { key: "product_code", label: "Product Code: IBFT" },
      {
        key: "transfer_reason",
        label: "Lý do chuyển CS: Skill đề xuất chuyển CS",
      },
      { key: "gt4_turn", label: ">3 lượt xử lý: Có" },
      { key: "transferred", label: "Đã chuyển CS: Không" },
    ]);

    const next = updateTicketFilters(current, { product_code: "", app: "Zalopay" });
    expect(next).not.toBe(current);
    expect(next.product_code).toBe("");
    expect(next.app).toBe("Zalopay");
    expect(current.product_code).toBe("IBFT");
  });
});
