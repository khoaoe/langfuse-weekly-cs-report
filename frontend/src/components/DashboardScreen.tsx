import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { WeekDefinition } from "../lib/dashboard-schema";
import {
  EMPTY_TICKET_FILTERS,
  activeTicketFilterChips,
  type TicketFilterKey,
  type TicketFilters,
  updateTicketFilters,
} from "../lib/dashboard-filters";
import { useDashboardRuntime } from "../hooks/useDashboardRuntime";
import { useDayRangeAggregates } from "../hooks/useDayRangeAggregates";
import { useFreshdeskCookieStatus } from "../hooks/useFreshdeskCookieStatus";
import {
  ALL_WEEKS_SCOPE,
  SELECTED_WEEKS_SCOPE,
  isObservedWeek,
  selectLatestWeek,
  selectView,
} from "../lib/selectors";
import {
  buildDayRangeWeekLabels,
  scopeSnapshotToDayRangeSnapshot,
  scopeSnapshotToWeeks,
} from "../lib/report-scope";
import { formatDateRangeLabel } from "../lib/format";
import { AbTestSection } from "./AbTestSection";
import { AppShell } from "./AppShell";
import { BelowFold } from "./BelowFold";
import { DecisionLedger } from "./DecisionLedger";
import { FreshdeskCookieDialog } from "./FreshdeskCookieDialog";
import { TicketExplorer } from "./TicketExplorer";
import { WeeklyReport } from "./WeeklyReport";
import styles from "./dashboard.module.css";

function scrollToSection(id: string, focusId?: string) {
  const section = document.getElementById(id);
  if (typeof section?.scrollIntoView === "function") {
    section.scrollIntoView({ block: "start" });
  }
  const focusTarget =
    focusId === undefined ? section : document.getElementById(focusId);
  if (focusTarget instanceof HTMLElement) {
    focusTarget.focus({ preventScroll: true });
  }
}

type ReportScopeState =
  | { readonly mode: "latest" }
  | { readonly mode: "all" }
  | { readonly mode: "weeks"; readonly weeks: readonly string[] }
  | { readonly mode: "range"; readonly from: string; readonly to: string };

function explorerWeekPatch(value: "all" | readonly string[]) {
  if (value === "all") {
    return { cohort_week: "", cohort_weeks: "" } as const;
  }
  if (value.length === 1) {
    return { cohort_week: value[0] ?? "", cohort_weeks: "" } as const;
  }
  return { cohort_week: "", cohort_weeks: value.join(",") } as const;
}

/** True day-grain range: Explorer syncs by the exact opened-date range, never
 * a week snap — unlike explorerWeekPatch(), which is week-shaped scope only. */
function explorerDayRangePatch(from: string, to: string) {
  return { opened_from: from, opened_to: to } as const;
}

