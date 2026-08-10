const STEP_MULTIPLIERS = [1, 2, 2.5, 5, 10] as const;
const TARGET_INTERVALS = 5;

/**
 * Builds a count axis from round human-readable steps.
 *
 * Volume is discrete, so the step never drops below one ticket. The ceiling
 * always covers the largest bar instead of clipping it to a prettier number.
 */
export function niceVolumeTicks(maxVolume: number): readonly number[] {
  if (!Number.isFinite(maxVolume) || maxVolume <= 0) {
    return Object.freeze([0, 1]);
  }

  const rawStep = Math.max(1, maxVolume / TARGET_INTERVALS);
  const exponent = Math.floor(Math.log10(rawStep));
  const magnitude = 10 ** exponent;
  const normalized = rawStep / magnitude;
  const multiplier =
    STEP_MULTIPLIERS.find((candidate) => candidate >= normalized) ?? 10;
  const step = Math.max(1, multiplier * magnitude);
  const intervalCount = Math.max(1, Math.ceil(maxVolume / step));
  const ticks = Array.from(
    { length: intervalCount + 1 },
    (_, index) => index * step,
  );
  return Object.freeze(ticks);
}
