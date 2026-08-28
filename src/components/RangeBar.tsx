import { useEffect, useState } from "react";
import { t } from "@/i18n";
import { clampRange } from "@/lib/selection";

type RangeBarProps = {
  from: number;
  to: number;
  total: number;
  selectedCount: number;
  onChangeRange: (from: number, to: number) => void;
  onSelectRange: () => void;
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    // P12: Enter confirms range like clicking Zaznacz — handle both inputs
    if (e.key === "Enter") {
      e.preventDefault();
      if (typeof window === "undefined") return;
      // clamp both fields (from or to) before select
      handleFromBlur();
      handleToBlur();
      window.setTimeout(() => onSelectRange(), 0);
    }
  };

  const handleFromBlur = (): void => {
    if (!N) {
      setFromStr(String(from));
      return;
    }
    const clamped = clampRange(fromStr === "" ? from : fromStr, toStr === "" ? to : toStr, N);
    if (clamped) {
      const [a, b] = clamped;
      onChangeRange(a, b);
      setFromStr(String(a));
      setToStr(String(b));
    } else {
      setFromStr(String(from));
      setToStr(String(to));
    }
  };

  const handleToBlur = (): void => {
    if (!N) {
      setToStr(String(to));
      return;
    }
    const clamped = clampRange(fromStr === "" ? from : fromStr, toStr === "" ? to : toStr, N);
    if (clamped) {
      const [a, b] = clamped;
      onChangeRange(a, b);
      setFromStr(String(a));
      setToStr(String(b));
    } else {
      setFromStr(String(from));
      setToStr(String(to));
    }
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
          type="number"
          inputMode="numeric"
          step={1}
          min={1}
          max={N || undefined}
          value={fromStr}
          onChange={(e) => handleFromChange(e.target.value)}
          onBlur={handleFromBlur}
          onKeyDown={handleKeyDown}
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
          type="number"
          inputMode="numeric"
          step={1}
          min={1}
          max={N || undefined}
          value={toStr}
          onChange={(e) => handleToChange(e.target.value)}
          onBlur={handleToBlur}
          onKeyDown={handleKeyDown}
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
          onClick={onSelectRange}
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
