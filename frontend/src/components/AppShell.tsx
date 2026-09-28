import {
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";

import logoColor from "../../../assets/brand/logos/zalopay-logo-color.png";
import logoWhite from "../../../assets/brand/logos/zalopay-logo-white.png";
import zMarkDark from "../../../assets/brand/graphics/zalopay-z-dark.png";
import zMarkLight from "../../../assets/brand/graphics/zalopay-z-light.png";
import type { DashboardSnapshot, WeekDefinition } from "../lib/dashboard-schema";
import type { ActiveFilterChip } from "../lib/dashboard-filters";
import { AB_TEST_ENABLED } from "../lib/api";
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
import styles from "./dashboard.module.css";
import themeStyles from "./theme-toggle.module.css";

const WEEK_DEFINITIONS: readonly WeekDefinition[] = ["mon_fri", "mon_sun"];
// Page order; each label is the section's h2 text, word for word.
const SECTIONS = [
  { id: "weekly", label: "Báo cáo tuần" },
  { id: "trend", label: "Xu hướng" },
  { id: "segments", label: "So sánh segment" },
  { id: "csat", label: "Mức hài lòng" },
  { id: "diagnostics", label: "Chẩn đoán chuyển CS" },
  { id: "tickets", label: "Ticket Explorer" },
  { id: "ai-tag-coverage", label: "Độ phủ Freshdesk" },
  { id: "ab-test", label: "A/B Test model" },
] as const;
const NAV_SECTIONS = SECTIONS.filter(
  (section) => AB_TEST_ENABLED || section.id !== "ab-test",
);

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
  readonly reportRange?: { readonly from: string; readonly to: string } | null;
  readonly onReportRangeChange?: (from: string, to: string) => void;
  readonly activeFilters: readonly ActiveFilterChip[];
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
  reportRange = null,
  onReportRangeChange = () => {},
  activeFilters,
  onResetFilters,
  freshdeskCookieState = null,
  onOpenFreshdeskCookieDialog = () => {},
  children,
}: AppShellProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<
    (typeof SECTIONS)[number]["id"]
  >(SECTIONS[0].id);
  const helpPanel = useRef<HTMLElement>(null);
  const helpButton = useRef<HTMLButtonElement>(null);
  const shellRef = useRef<HTMLElement>(null);
  const reportWindow =
    snapshot === null
      ? []
      : selectWeekly(selectView(snapshot, weekDefinition));

  useEffect(() => {
    if (helpOpen) {
      helpPanel.current?.focus();
    }
  }, [helpOpen]);

  // Publishes the sticky header's live height as `--shell-height`, which the
  // root `scroll-padding-top` reads, so a focused element scrolled into view
  // never lands under the header (WCAG 2.4.11). The height changes with
  // viewport width, zoom and filter chips, so a fixed value cannot hold.
  useEffect(() => {
    const shell = shellRef.current;
    if (shell === null || typeof ResizeObserver === "undefined") {
      return;
    }
    const root = document.documentElement;
    const observer = new ResizeObserver(() => {
      root.style.setProperty(
        "--shell-height",
        `${shell.getBoundingClientRect().height}px`,
      );
    });
    observer.observe(shell);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--shell-height");
    };
  }, []);

  // Scroll-spy: the current section is the one crossing a 1px band just
  // under the sticky header. Rebuilt when the header height changes, because
  // the band's offset is baked into rootMargin.
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") {
      return;
    }
    const nodes = SECTIONS.map((section) =>
      document.getElementById(section.id),
    ).filter((node): node is HTMLElement => node !== null);
    if (nodes.length === 0) {
      return;
    }
    let observer: IntersectionObserver | null = null;
    const observe = () => {
      observer?.disconnect();
      const top = Math.round(shellRef.current?.getBoundingClientRect().height ?? 0) + 1;
      const bottom = Math.max(0, window.innerHeight - top - 1);
      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              setActiveSection(entry.target.id as (typeof SECTIONS)[number]["id"]);
            }
          }
        },
        { rootMargin: `-${top}px 0px -${bottom}px 0px` },
      );
      for (const node of nodes) {
        observer.observe(node);
      }
    };
    observe();
    window.addEventListener("resize", observe);
    return () => {
      window.removeEventListener("resize", observe);
      observer?.disconnect();
    };
  }, [snapshot]);

  /**
   * Nav clicks scroll to the section top minus the live header height -- the
   * same offset the scroll-spy band sits at, so the clicked link is the one
   * that lights up. The URL hash is left alone: it carries the filter deep
   * link, not the section.
   */
  const handleSectionNavClick = (
    id: (typeof SECTIONS)[number]["id"],
    event: ReactMouseEvent<HTMLAnchorElement>,
  ) => {
    const target = document.getElementById(id);
    if (target === null) {
      return;
    }
    event.preventDefault();
    const offset = (shellRef.current?.getBoundingClientRect().height ?? 0) + 1;
    window.scrollTo({
      top: target.getBoundingClientRect().top + window.scrollY - offset,
    });
    setActiveSection(id);
  };

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

  return (
    <div className={styles.page}>
      <a className="skip-link" href="#dashboardMain">
        Tới nội dung chính
      </a>

      <header className={styles.shell} ref={shellRef}>
        <div className={styles.shellTop}>
          <div className={styles.shellInner}>
            {brandMark}

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
              {snapshot === null ? null : (
                <ReportScopePicker
                  reportWindow={reportWindow}
                  selectedWeeks={selectedReportWeeks}
                  allWeeksSelected={allReportWeeksSelected}
                  weekDefinition={weekDefinition}
                  onChange={onReportWeeksChange}
                  activeRange={reportRange}
                  onRangeChange={onReportRangeChange}
                />
              )}
            </div>

            <div className={styles.shellMeta}>
              {/* The chip takes the label's place; a CSS sizer keeps the
                  slot as wide as the widest chip, so a refresh moves nothing. */}
              <span>
                <span className={styles.metaLabel}>
                  {runtimeKind === "ready" ? (
                    <span>Cập nhật lúc</span>
                  ) : (
                    <span
                      id="statusChip"
                      className={styles.runtimeChip}
                      data-state={runtimeKind}
                    >
                      {runtimeKind === "loading"
                        ? "Đang tải"
                        : runtimeKind === "refreshing"
                          ? "Đang cập nhật"
                          : "Cập nhật lỗi"}
                    </span>
                  )}
                </span>{" "}
                <span id="updatedAt" className={styles.metaValue}>
                  {formatUpdatedAt(snapshot?.generated_at ?? null)}
                </span>
              </span>
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

        </div>

        <nav
          id="sectionNav"
          className={styles.nav}
          aria-label="Các phần của báo cáo"
        >
          <div className={styles.navInner}>
            {NAV_SECTIONS.map((section) => (
              <a
                key={section.id}
                className={styles.navLink}
                href={`#${section.id}`}
                aria-current={activeSection === section.id ? "location" : undefined}
                onClick={(event) => handleSectionNavClick(section.id, event)}
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
      </header>

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
            là CS nhận ticket mà AI chưa trả lời thực chất; bảng số chính gọi
            nhóm này là CS First. Chưa phân loại là
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

      {freshdeskCookieState === "expired" ? (
        <footer className={styles.opsFooter}>
          <button
            type="button"
            id="freshdeskCookieChip"
            className={styles.freshdeskCookieChip}
            onClick={openFreshdeskCookieDialog}
          >
            Cookie Freshdesk đã hết hạn — cập nhật
          </button>
        </footer>
      ) : null}
    </div>
  );
}
