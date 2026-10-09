"""
Weekly Report Service — builds and sends the two recurring SPIC MACAY recap emails:

1. Events report  → programs logged this week + academic-year-to-date totals,
   with an Excel attachment of the week's programs.
2. Artist report   → artists added this week, with two Excel attachments: the
   week's new artists, and the complete artist directory.

Triggered weekly by the APScheduler job set up in app/__init__.py, and can be
fired on demand via POST /api/admin/send-weekly-reports for testing.
"""
import io
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ── Excel builders ──────────────────────────────────────────────────────────

def _autofit(ws):
    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 50)


def build_events_excel(events: list) -> bytes:
    """One sheet: programs logged this week."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Programs This Week"
    headers = ['ID', 'Title', 'Artist', 'Institution', 'Module', 'Program Date',
               'City', 'State', 'Status', 'Logged On']
    ws.append(headers)
    for ev in events:
        ws.append([
            ev.get('id'),
            ev.get('title') or '',
            ev.get('artist_name') or '',
            ev.get('institution_name') or '',
            ev.get('module_name') or '',
            str(ev.get('start_date') or ''),
            ev.get('city') or '',
            ev.get('state') or '',
            ev.get('event_status') or '',
            str(ev.get('added_date') or ''),
        ])
    _autofit(ws)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_artists_excel(artists: list, sheet_title: str = "Artists") -> bytes:
    """One sheet of artist rows — reused for both the 'this week' and 'full directory'
    attachments (same shape, different row sets)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]  # Excel sheet name limit
    headers = ['ID', 'Name', 'Art Form', 'City', 'State', 'Email', 'Phone',
               'Artist Type', 'Grade', 'Added On']
    ws.append(headers)
    for a in artists:
        ws.append([
            a.get('tid'),
            a.get('name') or '',
            a.get('art_form') or '',
            a.get('city') or '',
            a.get('state') or '',
            a.get('email') or '',
            a.get('phone') or '',
            a.get('artist_type') or '',
            a.get('artist_grade') or '',
            str(a.get('added_date') or ''),
        ])
    _autofit(ws)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Orchestration ────────────────────────────────────────────────────────────

def send_weekly_events_report(event_service, notification_service, recipients: list) -> bool:
    """Build and send the weekly events recap email. Returns True if sent."""
    if not recipients:
        logger.warning("No recipients configured for the weekly events report — skipping")
        return False
    try:
        week_events = event_service.get_events_added_this_week()
        ay_stats = event_service.get_academic_year_to_date_stats()

        report_data = {
            'week_events': week_events,
            'week_count': len(week_events),
            'academic_year': ay_stats.get('academic_year', ''),
            'academic_year_total': ay_stats.get('total_events', 0),
            'events_by_status': ay_stats.get('events_by_status', []),
            'generated_on': datetime.now().strftime('%d %b %Y'),
        }

        excel_bytes = build_events_excel(week_events) if week_events else None

        return notification_service.send_weekly_events_report(report_data, recipients, excel_bytes)
    except Exception as e:
        logger.error(f"Failed to build/send weekly events report: {e}", exc_info=True)
        return False


def send_weekly_artist_report(event_service, notification_service, recipients: list) -> bool:
    """Build and send the weekly artist directory recap email. Returns True if sent."""
    if not recipients:
        logger.warning("No recipients configured for the weekly artist report — skipping")
        return False
    try:
        week_artists = event_service.get_artists_added_this_week()
        all_artists = event_service.get_all_artists()

        report_data = {
            'week_artists': week_artists,
            'week_count': len(week_artists),
            'total_artists': len(all_artists),
            'generated_on': datetime.now().strftime('%d %b %Y'),
        }

        week_excel = build_artists_excel(week_artists, "New This Week") if week_artists else None
        full_excel = build_artists_excel(all_artists, "Full Directory")

        return notification_service.send_weekly_artist_report(
            report_data, recipients, week_excel, full_excel
        )
    except Exception as e:
        logger.error(f"Failed to build/send weekly artist report: {e}", exc_info=True)
        return False


def send_payment_confirmations(event_service, notification_service, since_days: int = 30) -> dict:
    """
    Announce artist payments the finance team completed recently — one note to the artist,
    one to the coordinator who filed the APR.

    A payment stays inside the `since_days` window across several weekly runs, so each
    recipient is recorded in the notification ledger and skipped thereafter.
    """
    summary = {'artist_emails_sent': 0, 'coordinator_emails_sent': 0, 'payments_processed': 0}
    try:
        payments = event_service.get_completed_payments(since_days=since_days)
        if not payments:
            logger.info("No new completed payments to announce")
            return summary

        for pay in payments:
            artist_sent = False

            if pay.get('notify_artist'):
                artist_email = pay['artist_email'].strip()
                if notification_service.send_payment_completed_artist(pay, [artist_email]):
                    artist_sent = True
                    summary['artist_emails_sent'] += 1
                    event_service.record_payment_notification(
                        pay['payment_id'], 'artist', artist_email,
                        pay.get('event_id'), pay.get('artist_id'),
                    )

            if pay.get('notify_coordinator'):
                coordinator_email = pay['coordinator_email'].strip()
                # Distinguishes "artist already knows" from "please pass this on"
                payload = dict(pay, artist_notified=artist_sent or bool(pay.get('artist_email')))
                if notification_service.send_payment_completed_coordinator(payload, [coordinator_email]):
                    summary['coordinator_emails_sent'] += 1
                    event_service.record_payment_notification(
                        pay['payment_id'], 'coordinator', coordinator_email,
                        pay.get('event_id'), pay.get('artist_id'),
                    )

            summary['payments_processed'] += 1

        logger.info(f"Payment confirmations run complete — {summary}")
        return summary
    except Exception as e:
        logger.error(f"Failed to send payment confirmations: {e}", exc_info=True)
        return summary


def send_weekly_reports(event_service, notification_service, events_recipients: list,
                         artist_recipients: list, payment_window_days: int = 30) -> dict:
    """Send both weekly reports. Used by the scheduled job and the manual trigger route."""
    events_sent = send_weekly_events_report(event_service, notification_service, events_recipients)
    artist_sent = send_weekly_artist_report(event_service, notification_service, artist_recipients)
    payments = send_payment_confirmations(event_service, notification_service, payment_window_days)
    logger.info(f"Weekly reports run complete — events_sent={events_sent}, artist_sent={artist_sent}")
    return {
        'events_report_sent': events_sent,
        'artist_report_sent': artist_sent,
        'payment_confirmations': payments,
    }
