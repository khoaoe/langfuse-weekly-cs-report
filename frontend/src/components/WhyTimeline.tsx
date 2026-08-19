import { useState } from "react";

import type { TimelinePhase } from "../lib/why-schema";
import styles from "./why-drawer.module.css";

function PhaseRowItem({
  label,
  value,
  evidence,
}: {
  readonly label: string;
  readonly value: string;
  readonly evidence: Record<string, unknown>;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li className={styles.phaseRow}>
      <div>
        <span className={styles.phaseRowLabel}>{label}</span>
        <button
          type="button"
          className={styles.evidenceToggle}
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "Ẩn bằng chứng" : "Xem bằng chứng"}
        </button>
        {expanded ? (
          <pre className={styles.rawEvidence}>
            {JSON.stringify(evidence, null, 2)}
          </pre>
        ) : null}
      </div>
      <span className={styles.phaseRowValue}>{value}</span>
    </li>
  );
}

function PhaseItem({ phase }: { readonly phase: TimelinePhase }) {
  const [open, setOpen] = useState(!phase.collapsed);
  const canToggle = phase.rows.length > 0 && phase.state !== "quyet_dinh";
  const titleClass =
    phase.state === "quyet_dinh" ? styles.phaseTitleDecisive : styles.phaseTitle;
  const phaseClass = phase.state === "chan" ? styles.phaseBlocked : undefined;

  return (
    <li className={[styles.phase, phaseClass].filter(Boolean).join(" ")}>
      {canToggle ? (
        <button
          type="button"
          className={styles.phaseHead}
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <span className={titleClass}>{phase.title}</span>
          <span className={styles.phaseSummary}>{phase.summary}</span>
        </button>
      ) : (
        <div className={styles.phaseHeadStatic}>
          <span className={titleClass}>{phase.title}</span>
          <span className={styles.phaseSummary}>{phase.summary}</span>
        </div>
      )}
      {open && phase.rows.length > 0 ? (
        <ul className={styles.phaseRows}>
          {phase.rows.map((row, index) => (
            <PhaseRowItem
              key={`${row.label}-${index}`}
              label={row.label}
              value={row.value}
              evidence={row.evidence}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Five-phase "Agent đã làm gì" timeline (spec section 6). Used both inside
 * the WhyDrawer and on the #trace/{id} route (TraceExplainer.tsx), which is
 * why it is its own file instead of living inside WhyDrawer.tsx. */
export function WhyTimeline({
  phases,
}: {
  readonly phases: readonly TimelinePhase[];
}) {
  return (
    <div>
      <h3 className={styles.cardLabel}>Agent đã làm gì</h3>
      <ul className={styles.timeline}>
        {phases.map((phase) => (
          <PhaseItem key={phase.key} phase={phase} />
        ))}
      </ul>
    </div>
  );
}
