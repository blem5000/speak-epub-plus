import en from "./locales/en.json";
import pl from "./locales/pl.json";

type Locale = "en" | "pl";
type Messages = typeof en;

const catalogs: Record<Locale, Messages> = {
  en: en as Messages,
  pl: pl as Messages,
};

function detectLocale(): Locale {
  const lang =
    typeof navigator !== "undefined" ? navigator.language.toLowerCase() : "en";
  if (lang.startsWith("pl")) return "pl";
  return "en";
}

let currentLocale: Locale = detectLocale();
let currentMessages: Messages = catalogs[currentLocale];

export function getLocale(): Locale {
  return currentLocale;
}

export function setLocale(locale: Locale): void {
  if (catalogs[locale]) {
    currentLocale = locale;
    currentMessages = catalogs[locale];
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

// Auto-detect on import; expose for App usage
export const locale = currentLocale;
export const messages = currentMessages;
