import { within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/**
 * Opens a Ticket-Explorer-style `MultiSelectField` (a `<details>` disclosure
 * of checkboxes, replacing the old single-value `<select>`) and toggles one
 * option.
 *
 * jsdom does not apply the native `details:not([open]) > *:not(summary) {
 * display: none }` UA rule, so a closed panel's checkboxes stay queryable by
 * role — two dimension filters that happen to share an option label (e.g.
 * the same taxonomy string under both Category and App in test fixtures)
 * would otherwise collide. `panelId` scopes the checkbox lookup to the one
 * panel actually being opened; it's the same `id` passed to the
 * `MultiSelectField` (e.g. "issueCategoryInput").
 */
export async function toggleMultiSelectOption(
  user: UserEvent,
  scope: HTMLElement,
  panelId: string,
  fieldLabel: string,
  optionLabel: string,
): Promise<void> {
  const summary = within(scope).getByRole("button", {
    name: new RegExp(`^${fieldLabel}:`),
  });
  await user.click(summary);
  const panel = document.getElementById(panelId) as HTMLElement;
  await user.click(within(panel).getByRole("checkbox", { name: optionLabel }));
}

/** Reads a `MultiSelectField`'s displayed summary text (e.g. "AI xử lý trọn",
 * "Tất cả", or "2 đã chọn"), the replacement for a `<select>`'s `.value`. */
export function multiSelectSummaryText(
  scope: HTMLElement,
  fieldLabel: string,
): string {
  return within(scope)
    .getByRole("button", { name: new RegExp(`^${fieldLabel}:`) })
    .textContent as string;
}
