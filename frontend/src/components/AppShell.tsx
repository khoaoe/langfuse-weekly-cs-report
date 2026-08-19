import { useEffect, useRef, useState, type ReactNode } from "react";

import logoColor from "../../../assets/brand/logos/zalopay-logo-color.png";
import logoWhite from "../../../assets/brand/logos/zalopay-logo-white.png";
import zMarkDark from "../../../assets/brand/graphics/zalopay-z-dark.png";
import zMarkLight from "../../../assets/brand/graphics/zalopay-z-light.png";
import type { DashboardSnapshot, WeekDefinition } from "../lib/dashboard-schema";
import type {
  ActiveFilterChip,
  TicketFilterKey,
} from "../lib/dashboard-filters";
import {
  DATA_STALE_DISPLAY_MS,
  calculateDataQualityScore,
} from "../lib/data-quality-score";
import { formatUpdatedAt } from "../lib/format";
import type { DashboardRuntimeKind } from "../lib/runtime-state";
import {
  COHORT_DESCRIPTIONS,
  COHORT_LABELS,
  selectView,
  selectWeekly,
} from "../lib/selectors";
import { ThemeToggle } from "./ThemeToggle";
import { ReportScopePicker } from "./ReportScopePicker";
import { TraceExplainer } from "./TraceExplainer";
import styles from "./dashboard.module.css";
import themeStyles from "./theme-toggle.module.css";

const WEEK_DEFINITIONS: readonly WeekDefinition[] = ["mon_fri", "mon_sun"];
const TRACE_HASH = /^#trace(?:\/(.*))?$/;

/** No react-router in this SPA (see CLAUDE.md) -- #trace/<ticketId> is parsed
 * by hand and swaps only the main content area; the brand header and section
 * nav stay so CS always has a way back to the dashboard. */
function traceHashTicketId(hash: string): string | null | undefined {
  const match = TRACE_HASH.exec(hash);
  if (match === null) {
    return undefined;
  }
  const raw = match[1];
  if (raw === undefined || raw === "") {
    return null;
  }
  try {
    return decodeURIComponent(raw);
  } catch {
    return null;
  }
}

const SECTIONS = [
  { id: "weekly", label: "Báo cáo tuần" },
  { id: "entry-coverage", label: "Độ phủ Freshdesk" },
  { id: "trend", label: "Xu hướng" },
  { id: "segments", label: "So sánh segment" },
  { id: "csat", label: "Mức hài lòng" },
  { id: "diagnostics", label: "Chẩn đoán" },
  { id: "tickets", label: "Ticket Explorer" },
  { id: "ab-test", label: "A/B Test" },
] as const;

export interface AppShellProps {
  readonly weekDefinition: WeekDefinition;
  readonly onWeekDefinitionChange: (value: WeekDefinition) => void;
  readonly snapshot: DashboardSnapshot | null;
  readonly statusMessage: string;
  readonly onRefresh: () => void;
  readonly refreshDisabled: boolean;
  readonly refreshHint: string;
  readonly runtimeKind: DashboardRuntimeKind;
  readonly selectedReportWeeks?: readonly string[];
  readonly allReportWeeksSelected?: boolean;
  readonly onReportWeeksChange?: (
    value: "all" | readonly string[],
  ) => void;
  readonly activeFilters: readonly ActiveFilterChip[];
  readonly onRemoveFilter: (key: TicketFilterKey) => void;
  readonly onResetFilters: () => void;
  readonly freshdeskCookieState?: "ok" | "expired" | "missing" | null;
  readonly onOpenFreshdeskCookieDialog?: () => void;
  readonly children: ReactNode;
}

/**
 * The sticky operating shell.
 *
 * The logo is decorative because the brand name is carried by adjacent text,
 * so assistive technology announces "Zalopay" exactly once. Both official
 * variants are present so CSS can select the system theme before React loads
 * and the reader's explicit theme after hydration, without inline script.
 */
