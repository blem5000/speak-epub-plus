import { useState } from "react";
import { t } from "@/i18n";

export type PronunciationEntry = {
  from: string;
  to: string;
};

type PronunciationEditorProps = {
  entries: PronunciationEntry[];
  onChange: (entries: PronunciationEntry[]) => void;
};

/**
 * The pronunciation dictionary: how a word should be read. The replacement
 * is plain text (not SSML), so it works with every engine — the local Piper
 * one included.
 */
export default function PronunciationEditor({
  entries,
  onChange,
}: PronunciationEditorProps): JSX.Element {
  const [from, setFrom] = useState<string>("");
  const [to, setTo] = useState<string>("");
  const [error, setError] = useState<string>("");

  const add = (): void => {
    const source = from.trim();
    const target = to.trim();
    if (!source || !target) {
      setError(t("pronunciation.incomplete") as string);
      return;
    }
    const without = entries.filter((e) => e.from.toLowerCase() !== source.toLowerCase());
    onChange([...without, { from: source, to: target }]);
    setFrom("");
    setTo("");
    setError("");
  };

  const remove = (source: string): void => {
    onChange(entries.filter((e) => e.from !== source));
  };

  const exportJson = (): void => {
    const payload = JSON.stringify(entries, null, 2);
    try {
      void navigator.clipboard?.writeText(payload);
      setError("");
    } catch {
      setError(t("pronunciation.exportFailed") as string);
    }
  };

  return (
    <section
      className="rounded-lg border bg-card p-6 shadow-sm"
      aria-label={t("pronunciation.title") as string}
      data-testid="pronunciation-editor"
    >
      <h3 className="text-heading font-semibold">{t("pronunciation.title") as string}</h3>
      <p className="mt-1 text-body-sm text-muted-foreground">
        {t("pronunciation.helper") as string}
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-body-sm font-medium">{t("pronunciation.from") as string}</span>
          <input
            data-testid="pronunciation-from"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            placeholder="Arystoteles"
            className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-body-sm font-medium">{t("pronunciation.to") as string}</span>
          <input
            data-testid="pronunciation-to"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder="ary-stoteles"
            className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        <button
          type="button"
          data-testid="pronunciation-add"
          onClick={add}
          className="h-9 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("pronunciation.add") as string}
        </button>
        {entries.length > 0 ? (
          <button
            type="button"
            data-testid="pronunciation-export"
            onClick={exportJson}
            className="h-9 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("pronunciation.export") as string}
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="mt-2 text-body-sm text-destructive" role="alert" data-testid="pronunciation-error">
          {error}
        </p>
      ) : null}

      {entries.length > 0 ? (
        <ul className="mt-3 space-y-1" data-testid="pronunciation-list">
          {entries.map((entry) => (
            <li
              key={entry.from}
              className="flex items-center justify-between gap-3 text-body-sm"
              data-testid={`pronunciation-row-${entry.from}`}
            >
              <span className="min-w-0 truncate">
                <span className="font-medium">{entry.from}</span>
                <span className="text-muted-foreground"> → {entry.to}</span>
              </span>
              <button
                type="button"
                data-testid={`pronunciation-remove-${entry.from}`}
                onClick={() => remove(entry.from)}
                aria-label={t("pronunciation.remove", { word: entry.from }) as string}
                className="shrink-0 rounded-md border border-input bg-card px-2 py-0.5 text-body-xs hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("pronunciation.removeShort") as string}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-body-sm text-muted-foreground" data-testid="pronunciation-empty">
          {t("pronunciation.empty") as string}
        </p>
      )}
    </section>
  );
}
