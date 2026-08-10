export type SortDirection = "asc" | "desc";

export interface TableSort<TKey extends PropertyKey = string> {
  key: TKey;
  direction: SortDirection;
}

export type SortValue = string | number | boolean | null | undefined;

const vietnameseCollator = new Intl.Collator("vi", {
  numeric: true,
  sensitivity: "base",
});

const VALUE_TYPE_ORDER: Readonly<Record<"number" | "string" | "boolean", number>> = {
  number: 0,
  string: 1,
  boolean: 2,
};

type DefinedSortValue = Exclude<SortValue, null | undefined>;
type SortValueType = keyof typeof VALUE_TYPE_ORDER;

function isMissing(value: SortValue): value is null | undefined {
  return value === null || value === undefined;
}

function sortValueType(value: DefinedSortValue): SortValueType {
  if (typeof value === "number") {
    return "number";
  }
  if (typeof value === "boolean") {
    return "boolean";
  }
  return "string";
}

function compareDefinedValues(
  left: DefinedSortValue,
  right: DefinedSortValue,
): number {
  const leftType = sortValueType(left);
  const rightType = sortValueType(right);

  if (leftType !== rightType) {
    return VALUE_TYPE_ORDER[leftType] - VALUE_TYPE_ORDER[rightType];
  }

  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }
  if (typeof left === "boolean" && typeof right === "boolean") {
    return Number(left) - Number(right);
  }
  return vietnameseCollator.compare(String(left), String(right));
}

function compareSortValues(
  left: SortValue,
  right: SortValue,
  direction: SortDirection,
): number {
  if (isMissing(left)) {
    return isMissing(right) ? 0 : 1;
  }
  if (isMissing(right)) {
    return -1;
  }

  const compared = compareDefinedValues(left, right);
  return direction === "asc" ? compared : -compared;
}

/**
 * Sorts a copied row list, evaluates each accessor once, and preserves source
 * order when two values compare equal.
 */
export function stableSortRows<T>(
  rows: readonly T[],
  getValue: (row: T) => SortValue,
  direction: SortDirection,
): T[] {
  return rows
    .map((row, sourceIndex) => ({
      row,
      sourceIndex,
      value: getValue(row),
    }))
    .sort((left, right) => (
      compareSortValues(left.value, right.value, direction)
      || left.sourceIndex - right.sourceIndex
    ))
    .map(({ row }) => row);
}

/**
 * Produces a new controlled-sort state. Re-selecting the active key flips its
 * direction; selecting another key starts with the supplied direction.
 */
export function toggleTableSort<TKey extends PropertyKey>(
  current: TableSort<TKey> | null | undefined,
  key: TKey,
  initialDirection: SortDirection = "asc",
): TableSort<TKey> {
  return {
    key,
    direction: current?.key === key
      ? current.direction === "asc" ? "desc" : "asc"
      : initialDirection,
  };
}
