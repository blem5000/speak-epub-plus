import { useRef } from "react";
import { t } from "@/i18n";

type FindInputProps = {
  value: string;
  onChange: (value: string) => void;
  searching?: boolean;
};

export default function FindInput({ value, onChange, searching }: FindInputProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleClear = (): void => {
    onChange("");
    inputRef.current?.focus();
  };

  const handlePaste = async (): Promise<void> => {
    try {
      // Prefer modern clipboard API — guard for SSR/jsdom
      if (typeof navigator !== "undefined" && navigator.clipboard?.readText) {
        const text = await navigator.clipboard.readText();
        if (typeof text === "string") {
          onChange(text);
          // keep focus
          inputRef.current?.focus();
          return;
        }
      }
    } catch {
      // fallback: try execCommand paste? ignore
    }
    // If clipboard not available, just focus so user can Ctrl+V
    inputRef.current?.focus();
    // attempt to trigger paste via document.execCommand for older browsers
    try {
      if (typeof document !== "undefined" && (document as unknown as { execCommand?: (cmd: string) => boolean }).execCommand) {
        (document as unknown as { execCommand: (cmd: string) => boolean }).execCommand("paste");
      }
    } catch {
      // noop
    }
  };

  const showClear = (value?.length ?? 0) > 0;

  return (
    <div className="relative w-full">
      <input
        ref={inputRef}
        data-testid="find-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("find.placeholder")}
        aria-label={t("find.placeholder")}
        className="h-11 w-full rounded-md border border-input bg-card px-4 pr-20 text-body placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-0"
        // 44px per spec, focus:ring-2 ring AA — AA contrast verified
        autoFocus
      />
      <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center gap-1">
        {showClear ? (
          <button
            type="button"
            onClick={handleClear}
            aria-label={t("find.clear") ?? "Clear"}
            className="pointer-events-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            tabIndex={0}
          >
            {/* x icon */}
            <span aria-hidden="true" className="text-body-sm leading-none">
              ×
            </span>
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => {
            void handlePaste();
          }}
          aria-label={t("find.paste") ?? "Paste"}
          className="pointer-events-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          tabIndex={0}
        >
          {/* paste icon: simple clipboard glyph */}
          <span aria-hidden="true" className="text-[11px] leading-none">
            ⎘
          </span>
        </button>
        {searching ? (
          <span
            aria-label={t("find.searching")}
            className="ml-1 inline-block h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent"
            role="status"
          />
        ) : null}
      </div>
    </div>
  );
}
