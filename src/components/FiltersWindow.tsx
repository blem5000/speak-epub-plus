import { useEffect, useRef } from "react";
import { t } from "@/i18n";
import Filters from "./Filters";

type FiltersWindowProps = {
  open: boolean;
  onClose: () => void;
};

export default function FiltersWindow({ open, onClose }: FiltersWindowProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);

  // focus trap + Esc + auto focus
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const prev = document.activeElement as HTMLElement | null;
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length > 0) {
      focusable[0].focus();
    } else {
      dialog.focus();
    }
    const handleKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialog) {
        const focusables = Array.from(
          dialog.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        ).filter((el) => !el.hasAttribute("disabled") && el.getAttribute("aria-hidden") !== "true");
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey) {
          if (active === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (active === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      prev?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="presentation"
      onClick={onClose}
      data-testid="filters-window-overlay"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" aria-hidden="true" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={(t("filters.title") as string) || "Filters"}
        data-testid="filters-window-dialog"
        tabIndex={-1}
        className="relative max-h-[90vh] w-full max-w-[640px] overflow-auto rounded-lg border bg-card shadow-lg focus-visible:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b bg-card px-6 py-4">
          <h2 className="text-heading font-semibold">{t("filters.title") || "Filtry"}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={(t("filters.title") as string) || "Close"}
            className="rounded-md p-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="filters-window-close"
          >
            ×
          </button>
        </div>
        <div className="p-6">
          <Filters />
        </div>
        <div className="flex justify-end gap-2 border-t px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="filters-window-close-footer"
          >
            {t("preview.original") ? "Zamknij" : "Close"}
          </button>
        </div>
      </div>
    </div>
  );
}
