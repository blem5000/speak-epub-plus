type ThrottleBadgeProps = {
  tier?: string | null;
  delay?: number | null;
  throttle?: { tier: string; delay: number } | null;
};

export default function ThrottleBadge({ tier, delay, throttle }: ThrottleBadgeProps): JSX.Element {
  const effectiveTier = throttle?.tier ?? tier ?? "polite";
  const effectiveDelay = throttle?.delay ?? delay ?? 4000;
  const isSafe = effectiveTier === "safe";

  const text = isSafe ? `safe ${effectiveDelay}` : "polite (oczekiwanie)";
  const ariaLabel = `throttle ${effectiveTier} ${effectiveDelay}`;

  return (
    <span
      data-testid="throttle-badge"
      aria-live="polite"
      aria-label={ariaLabel}
      className={
        "rounded-full px-3 py-1 text-body-sm font-medium " +
        (isSafe ? "bg-warning text-warning-foreground border border-warning/20" : "bg-muted text-muted-foreground")
      }
    >
      {text}
    </span>
  );
}
