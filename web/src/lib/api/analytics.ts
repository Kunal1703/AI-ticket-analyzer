/**
 * Typed wrappers over the backend analytics endpoints (`/v1/analytics/*`).
 * Server-only, tenant-scoped (bearer + `X-Organization-Id` via `apiFetch`).
 */

import "server-only";

import { apiFetch } from "./http";
import type { AnalyticsSummary, TimeseriesMetric, TimeseriesResponse } from "./types";

export interface AnalyticsWindow {
  start?: string;
  end?: string;
}

function windowQuery(win: AnalyticsWindow): URLSearchParams {
  const qs = new URLSearchParams();
  if (win.start) qs.set("start", win.start);
  if (win.end) qs.set("end", win.end);
  return qs;
}

export function getSummary(
  token: string,
  orgId: string,
  win: AnalyticsWindow = {},
): Promise<AnalyticsSummary> {
  const qs = windowQuery(win).toString();
  return apiFetch<AnalyticsSummary>(`/v1/analytics/summary${qs ? `?${qs}` : ""}`, {
    token,
    orgId,
  });
}

export function getTimeseries(
  token: string,
  orgId: string,
  metric: TimeseriesMetric,
  win: AnalyticsWindow = {},
): Promise<TimeseriesResponse> {
  const qs = windowQuery(win);
  qs.set("metric", metric);
  return apiFetch<TimeseriesResponse>(`/v1/analytics/timeseries?${qs.toString()}`, {
    token,
    orgId,
  });
}
