import { useEffect, useState } from "react";
import { t } from "@/i18n";
import { clamp } from "@/lib/selection";

type RangeBarProps = {
  from: number;
  to: number;
  total: number;
  selectedCount: number;
  onChangeRange: (from: number, to: number) => void;
  // Explicit committed range — never reads parent props, so type→Enter/click
  // always uses what is in the fields (no stale-closure after typing).
  onSelectRange: (from: number, to: number) => void;
  onClear: () => void;
};

export default function RangeBar({
  from,
  to,
  total,
  selectedCount,
  onChangeRange,
  onSelectRange,
  onClear,
}: RangeBarProps): JSX.Element {
  const N = total;
  const disabled = N === 0;

  // local string state to allow empty field while typing
  const [fromStr, setFromStr] = useState(String(from));
  const [toStr, setToStr] = useState(String(to));

  useEffect(() => {
    setFromStr(String(from));
  }, [from]);
  useEffect(() => {
    setToStr(String(to));
  }, [to]);

  const handleFromChange = (val: string): void => {
    // P11: do not propagate out-of-bounds before blur — keep typing local
    setFromStr(val);
  };

  const handleToChange = (val: string): void => {
    // P11: do not propagate out-of-bounds before blur — keep typing local
    setToStr(val);
  };

  const selectAllOnFocus = (e: React.FocusEvent<HTMLInputElement>): void => {
    // Clicking/focusing a range field selects its content so typing replaces
    // it immediately — no Ctrl+A needed. Subsequent clicks place the cursor
    // normally (focus fires only on entry).
    try {
      e.target.select();
    } catch {
      // noop (jsdom without layout still supports select)
    }
  };

  const commitFields = (): [number, number] | null => {
    // Commit each field independently: clamp to 1..N but NEVER swap.
    // The user types lower-then-higher across two fields; rewriting what
    // they just typed (93,30 → 30,93) is the bug. Order normalizes at
    // selection time (rangeToSet / positional slice handle inversion).
    if (!N) return null;
    const commitOne = (raw: string, fallback: number): number | null => {
      if (raw === "") return fallback;
      const n = Number(raw);
      if (!Number.isFinite(n)) return null;
      return clamp(n, 1, N);
    };
    const a = commitOne(fromStr, from);
    const b = commitOne(toStr, to);
    if (a === null || b === null) return null;
    onChangeRange(a, b);
    setFromStr(String(a));
    setToStr(String(b));
    return [a, b];
  };

  const revertFields = (): void => {
    setFromStr(String(from));
    setToStr(String(to));
  };

  const handleSelectClick = (): void => {
    // Commit the visible fields first, then select exactly that range —
    // parent props may still hold pre-typing values at this point.
    const committed = commitFields();
    if (!committed) {
      revertFields();
      return;
    }
    onSelectRange(committed[0], committed[1]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, kind: "from" | "to"): void => {
    // P12: Enter confirms range like clicking Zaznacz — handle both inputs
    if (e.key === "Enter") {
      e.preventDefault();
      handleSelectClick();
      return;
    }
    // type="text" has no native spinner: ArrowUp/Down step by 1 and commit.
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      if (!N) return;
      const delta = e.key === "ArrowUp" ? 1 : -1;
      const isFrom = kind === "from";
      const raw = isFrom ? fromStr : toStr;
      const fallback = isFrom ? from : to;
      const base = raw === "" ? fallback : Number(raw);
      if (!Number.isFinite(base)) return;
      const v = clamp(Math.trunc(base) + delta, 1, N);
      if (isFrom) {
        setFromStr(String(v));
        onChangeRange(v, to);
      } else {
        setToStr(String(v));
        onChangeRange(from, v);
      }
    }
  };

  const handleFromBlur = (): void => {
    if (!N) {
      revertFields();
      return;
    }
    if (!commitFields()) revertFields();
  };

  const handleToBlur = (): void => {
    if (!N) {
      revertFields();
      return;
    }
    if (!commitFields()) revertFields();
  };

  // aria-invalid when value out of bounds (empty while typing is not invalid)
  const fromInvalid = N > 0 && fromStr !== "" && (!Number.isFinite(Number(fromStr)) || Number(fromStr) < 1 || Number(fromStr) > N);
  const toInvalid = N > 0 && toStr !== "" && (!Number.isFinite(Number(toStr)) || Number(toStr) < 1 || Number(toStr) > N);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-2">
        <label htmlFor="range-from" className="text-body-sm font-medium">
          {t("range.from")}
        </label>
        <input
          id="range-from"
          data-testid="range-from"
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete="off"
          value={fromStr}
          onChange={(e) => handleFromChange(e.target.value)}
          onBlur={handleFromBlur}
          onFocus={selectAllOnFocus}
          onKeyDown={(e) => handleKeyDown(e, "from")}
          disabled={disabled}
          aria-disabled={disabled}
          aria-invalid={fromInvalid || undefined}
          className="h-9 w-20 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label={t("range.from")}
        />
        <span className="text-muted-foreground">–</span>
        <label htmlFor="range-to" className="text-body-sm font-medium">
          {t("range.to")}
        </label>
        <input
          id="range-to"
          data-testid="range-to"
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete="off"
          value={toStr}
          onChange={(e) => handleToChange(e.target.value)}
          onBlur={handleToBlur}
          onFocus={selectAllOnFocus}
          onKeyDown={(e) => handleKeyDown(e, "to")}
          disabled={disabled}
          aria-disabled={disabled}
          aria-invalid={toInvalid || undefined}
          className="h-9 w-20 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label={t("range.to")}
        />
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="range-select"
          onClick={handleSelectClick}
          disabled={disabled}
          aria-disabled={disabled}
          className="rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {t("range.select")}
        </button>
        <button
          type="button"
          data-testid="range-deselect"
          onClick={onClear}
          disabled={disabled && selectedCount === 0}
          aria-disabled={disabled && selectedCount === 0}
          className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {t("range.deselect")}
        </button>
      </div>

      <div className="ml-auto text-body-sm text-muted-foreground" data-testid="selected-label">
        {t("chapterList.selected", { count: selectedCount, total: N })}
      </div>
    </div>
  );
}
