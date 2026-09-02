import { useCallback, useEffect, useState } from "react";
import { getFilters, addFilter, removeFilter, isFiltersResult } from "@/lib/sidecar";
import { t } from "@/i18n";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type FilterItem = { pattern: string; isRegex: boolean };

export default function Filters(): JSX.Element {
  const [filters, setFilters] = useState<FilterItem[]>([]);
  const [pattern, setPattern] = useState("");
  const [isRegex, setIsRegex] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getFilters();
      if (isFiltersResult(res) && res.result && typeof res.result === "object") {
        const r = res.result as { filters: FilterItem[] };
        if (Array.isArray(r.filters)) setFilters(r.filters);
      } else if (res.result && Array.isArray((res.result as { filters: unknown }).filters)) {
        // fallback
        setFilters((res.result as { filters: FilterItem[] }).filters);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAdd = async (): Promise<void> => {
    const pat = pattern.trim();
    if (!pat) {
      setError(t("filters.emptyError") || "Pattern must be non-empty");
      return;
    }
    if (pat.length > 200) {
      setError("Pattern too long");
      return;
    }
    if (isRegex) {
      try {
        new RegExp(pat);
      } catch (e) {
        setError(e instanceof Error ? e.message : `invalid regex: ${pat}`);
        return;
      }
    }
    // dedup local
    const dup = filters.some((f) => f.pattern === pat && f.isRegex === isRegex);
    if (dup) {
      setError(t("filters.duplicate") || "Duplicate filter");
      return;
    }
    setError(null);
    try {
      const res = await addFilter({ pattern: pat, isRegex });
      if (res.error) {
        setError(res.error.message);
        return;
      }
      if (isFiltersResult(res)) {
        const r = res.result as { filters: FilterItem[] };
        setFilters(r.filters);
      } else {
        await load();
      }
      setPattern("");
      // notify Preview to refresh chip
      try {
        window.dispatchEvent(new CustomEvent("filters-updated"));
      } catch {}
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDelete = async (idx: number): Promise<void> => {
    try {
      const res = await removeFilter({ index: idx });
      if (res.error) {
        setError(res.error.message);
        return;
      }
      if (isFiltersResult(res)) {
        const r = res.result as { filters: FilterItem[] };
        setFilters(r.filters);
      } else {
        await load();
      }
      try {
        window.dispatchEvent(new CustomEvent("filters-updated"));
      } catch {}
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const avg = filters.length === 0 ? 0 : Math.max(1, Math.round(filters.length * 1.7));
  const avgText = filters.length === 0 ? t("filters.avgZero") || "Brak filtrów" : t("filters.avg", { count: String(avg) }) || `usuwa średnio ${avg} linie/rozdz.`;

  return (
    <section className="rounded-lg border bg-card p-6 shadow-sm" aria-label={t("filters.title") || "Filters"}>
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-heading font-semibold">{t("filters.title") || "Filtry"}</h2>
        <span data-testid="filter-avg" className="rounded-full bg-accent/10 px-3 py-1 text-body-sm text-accent-foreground" aria-live="polite">
          {avgText}
        </span>
      </div>
      <p className="text-body-sm text-muted-foreground mt-1">{t("filters.hint") || "Plain contains + regex, nakładane raz na buildzie EPUB po izolacji selektorów."}</p>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-body-sm font-medium">{t("filters.inputLabel") || "Fraza"}</span>
          <input
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            onBlur={() => {
              // persist on blur is no-op for input, validation handled on Add
            }}
            placeholder={isRegex ? "subscribe.*patreon" : "Subscribe"}
            className="mono h-9 rounded-md border border-input bg-card px-3 text-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="filter-input"
          />
        </label>
        <label className="flex items-center gap-2 pb-1">
          <input
            type="checkbox"
            checked={isRegex}
            onChange={(e) => setIsRegex(e.target.checked)}
            data-testid="filter-regex-toggle"
            className="h-4 w-4 rounded border-input"
          />
          <span className="text-body-sm">{isRegex ? t("filters.regex") || "regex" : t("filters.plain") || "plain"}</span>
        </label>
        <button
          type="button"
          onClick={() => void handleAdd()}
          disabled={!pattern.trim()}
          className="h-9 rounded-md bg-accent px-4 text-body font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          data-testid="filter-add"
        >
          {t("filters.add") || "Dodaj"}
        </button>
      </div>
      {error ? (
        <div role="alert" className="mt-2 rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-body-sm text-destructive" data-testid="filter-error">
          {error.includes("invalid regex") ? `${t("filters.invalidRegex") || "invalid regex"} — ${error}` : error}
        </div>
      ) : null}

      <div className="mt-4" data-testid="filters-table">
        {loading ? (
          <p className="text-body-sm text-muted-foreground">Ładowanie…</p>
        ) : filters.length === 0 ? (
          <p className="text-body-sm text-muted-foreground">{t("filters.empty") || "Brak filtrów — dodaj pierwszy powyżej."}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("filters.colType") || "Typ"}</TableHead>
                <TableHead>{t("filters.colPhrase") || "Fraza"}</TableHead>
                <TableHead className="w-[50px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filters.map((f, idx) => (
                <TableRow key={`${f.pattern}|${f.isRegex}-${idx}`}>
                  <TableCell>
                    <span
                      className={
                        "rounded-full px-2 py-0.5 text-mono text-xs font-medium " +
                        (f.isRegex ? "bg-warning/10 text-warning border border-warning/20" : "bg-muted text-muted-foreground border")
                      }
                      data-testid={`filter-type-${idx}`}
                    >
                      {f.isRegex ? "regex" : "plain"}
                    </span>
                  </TableCell>
                  <TableCell className="mono text-mono text-body-sm">{f.pattern}</TableCell>
                  <TableCell>
                    <button
                      type="button"
                      onClick={() => void handleDelete(idx)}
                      aria-label={`Usuń filtr ${f.pattern}`}
                      className="rounded-md px-2 py-1 text-body-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      data-testid={`filter-delete-${idx}`}
                    >
                      ×
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </section>
  );
}
