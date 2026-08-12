/**
 * Same-origin API client.
 *
 * Every request is relative, so the SPA can never reach a third party under
 * the strict `connect-src 'self'` policy. Server error bodies are discarded:
 * only an opaque status reaches the UI, and nothing from a response is ever
 * rendered as raw text.
 */
export const DASHBOARD_ENDPOINT = "/api/dashboard";
export const TICKETS_ENDPOINT = "/api/tickets";
export const ENTRY_COVERAGE_TICKETS_ENDPOINT =
  "/api/freshdesk-entry-coverage/tickets";
export const REFRESH_ENDPOINT = "/api/refresh";

/** The backend rejects a refresh that does not carry this exact header. */
export const REFRESH_ACTION_HEADER = "X-Dashboard-Action";
export const REFRESH_ACTION_VALUE = "refresh";

export class DashboardRequestError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`dashboard request failed with status ${status}`);
    this.name = "DashboardRequestError";
    this.status = status;
  }
}

const JSON_HEADERS: Readonly<Record<string, string>> = { Accept: "application/json" };

async function readJson(response: Response): Promise<unknown> {
  // `202 Accepted` is the documented "snapshot not built yet" answer and is a
  // successful read of the state envelope, not a failure.
  if (response.status !== 200 && response.status !== 202) {
    throw new DashboardRequestError(response.status);
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new DashboardRequestError(response.status);
  }
}

export async function fetchDashboardEnvelope(signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(DASHBOARD_ENDPOINT, {
    method: "GET",
    credentials: "same-origin",
    headers: JSON_HEADERS,
    ...(signal ? { signal } : {}),
  });
  return readJson(response);
}

export async function requestRefresh(signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(REFRESH_ENDPOINT, {
    method: "POST",
    credentials: "same-origin",
    headers: { ...JSON_HEADERS, [REFRESH_ACTION_HEADER]: REFRESH_ACTION_VALUE },
    ...(signal ? { signal } : {}),
  });
  return readJson(response);
}

export type TicketQuery = Readonly<
  Record<string, string | number | boolean | null | undefined>
>;

export function ticketQueryString(query: TicketQuery): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }
    params.set(name, String(value));
  }
  const serialised = params.toString();
  return serialised === "" ? "" : `?${serialised}`;
}

export async function fetchTicketPage(
  query: TicketQuery,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetch(`${TICKETS_ENDPOINT}${ticketQueryString(query)}`, {
    method: "GET",
    credentials: "same-origin",
    headers: JSON_HEADERS,
    ...(signal ? { signal } : {}),
  });
  return readJson(response);
}

export async function fetchEntryCoverageTicketPage(
  query: TicketQuery,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetch(
    `${ENTRY_COVERAGE_TICKETS_ENDPOINT}${ticketQueryString(query)}`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: JSON_HEADERS,
      ...(signal ? { signal } : {}),
    },
  );
  return readJson(response);
}
