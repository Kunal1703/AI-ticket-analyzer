/**
 * Pure parsing/serialization + scaling helpers for the analytics dashboard
 * (Next.js-free, unit-tested). The backend validates dates (ISO `YYYY-MM-DD`)
 * and the metric enum, so we only forward well-formed values.
 */

import type { TimeseriesMetric } from "../api/types";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export interface AnalyticsParams {
  start?: string;
  end?: string;
  metric: TimeseriesMetric;
}

type RawParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Return the value only if it is a well-formed calendar date (else undefined). */
export function validDate(value: string | undefined): string | undefined {
  if (!value || !ISO_DATE.test(value)) return undefined;
  return Number.isNaN(Date.parse(value)) ? undefined : value;
}

/** Parse raw search params into validated analytics parameters. */
export function parseAnalyticsParams(sp: RawParams): AnalyticsParams {
  const rawMetric = first(sp.metric);
  const metric: TimeseriesMetric = rawMetric === "analyses" ? "analyses" : "tickets";
  return { start: validDate(first(sp.start)), end: validDate(first(sp.end)), metric };
}

/** Build an `/analytics` href with the given (partial) params merged in. */
export function buildAnalyticsHref(params: Partial<AnalyticsParams>): string {
  const qs = new URLSearchParams();
  if (params.metric && params.metric !== "tickets") qs.set("metric", params.metric);
  if (params.start) qs.set("start", params.start);
  if (params.end) qs.set("end", params.end);
  const query = qs.toString();
  return query ? `/analytics?${query}` : "/analytics";
}

/**
 * Percentage width for a bar of `value` against `max` (0–100, clamped). Returns
 * 0 when `max` is non-positive so an empty dataset renders flat, not NaN.
 */
export function barPercent(value: number, max: number): number {
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (value / max) * 100));
}

/** Record → entries sorted by count descending (stable for ties by insertion). */
export function sortedEntries(record: Record<string, number>): [string, number][] {
  return Object.entries(record).sort((a, b) => b[1] - a[1]);
}
