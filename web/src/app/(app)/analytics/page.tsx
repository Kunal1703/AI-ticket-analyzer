import { AnalyticsControls } from "@/components/AnalyticsControls";
import { DistributionBars, priorityBarColor } from "@/components/DistributionBars";
import { ErrorPanel } from "@/components/ErrorPanel";
import { StatTile } from "@/components/StatTile";
import { TimeseriesChart } from "@/components/TimeseriesChart";
import { getSummary, getTimeseries } from "@/lib/api/analytics";
import { ApiError } from "@/lib/api/errors";
import type { AnalyticsSummary, TimeseriesResponse } from "@/lib/api/types";
import { getAuthedContext } from "@/lib/auth/guard";
import { parseAnalyticsParams } from "@/lib/analytics/query";

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = parseAnalyticsParams(await searchParams);
  const { token, orgId } = await getAuthedContext();
  const win = { start: params.start, end: params.end };

  let summary: AnalyticsSummary | null = null;
  let timeseries: TimeseriesResponse | null = null;
  let errorMessage: string | null = null;
  try {
    [summary, timeseries] = await Promise.all([
      getSummary(token, orgId, win),
      getTimeseries(token, orgId, params.metric, win),
    ]);
  } catch (error) {
    errorMessage =
      error instanceof ApiError
        ? error.message
        : "Could not load analytics. Is the backend running?";
  }

  const metricLabel = params.metric === "analyses" ? "Analyses" : "Tickets";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>

      <AnalyticsControls params={params} />

      {errorMessage || !summary || !timeseries ? (
        <ErrorPanel
          title="Couldn't load analytics"
          message={errorMessage ?? "No data available."}
        />
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <StatTile label="Total tickets" value={summary.total_tickets} />
            <StatTile label="Total analyses" value={summary.total_analyses} />
          </section>

          <Panel title={`${metricLabel} per day`}>
            <TimeseriesChart points={timeseries.points} label={metricLabel} />
          </Panel>

          <section className="grid gap-4 lg:grid-cols-2">
            <Panel title="By priority">
              <DistributionBars data={summary.by_priority} colorFor={priorityBarColor} />
            </Panel>
            <Panel title="By category">
              <DistributionBars data={summary.by_category} />
            </Panel>
          </section>
        </>
      )}
    </div>
  );
}
