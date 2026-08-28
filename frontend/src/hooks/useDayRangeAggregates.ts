import { useQuery } from "@tanstack/react-query";

import { fetchTicketPage } from "../lib/api";
import {
  parseDayAggregatesResponse,
  type DayAggregate,
  type WeekDefinition,
} from "../lib/dashboard-schema";
import { dateRangeSpanDays, parseIsoDate } from "../lib/format";

/** §B1's rolling rate needs 6 days of history before the first plotted point. */
const MIN_ROLLING_LOOKBACK_DAYS = 6;

export interface DayRangeAggregates {
  /** Lookback window + plotted range, in chronological order — feeds rollingRate(). */
  readonly allDays: readonly DayAggregate[];
  /** Exactly the selected from...to range, for rendering (never the lookback days). */
  readonly plottedDays: readonly DayAggregate[];
}

/**
 * The lookback must cover at least one full "khoảng liền trước cùng độ dài"
 * as well as the rolling-rate minimum, or a wide selected range would have no
 * previous window fully fetched to compare against.
 */
function lookbackFrom(from: string, to: string): string {
  const parsed = parseIsoDate(from);
  if (parsed === null) {
    return from;
  }
  const spanDays = dateRangeSpanDays(from, to) ?? MIN_ROLLING_LOOKBACK_DAYS;
  const lookbackDays = Math.max(MIN_ROLLING_LOOKBACK_DAYS, spanDays);
  const shifted = new Date(parsed);
  shifted.setUTCDate(parsed.getUTCDate() - lookbackDays);
  return shifted.toISOString().slice(0, 10);
}

export function useDayRangeAggregates({
  from,
  to,
  weekDefinition,
  enabled,
}: {
  readonly from: string;
  readonly to: string;
  readonly weekDefinition: WeekDefinition;
  readonly enabled: boolean;
}) {
  const openedFrom = lookbackFrom(from, to);
  const query = {
    aggregate: 1,
    opened_from: openedFrom,
    opened_to: to,
    week_definition: weekDefinition,
  } as const;

  return useQuery({
    queryKey: ["day-range-aggregates", query],
    enabled: enabled && from !== "" && to !== "",
    retry: false,
    queryFn: async ({ signal }): Promise<DayRangeAggregates> => {
      const parsed = parseDayAggregatesResponse(
        await fetchTicketPage(query, signal),
      );
      if (!parsed.ok) {
        throw new Error(parsed.message);
      }
      const allDays = [...parsed.data.days].sort((left, right) =>
        left.day.localeCompare(right.day),
      );
      const plottedDays = allDays.filter((day) => day.day >= from && day.day <= to);
      return { allDays, plottedDays };
    },
  });
}
