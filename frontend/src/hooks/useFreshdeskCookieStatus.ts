import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchFreshdeskCookieState,
  updateFreshdeskCookie,
  type FreshdeskCookieState,
} from "../lib/api";

/** Cookie expiry is measured in days, not minutes -- no need to poll fast. */
const POLL_MS = 5 * 60 * 1_000;

export interface FreshdeskCookieController {
  readonly state: FreshdeskCookieState | null;
  readonly submitCookie: (cookie: string) => Promise<boolean>;
}

/** Owns the Freshdesk-cookie status read loop and the update mutation. */
export function useFreshdeskCookieStatus(): FreshdeskCookieController {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["freshdesk-cookie-state"],
    queryFn: ({ signal }) => fetchFreshdeskCookieState(signal),
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: POLL_MS,
  });

  const submitCookie = useCallback(
    async (cookie: string): Promise<boolean> => {
      try {
        await updateFreshdeskCookie(cookie);
      } catch {
        return false;
      }
      await queryClient.invalidateQueries({
        queryKey: ["freshdesk-cookie-state"],
      });
      return true;
    },
    [queryClient],
  );

  return { state: query.data ?? null, submitCookie };
}
