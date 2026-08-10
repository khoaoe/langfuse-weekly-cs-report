import { expect, test } from "@playwright/test";


type Theme = "light" | "dark";

const THEME_COPY = {
  light: {
    label: "Giao diện hiện tại: Sáng; chuyển sang Tối",
    visible: "Sáng",
    pressed: "false",
    canvas: "#f4f7fc",
    controlBackgrounds: ["rgb(255, 255, 255)", "rgb(238, 242, 249)"],
  },
  dark: {
    label: "Giao diện hiện tại: Tối; chuyển sang Sáng",
    visible: "Tối",
    pressed: "true",
    canvas: "#0d1117",
    controlBackgrounds: ["rgb(21, 27, 35)", "rgb(27, 34, 44)"],
  },
} as const;

function opposite(theme: Theme): Theme {
  return theme === "light" ? "dark" : "light";
}

test("allows a visible light/dark override and persists it after reload", async ({
  page,
}, testInfo) => {
  const initialTheme: Theme = testInfo.project.name.endsWith("dark")
    ? "dark"
    : "light";
  const nextTheme = opposite(initialTheme);

  await page.goto("/");

  const html = page.locator("html");
  const initialToggle = page.getByRole("button", {
    name: THEME_COPY[initialTheme].label,
  });

  await expect(html).toHaveAttribute("data-theme", initialTheme);
  await expect(initialToggle).toBeVisible();
  await expect(initialToggle).toHaveText(THEME_COPY[initialTheme].visible);
  await expect(initialToggle).toHaveAttribute(
    "aria-pressed",
    THEME_COPY[initialTheme].pressed,
  );
  await expect
    .poll(() =>
      html.evaluate((root) =>
        getComputedStyle(root).getPropertyValue("--canvas").trim(),
      ),
    )
    .toBe(THEME_COPY[initialTheme].canvas);

  const tapTarget = await initialToggle.boundingBox();
  expect(tapTarget).not.toBeNull();
  expect(tapTarget?.width).toBeGreaterThanOrEqual(44);
  expect(tapTarget?.height).toBeGreaterThanOrEqual(44);

  await initialToggle.click();

  const nextToggle = page.getByRole("button", {
    name: THEME_COPY[nextTheme].label,
  });
  await expect(html).toHaveAttribute("data-theme", nextTheme);
  for (const controlId of ["refreshButton", "themeToggle"]) {
    expect(THEME_COPY[nextTheme].controlBackgrounds).toContain(
      await page.locator(`#${controlId}`).evaluate(
        (control) => getComputedStyle(control).backgroundColor,
      ),
    );
  }
  await expect(nextToggle).toHaveText(THEME_COPY[nextTheme].visible);
  await expect(nextToggle).toHaveAttribute(
    "aria-pressed",
    THEME_COPY[nextTheme].pressed,
  );
  await expect
    .poll(() =>
      html.evaluate((root) =>
        getComputedStyle(root).getPropertyValue("--canvas").trim(),
      ),
    )
    .toBe(THEME_COPY[nextTheme].canvas);
  expect(
    await page.evaluate(() => localStorage.getItem("weekly-cs-theme-v1")),
  ).toBe(nextTheme);

  await page.reload();

  await expect(page.locator("html")).toHaveAttribute("data-theme", nextTheme);
  await expect(
    page.getByRole("button", { name: THEME_COPY[nextTheme].label }),
  ).toHaveText(THEME_COPY[nextTheme].visible);
  expect(
    await page.evaluate(() => localStorage.getItem("weekly-cs-theme-v1")),
  ).toBe(nextTheme);
});
