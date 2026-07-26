import Link from "next/link";

import { AnalysisCard } from "@/components/AnalysisCard";
import { StatusBadge } from "@/components/badges";
import { ErrorPanel } from "@/components/ErrorPanel";
import { FeedbackForm } from "@/components/FeedbackForm";
import { AssigneeControl, StatusControl } from "@/components/TicketControls";
import { TicketActionButton } from "@/components/TicketActionButton";
import { getTicket, listFeedback } from "@/lib/api/tickets";
import { ApiError } from "@/lib/api/errors";
import type { FeedbackResponse, TicketDetail } from "@/lib/api/types";
import { getAuthedContext } from "@/lib/auth/guard";
import { formatDateTime, formatSla, isOverdue } from "@/lib/format";
import { applyRoutingAction, reanalyzeAction } from "@/lib/tickets/actions";

export default async function TicketDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const { token, orgId } = await getAuthedContext();

  let ticket: TicketDetail;
  try {
    ticket = await getTicket(token, orgId, id);
  } catch (error) {
    const message =
      error instanceof ApiError && error.status === 404
        ? "This ticket does not exist in your organization."
        : "Could not load the ticket. Is the backend running?";
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorPanel title="Ticket unavailable" message={message} />
      </div>
    );
  }

  // Feedback is best-effort context; a failure here shouldn't break the page.
  let feedback: FeedbackResponse[] = [];
  try {
    feedback = await listFeedback(token, orgId, id);
  } catch {
    feedback = [];
  }

  // API returns analyses oldest-first; the last is the latest version.
  const analyses = ticket.analyses;
  const latest = analyses.length > 0 ? analyses[analyses.length - 1] : null;
  const history = [...analyses].reverse();

  return (
    <div className="space-y-6">
      <BackLink />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">Ticket {id.slice(0, 8)}</h1>
            <StatusBadge status={ticket.status} />
          </div>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            {ticket.source} · created {formatDateTime(ticket.created_at)} · SLA:{" "}
            <span className={isOverdue(ticket.sla_due_at) ? "text-red-600 dark:text-red-400" : ""}>
              {formatSla(ticket.sla_due_at)}
            </span>
          </p>
        </div>
        <div className="flex items-start gap-3">
          <TicketActionButton
            ticketId={id}
            action={reanalyzeAction}
            label="Re-analyze"
            pendingLabel="Re-analyzing…"
          />
          <TicketActionButton
            ticketId={id}
            action={applyRoutingAction}
            label="Apply routing"
            pendingLabel="Routing…"
          />
        </div>
      </div>

      <section className="grid gap-4 rounded-lg border border-neutral-200 bg-white p-4 sm:grid-cols-2 dark:border-neutral-800 dark:bg-neutral-900">
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase text-neutral-500 dark:text-neutral-400">
            Status
          </h2>
          <StatusControl ticketId={id} current={ticket.status} />
        </div>
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase text-neutral-500 dark:text-neutral-400">
            Assignee
          </h2>
          <AssigneeControl ticketId={id} current={ticket.assignee} />
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase text-neutral-500 dark:text-neutral-400">
          Original message
        </h2>
        <pre className="whitespace-pre-wrap rounded-lg border border-neutral-200 bg-white p-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
          {ticket.raw_text}
        </pre>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase text-neutral-500 dark:text-neutral-400">
          Analysis history ({analyses.length})
        </h2>
        {history.length === 0 ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            No analysis yet. Use “Re-analyze” to generate one.
          </p>
        ) : (
          <div className="space-y-3">
            {history.map((a) => (
              <AnalysisCard key={a.id} analysis={a} isLatest={latest?.id === a.id} />
            ))}
          </div>
        )}
      </section>

      {latest ? (
        <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="mb-3 text-sm font-semibold uppercase text-neutral-500 dark:text-neutral-400">
            Feedback on latest analysis
          </h2>
          <FeedbackForm ticketId={id} analysisId={latest.id} />

          {feedback.length > 0 ? (
            <ul className="mt-4 space-y-2 border-t border-neutral-200 pt-4 text-sm dark:border-neutral-800">
              {feedback.map((f) => (
                <li key={f.id} className="text-neutral-600 dark:text-neutral-400">
                  <span className="font-medium">{f.rating}</span>
                  {f.corrected_category ? ` · cat→ ${f.corrected_category}` : ""}
                  {f.corrected_priority ? ` · pri→ ${f.corrected_priority}` : ""}
                  {f.comment ? ` · “${f.comment}”` : ""}
                  <span className="ml-2 text-xs text-neutral-400">{formatDateTime(f.created_at)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/tickets" className="text-sm text-neutral-500 underline dark:text-neutral-400">
      ← Back to tickets
    </Link>
  );
}
