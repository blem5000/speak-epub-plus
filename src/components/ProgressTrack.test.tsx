import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ProgressTrack from "./ProgressTrack";

describe("ProgressTrack", () => {
  it("renders 0% when total 0", () => {
    render(<ProgressTrack done={0} total={0} />);
    const track = screen.getByTestId("progress-track");
    expect(track).toBeInTheDocument();
    expect(track.getAttribute("aria-valuenow")).toBe("0");
    const fill = screen.getByTestId("progress-fill");
    expect(fill.style.width).toBe("0%");
  });

  it("renders width 50% for 1/2", () => {
    render(<ProgressTrack done={1} total={2} />);
    expect(screen.getByTestId("progress-track").getAttribute("aria-valuenow")).toBe("50");
    expect(screen.getByTestId("progress-fill").style.width).toBe("50%");
  });

  it("renders 100% for done==total", () => {
    render(<ProgressTrack done={5} total={5} />);
    expect(screen.getByTestId("progress-track").getAttribute("aria-valuenow")).toBe("100");
    expect(screen.getByTestId("progress-fill").style.width).toBe("100%");
  });

  it("caps at 100% even if done > total", () => {
    render(<ProgressTrack done={10} total={5} />);
    expect(screen.getByTestId("progress-fill").style.width).toBe("100%");
  });

  it("has progressbar role", () => {
    render(<ProgressTrack done={2} total={4} />);
    expect(screen.getByTestId("progress-track").getAttribute("role")).toBe("progressbar");
  });
});
