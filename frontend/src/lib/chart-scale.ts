const STEP_MULTIPLIERS = [1, 2, 2.5, 5, 10] as const;
const TARGET_INTERVALS = 5;

function niceTicks(
  maxValue: number,
  minStep: number,
  fallback: readonly number[],
): readonly number[] {
  if (!Number.isFinite(maxValue) || maxValue <= 0) {
    return fallback;
  }

  const rawStep = Math.max(minStep, maxValue / TARGET_INTERVALS);
  const exponent = Math.floor(Math.log10(rawStep));
  const magnitude = 10 ** exponent;
  const normalized = rawStep / magnitude;
  const multiplier =
    STEP_MULTIPLIERS.find((candidate) => candidate >= normalized) ?? 10;
  const step = Math.max(minStep, multiplier * magnitude);
  const intervalCount = Math.max(1, Math.ceil(maxValue / step));
  return Object.freeze(
    Array.from({ length: intervalCount + 1 }, (_, index) => index * step),
  );
}

/**
 * Builds a count axis from round human-readable steps.
 *
 * Volume is discrete, so the step never drops below one ticket. The ceiling
 * always covers the largest bar instead of clipping it to a prettier number.
 */
export function niceVolumeTicks(maxVolume: number): readonly number[] {
  return niceTicks(maxVolume, 1, Object.freeze([0, 1]));
}

/**
 * Builds a percentage axis from round steps, covering ratios that can exceed
 * 100% (a per-ticket count average, like reopens per AI-First ticket) instead
 * of clipping them to a fixed 0-100 range.
 */
export function niceRateTicks(maxRate: number): readonly number[] {
  return niceTicks(
    Math.max(1, maxRate),
    0.25,
    Object.freeze([0, 0.25, 0.5, 0.75, 1]),
  );
}
