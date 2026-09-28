import {
  EMPTY_TICKET_FILTERS,
  type TicketFilterKey,
  type TicketFilters,
} from "./dashboard-filters";
import type { WeekDefinition } from "./dashboard-schema";

/** D7: the report scope and Explorer filters live in the hash so a link
 * reopens the same view. No Ticket ID, ever -- a shared link must not point
 * at one customer. */
export type DeepLinkScope =
  | { readonly mode: "latest" }
  | { readonly mode: "all" }
  | { readonly mode: "weeks"; readonly weeks: readonly string[] }
  | { readonly mode: "range"; readonly from: string; readonly to: string };

export interface DeepLinkState {
  readonly weekDefinition: WeekDefinition;
  readonly scope: DeepLinkScope;
  readonly filters: TicketFilters;
}

// Scope keys are derived from `w`/`r`, so they are not repeated in `f`.
const NOT_LINKED: ReadonlySet<string> = new Set([
  "cohort_week",
  "cohort_weeks",
  "opened_from",
  "opened_to",
  "ticket_id",
]);
const LINKED_KEYS = Object.keys(EMPTY_TICKET_FILTERS).filter(
  (key) => !NOT_LINKED.has(key),
) as TicketFilterKey[];
const ISO_DATE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

export function encodeDeepLink({
  weekDefinition,
  scope,
  filters,
}: DeepLinkState): string {
  const params = new URLSearchParams();
  if (weekDefinition !== "mon_fri") {
    params.set("v", weekDefinition);
  }
  if (scope.mode === "all") {
    params.set("w", "all");
  } else if (scope.mode === "weeks") {
    params.set("w", scope.weeks.join(","));
  } else if (scope.mode === "range") {
    params.set("r", `${scope.from}~${scope.to}`);
  }
  const pairs = LINKED_KEYS.filter((key) => filters[key] !== "").map(
    (key) => `${key}:${filters[key]}`,
  );
  if (pairs.length > 0) {
    params.set("f", pairs.join(";"));
  }
  return params.toString();
}

export function decodeDeepLink(hash: string): {
  weekDefinition?: WeekDefinition;
  scope?: DeepLinkScope;
  filters: Partial<TicketFilters>;
} {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const result: ReturnType<typeof decodeDeepLink> = { filters: {} };
  const view = params.get("v");
  if (view === "mon_sun" || view === "mon_fri") {
    result.weekDefinition = view;
  }
  const weeks = params.get("w");
  const range = params.get("r")?.split("~");
  if (weeks === "all") {
    result.scope = { mode: "all" };
  } else if (weeks !== null) {
    const valid = weeks.split(",").filter((week) => ISO_DATE.test(week));
    if (valid.length > 0) {
      result.scope = { mode: "weeks", weeks: valid };
    }
  } else if (
    range?.length === 2 &&
    range.every((date) => ISO_DATE.test(date))
  ) {
    result.scope = { mode: "range", from: range[0]!, to: range[1]! };
  }
  const filters: Partial<Record<TicketFilterKey, string>> = {};
  for (const pair of (params.get("f") ?? "").split(";")) {
    const split = pair.indexOf(":");
    const key = pair.slice(0, split) as TicketFilterKey;
    if (split > 0 && LINKED_KEYS.includes(key)) {
      filters[key] = pair.slice(split + 1);
    }
  }
  result.filters = filters;
  return result;
}
