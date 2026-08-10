import { describe, expect, it } from "vitest";

import {
  stableSortRows,
  toggleTableSort,
  type TableSort,
} from "../src/lib/table-sort";

describe("stableSortRows", () => {
  it("returns a new array and leaves the input untouched", () => {
    const rows = Object.freeze([
      Object.freeze({ id: "b", value: 2 }),
      Object.freeze({ id: "a", value: 1 }),
    ]);

    const sorted = stableSortRows(rows, (row) => row.value, "asc");

    expect(sorted).not.toBe(rows);
    expect(sorted.map((row) => row.id)).toEqual(["a", "b"]);
    expect(rows.map((row) => row.id)).toEqual(["b", "a"]);
  });

  it("sorts Vietnamese text with natural numeric semantics", () => {
    const rows = [
      { label: "Mục 10" },
      { label: "Ân" },
      { label: "Mục 2" },
      { label: "Ăn" },
      { label: "An" },
    ];

    expect(stableSortRows(rows, (row) => row.label, "asc").map((row) => row.label))
      .toEqual(["An", "Ăn", "Ân", "Mục 2", "Mục 10"]);
  });

  it("sorts numbers and booleans in both directions", () => {
    const numbers = [{ value: 7 }, { value: -1 }, { value: 3 }];
    const booleans = [{ value: true }, { value: false }];

    expect(stableSortRows(numbers, (row) => row.value, "asc").map((row) => row.value))
      .toEqual([-1, 3, 7]);
    expect(stableSortRows(numbers, (row) => row.value, "desc").map((row) => row.value))
      .toEqual([7, 3, -1]);
    expect(stableSortRows(booleans, (row) => row.value, "asc").map((row) => row.value))
      .toEqual([false, true]);
    expect(stableSortRows(booleans, (row) => row.value, "desc").map((row) => row.value))
      .toEqual([true, false]);
  });

  it("keeps null and undefined last for ascending and descending sorts", () => {
    const rows = [
      { id: "null", value: null },
      { id: "two", value: 2 },
      { id: "missing", value: undefined },
      { id: "one", value: 1 },
    ];

    expect(stableSortRows(rows, (row) => row.value, "asc").map((row) => row.id))
      .toEqual(["one", "two", "null", "missing"]);
    expect(stableSortRows(rows, (row) => row.value, "desc").map((row) => row.id))
      .toEqual(["two", "one", "null", "missing"]);
  });

  it("preserves original order when values compare equal", () => {
    const rows = [
      { id: 1, label: "AI First" },
      { id: 2, label: "ai first" },
      { id: 3, label: "AI FIRST" },
    ];

    expect(stableSortRows(rows, (row) => row.label, "asc").map((row) => row.id))
      .toEqual([1, 2, 3]);
    expect(stableSortRows(rows, (row) => row.label, "desc").map((row) => row.id))
      .toEqual([1, 2, 3]);
  });
});

describe("toggleTableSort", () => {
  type Key = "label" | "total";

  it("creates a sort state, then toggles direction without mutation", () => {
    const initial = toggleTableSort<Key>(undefined, "label");
    const current = Object.freeze<TableSort<Key>>({ key: "label", direction: "asc" });
    const next = toggleTableSort(current, "label");

    expect(initial).toEqual({ key: "label", direction: "asc" });
    expect(next).toEqual({ key: "label", direction: "desc" });
    expect(next).not.toBe(current);
    expect(current).toEqual({ key: "label", direction: "asc" });
  });

  it("uses the requested initial direction when changing columns", () => {
    const current: TableSort<Key> = { key: "label", direction: "desc" };

    expect(toggleTableSort(current, "total", "desc")).toEqual({
      key: "total",
      direction: "desc",
    });
  });
});