function DashboardBody() {
  const [weekDefinition, setWeekDefinition] = useState<WeekDefinition>("mon_fri");
  const [reportScope, setReportScope] = useState<ReportScopeState>({
    mode: "latest",
  });
  const [filters, setFilters] = useState<TicketFilters>(EMPTY_TICKET_FILTERS);
  const [activeDay, setActiveDay] = useState("");
  const { state, refresh, refreshDisabled, refreshHint } = useDashboardRuntime();
  const { state: freshdeskCookie, submitCookie } = useFreshdeskCookieStatus();
  const [cookieDialogOpen, setCookieDialogOpen] = useState(false);
  const snapshot = state.snapshot;
  const isDayRangeMode = reportScope.mode === "range";
  const reportView =
    snapshot === null ? null : selectView(snapshot, weekDefinition);
  const latestReportWeek =
    reportView === null ? null : selectLatestWeek(reportView);
  const observedReportWeeks = useMemo(
    () =>
      reportView === null
        ? []
        : reportView.weekly
            .filter((week) => week.has_data)
            .map((week) => week.cohort_week)
            .sort((left, right) => right.localeCompare(left)),
    [reportView],
  );
  const dayRangeQuery = useDayRangeAggregates({
    from: reportScope.mode === "range" ? reportScope.from : "",
    to: reportScope.mode === "range" ? reportScope.to : "",
    weekDefinition,
    enabled: isDayRangeMode,
  });
  const selectedReportWeeks = useMemo(() => {
    if (reportScope.mode === "all") {
      return observedReportWeeks;
    }
    if (reportScope.mode === "latest" || reportScope.mode === "range") {
      return latestReportWeek === null ? [] : [latestReportWeek.cohort_week];
    }
    const observed = new Set(observedReportWeeks);
    const selected = reportScope.weeks.filter((week) => observed.has(week));
    return selected.length > 0
      ? selected
      : latestReportWeek === null
        ? []
        : [latestReportWeek.cohort_week];
  }, [latestReportWeek, observedReportWeeks, reportScope]);
  const allReportWeeksSelected = reportScope.mode === "all";
  const multiWeekSelection =
    !isDayRangeMode && !allReportWeeksSelected && selectedReportWeeks.length > 1;
  const reportWeek =
    !isDayRangeMode && !allReportWeeksSelected && selectedReportWeeks.length === 1
      ? (selectedReportWeeks[0] ?? "")
      : "";
  const ledgerScope = allReportWeeksSelected
    ? ALL_WEEKS_SCOPE
    : multiWeekSelection
      ? SELECTED_WEEKS_SCOPE
      : reportWeek;
  const dayRangeData = isDayRangeMode ? dayRangeQuery.data : undefined;
  const reportSnapshot = useMemo(() => {
    if (snapshot === null) {
      return snapshot;
    }
    if (isDayRangeMode) {
      return dayRangeData === undefined
        ? null
        : scopeSnapshotToDayRangeSnapshot(
            snapshot,
            weekDefinition,
            dayRangeData.plottedDays,
          );
    }
    return multiWeekSelection
      ? scopeSnapshotToWeeks(snapshot, weekDefinition, selectedReportWeeks)
      : snapshot;
  }, [
    dayRangeData,
    isDayRangeMode,
    multiWeekSelection,
    reportScope,
    selectedReportWeeks,
    snapshot,
    weekDefinition,
  ]);
  const dayRangeProps = useMemo(() => {
    if (
      !isDayRangeMode ||
      reportScope.mode !== "range" ||
      dayRangeData === undefined ||
      snapshot === null
    ) {
      return {};
    }
    return {
      dayRange: {
        from: reportScope.from,
        to: reportScope.to,
        allDays: dayRangeData.allDays,
        plottedDays: dayRangeData.plottedDays,
        activeDay,
        onDaySelect: setActiveDay,
      },
      weeklySnapshot: snapshot,
    };
  }, [activeDay, dayRangeData, isDayRangeMode, reportScope, snapshot]);
  const weeklyReportDayRangeProps = useMemo(() => {
    if (!isDayRangeMode || reportScope.mode !== "range" || dayRangeData === undefined) {
      return {};
    }
    return {
      dayRangeWeekLabels: buildDayRangeWeekLabels(dayRangeData.plottedDays),
      dayRangeLabel: formatDateRangeLabel(reportScope.from, reportScope.to),
    };
  }, [dayRangeData, isDayRangeMode, reportScope]);
  const currentExplorerWeekPatch = useMemo(
    () =>
      isDayRangeMode && reportScope.mode === "range"
        ? explorerDayRangePatch(reportScope.from, reportScope.to)
        : explorerWeekPatch(allReportWeeksSelected ? "all" : selectedReportWeeks),
    [allReportWeeksSelected, isDayRangeMode, reportScope, selectedReportWeeks],
  );
  const hasSnapshot = snapshot !== null;
  const activeFilters = useMemo(
    () => activeTicketFilterChips(filters, weekDefinition),
    [filters, weekDefinition],
  );
  const shellFilters = useMemo(
    () =>
      activeFilters.filter(
        (filter) =>
          filter.key !== "cohort_week" && filter.key !== "cohort_weeks",
      ),
    [activeFilters],
  );

  // Global report scope flows into Explorer once per distinct scope value. A
  // later local Explorer change (a different week, or an opened-date range)
  // deliberately does not flow back into the report, and must survive
  // background snapshot refreshes: every successful poll produces a new
  // `currentExplorerWeekPatch` object even when its cohort_week/cohort_weeks
  // strings are unchanged, so comparing by object identity (or re-running
  // this effect on every such object) would silently clobber the user's own
  // filter choice on the next refresh. Tracking the last-applied scope by
  // value, not by object reference, makes the "once" in the comment above
  // actually true.
  const syncedWeekPatchKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!hasSnapshot) {
      return;
    }
    // The "opened_from" branch below is defensive: today, changeReportRange
    // is the only setter of scope "range" and it always applies its own
    // opened_from/opened_to patch synchronously in the same action, so this
    // effect never actually observes a day-range patchKey change in practice
    // (verified: no test can force it RED). Keep the branch correct anyway
    // in case a future caller sets "range" scope without also patching
    // filters itself.
    const patchKey =
      "opened_from" in currentExplorerWeekPatch
        ? `range|${currentExplorerWeekPatch.opened_from}|${currentExplorerWeekPatch.opened_to}`
        : `weeks|${currentExplorerWeekPatch.cohort_week}|${currentExplorerWeekPatch.cohort_weeks}`;
    if (syncedWeekPatchKeyRef.current === patchKey) {
      return;
    }
    syncedWeekPatchKeyRef.current = patchKey;
    setFilters((current) => updateTicketFilters(current, currentExplorerWeekPatch));
  }, [currentExplorerWeekPatch, hasSnapshot]);

  useEffect(() => {
    if (reportView === null || isDayRangeMode) {
      return;
    }
    setFilters((current) =>
      current.cohort_week === "" ||
      isObservedWeek(reportView, current.cohort_week)
        ? current
        : updateTicketFilters(current, currentExplorerWeekPatch),
    );
  }, [currentExplorerWeekPatch, isDayRangeMode, reportView]);

  const removeFilter = useCallback((key: TicketFilterKey) => {
    setFilters((current) => updateTicketFilters(current, { [key]: "" }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(EMPTY_TICKET_FILTERS);
  }, []);

  const changeReportWeeks = useCallback((scope: "all" | readonly string[]) => {
    setReportScope(
      scope === "all"
        ? { mode: "all" }
        : { mode: "weeks", weeks: [...scope] },
    );
    setFilters((current) =>
      updateTicketFilters(current, explorerWeekPatch(scope)),
    );
  }, []);

  const changeReportRange = useCallback(
    (from: string, to: string) => {
      if (from === "" && to === "") {
        changeReportWeeks("all");
        return;
      }
      setReportScope({ mode: "range", from, to });
      setActiveDay("");
      setFilters((current) =>
        updateTicketFilters(current, explorerDayRangePatch(from, to)),
      );
    },
    [changeReportWeeks],
  );

  const applyExplorerFilter = useCallback((patch: Partial<TicketFilters>) => {
    setFilters((current) =>
      updateTicketFilters(current, { ...currentExplorerWeekPatch, ...patch }),
    );
    window.setTimeout(() => {
      scrollToSection("tickets", "tickets-title");
    }, 0);
  }, [currentExplorerWeekPatch]);

  const applyLedgerFilter = useCallback((patch: Partial<TicketFilters>) => {
    setFilters(() => ({
      ...EMPTY_TICKET_FILTERS,
      ...currentExplorerWeekPatch,
      ...patch,
    }));
    window.setTimeout(() => {
      scrollToSection("tickets", "tickets-title");
    }, 0);
  }, [currentExplorerWeekPatch]);
  const showStuckTickets = useCallback((cohortWeek: string) => {
    applyLedgerFilter({
      cohort_week: cohortWeek,
      cohort_weeks: "",
      gt4_turn: "true",
      transferred: "false",
    });
  }, [applyLedgerFilter]);

  return (
    <>
    <AppShell
      weekDefinition={weekDefinition}
      onWeekDefinitionChange={setWeekDefinition}
      snapshot={snapshot}
      statusMessage={state.message}
      onRefresh={refresh}
      refreshDisabled={refreshDisabled}
      refreshHint={refreshHint}
      runtimeKind={state.kind}
      selectedReportWeeks={selectedReportWeeks}
      allReportWeeksSelected={allReportWeeksSelected}
      onReportWeeksChange={changeReportWeeks}
      reportRange={reportScope.mode === "range" ? reportScope : null}
      onReportRangeChange={changeReportRange}
      activeFilters={shellFilters}
      onRemoveFilter={removeFilter}
      onResetFilters={resetFilters}
      freshdeskCookieState={freshdeskCookie?.state ?? null}
      onOpenFreshdeskCookieDialog={() => setCookieDialogOpen(true)}
    >
      {snapshot === null ? (
        <div
          className={styles.skeleton}
          data-testid="dashboard-skeleton"
          aria-hidden="true"
        >
          <span className={styles.skeletonTitle} />
          <span className={styles.skeletonLine} />
          <span className={styles.skeletonLineShort} />
          <div className={styles.skeletonLedger}>
            {Array.from({ length: 4 }, (_, index) => (
              <span key={index} />
            ))}
          </div>
        </div>
      ) : reportSnapshot === null ? (
        <div
          className={styles.skeleton}
          data-testid="day-range-skeleton"
          aria-hidden="true"
        >
          <span className={styles.skeletonTitle} />
          <span className={styles.skeletonLine} />
          <span className={styles.skeletonLineShort} />
          <div className={styles.skeletonLedger}>
            {Array.from({ length: 4 }, (_, index) => (
              <span key={index} />
            ))}
          </div>
        </div>
      ) : (
        <>
          <DecisionLedger
            snapshot={reportSnapshot}
            weekDefinition={weekDefinition}
            activeWeek={ledgerScope}
            reportRange={reportScope.mode === "range" ? reportScope : null}
            onCellSelect={applyLedgerFilter}
          />
          <WeeklyReport
            snapshot={reportSnapshot}
            weekDefinition={weekDefinition}
            {...weeklyReportDayRangeProps}
          />
          <BelowFold
            snapshot={reportSnapshot}
            {...dayRangeProps}
            weekDefinition={weekDefinition}
            activeWeek={reportWeek}
            allWeeks={allReportWeeksSelected || multiWeekSelection}
            onWeekSelect={(week) => changeReportWeeks([week])}
            onSegmentSelect={(key, value) => {
              applyExplorerFilter({ [key]: value });
            }}
            onShowStuckTickets={showStuckTickets}
            onTicketFilterSelect={applyExplorerFilter}
            activeCsatBreakdownFilters={{
              outcome: filters.outcome,
              skill: filters.skill,
              issue_category: filters.issue_category,
            }}
            onCsatBreakdownGroupingChange={() => {
              setFilters((current) =>
                updateTicketFilters(current, {
                  outcome: "",
                  skill: "",
                  issue_category: "",
                }),
              );
            }}
            onCsatBreakdownSelect={(grouping, value) => {
              setFilters(() => ({
                ...EMPTY_TICKET_FILTERS,
                ...currentExplorerWeekPatch,
                [grouping]: value,
              }));
            }}
            freshdeskCookieState={freshdeskCookie?.state ?? null}
            onOpenFreshdeskCookieDialog={() => setCookieDialogOpen(true)}
          />
          <TicketExplorer
            snapshot={snapshot}
            weekDefinition={weekDefinition}
            enabled={state.kind !== "loading"}
            filters={filters}
            onFiltersChange={setFilters}
          />
        </>
      )}
      {/* Independent of the weekly snapshot: this reads Langfuse directly on
          its own time window, so it must not wait on the (slower, more
          fragile) full weekly pipeline. */}
      <AbTestSection
        selectedReportWeeks={selectedReportWeeks}
        weekDefinition={weekDefinition}
        reportRange={reportScope.mode === "range" ? reportScope : null}
      />
    </AppShell>
    <FreshdeskCookieDialog
      open={cookieDialogOpen}
      onClose={() => setCookieDialogOpen(false)}
      onSubmit={submitCookie}
    />
    </>
  );
}

/**
 * The whole dashboard screen.
 *
 * Switching cohort is a client-only view change: both `mon_sun` and `mon_fri`
 * already travel inside one envelope, so the toggle never issues a request and
 * never invalidates the report the operator is reading.
 */
export function DashboardScreen() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
            gcTime: 10 * 60 * 1_000,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <DashboardBody />
    </QueryClientProvider>
  );
}
