import { createHash } from "node:crypto";

import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";


const BRAND_ASSET_HASHES = {
  "logo-light":
    "6f401d0089ffce4d4069638e57bd6e4f16b9cdbb6fbe5ed412353e9217001dc5",
  "logo-dark":
    "a778739822f1f44d3ce0779d019b90f2e38d4575705e72fe0045895c3c60e2da",
  "shell-z-light":
    "8a5a40e6781a8b3fe281e5c549bb5b2e56245d2226d0cf212fc00a2d51c2dae2",
  "shell-z-dark":
    "968a9b22fb3fc99424160184dfd80215cc7cca9f124c5ba456c56a85e8faccec",
} as const;

type Theme = "light" | "dark";

function opposite(theme: Theme): Theme {
  return theme === "light" ? "dark" : "light";
}

async function expectOfficialAsset(
  locator: Locator,
  request: APIRequestContext,
  expectedHash: string,
) {
  await expect(locator).toHaveCount(1);
  await expect(locator).toHaveAttribute("alt", "");

  const source = await locator.getAttribute("src");
  expect(source).not.toBeNull();
  const response = await request.get(new URL(source ?? "", await locator.page().url()).href);
  expect(response.status()).toBe(200);
  expect(createHash("sha256").update(await response.body()).digest("hex")).toBe(
    expectedHash,
  );
}

async function expectSelectedThemeAssets(page: Page, theme: Theme) {
  const hiddenTheme = opposite(theme);
  const visibleLogo = page.locator(`[data-theme-asset="logo-${theme}"]`);
  const hiddenLogo = page.locator(`[data-theme-asset="logo-${hiddenTheme}"]`);
  const selectedMark = page.locator(`[data-brand-mark="shell-z-${theme}"]`);
  const hiddenMark = page.locator(`[data-brand-mark="shell-z-${hiddenTheme}"]`);

  await expect(visibleLogo).toBeVisible();
  await expect(hiddenLogo).toBeHidden();
  await expect(selectedMark).toHaveCSS("display", "block");
  await expect(hiddenMark).toHaveCSS("display", "none");
}

async function brandAlignment(page: Page, theme: Theme) {
  return page.locator(".visually-hidden", { hasText: "Zalopay" }).evaluate(
    (brandName, selectedTheme) => {
      const brand = brandName.parentElement;
      const frame = brand?.querySelector<HTMLElement>(
        "[data-brand-logo-frame]",
      );
      const logo = brand?.querySelector<HTMLElement>(
        `[data-theme-asset="logo-${selectedTheme}"]`,
      );
      const product = brand?.querySelector<HTMLElement>(
        "[data-product-name]",
      );
      if (brand === null || frame == null || logo == null || product == null) {
        throw new Error("Brand lockup is incomplete");
      }
      const brandBox = brand.getBoundingClientRect();
      const frameBox = frame.getBoundingClientRect();
      const logoBox = logo.getBoundingClientRect();
      const productBox = product.getBoundingClientRect();
      return {
        brandTop: brandBox.top,
        brandHeight: brandBox.height,
        brandDisplay: getComputedStyle(brand).display,
        brandColumns: getComputedStyle(brand).gridTemplateColumns,
        frameLeft: frameBox.left,
        frameTop: frameBox.top,
        frameWidth: frameBox.width,
        frameHeight: frameBox.height,
        logoLeft: logoBox.left,
        logoTop: logoBox.top,
        logoWidth: logoBox.width,
        logoHeight: logoBox.height,
        productTop: productBox.top,
        productLeft: productBox.left,
        productWidth: productBox.width,
        frameCentre: frameBox.top + frameBox.height / 2,
        productCentre: productBox.top + productBox.height / 2,
      };
    },
    theme,
  );
}

async function opaqueBounds(locator: Locator) {
  return locator.evaluate(async (node) => {
    if (!(node instanceof HTMLImageElement)) {
      throw new Error("Expected a logo image");
    }
    await node.decode();
    const canvas = document.createElement("canvas");
    canvas.width = node.naturalWidth;
    canvas.height = node.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (context === null) {
      throw new Error("Canvas 2D context is unavailable");
    }
    context.drawImage(node, 0, 0);
    const pixels = context.getImageData(
      0,
      0,
      canvas.width,
      canvas.height,
    ).data;
    let left = canvas.width;
    let right = -1;
    let top = canvas.height;
    let bottom = -1;
    for (let y = 0; y < canvas.height; y += 1) {
      for (let x = 0; x < canvas.width; x += 1) {
        if ((pixels[(y * canvas.width + x) * 4 + 3] ?? 0) === 0) {
          continue;
        }
        left = Math.min(left, x);
        right = Math.max(right, x);
        top = Math.min(top, y);
        bottom = Math.max(bottom, y);
      }
    }
    if (right < left || bottom < top) {
      throw new Error("Logo image has no opaque pixels");
    }
    return { left, right, top, bottom };
  });
}

function expectAlignedLockup(alignment: Awaited<ReturnType<typeof brandAlignment>>) {
  expect(alignment.brandDisplay).toBe("grid");
  expect(Math.abs(alignment.frameCentre - alignment.productCentre)).toBeLessThanOrEqual(
    1,
  );
  expect(alignment.logoLeft).toBe(alignment.frameLeft);
  expect(alignment.logoTop).toBe(alignment.frameTop);
  expect(alignment.logoWidth).toBe(alignment.frameWidth);
  expect(alignment.logoHeight).toBe(alignment.frameHeight);
  expect(alignment.productLeft).toBeGreaterThan(alignment.frameLeft);
}

