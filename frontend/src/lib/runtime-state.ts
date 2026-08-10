import {
  type DashboardSnapshot,
  parseDashboardEnvelope,
} from "./dashboard-schema";

export type DashboardRuntimeKind =
  | "loading"
  | "ready"
  | "refreshing"
  | "stale_error";

export interface DashboardRuntime {
  readonly kind: DashboardRuntimeKind;
  readonly snapshot: DashboardSnapshot | null;
  readonly message: string;
}

export type DashboardRuntimeAction =
  | { readonly type: "envelope"; readonly envelope: unknown }
  | { readonly type: "refresh-start" }
  | { readonly type: "request-failed"; readonly errorCode?: string | null };

const LOADING_MESSAGE = "Đang tải dữ liệu dashboard.";
const REFRESHING_MESSAGE = "Đang làm mới dữ liệu.";
const STALE_MESSAGE =
  "Không thể tải dữ liệu mới. Đang hiển thị dữ liệu gần nhất.";
const NO_DATA_MESSAGE = "Chưa tải được dữ liệu dashboard. Hệ thống sẽ thử lại.";

export function initialDashboardRuntime(): DashboardRuntime {
  return { kind: "loading", snapshot: null, message: LOADING_MESSAGE };
}

function messageFor(kind: DashboardRuntimeKind, hasSnapshot: boolean): string {
  switch (kind) {
    case "loading":
      return LOADING_MESSAGE;
    case "refreshing":
      return REFRESHING_MESSAGE;
    case "stale_error":
      return hasSnapshot ? STALE_MESSAGE : NO_DATA_MESSAGE;
    case "ready":
      return "";
  }
}

function transition(
  kind: DashboardRuntimeKind,
  snapshot: DashboardSnapshot | null,
): DashboardRuntime {
  return { kind, snapshot, message: messageFor(kind, snapshot !== null) };
}

/**
 * Folds server envelopes and user actions into the four runtime states.
 *
 * The last successfully parsed snapshot is retained across refreshes and
 * failures so an operator never loses the report they were reading, and the
 * server error code is never placed in user-facing text.
 */
export function reduceDashboardRuntime(
  state: DashboardRuntime,
  action: DashboardRuntimeAction,
): DashboardRuntime {
  switch (action.type) {
    case "refresh-start":
      return transition(
        state.snapshot === null ? "loading" : "refreshing",
        state.snapshot,
      );

    case "request-failed":
      return transition("stale_error", state.snapshot);

    case "envelope": {
      const parsed = parseDashboardEnvelope(action.envelope);
      if (!parsed.ok) {
        // A payload we cannot verify is treated as a failed read rather than
        // rendered optimistically.
        return transition("stale_error", state.snapshot);
      }

      const snapshot = parsed.data.snapshot ?? state.snapshot;
      if (snapshot === null) {
        return transition("loading", null);
      }
      if (parsed.data.status === "stale_error") {
        return transition("stale_error", snapshot);
      }
      if (parsed.data.status === "refreshing" || parsed.data.refreshing) {
        return transition("refreshing", snapshot);
      }
      return transition("ready", snapshot);
    }
  }
}
