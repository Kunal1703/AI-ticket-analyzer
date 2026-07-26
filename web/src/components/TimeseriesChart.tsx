import type { TimeseriesPoint } from "@/lib/api/types";

/**
 * A single-series daily bar chart (change-over-time). One hue; recessive
 * baseline; each bar carries a native hover tooltip (`<title>`) with its
 * date + count. Values aren't printed on every bar (that's an anti-pattern) —
 * the peak is called out in the caption and per-bar values are on hover.
 */
export function TimeseriesChart({ points, label }: { points: TimeseriesPoint[]; label: string }) {
  if (points.length === 0) {
    return (
      <p className="text-sm text-neutral-500 dark:text-neutral-400">No data in this range.</p>
    );
  }

  const W = 720;
  const H = 180;
  const pad = 24;
  const max = Math.max(...points.map((p) => p.count), 1);
  const slot = (W - pad * 2) / points.length;
  const barW = Math.max(1, slot * 0.7);
  const peak = Math.max(...points.map((p) => p.count));

  return (
    <figure className="space-y-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`${label} per day from ${points[0].date} to ${points[points.length - 1].date}`}
        preserveAspectRatio="none"
      >
        <line
          x1={pad}
          y1={H - pad}
          x2={W - pad}
          y2={H - pad}
          className="stroke-neutral-200 dark:stroke-neutral-700"
          strokeWidth={1}
        />
        {points.map((p, i) => {
          const h = (p.count / max) * (H - pad * 2);
          const x = pad + i * slot + (slot - barW) / 2;
          const y = H - pad - h;
          return (
            <rect
              key={p.date}
              x={x}
              y={y}
              width={barW}
              height={h}
              rx={2}
              className="fill-sky-500 dark:fill-sky-400"
            >
              <title>{`${p.date}: ${p.count}`}</title>
            </rect>
          );
        })}
      </svg>
      <figcaption className="flex justify-between text-xs text-neutral-500 dark:text-neutral-400">
        <span>{points[0].date}</span>
        <span>peak {peak}</span>
        <span>{points[points.length - 1].date}</span>
      </figcaption>
    </figure>
  );
}
