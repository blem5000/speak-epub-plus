/**
 * src/lib/selection.ts — pure helpers for Chapter List selection (FR2)
 * No React, unit-testable. Clamp, range sync, bulk shift.
 */

export function clamp(n: number, min: number, max: number): number {
  if (!Number.isFinite(n)) return min;
  if (n < min) return min;
  if (n > max) return max;
  return Math.trunc(n);
}

/**
 * Build Set<number> for inclusive range from..to clamped to 1..total.
 * Handles swap if from > to, and empty/non-numeric → empty set (no-op).
 * Returns empty set if either input is non-finite or total <1.
 */
export function rangeToSet(from: unknown, to: unknown, total: number): Set<number> {
  const N = Math.trunc(total);
  if (!Number.isFinite(N) || N < 1) return new Set();
  if (from === "" || to === "" || from == null || to == null) return new Set();
  if (typeof from === "boolean" || typeof to === "boolean") return new Set();
  const f = Number(from);
  const t = Number(to);
  if (!Number.isFinite(f) || !Number.isFinite(t)) return new Set();
  let a = clamp(f, 1, N);
  let b = clamp(t, 1, N);
  if (a > b) {
    const tmp = a;
    a = b;
    b = tmp;
  }
  // cap huge range to prevent freeze (still >500 warning but avoid 1M Set)
  if (b - a > 5000) return new Set();
  const out = new Set<number>();
  for (let i = a; i <= b; i++) out.add(i);
  return out;
}

export function toggleSet(set: Set<number>, n: number): Set<number> {
  if (!Number.isInteger(n) || !Number.isFinite(n) || n < 1) return new Set(set);
  const next = new Set(set);
  if (next.has(n)) next.delete(n);
  else next.add(n);
  return next;
}

/**
 * Bulk shift: if anchor is null → single toggle of clicked.
 * Else toggles/adds range anchor..clicked.
 * For FR2 bulk: if 1-30 selected and anchor 10 then Shift+click 40 → 10..40 union (adds missing).
 * Strategy: union range anchor..clicked into set. If range already fully selected, toggle could remove?
 * Simpler and spec-aligned: union (add all in range). Keeps “Wybrano” growing.
 * Tests expect bulk adds 31..40 to existing 1..30 => 1..40.
 */
export function bulkShift(
  anchor: number | null,
  clicked: number,
  selected: Set<number>
): Set<number> {
  if (typeof clicked === "boolean" || typeof anchor === "boolean") {
    return toggleSet(selected, Number(clicked));
  }
  if (anchor == null || !Number.isFinite(anchor) || !Number.isInteger(clicked) || !Number.isFinite(clicked) || clicked < 1) {
    return toggleSet(selected, clicked);
  }
  // clamp to >=1 and ensure ints, OOB clamp (P14)
  const a = clamp(Math.trunc(anchor), 1, 100000);
  const c = clamp(Math.trunc(clicked), 1, 100000);
  if (!Number.isFinite(a) || !Number.isFinite(c) || a < 1 || c < 1) return toggleSet(selected, clicked);
  const lo = Math.min(a, c);
  const hi = Math.max(a, c);
  if (hi - lo > 5000) return new Set(selected); // cap still silent for N=142, defer feedback to UI
  const next = new Set(selected);
  // P14: if range already fully selected, bulk deselect, else union
  let allSelected = true;
  for (let i = lo; i <= hi; i++) {
    if (!next.has(i)) {
      allSelected = false;
      break;
    }
  }
  if (allSelected) {
    for (let i = lo; i <= hi; i++) next.delete(i);
  } else {
    for (let i = lo; i <= hi; i++) next.add(i);
  }
  return next;
}

/**
 * Pure label helper — returns “count/total” string for t() interpolation.
 * Component does t("chapterList.selected", {count, total}) ; this helper for unit test.
 */
export function selectedCountLabel(count: number, total: number): string {
  return `${count} / ${total}`;
}

/**
 * Helper to clamp od/do inputs on blur — returns [clampedFrom, clampedTo] with swap.
 */
export function clampRange(from: unknown, to: unknown, total: number): [number, number] | null {
  if (from === "" || to === "" || from == null || to == null) return null;
  const f = Number(from);
  const t = Number(to);
  if (!Number.isFinite(f) || !Number.isFinite(t)) return null;
  let a = clamp(f, 1, total);
  let b = clamp(t, 1, total);
  if (a > b) [a, b] = [b, a];
  return [a, b];
}
