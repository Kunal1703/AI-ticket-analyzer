"""
Ticket read / history API (Milestone M3.1).

Exposes tenant-scoped, read-only access to tickets and their versioned analyses
(``/v1/tickets``). Tickets are created implicitly by the analyze path
(``get_or_create_ticket``); this package never creates or mutates them — it only
lists and reads them, scoped to the caller's organization.
"""

from app.tickets.base import FeedbackStore, TicketStore

__all__ = ["FeedbackStore", "TicketStore"]
