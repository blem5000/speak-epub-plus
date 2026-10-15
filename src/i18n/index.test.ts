import { describe, it, expect, beforeEach, vi } from "vitest";

describe("i18n auto-detect pl/en", () => {
  void (globalThis.navigator as unknown as { language?: string } | undefined);

  function mockNavigatorLanguage(lang: string | undefined): void {
    try {
      Object.defineProperty(window, "navigator", {
        value: { language: lang },
        configurable: true,
        writable: true,
      });
    } catch {
      // fallback jsdom
      (globalThis as unknown as { navigator: unknown }).navigator = { language: lang };
    }
  }

  beforeEach(() => {
    vi.resetModules();
  });

  it("detectLocale pl-PL → pl, en-US → en, unknown → en", async () => {
    mockNavigatorLanguage("pl-PL");
    vi.resetModules();
    const modPl = await import("./index");
    expect(modPl.detectLocale()).toBe("pl");
    expect(modPl.getLocale()).toBe("pl");
    expect(modPl.t("settings.title" as unknown as keyof typeof modPl.catalogs.en)).toBe("Ustawienia");

    mockNavigatorLanguage("en-US");
    vi.resetModules();
    const modEn = await import("./index");
    expect(modEn.detectLocale()).toBe("en");
    expect(modEn.getLocale()).toBe("en");

    mockNavigatorLanguage("de-DE");
    vi.resetModules();
    const modDe = await import("./index");
    expect(modDe.detectLocale()).toBe("en");
    expect(modDe.getLocale()).toBe("en");

    mockNavigatorLanguage("PL-pl");
    vi.resetModules();
    const modPlUpper = await import("./index");
    expect(modPlUpper.detectLocale()).toBe("pl");

    // navigator undefined → en
    try {
      Object.defineProperty(window, "navigator", {
        value: undefined,
        configurable: true,
      });
    } catch {}
    vi.resetModules();
    const modNoNav = await import("./index");
    expect(modNoNav.detectLocale()).toBe("en");

    // restore
    mockNavigatorLanguage("en-US");
    vi.resetModules();
    await import("./index");
  });

  it("t() fallback en when pl key missing", async () => {
    mockNavigatorLanguage("pl-PL");
    vi.resetModules();
    const mod = await import("./index");
    mod.setLocale("pl");
    // add a key only in en for test: use existing key that is in en but delete from pl catalog for this test via direct catalogs mutation
    const enKey = "settings.toast.saved" as unknown as keyof typeof mod.catalogs.en;
    // ensure key exists in en
    expect(mod.catalogs.en[enKey]).toBeDefined();
    // simulate missing in pl by deleting from pl catalog copy (mutate)
    const originalPlVal = (mod.catalogs.pl as Record<string, unknown>)[enKey as string];
    delete (mod.catalogs.pl as Record<string, unknown>)[enKey as string];
    // t should fallback to en
    expect(mod.t(enKey)).toBe(mod.catalogs.en[enKey]);
    // restore
    if (originalPlVal !== undefined) {
      (mod.catalogs.pl as Record<string, unknown>)[enKey as string] = originalPlVal;
    }
    // no throw on totally missing key
    expect(() => mod.t("nonexistent.key" as unknown as keyof typeof mod.catalogs.en)).not.toThrow();
    expect(mod.t("nonexistent.key" as unknown as keyof typeof mod.catalogs.en)).toBe("nonexistent.key");
  });

  it("setLocale switches and only accepts en|pl", async () => {
    mockNavigatorLanguage("en-US");
    vi.resetModules();
    const mod = await import("./index");
    expect(mod.getLocale()).toBe("en");
    mod.setLocale("pl");
    expect(mod.getLocale()).toBe("pl");
    expect(mod.t("settings.title" as unknown as keyof typeof mod.catalogs.en)).toBe("Ustawienia");
    // invalid locale ignored
    (mod.setLocale as (l: string) => void)("de");
    expect(mod.getLocale()).toBe("pl");
    (mod.setLocale as (l: string) => void)("EN" as unknown as string);
    expect(mod.getLocale()).toBe("pl");
    mod.setLocale("en");
    expect(mod.getLocale()).toBe("en");
    expect(mod.locale).toBe("en");
    expect(mod.messages).toBe(mod.catalogs.en);
  });

  it("no throw on missing key and fallback to en", async () => {
    vi.resetModules();
    const mod = await import("./index");
    expect(() => mod.t("settings.title" as unknown as keyof typeof mod.catalogs.en)).not.toThrow();
    expect(() => mod.t("missing.key.never" as unknown as keyof typeof mod.catalogs.en)).not.toThrow();
  });

  it("navigator.language lowercases and guards", async () => {
    mockNavigatorLanguage("Pl-pL");
    vi.resetModules();
    const mod = await import("./index");
    expect(mod.detectLocale()).toBe("pl");
    mockNavigatorLanguage(undefined);
    vi.resetModules();
    const mod2 = await import("./index");
    expect(mod2.detectLocale()).toBe("en");
  });

  it("en/pl catalogs have identical key sets (no drift)", async () => {
    vi.resetModules();
    const mod = await import("./index");
    expect(Object.keys(mod.catalogs.pl).sort()).toEqual(Object.keys(mod.catalogs.en).sort());
    // newly adopted M4 keys must exist in both
    for (const key of ["toast.ban", "ffmpeg.missing", "filters.close", "preview.close", "preview.rendered"]) {
      expect(mod.catalogs.en).toHaveProperty(key);
      expect(mod.catalogs.pl).toHaveProperty(key);
    }
  });
});
