import { useQuery } from "@tanstack/react-query";

import { fetchTicketPage } from "../lib/api";
import {
  parseDayAggregatesResponse,
  type DayAggregate,
  type WeekDefinition,
} from "../lib/dashboard-schema";
import { parseIsoDate } from "../lib/format";

/** §B1's rolling rate needs 6 days of history before the first plotted point. */
const ROLLING_LOOKBACK_DAYS = 6;

export interface DayRangeAggregates {
  /** Lookback window + plotted range, in chronological order — feeds rollingRate(). */
  readonly allDays: readonly DayAggregate[];
  /** Exactly the selected from...to range, for rendering (never the lookback days). */
  readonly plottedDays: readonly DayAggregate[];
}

function lookbackFrom(from: string): string {
  const parsed = parseIsoDate(from);
  if (parsed === null) {
    return from;
  }
  const shifted = new Date(parsed);
  shifted.setUTCDate(parsed.getUTCDate() - ROLLING_LOOKBACK_DAYS);
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
  const openedFrom = lookbackFrom(from);
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
