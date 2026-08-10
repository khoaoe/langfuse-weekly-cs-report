import { expect, test, type Page } from "@playwright/test";

async function activateKeyboardSkipLink(page: Page) {
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Tới nội dung chính" });
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();

  await page.keyboard.press("Enter");
  const main = page.locator("#dashboardMain");
  await expect(main).toBeFocused();
  await expect(page).toHaveURL(/#dashboardMain$/);

  return main.evaluate((node) => {
    const shell = document.querySelector("header");
    if (shell === null) {
      throw new Error("Missing sticky shell");
    }
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return {
      mainTop: box.top,
      shellBottom: shell.getBoundingClientRect().bottom,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
    };
  });
}

function expectVisibleMainFocus(focus: Awaited<ReturnType<typeof activateKeyboardSkipLink>>) {
  expect(focus.mainTop).toBeGreaterThanOrEqual(focus.shellBottom - 1);
  expect(focus.outlineStyle).not.toBe("none");
  expect(focus.outlineWidth).not.toBe("0px");
}

test.describe("main-content skip link", () => {
  test("focuses ready content without sticky-shell overlap", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    expectVisibleMainFocus(await activateKeyboardSkipLink(page));
  });

  test("keeps the target available while loading", async ({ page }) => {
    await page.route("**/api/dashboard", (route) =>
      route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          status: "loading",
          refreshing: true,
          last_error_code: null,
          last_error_at: null,
          snapshot: null,
        }),
      }),
    );

    await page.goto("/");
    await expect(page.getByRole("status")).toHaveText("Đang tải dữ liệu dashboard.");

    expectVisibleMainFocus(await activateKeyboardSkipLink(page));
  });

  test("keeps focused content clear on a compact mobile viewport", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name !== "mobile-light",
      "compact geometry only needs one color-scheme run",
    );
    await page.setViewportSize({ width: 320, height: 568 });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    expectVisibleMainFocus(await activateKeyboardSkipLink(page));
  });
});
