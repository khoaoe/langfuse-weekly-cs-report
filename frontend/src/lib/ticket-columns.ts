/**
 * Ticket Explorer column visibility.
 *
 * The allowlist is the sanitised v15 ticket projection and nothing else: any
 * key that ever appeared in storage but is not in this list — including keys
 * that could carry raw payloads or internal Langfuse identifiers — is dropped
 * on read, so a tampered or stale localStorage value can never widen the UI.
 * `tpe_status` remains in the API storage shape for compatibility, but is not
 * a source-faithful product field and must not be renderable or exportable.
 */
export const LEGACY_TICKET_COLUMN_STORAGE_KEY = "weekly-cs-ticket-columns-v1";
const V2_TICKET_COLUMN_STORAGE_KEY = "weekly-cs-ticket-columns-v2";
export const PREVIOUS_TICKET_COLUMN_STORAGE_KEY = "weekly-cs-ticket-columns-v3";
// Not bumped for `tool_error_codes`: the column is off by default, so every
// stored v4 selection stays valid and only gains a newly allowlisted key.
export const TICKET_COLUMN_STORAGE_KEY = "weekly-cs-ticket-columns-v4";

export const TICKET_COLUMNS = [
  { key: "ticket_id", label: "Ticket", core: true },
  { key: "opened_at", label: "Thời gian mở", core: true },
  { key: "cohort_week", label: "Tuần", core: true },
  { key: "cohort_status", label: "Trạng thái tuần", core: false },
  { key: "is_weekend_start", label: "Bắt đầu cuối tuần", core: false },
  { key: "outcome", label: "Kết quả", core: true },
  {
    key: "csat_satisfaction",
    label: "CSAT",
    core: true,
  },
  { key: "ai_first", label: "AI First", core: false },
  { key: "transferred", label: "Đã chuyển CS", core: true },
  { key: "transfer_reason", label: "Lý do chuyển CS", core: true },
  { key: "reopen_lifetime", label: "Số lần reopen", core: false },
  { key: "reopen_within_7d", label: "Reopen trong 7 ngày", core: false },
  { key: "ai_reply_count", label: "Phản hồi AI", core: false },
  { key: "turn_count", label: "Tổng lượt xử lý", core: true },
  { key: "gt4_turn", label: ">3 lượt xử lý", core: true },
  { key: "issue_category", label: "Category", core: false },
  { key: "app", label: "App", core: false },
  { key: "product_code", label: "Product Code", core: false },
  { key: "skill", label: "Skill", core: false },
  { key: "intent", label: "Intent", core: false },
  { key: "tpe_code", label: "Transstatus", core: false },
  { key: "model_core", label: "Model", core: false },
  { key: "tool_error_codes", label: "Lỗi gọi tool", core: false },
  {
    key: "escalation_guard_blocked",
    label: "Chặn chuyển CS trùng",
    core: false,
  },
  { key: "data_quality", label: "Chất lượng dữ liệu", core: false },
] as const satisfies readonly { key: string; label: string; core: boolean }[];

export type TicketColumnKey = (typeof TICKET_COLUMNS)[number]["key"];

const ALLOWED_KEYS: ReadonlySet<string> = new Set(
  TICKET_COLUMNS.map((column) => column.key),
);

export const DEFAULT_TICKET_COLUMNS: readonly TicketColumnKey[] =
  TICKET_COLUMNS.filter((column) => column.core).map((column) => column.key);

function allowlist(values: readonly unknown[]): TicketColumnKey[] {
  const seen = new Set<string>();
  const kept: TicketColumnKey[] = [];
  for (const value of values) {
    if (typeof value !== "string" || seen.has(value) || !ALLOWED_KEYS.has(value)) {
      continue;
    }
    seen.add(value);
    kept.push(value as TicketColumnKey);
  }
  return kept;
}

function withMandatoryTicketFirst(
  columns: readonly TicketColumnKey[],
): TicketColumnKey[] {
  return [
    "ticket_id",
    ...columns.filter((column) => column !== "ticket_id"),
  ];
}

