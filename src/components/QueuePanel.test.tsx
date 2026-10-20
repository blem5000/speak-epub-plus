import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QueuePanel from "./QueuePanel";

describe("QueuePanel", () => {
  const noop = (): void => {};

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is hidden when the queue is empty", () => {
    render(
      <QueuePanel
        items={[]}
        outcomes={[]}
        running={false}
        progress={null}
        onRemove={noop}
        onClear={noop}
        onConvert={noop}
      />
    );
    expect(screen.queryByTestId("queue-panel")).not.toBeInTheDocument();
  });

  it("lists the queued books and removes one", async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    render(
      <QueuePanel
        items={[
          { url: "https://x.test/a", title: "Pierwsza" },
          { url: "https://x.test/b", title: "Druga" },
        ]}
        outcomes={[]}
        running={false}
        progress={null}
        onRemove={onRemove}
        onClear={noop}
        onConvert={noop}
      />
    );
    expect(screen.getByTestId("queue-panel")).toBeInTheDocument();
    expect(screen.getByText("Pierwsza")).toBeInTheDocument();
    await user.click(screen.getByTestId("queue-remove-https://x.test/a"));
    expect(onRemove).toHaveBeenCalledWith("https://x.test/a");
  });

  it("disables the convert button while running and shows the progress", () => {
    render(
      <QueuePanel
        items={[{ url: "https://x.test/a", title: "Pierwsza" }]}
        outcomes={[]}
        running
        progress={{ index: 1, total: 3, title: "Pierwsza" }}
        onRemove={noop}
        onClear={noop}
        onConvert={noop}
      />
    );
    expect(screen.getByTestId("queue-convert")).toBeDisabled();
    expect(screen.getByTestId("queue-progress").textContent).toContain("1/3");
  });

  it("shows the outcome of every book", async () => {
    render(
      <QueuePanel
        items={[
          { url: "https://x.test/a", title: "Pierwsza" },
          { url: "https://x.test/b", title: "Druga" },
        ]}
        outcomes={[
          { url: "https://x.test/a", title: "Pierwsza", status: "ok", path: "out/a.m4b" },
          { url: "https://x.test/b", title: "Druga", status: "error", message: "boom" },
        ]}
        running={false}
        progress={null}
        onRemove={noop}
        onClear={noop}
        onConvert={noop}
      />
    );
    await waitFor(() => expect(screen.getByTestId("queue-status-https://x.test/a")).toBeInTheDocument());
    expect(screen.getByTestId("queue-status-https://x.test/a").textContent).toMatch(/Gotowe|Done/);
    expect(screen.getByTestId("queue-status-https://x.test/b").textContent).toContain("boom");
  });
});