function expectSameLogoGrid(
  actual: Awaited<ReturnType<typeof brandAlignment>>,
  expected: Awaited<ReturnType<typeof brandAlignment>>,
) {
  expect(actual.frameLeft).toBeCloseTo(expected.frameLeft, 0);
  expect(actual.frameTop).toBeCloseTo(expected.frameTop, 0);
  expect(actual.frameWidth).toBeCloseTo(expected.frameWidth, 0);
  expect(actual.frameHeight).toBeCloseTo(expected.frameHeight, 0);
  expect(actual.productLeft).toBeCloseTo(expected.productLeft, 0);
  expect(actual.frameCentre).toBeCloseTo(expected.frameCentre, 0);
  expect(actual.productCentre).toBeCloseTo(expected.productCentre, 0);
}

test("ships and switches the official mode-specific logo and Z mark", async ({
  page,
  request,
}, testInfo) => {
  await page.goto("/");

  const initialTheme: Theme = testInfo.project.name.endsWith("dark")
    ? "dark"
    : "light";
  const nextTheme = opposite(initialTheme);
  const desktop = testInfo.project.name.startsWith("desktop");

  const logoLight = page.locator('[data-theme-asset="logo-light"]');
  const logoDark = page.locator('[data-theme-asset="logo-dark"]');
  const markLight = page.locator('[data-brand-mark="shell-z-light"]');
  const markDark = page.locator('[data-brand-mark="shell-z-dark"]');

  await expectOfficialAsset(
    logoLight,
    request,
    BRAND_ASSET_HASHES["logo-light"],
  );
  await expectOfficialAsset(
    logoDark,
    request,
    BRAND_ASSET_HASHES["logo-dark"],
  );
  await expectOfficialAsset(
    markLight,
    request,
    BRAND_ASSET_HASHES["shell-z-light"],
  );
  await expectOfficialAsset(
    markDark,
    request,
    BRAND_ASSET_HASHES["shell-z-dark"],
  );

  for (const logo of [logoLight, logoDark]) {
    await expect(logo).toHaveAttribute("width", "106");
    await expect(logo).toHaveAttribute("height", "24");
  }
  for (const mark of [markLight, markDark]) {
    await expect(mark).toHaveAttribute("width", "1249");
    await expect(mark).toHaveAttribute("height", "1439");
  }

  await expectSelectedThemeAssets(page, initialTheme);

  const initialMark = page.locator(
    `[data-brand-mark="shell-z-${initialTheme}"]`,
  );
  const markContainer = page.locator(
    '[data-brand-mark-container="shell-z"]',
  );
  await expect(markContainer).toHaveCount(1);
  if (desktop) {
    await expect(initialMark).toBeVisible();
    const placement = await initialMark.evaluate((image) => {
      const container = image.parentElement;
      if (container === null) {
        throw new Error("Z mark is missing its clipping container");
      }
      const box = container.getBoundingClientRect();
      const style = getComputedStyle(image);
      return {
        right: box.right,
        viewport: window.innerWidth,
        overflow: getComputedStyle(container).overflow,
        zIndex: Number(getComputedStyle(container).zIndex),
        objectFit: style.objectFit,
        objectPosition: style.objectPosition,
      };
    });
    expect(placement.right).toBe(placement.viewport);
    expect(placement.overflow).toBe("hidden");
    expect(placement.zIndex).toBeGreaterThan(1);
    expect(placement.objectFit).toBe("cover");
    expect(placement.objectPosition).toBe("0% 50%");
  } else {
    await expect(markContainer).toBeHidden();
  }

  await page.getByRole("button", {
    name:
      initialTheme === "light"
        ? "Giao diện hiện tại: Sáng; chuyển sang Tối"
        : "Giao diện hiện tại: Tối; chuyển sang Sáng",
  }).click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", nextTheme);
  await expectSelectedThemeAssets(page, nextTheme);
  if (desktop) {
    await expect(
      page.locator(`[data-brand-mark="shell-z-${nextTheme}"]`),
    ).toBeVisible();
  }
});

test("keeps the light and dark brand lockups on the same visual grid", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-light",
    "A single 720px run switches through both themes.",
  );
  await page.setViewportSize({ width: 720, height: 900 });
  await page.goto("/");
  const initialTheme: Theme = testInfo.project.name.endsWith("dark")
    ? "dark"
    : "light";
  const nextTheme = opposite(initialTheme);
  const lightOpaque = await opaqueBounds(
    page.locator('[data-theme-asset="logo-light"]'),
  );
  const darkOpaque = await opaqueBounds(
    page.locator('[data-theme-asset="logo-dark"]'),
  );
  expect(darkOpaque).toEqual(lightOpaque);

  const initial = await brandAlignment(page, initialTheme);
  expectAlignedLockup(initial);

  await page.getByRole("button", {
    name:
      initialTheme === "light"
        ? "Giao diện hiện tại: Sáng; chuyển sang Tối"
        : "Giao diện hiện tại: Tối; chuyển sang Sáng",
  }).click();
  const next = await brandAlignment(page, nextTheme);
  expectAlignedLockup(next);
  expectSameLogoGrid(next, initial);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  const compactInitial = await brandAlignment(page, nextTheme);
  expectAlignedLockup(compactInitial);
  expect(compactInitial.frameWidth).toBe(88);
  expect(compactInitial.frameHeight).toBe(20);

  await page.getByRole("button", {
    name:
      nextTheme === "light"
        ? "Giao diện hiện tại: Sáng; chuyển sang Tối"
        : "Giao diện hiện tại: Tối; chuyển sang Sáng",
  }).click();
  const compactNext = await brandAlignment(page, initialTheme);
  expectAlignedLockup(compactNext);
  expectSameLogoGrid(compactNext, compactInitial);
});
