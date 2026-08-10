import { describe, expect, it } from "vitest";

import {
  TICKET_COLUMNS,
  LEGACY_TICKET_COLUMN_STORAGE_KEY,
  PREVIOUS_TICKET_COLUMN_STORAGE_KEY,
  TICKET_COLUMN_STORAGE_KEY,
  DEFAULT_TICKET_COLUMNS,
  readVisibleTicketColumns,
  writeVisibleTicketColumns,
} from "../src/lib/ticket-columns";

describe("Ticket Explorer column persistence", () => {
  it("migrates v3 to v4 and makes the transfer reason visible once", () => {
    localStorage.setItem(
      PREVIOUS_TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id", "outcome", "transferred", "turn_count"]),
    );

    expect(TICKET_COLUMN_STORAGE_KEY).toBe("weekly-cs-ticket-columns-v4");
    expect(readVisibleTicketColumns()).toEqual([
      "ticket_id",
      "outcome",
      "transferred",
      "transfer_reason",
      "turn_count",
    ]);
  });

  it("migrates a valid v1 selection once and inserts opened time plus satisfaction", () => {
    localStorage.setItem(
      LEGACY_TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id", "cohort_week", "outcome", "turn_count"]),
    );

    expect(readVisibleTicketColumns()).toEqual([
      "ticket_id",
      "opened_at",
      "cohort_week",
      "outcome",
      "transfer_reason",
      "csat_satisfaction",
      "turn_count",
    ]);
    expect(JSON.parse(localStorage.getItem(TICKET_COLUMN_STORAGE_KEY) ?? "null")).toEqual([
      "ticket_id",
      "opened_at",
      "cohort_week",
      "outcome",
      "transfer_reason",
      "csat_satisfaction",
      "turn_count",
    ]);
    expect(localStorage.getItem(LEGACY_TICKET_COLUMN_STORAGE_KEY)).not.toBeNull();
  });

  it("places migrated satisfaction after week or mandatory Ticket when outcome is hidden", () => {
    localStorage.setItem(
      LEGACY_TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["cohort_week", "turn_count"]),
    );
    expect(readVisibleTicketColumns()).toEqual([
      "ticket_id",
      "opened_at",
      "transfer_reason",
      "cohort_week",
      "csat_satisfaction",
      "turn_count",
    ]);

    localStorage.clear();
    localStorage.setItem(
      LEGACY_TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["turn_count"]),
    );
    expect(readVisibleTicketColumns()).toEqual([
      "ticket_id",
      "opened_at",
      "transfer_reason",
      "csat_satisfaction",
      "turn_count",
    ]);
  });

  it("migrates v2 to v4 by adding opened time and transfer reason while preserving hidden satisfaction", () => {
    localStorage.setItem(
      "weekly-cs-ticket-columns-v2",
      JSON.stringify(["turn_count", "ticket_id", "turn_count"]),
    );
    localStorage.setItem(
      LEGACY_TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id", "outcome"]),
    );

    expect(TICKET_COLUMN_STORAGE_KEY).toBe("weekly-cs-ticket-columns-v4");
    expect(readVisibleTicketColumns()).toEqual([
      "ticket_id",
      "opened_at",
      "transfer_reason",
      "turn_count",
    ]);
    expect(
      JSON.parse(localStorage.getItem(TICKET_COLUMN_STORAGE_KEY) ?? "null"),
    ).toEqual(["ticket_id", "opened_at", "transfer_reason", "turn_count"]);
  });

  it("shows opened time by default but lets a v4 selection hide it", () => {
    expect(DEFAULT_TICKET_COLUMNS).toContain("opened_at");

    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id", "cohort_week"]),
    );
    expect(readVisibleTicketColumns()).toEqual(["ticket_id", "cohort_week"]);
  });

  it("falls back safely for tampered v1 or v2 without copying private keys", () => {
    localStorage.setItem(
      LEGACY_TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["raw_payload", "trace_id"]),
    );
    expect(readVisibleTicketColumns()).toEqual(DEFAULT_TICKET_COLUMNS);
    expect(JSON.parse(localStorage.getItem(TICKET_COLUMN_STORAGE_KEY) ?? "null")).toEqual(
      DEFAULT_TICKET_COLUMNS,
    );

    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["raw_payload", "trace_id"]),
    );
    expect(readVisibleTicketColumns()).toEqual(DEFAULT_TICKET_COLUMNS);
  });

  it("persists only unique allowlisted column keys with Ticket first", () => {
    writeVisibleTicketColumns(["turn_count", "ticket_id", "ticket_id", "not_a_column"]);

    expect(JSON.parse(localStorage.getItem(TICKET_COLUMN_STORAGE_KEY) ?? "null")).toEqual([
      "ticket_id",
      "turn_count",
    ]);
  });

  it("restores mandatory Ticket first in legacy selections that omitted it", () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["turn_count", "cohort_week"]),
    );

    expect(readVisibleTicketColumns()).toEqual([
      "ticket_id",
      "turn_count",
      "cohort_week",
    ]);
    expect(writeVisibleTicketColumns(["turn_count"])).toEqual([
      "ticket_id",
      "turn_count",
    ]);
    expect(
      JSON.parse(localStorage.getItem(TICKET_COLUMN_STORAGE_KEY) ?? "null"),
    ).toEqual(["ticket_id", "turn_count"]);
  });

  it("rejects malformed or privacy-bearing local storage values", () => {
    localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, JSON.stringify(["ticket_id", "raw_payload", "trace_id"]));

    expect(readVisibleTicketColumns()).toEqual(["ticket_id"]);
  });

  it("drops the legacy TPE status column instead of exposing inferred status", () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id", "tpe_code", "tpe_status"]),
    );

    expect(readVisibleTicketColumns()).toEqual(["ticket_id", "tpe_code"]);
    expect(writeVisibleTicketColumns(["ticket_id", "tpe_status"])).toEqual([
      "ticket_id",
    ]);
  });

  it("drops raw guardrail taxonomy from legacy Explorer selections", () => {
    localStorage.setItem(
      TICKET_COLUMN_STORAGE_KEY,
      JSON.stringify(["ticket_id", "guardrail_rule", "escalation_guard_blocked"]),
    );

    expect(readVisibleTicketColumns()).toEqual([
      "ticket_id",
      "escalation_guard_blocked",
    ]);
    expect(writeVisibleTicketColumns(["ticket_id", "guardrail_rule"])).toEqual([
      "ticket_id",
    ]);
    expect(
      TICKET_COLUMNS.find(
        (column) => column.key === "escalation_guard_blocked",
      )?.label,
    ).toBe("Chặn chuyển CS trùng");
  });
});
