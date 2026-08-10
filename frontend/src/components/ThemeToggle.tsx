import { useLayoutEffect, useState } from "react";

import styles from "./theme-toggle.module.css";

type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "weekly-cs-theme-v1";

function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    return null;
  }
}

function readSystemTheme(): Theme {
  if (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  ) {
    return "dark";
  }
  return "light";
}

function initialTheme(): Theme {
  return readStoredTheme() ?? readSystemTheme();
}

function persistTheme(theme: Theme) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage can be unavailable in hardened/private browser contexts. The
    // in-memory choice still works for the current page without weakening CSP.
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const isDark = theme === "dark";
  const currentLabel = isDark ? "Tối" : "Sáng";
  const nextLabel = isDark ? "Sáng" : "Tối";

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    return () => {
      if (root.dataset.theme === theme) {
        delete root.dataset.theme;
      }
    };
  }, [theme]);

  const toggleTheme = () => {
    const nextTheme: Theme = isDark ? "light" : "dark";
    persistTheme(nextTheme);
    setTheme(nextTheme);
  };

  return (
    <button
      id="themeToggle"
      type="button"
      className={styles.toggle}
      aria-label={`Giao diện hiện tại: ${currentLabel}; chuyển sang ${nextLabel}`}
      aria-pressed={isDark}
      title={`Chuyển sang giao diện ${nextLabel.toLocaleLowerCase("vi")}`}
      onClick={toggleTheme}
    >
      <span className={styles.indicator} aria-hidden="true" />
      <span>{currentLabel}</span>
    </button>
  );
}
