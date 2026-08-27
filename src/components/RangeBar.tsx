import { t } from "@/i18n";
import { clamp } from "@/lib/selection";

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

  const handleFromChange = (val: string): void => {
    if (val === "") {
      // empty → no-op, keep current but allow user to clear field? Treat as ignore
      // we keep previous value
      return;
    }
    const num = Number(val);
    if (!Number.isFinite(num)) return;
    // immediate update without clamp; clamp onBlur / onSelect
    onChangeRange(num, to);
  };

  const handleToChange = (val: string): void => {
    if (val === "") return;
    const num = Number(val);
    if (!Number.isFinite(num)) return;
    onChangeRange(from, num);
  };

  const handleFromBlur = (): void => {
    if (!N) return;
    const clamped = clamp(Number(from), 1, N);
    // also swap if needed? spec says clamp od<1→1 do>N→N od>do swap
    let a = clamped;
    let b = clamp(Number(to), 1, N);
    if (a > b) [a, b] = [b, a];
    onChangeRange(a, b);
  };

  const handleToBlur = (): void => {
    if (!N) return;
    let a = clamp(Number(from), 1, N);
    let b = clamp(Number(to), 1, N);
    if (a > b) [a, b] = [b, a];
    onChangeRange(a, b);
  };

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
          min={1}
          max={N || undefined}
          value={from}
          onChange={(e) => handleFromChange(e.target.value)}
          onBlur={handleFromBlur}
          className="h-9 w-20 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
          min={1}
          max={N || undefined}
          value={to}
          onChange={(e) => handleToChange(e.target.value)}
          onBlur={handleToBlur}
          className="h-9 w-20 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t("range.to")}
        />
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="range-select"
          onClick={onSelectRange}
          className="rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("range.select")}
        </button>
        <button
          type="button"
          data-testid="range-deselect"
          onClick={onClear}
          className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
