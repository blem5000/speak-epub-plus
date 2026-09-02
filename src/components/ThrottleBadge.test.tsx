import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ThrottleBadge from "./ThrottleBadge";

describe("ThrottleBadge", () => {
  it("renders polite default", () => {
    render(<ThrottleBadge tier="polite" delay={4000} />);
    const badge = screen.getByTestId("throttle-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toMatch(/polite/);
    expect(badge.getAttribute("aria-live")).toBe("polite");
    expect(badge.className).toContain("bg-muted");
  });

  it("renders safe with bg-warning and 10000", () => {
    render(<ThrottleBadge tier="safe" delay={10000} />);
    const badge = screen.getByTestId("throttle-badge");
    expect(badge.textContent).toBe("safe 10000");
    expect(badge.className).toContain("bg-warning");
  });

  it("handles throttle prop object", () => {
    render(<ThrottleBadge throttle={{ tier: "safe", delay: 10000 }} />);
    expect(screen.getByTestId("throttle-badge").textContent).toBe("safe 10000");
  });

  it("aria-live polite and warning style when safe", () => {
    render(<ThrottleBadge throttle={{ tier: "safe", delay: 10000 }} />);
    const badge = screen.getByTestId("throttle-badge");
    expect(badge.getAttribute("aria-live")).toBe("polite");
    expect(badge.textContent).toContain("safe");
  });
});
