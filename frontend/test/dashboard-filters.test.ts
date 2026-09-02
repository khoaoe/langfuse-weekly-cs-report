import { describe, expect, it } from "vitest";

import {
  EMPTY_TICKET_FILTERS,
  activeTicketFilterChips,
  findTpeOptionSource,
  tpeOptionLabel,
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

  it("chips a tool-error pair filter under its own Vietnamese label", () => {
    const current = {
      ...EMPTY_TICKET_FILTERS,
      tool_error_codes:
        "get_bank_name:UNKNOWN_BANK_CODE,get_zalopay_id_by_phone:NOT_FOUND",
    } as const;

    expect(activeTicketFilterChips(current, "mon_sun")).toEqual([
      {
        key: "tool_error_codes",
        label:
          "Lỗi gọi tool: get_bank_name:UNKNOWN_BANK_CODE, get_zalopay_id_by_phone:NOT_FOUND",
      },
    ]);
  });

  it("selecting an opened-date range clears the week filter, and vice versa", () => {
    const withWeek = updateTicketFilters(EMPTY_TICKET_FILTERS, {
      cohort_week: "2026-07-20",
    });
    expect(withWeek.cohort_week).toBe("2026-07-20");

    const withRange = updateTicketFilters(withWeek, {
      opened_from: "2026-07-06",
      opened_to: "2026-07-30",
    });
    expect(withRange.opened_from).toBe("2026-07-06");
    expect(withRange.opened_to).toBe("2026-07-30");
    expect(withRange.cohort_week).toBe("");
    expect(withRange.cohort_weeks).toBe("");

    const backToWeek = updateTicketFilters(withRange, {
      cohort_weeks: "2026-07-13,2026-07-20",
    });
    expect(backToWeek.cohort_weeks).toBe("2026-07-13,2026-07-20");
    expect(backToWeek.opened_from).toBe("");
    expect(backToWeek.opened_to).toBe("");
  });

  it("shows one combined chip for the opened-date range and clears both bounds together", () => {
    const current = {
      ...EMPTY_TICKET_FILTERS,
      opened_from: "2026-07-06",
      opened_to: "2026-07-30",
    };

    expect(activeTicketFilterChips(current, "mon_sun")).toEqual([
      {
        key: "opened_from",
        label: "Ngày mở: 06/07–30/07",
        clearKeys: ["opened_from", "opened_to"],
      },
    ]);

    const chip = activeTicketFilterChips(current, "mon_sun")[0];
    const cleared = updateTicketFilters(
      current,
      Object.fromEntries((chip?.clearKeys ?? []).map((key) => [key, ""])),
    );
    expect(cleared.opened_from).toBe("");
    expect(cleared.opened_to).toBe("");
    expect(activeTicketFilterChips(cleared, "mon_sun")).toEqual([]);
  });

  it("nhan option Transstatus uu tien status, giu ma trong ngoac", () => {
    expect(tpeOptionLabel({ transstatus: "1", step_result: "1", status: "SUCCESSFUL" }))
      .toBe("SUCCESSFUL (1 / 1)");
    expect(tpeOptionLabel({ transstatus: "-217", step_result: "-5025", status: null }))
      .toBe("Chưa phân loại (-217 / -5025)");
  });

  it("findTpeOptionSource tra ve undefined khi mot transstatus co nhieu status khac nhau", () => {
    // -365 la ma that trong runtime/dashboard_snapshot.json: tach thanh
    // FAILED_FACE_AUTH / WAITING_NFC_REVIEW / FAILED_NFC / FAILED_OTP tuy
    // step_result, khong status nao chiem da so. Danh nhan bang status cua
    // hang co count cao nhat se gan sai status cho phan lon ticket con lai.
    const ambiguous = [
      { transstatus: "-365", step_result: "-1013", count: 24, status: "FAILED_FACE_AUTH" },
      { transstatus: "-365", step_result: "-1014", count: 12, status: "WAITING_NFC_REVIEW" },
      { transstatus: "-365", step_result: "-1015", count: 12, status: "FAILED_NFC" },
      { transstatus: "-365", step_result: "-1016", count: 4, status: "FAILED_OTP" },
    ];
    expect(findTpeOptionSource("-365", ambiguous)).toBeUndefined();
  });

  it("findTpeOptionSource tra ve hang dau tien (count cao nhat, da sap xep tu backend) khi chi co mot status", () => {
    const unambiguous = [
      { transstatus: "1", step_result: "1", count: 10, status: "SUCCESSFUL" },
      { transstatus: "1", step_result: "2", count: 5, status: "SUCCESSFUL" },
    ];
    expect(findTpeOptionSource("1", unambiguous)).toEqual(unambiguous[0]);
  });

  it("findTpeOptionSource tra ve undefined khi khong co hang nao khop transstatus", () => {
    expect(findTpeOptionSource("999999", [])).toBeUndefined();
  });
});
