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
export const FRESHDESK_COOKIE_ENDPOINT = "/api/freshdesk-cookie";
export const TRACE_EXPLAIN_ENDPOINT = "/api/trace-explain";
export const AB_TEST_ENDPOINT = "/api/ab-test";
export const AB_TEST_DEFAULT_ENDPOINT = "/api/ab-test/default";
export const AB_TEST_MODELS_ENDPOINT = "/api/ab-test/models";

/** The backend rejects a refresh that does not carry this exact header. */
export const REFRESH_ACTION_HEADER = "X-Dashboard-Action";
export const REFRESH_ACTION_VALUE = "refresh";
export const FRESHDESK_COOKIE_ACTION_VALUE = "update_freshdesk_cookie";

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

export interface FreshdeskCookieState {
  readonly state: "ok" | "expired" | "missing";
  readonly updated_at: string | null;
  readonly last_verified_at: string | null;
}

export async function fetchFreshdeskCookieState(
  signal?: AbortSignal,
): Promise<FreshdeskCookieState> {
  const response = await fetch(FRESHDESK_COOKIE_ENDPOINT, {
    method: "GET",
    credentials: "same-origin",
    headers: JSON_HEADERS,
    ...(signal ? { signal } : {}),
  });
  return (await readJson(response)) as FreshdeskCookieState;
}

/** Throws DashboardRequestError(status) for 400/404/503 domain errors, same
 * as every other endpoint here -- the caller inspects `.status` to choose a
 * Vietnamese message instead of showing the raw code. */
export async function fetchTraceExplanation(
  ticketId: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetch(
    `${TRACE_EXPLAIN_ENDPOINT}/${encodeURIComponent(ticketId)}`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: JSON_HEADERS,
      ...(signal ? { signal } : {}),
    },
  );
  if (response.status !== 200) {
    throw new DashboardRequestError(response.status);
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new DashboardRequestError(response.status);
  }
}

/** Throws DashboardRequestError(status) for 400/404/503 domain errors, same
 * as fetchTraceExplanation -- separate request so the deterministic dossier
 * (and its own cache) never blocks on the trace_explain payload or vice versa. */
export async function fetchWhyExplanation(
  ticketId: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetch(
    `${TRACE_EXPLAIN_ENDPOINT}/${encodeURIComponent(ticketId)}/why`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: JSON_HEADERS,
      ...(signal ? { signal } : {}),
    },
  );
  if (response.status !== 200) {
    throw new DashboardRequestError(response.status);
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new DashboardRequestError(response.status);
  }
}

/** Separate from fetchWhyExplanation so its own (potentially slow, LLM-
 * dependent) loading state never blocks the deterministic dossier from
 * rendering. Only call once /why has returned llm_status === "pending". */
export async function fetchWhyNarration(
  ticketId: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await fetch(
    `${TRACE_EXPLAIN_ENDPOINT}/${encodeURIComponent(ticketId)}/why-narration`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: JSON_HEADERS,
      ...(signal ? { signal } : {}),
    },
  );
  if (response.status !== 200) {
    throw new DashboardRequestError(response.status);
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new DashboardRequestError(response.status);
  }
}

/** Throws DashboardRequestError(status) for 400/503 domain errors, same as
 * every other endpoint here -- the caller inspects `.status` to choose a
 * Vietnamese message instead of showing the raw code. */
export async function fetchAbTest(
  start: string,
  end: string,
  arms?: readonly string[],
  signal?: AbortSignal,
): Promise<unknown> {
  const params = new URLSearchParams({ start, end });
  if (arms && arms.length > 0) {
    params.set("arms", arms.join(","));
  }
  const response = await fetch(`${AB_TEST_ENDPOINT}?${params.toString()}`, {
    method: "GET",
    credentials: "same-origin",
    headers: JSON_HEADERS,
    ...(signal ? { signal } : {}),
  });
  if (response.status !== 200) {
    throw new DashboardRequestError(response.status);
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new DashboardRequestError(response.status);
  }
}

/** Which models currently have Langfuse traffic, most active first, each
 * with its cached (or freshly discovered) first-seen timestamp -- the data
 * source for the A/B picker and its auto default window. */
export async function fetchAbTestModels(signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(AB_TEST_MODELS_ENDPOINT, {
    method: "GET",
    credentials: "same-origin",
    headers: JSON_HEADERS,
    ...(signal ? { signal } : {}),
  });
  if (response.status !== 200) {
    throw new DashboardRequestError(response.status);
  }
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new DashboardRequestError(response.status);
  }
}

/** Envelope shape mirrors /api/dashboard: 202 "not ready yet" is a normal
 * read, not a failure -- only an unexpected status/body throws. */
export interface AbTestDefaultEnvelope {
  readonly status: "ready" | "loading" | "stale_error";
  readonly data: unknown;
  readonly last_error_code?: string | null;
}

export async function fetchAbTestDefault(
  signal?: AbortSignal,
): Promise<AbTestDefaultEnvelope> {
  const response = await fetch(AB_TEST_DEFAULT_ENDPOINT, {
    method: "GET",
    credentials: "same-origin",
    headers: JSON_HEADERS,
    ...(signal ? { signal } : {}),
  });
  if (response.status !== 200 && response.status !== 202) {
    throw new DashboardRequestError(response.status);
  }
  try {
    return (await response.json()) as AbTestDefaultEnvelope;
  } catch {
    throw new DashboardRequestError(response.status);
  }
}

/** Throws DashboardRequestError(400) when the backend rejects the cookie
 * itself (invalid or expired) after its one live verify call. */
export async function updateFreshdeskCookie(
  cookie: string,
): Promise<FreshdeskCookieState> {
  const response = await fetch(FRESHDESK_COOKIE_ENDPOINT, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      ...JSON_HEADERS,
      "Content-Type": "application/json",
      [REFRESH_ACTION_HEADER]: FRESHDESK_COOKIE_ACTION_VALUE,
    },
    body: JSON.stringify({ cookie }),
  });
  return (await readJson(response)) as FreshdeskCookieState;
}