export function AppShell({
  weekDefinition,
  onWeekDefinitionChange,
  snapshot,
  statusMessage,
  onRefresh,
  refreshDisabled,
  refreshHint,
  runtimeKind,
  selectedReportWeeks = [],
  allReportWeeksSelected = true,
  onReportWeeksChange = () => {},
  activeFilters,
  onRemoveFilter,
  onResetFilters,
  freshdeskCookieState = null,
  onOpenFreshdeskCookieDialog = () => {},
  children,
}: AppShellProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<
    (typeof SECTIONS)[number]["id"]
  >(SECTIONS[0].id);
  const [hash, setHash] = useState(() =>
    typeof window === "undefined" ? "" : window.location.hash,
  );
  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  const traceTicketId = traceHashTicketId(hash);
  const helpPanel = useRef<HTMLElement>(null);
  const helpButton = useRef<HTMLButtonElement>(null);
  const shellRef = useRef<HTMLElement>(null);
  const snapshotQuality =
    snapshot === null ? null : calculateDataQualityScore(snapshot);
  const displaysStale =
    runtimeKind === "stale_error" ||
    (snapshotQuality?.ageMs !== null &&
      snapshotQuality?.ageMs !== undefined &&
      snapshotQuality.ageMs > DATA_STALE_DISPLAY_MS);
  const displayedRuntimeKind = displaysStale ? "stale_error" : runtimeKind;
  const reportWindow =
    snapshot === null
      ? []
      : selectWeekly(selectView(snapshot, weekDefinition));

  useEffect(() => {
    if (helpOpen) {
      helpPanel.current?.focus();
    }
  }, [helpOpen]);

  useEffect(() => {
    const nodes = SECTIONS.map((section) =>
      document.getElementById(section.id),
    ).filter((node): node is HTMLElement => node !== null);
    const firstNode = nodes[0];
    if (firstNode === undefined) {
      return;
    }
    const updateActiveSection = () => {
      const offset =
        (shellRef.current?.getBoundingClientRect().height ?? 0) + 1;
      let current = firstNode.id as (typeof SECTIONS)[number]["id"];
      for (const node of nodes) {
        if (node.getBoundingClientRect().top <= offset) {
          current = node.id as (typeof SECTIONS)[number]["id"];
        }
      }
      setActiveSection(current);
    };
    updateActiveSection();
    window.addEventListener("scroll", updateActiveSection, { passive: true });
    window.addEventListener("resize", updateActiveSection);
    return () => {
      window.removeEventListener("scroll", updateActiveSection);
      window.removeEventListener("resize", updateActiveSection);
    };
  }, [snapshot]);

  const openFreshdeskCookieDialog = () => {
    const section = document.getElementById("csat");
    if (typeof section?.scrollIntoView === "function") {
      section.scrollIntoView({ block: "start" });
    }
    onOpenFreshdeskCookieDialog();
  };

  const closeHelp = () => {
    setHelpOpen(false);
    window.setTimeout(() => {
      helpButton.current?.focus();
    }, 0);
  };

  const brandMark = (
    <div className={styles.brand}>
      <span
        className={styles.logoFrame}
        aria-hidden="true"
        data-brand-logo-frame
      >
        <img
          className={`${styles.logo} ${themeStyles.themedAsset} ${themeStyles.lightAsset}`}
          src={logoColor}
          alt=""
          width="106"
          height="24"
          data-theme-asset="logo-light"
        />
        <img
          className={`${styles.logo} ${themeStyles.themedAsset} ${themeStyles.darkAsset}`}
          src={logoWhite}
          alt=""
          width="106"
          height="24"
          data-theme-asset="logo-dark"
        />
      </span>
      <span className="visually-hidden">Zalopay</span>
      <span className={styles.productName} data-product-name>
        Báo cáo hiệu quả CS Agent
      </span>
    </div>
  );

  if (traceTicketId !== undefined) {
    return (
      <div className={styles.page}>
        <a className="skip-link" href="#dashboardMain">
          Tới nội dung chính
        </a>
        <header className={styles.shell}>
          <div className={styles.shellTop}>
            <div className={styles.shellInner}>
              {brandMark}
              <ThemeToggle />
            </div>
          </div>
        </header>
        <main id="dashboardMain" className={styles.main} tabIndex={-1}>
          <TraceExplainer ticketId={traceTicketId} />
        </main>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <a className="skip-link" href="#dashboardMain">
        Tới nội dung chính
      </a>

      <header className={styles.shell} ref={shellRef}>
        <div className={styles.shellTop}>
        <div className={styles.shellInner}>
          {brandMark}

          <div className={styles.shellMeta}>
            <span
              id="statusChip"
              className={`${styles.runtimeChip} ${
                displayedRuntimeKind === "ready" ? styles.runtimeReady : ""
              }`}
              data-state={displayedRuntimeKind}
            >
              {displayedRuntimeKind === "loading"
                ? "Đang tải"
                : displayedRuntimeKind === "refreshing"
                  ? "Đang cập nhật"
                  : displayedRuntimeKind === "stale_error"
                    ? "Dữ liệu cũ"
                    : "Sẵn sàng"}
            </span>
            {freshdeskCookieState === "expired" ||
            freshdeskCookieState === "missing" ? (
              <button
                type="button"
                id="freshdeskCookieChip"
                className={styles.freshdeskCookieChip}
                onClick={openFreshdeskCookieDialog}
              >
                Freshdesk: cần cookie
              </button>
            ) : null}
            <span>
              Cập nhật{" "}
              <span
                id="updatedAt"
                className={`${styles.metaValue} ${
                  displaysStale ? styles.staleTimestamp : ""
                }`}
              >
                {displaysStale ? "dữ liệu cũ · " : ""}
                {formatUpdatedAt(snapshot?.generated_at ?? null)}
              </span>
            </span>
          </div>

          <div className={styles.controls}>
            <div
              id="weekDefinitionToggle"
              className={styles.segmented}
              role="group"
              aria-label="Định nghĩa tuần"
            >
              {WEEK_DEFINITIONS.map((value) => (
                <button
                  key={value}
                  type="button"
                  className={styles.segmentedButton}
                  aria-pressed={weekDefinition === value}
                  title={COHORT_DESCRIPTIONS[value]}
                  onClick={() => onWeekDefinitionChange(value)}
                >
                  {COHORT_LABELS[value]}
                </button>
              ))}
            </div>
            <button
              type="button"
              id="refreshButton"
              className={styles.action}
              onClick={onRefresh}
              disabled={refreshDisabled}
              title={refreshHint}
            >
              Làm mới
            </button>
            <ThemeToggle />
          </div>
        </div>

        <span
          className={styles.shellEdgeMark}
          aria-hidden="true"
          data-brand-mark-container="shell-z"
        >
          <img
            className={`${styles.shellEdgeMarkImage} ${themeStyles.themedAsset} ${themeStyles.lightAsset}`}
            src={zMarkLight}
            alt=""
            width="1249"
            height="1439"
            data-brand-mark="shell-z-light"
          />
          <img
            className={`${styles.shellEdgeMarkImage} ${themeStyles.themedAsset} ${themeStyles.darkAsset}`}
            src={zMarkDark}
            alt=""
            width="1249"
            height="1439"
            data-brand-mark="shell-z-dark"
          />
        </span>

        {snapshot === null ? null : (
          <div className={styles.reportScopeBar}>
            <ReportScopePicker
              reportWindow={reportWindow}
              selectedWeeks={selectedReportWeeks}
              allWeeksSelected={allReportWeeksSelected}
              weekDefinition={weekDefinition}
              onChange={onReportWeeksChange}
            />
          </div>
        )}
        </div>

        <nav
          id="sectionNav"
          className={styles.nav}
          aria-label="Các phần của báo cáo"
        >
          <div className={styles.navInner}>
            {SECTIONS.map((section) => (
              <a
                key={section.id}
                className={styles.navLink}
                href={`#${section.id}`}
                aria-current={activeSection === section.id ? "location" : undefined}
                onClick={() => setActiveSection(section.id)}
              >
                {section.label}
              </a>
            ))}
            <button
              id="resetFiltersButton"
              type="button"
              className={styles.navAction}
              disabled={activeFilters.length === 0}
              onClick={onResetFilters}
            >
              Xoá lọc
            </button>
            <button
              id="howToReadButton"
              ref={helpButton}
              type="button"
              className={styles.navAction}
              aria-expanded={helpOpen}
              aria-controls="howToReadPanel"
              onClick={() => setHelpOpen((current) => !current)}
            >
              Cách đọc
            </button>
          </div>
        </nav>

        {activeFilters.length === 0 ? null : (
          <div
            id="activeFilterChips"
            className={styles.filterChips}
            role="region"
            aria-label="Bộ lọc đang áp dụng"
          >
            {activeFilters.map((filter) => (
              <span key={filter.key} className={styles.filterChip}>
                {filter.label}
                <button
                  type="button"
                  aria-label={`Bỏ lọc ${filter.label}`}
                  onClick={() => onRemoveFilter(filter.key)}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {helpOpen ? (
          <aside
            id="howToReadPanel"
            ref={helpPanel}
            className={styles.helpPanel}
            role="region"
            aria-label="Cách đọc dashboard"
            tabIndex={-1}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                closeHelp();
              }
            }}
          >
            <strong>Cách đọc</strong>
            <button
              type="button"
              className={styles.action}
              onClick={closeHelp}
            >
              Đóng
            </button>
            <p>
              AI xử lý trọn là ticket kết thúc ở AI. AI trả lời rồi chuyển CS là
              ticket đã có phản hồi AI trước khi bàn giao. Chuyển CS ngay từ đầu
              là CS nhận ticket mà AI chưa trả lời thực chất. Chưa phân loại là
              ticket chưa đủ tín hiệu để kết luận.
            </p>
            <p>
              Đọc bảng tuần từ số ticket đến kết quả và reopen. Với WTD,
              phần tóm tắt và biểu đồ chỉ so các tuần tới cùng ngày đã hoàn tất
              khi đủ dữ liệu đối chiếu; bảng tuần vẫn giữ số thực của tuần.
              Transstatus và Step result là trạng thái xử lý giao dịch.
            </p>
          </aside>
        ) : null}
      </header>

      <p
        id="liveStatus"
        role="status"
        aria-live="polite"
        className={`${styles.status} ${statusMessage === "" ? "" : styles.statusFilled}`}
      >
        {statusMessage}
      </p>

      <main id="dashboardMain" className={styles.main} tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