export function readVisibleTicketColumns(): readonly TicketColumnKey[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(TICKET_COLUMN_STORAGE_KEY);
  } catch {
    return DEFAULT_TICKET_COLUMNS;
  }
  if (raw !== null) {
    return parseStoredColumns(raw);
  }

  let previousRaw: string | null = null;
  try {
    previousRaw = localStorage.getItem(PREVIOUS_TICKET_COLUMN_STORAGE_KEY);
  } catch {
    return DEFAULT_TICKET_COLUMNS;
  }
  if (previousRaw !== null) {
    const migrated = insertTransferReason(parseStoredColumns(previousRaw));
    try {
      localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, JSON.stringify(migrated));
    } catch {
      // The migrated in-memory selection remains usable when storage is blocked.
    }
    return migrated;
  }

  let v2Raw: string | null = null;
  try {
    v2Raw = localStorage.getItem(V2_TICKET_COLUMN_STORAGE_KEY);
  } catch {
    return DEFAULT_TICKET_COLUMNS;
  }
  if (v2Raw !== null) {
    const migrated = insertTransferReason(
      insertOpenedAt(parseStoredColumns(v2Raw)),
    );
    try {
      localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, JSON.stringify(migrated));
    } catch {
      // The migrated in-memory selection remains usable when storage is blocked.
    }
    return migrated;
  }

  let legacyRaw: string | null = null;
  try {
    legacyRaw = localStorage.getItem(LEGACY_TICKET_COLUMN_STORAGE_KEY);
  } catch {
    return DEFAULT_TICKET_COLUMNS;
  }
  if (legacyRaw === null) {
    return DEFAULT_TICKET_COLUMNS;
  }
  const legacy = parseStoredColumns(legacyRaw);
  const migrated = insertTransferReason(
    insertOpenedAt(insertSatisfaction(legacy)),
  );
  try {
    localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, JSON.stringify(migrated));
  } catch {
    // The migrated in-memory selection remains usable when storage is blocked.
  }
  return migrated;
}

function insertOpenedAt(
  columns: readonly TicketColumnKey[],
): readonly TicketColumnKey[] {
  if (columns.includes("opened_at")) {
    return columns;
  }
  const ticketIndex = columns.indexOf("ticket_id");
  const index = ticketIndex < 0 ? 0 : ticketIndex + 1;
  return [
    ...columns.slice(0, index),
    "opened_at",
    ...columns.slice(index),
  ];
}

function parseStoredColumns(raw: string): readonly TicketColumnKey[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return DEFAULT_TICKET_COLUMNS;
  }
  if (!Array.isArray(parsed)) {
    return DEFAULT_TICKET_COLUMNS;
  }

  const kept = allowlist(parsed);
  if (parsed.length > 0 && kept.length === 0) {
    return DEFAULT_TICKET_COLUMNS;
  }
  return withMandatoryTicketFirst(kept);
}

function insertSatisfaction(
  columns: readonly TicketColumnKey[],
): readonly TicketColumnKey[] {
  if (columns.includes("csat_satisfaction")) {
    return columns;
  }
  const anchor = columns.includes("outcome")
    ? "outcome"
    : columns.includes("cohort_week")
      ? "cohort_week"
      : "ticket_id";
  const index = columns.indexOf(anchor);
  return [
    ...columns.slice(0, index + 1),
    "csat_satisfaction",
    ...columns.slice(index + 1),
  ];
}

function insertTransferReason(
  columns: readonly TicketColumnKey[],
): readonly TicketColumnKey[] {
  if (columns.includes("transfer_reason")) {
    return columns;
  }
  const anchor = columns.includes("transferred")
    ? "transferred"
    : columns.includes("outcome")
      ? "outcome"
      : columns.includes("opened_at")
        ? "opened_at"
        : "ticket_id";
  const index = columns.indexOf(anchor);
  return [
    ...columns.slice(0, index + 1),
    "transfer_reason",
    ...columns.slice(index + 1),
  ];
}

export function writeVisibleTicketColumns(
  columns: readonly unknown[],
): readonly TicketColumnKey[] {
  const kept = allowlist(columns);
  const normalised =
    columns.length > 0 && kept.length === 0
      ? [...DEFAULT_TICKET_COLUMNS]
      : withMandatoryTicketFirst(kept);
  try {
    localStorage.setItem(TICKET_COLUMN_STORAGE_KEY, JSON.stringify(normalised));
  } catch {
    // Persistence is a convenience; a full or blocked store must not break the
    // session, and the in-memory selection is still returned to the caller.
  }
  return normalised;
}
