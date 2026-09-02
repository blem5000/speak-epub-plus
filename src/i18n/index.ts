import en from "./locales/en.json";
import pl from "./locales/pl.json";

type Locale = "en" | "pl";
type Messages = typeof en;

const catalogs: Record<Locale, Messages> = {
  en: en as Messages,
  pl: pl as Messages,
};

export function detectLocale(): Locale {
  try {
    const navLang =
      typeof navigator !== "undefined" ? (navigator as unknown as { language?: unknown }).language : undefined;
    const lang = typeof navLang === "string" ? navLang.toLowerCase() : "en";
    if (lang.startsWith("pl")) return "pl";
    return "en";
  } catch {
    return "en";
  }
}

let currentLocale: Locale = detectLocale();
let currentMessages: Messages = catalogs[currentLocale];

export function getLocale(): Locale {
  return currentLocale;
}

export function setLocale(locale: string): void {
  // only accept en|pl — guard strict per spec 4.2
  if (locale === "en" || locale === "pl") {
    currentLocale = locale;
    currentMessages = catalogs[locale];
    // keep exported snapshots in sync for consumers that import `locale`/`messages` directly
    locale = currentLocale;
    messages = currentMessages;
  }
}

export function t(
  key: keyof Messages,
  params?: Record<string, string | number>
): string {
  const fallback = catalogs.en[key] ?? key;
  const template = (currentMessages[key] ?? fallback) as string;
  if (!params) return template;
  return Object.entries(params).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    template
  );
}

// Auto-detect on import; expose for App usage (mutable to stay in sync after setLocale)
export let locale: Locale = currentLocale;
export let messages: Messages = currentMessages;

// test hook: re-run detection (useful after mocking navigator.language)
export function __resetLocaleForTest(): void {
  currentLocale = detectLocale();
  currentMessages = catalogs[currentLocale];
  locale = currentLocale;
  messages = currentMessages;
}

export { catalogs };
