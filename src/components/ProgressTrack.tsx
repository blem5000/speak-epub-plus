type ProgressTrackProps = {
  done: number;
  total: number;
};

export default function ProgressTrack({ done, total }: ProgressTrackProps): JSX.Element {
  const percent = total ? (done / total) * 100 : 0;
  const width = `${Math.min(100, Math.max(0, percent))}%`;
  return (
    <div
      data-testid="progress-track"
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`progress ${done}/${total}`}
      className="h-1.5 w-full rounded-full bg-muted overflow-hidden"
      style={{ background: "var(--color-muted, #F1F3F5)" }}
    >
      <div
        data-testid="progress-fill"
        className="h-full rounded-full bg-accent transition-all"
        style={{ width, background: "var(--color-accent, #2B5CE6)" }}
      />
    </div>
  );
}
