/**
 * Pure form-parsing helpers for the admin panel (Next.js-free, unit-tested).
 */

/** Split a comma-separated field into a trimmed, de-duplicated, non-empty list. */
export function parseCsvList(value: string | null | undefined): string[] {
  if (!value) return [];
  const seen = new Set<string>();
  for (const part of value.split(",")) {
    const trimmed = part.trim();
    if (trimmed) seen.add(trimmed);
  }
  return [...seen];
}

/**
 * Build a routing rule's `conditions` object from optional category/priority,
 * omitting empty values (the backend treats present keys as required matches).
 */
export function buildRoutingConditions(
  category: string | null | undefined,
  priority: string | null | undefined,
): Record<string, string> {
  const conditions: Record<string, string> = {};
  if (category) conditions.category = category;
  if (priority) conditions.priority = priority;
  return conditions;
}

/**
 * Build a routing rule's `actions` object: an optional assignee and a tag list.
 * `tags` is always present (possibly empty), matching the backend default.
 */
export function buildRoutingActions(
  assignee: string | null | undefined,
  tagsCsv: string | null | undefined,
): Record<string, unknown> {
  const actions: Record<string, unknown> = { tags: parseCsvList(tagsCsv) };
  const trimmed = assignee?.trim();
  if (trimmed) actions.assignee = trimmed;
  return actions;
}
