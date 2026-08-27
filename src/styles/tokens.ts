/**
 * Design tokens distilled from DESIGN.md (neutral + single accent blue).
 * Used as JS source of truth; CSS vars in globals.css mirror these values.
 * Tailwind theme extends via tailwind.config.ts importing this file.
 */
export const tokens = {
  colors: {
    background: "#F8F9FA",
    backgroundDark: "#0F1115",
    foreground: "#1A1D23",
    foregroundDark: "#E6E8EB",
    muted: "#F1F3F5",
    mutedDark: "#1E2128",
    mutedForeground: "#6B7280",
    mutedForegroundDark: "#9AA0AE",
    border: "#E5E7EB",
    borderDark: "#2A2E37",
    input: "#E5E7EB",
    inputDark: "#2A2E37",
    ring: "#2B5CE6",
    ringDark: "#6B8AFF",
    primary: "#1A1D23",
    primaryForeground: "#FFFFFF",
    primaryDark: "#E6E8EB",
    primaryForegroundDark: "#0F1115",
    accent: "#2B5CE6",
    accentForeground: "#FFFFFF",
    accentDark: "#6B8AFF",
    accentForegroundDark: "#0F1115",
    success: "#0E9F6E",
    warning: "#E3A008",
    destructive: "#E02424",
    card: "#FFFFFF",
    cardDark: "#1A1D23",
  },
  typography: {
    display: {
      fontFamily: "Inter, Geist Sans, system-ui, sans-serif",
      fontSize: "28px",
      fontWeight: "600",
      lineHeight: "1.2",
      letterSpacing: "-0.02em",
    },
    displaySm: {
      fontFamily: "Inter, Geist Sans, system-ui, sans-serif",
      fontSize: "20px",
      fontWeight: "600",
      lineHeight: "1.25",
    },
    heading: {
      fontFamily: "Inter, Geist Sans, system-ui, sans-serif",
      fontSize: "16px",
      fontWeight: "600",
      lineHeight: "1.4",
    },
    body: {
      fontFamily: "Inter, Geist Sans, system-ui, sans-serif",
      fontSize: "14px",
      fontWeight: "400",
      lineHeight: "1.5",
    },
    bodySm: {
      fontFamily: "Inter, Geist Sans, system-ui, sans-serif",
      fontSize: "13px",
      fontWeight: "400",
      lineHeight: "1.5",
    },
    mono: {
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
      fontSize: "12px",
      fontWeight: "400",
      lineHeight: "1.5",
    },
  },
  rounded: {
    sm: "6px",
    md: "8px",
    lg: "12px",
    xl: "16px",
    full: "9999px",
  },
  spacing: {
    xs: "4px",
    sm: "8px",
    md: "16px",
    lg: "24px",
    xl: "32px",
    "2xl": "48px",
  },
} as const;

export type Tokens = typeof tokens;
