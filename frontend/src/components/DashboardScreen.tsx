import { useCallback, useEffect, useMemo, useState } from "react";
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
import { useFreshdeskCookieStatus } from "../hooks/useFreshdeskCookieStatus";
import {
  ALL_WEEKS_SCOPE,
  SELECTED_WEEKS_SCOPE,
  isObservedWeek,
  selectLatestWeek,
  selectView,
} from "../lib/selectors";
import { scopeSnapshotToWeeks } from "../lib/report-scope";
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
  | { readonly mode: "weeks"; readonly weeks: readonly string[] };

function explorerWeekPatch(value: "all" | readonly string[]) {
  if (value === "all") {
    return { cohort_week: "", cohort_weeks: "" } as const;
  }
  if (value.length === 1) {
    return { cohort_week: value[0] ?? "", cohort_weeks: "" } as const;
  }
  return { cohort_week: "", cohort_weeks: value.join(",") } as const;
}

function DashboardBody() {
  const [weekDefinition, setWeekDefinition] = useState<WeekDefinition>("mon_fri");
  const [reportScope, setReportScope] = useState<ReportScopeState>({
    mode: "latest",
  });
  const [filters, setFilters] = useState<TicketFilters>(EMPTY_TICKET_FILTERS);
  const [qualityExpanded, setQualityExpanded] = useState(false);
  const { state, refresh, refreshDisabled, refreshHint } = useDashboardRuntime();
  const { state: freshdeskCookie, submitCookie } = useFreshdeskCookieStatus();
  const [cookieDialogOpen, setCookieDialogOpen] = useState(false);
  const snapshot = state.snapshot;
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
  const selectedReportWeeks = useMemo(() => {
    if (reportScope.mode === "all") {
      return observedReportWeeks;
    }
    if (reportScope.mode === "latest") {
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
    !allReportWeeksSelected && selectedReportWeeks.length > 1;
  const reportWeek =
    !allReportWeeksSelected && selectedReportWeeks.length === 1
      ? (selectedReportWeeks[0] ?? "")
      : "";
  const ledgerScope = allReportWeeksSelected
    ? ALL_WEEKS_SCOPE
    : multiWeekSelection
      ? SELECTED_WEEKS_SCOPE
      : reportWeek;
  const reportSnapshot = useMemo(
    () =>
      snapshot === null || !multiWeekSelection
        ? snapshot
        : scopeSnapshotToWeeks(snapshot, weekDefinition, selectedReportWeeks),
    [multiWeekSelection, selectedReportWeeks, snapshot, weekDefinition],
  );
  const currentExplorerWeekPatch = useMemo(
    () =>
      explorerWeekPatch(
        allReportWeeksSelected ? "all" : selectedReportWeeks,
      ),
    [allReportWeeksSelected, selectedReportWeeks],
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

  // Global report scope flows into Explorer once. A later local Explorer week
  // change deliberately does not flow back into the report.
  useEffect(() => {
    if (!hasSnapshot) {
      return;
    }
    setFilters((current) =>
      current.cohort_week === currentExplorerWeekPatch.cohort_week &&
      current.cohort_weeks === currentExplorerWeekPatch.cohort_weeks
        ? current
        : updateTicketFilters(current, currentExplorerWeekPatch),
    );
  }, [currentExplorerWeekPatch, hasSnapshot]);

  useEffect(() => {
    if (reportView === null) {
      return;
    }
    setFilters((current) =>
      current.cohort_week === "" ||
      isObservedWeek(reportView, current.cohort_week)
        ? current
        : updateTicketFilters(current, currentExplorerWeekPatch),
    );
  }, [currentExplorerWeekPatch, reportView]);

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
      ) : (
        <>
          <DecisionLedger
            snapshot={reportSnapshot ?? snapshot}
            weekDefinition={weekDefinition}
            activeWeek={ledgerScope}
            onCellSelect={applyLedgerFilter}
          />
          <WeeklyReport
            snapshot={reportSnapshot ?? snapshot}
            weekDefinition={weekDefinition}
          />
          <BelowFold
            snapshot={reportSnapshot ?? snapshot}
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
            qualityExpanded={qualityExpanded}
            onQualityExpandedChange={setQualityExpanded}
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
