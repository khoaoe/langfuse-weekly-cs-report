import { describe, expect, it } from "vitest";

import { EMPTY_TICKET_FILTERS } from "../src/lib/dashboard-filters";
import { decodeDeepLink, encodeDeepLink } from "../src/lib/deep-link";

describe("deep link", () => {
  it("round-trips scope, week definition and Explorer filters", () => {
    const state = {
      weekDefinition: "mon_sun" as const,
      scope: { mode: "weeks" as const, weeks: ["2026-09-21", "2026-09-14"] },
      filters: {
        ...EMPTY_TICKET_FILTERS,
        cohort_weeks: "2026-09-21,2026-09-14",
        outcome: "direct_cs,ai_then_cs",
        tool_error_codes: "get_user_kyc_profile:NOT_FOUND",
      },
    };
    const hash = encodeDeepLink(state);

    expect(decodeURIComponent(hash)).toBe(
      "v=mon_sun&w=2026-09-21,2026-09-14&f=outcome:direct_cs,ai_then_cs;tool_error_codes:get_user_kyc_profile:NOT_FOUND",
    );
    expect(decodeDeepLink(`#${hash}`)).toEqual({
      weekDefinition: "mon_sun",
      scope: state.scope,
      filters: {
        outcome: "direct_cs,ai_then_cs",
        tool_error_codes: "get_user_kyc_profile:NOT_FOUND",
      },
    });
  });

  it("encodes the default view as an empty hash and never carries a Ticket ID", () => {
    expect(
      encodeDeepLink({
        weekDefinition: "mon_fri",
        scope: { mode: "latest" },
        filters: { ...EMPTY_TICKET_FILTERS, ticket_id: "123456" },
      }),
    ).toBe("");
    expect(decodeDeepLink("#f=ticket_id:123456").filters).toEqual({});
  });

  it("round-trips all weeks and a day range", () => {
    for (const scope of [
      { mode: "all" as const },
      { mode: "range" as const, from: "2026-09-01", to: "2026-09-10" },
    ]) {
      const hash = encodeDeepLink({
        weekDefinition: "mon_fri",
        scope,
        filters: EMPTY_TICKET_FILTERS,
      });
      expect(decodeDeepLink(`#${hash}`).scope).toEqual(scope);
    }
  });

  it("ignores hashes it did not write and malformed values", () => {
    expect(decodeDeepLink("#ab-test")).toEqual({ filters: {} });
    expect(decodeDeepLink("#v=nope&w=2026-13-99&r=x~y&f=bogus:1")).toEqual({
      filters: {},
    });
  });
});
