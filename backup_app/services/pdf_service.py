"""
PDF Generation Service — SPIC MACAY Artist Payment Reports
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Directory where APR PDFs are saved  (app/static/pdfs/)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # → app/
PDFS_DIR  = os.path.join(_BASE_DIR, 'static', 'pdfs')

# Directory where optional event/program photos are saved  (app/static/event_photos/)
EVENT_PHOTOS_DIR = os.path.join(_BASE_DIR, 'static', 'event_photos')


# ── Public API ────────────────────────────────────────────────────────────────

def generate_apr_pdf(apr_data: dict, event_data: dict, coordinator_data: dict = None) -> bytes:
    """
    Generate a SPIC MACAY APR PDF and return it as bytes.

    Args:
        apr_data:         {'request_id': ..., 'custom_apr': ..., 'status': ...}
        event_data:       event details; for circuits includes 'circuit_events' list, for
                           virasats includes 'virasat_events' list (each with its own
                           artist_name/art_form/module_name — one institution, many artists)
        coordinator_data: optional {'coordinator_name': ..., 'coordinator_email': ...}

    Returns:
        PDF as bytes; empty bytes on failure.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        logger.error("fpdf2 not installed — cannot generate APR PDF")
        return b''

    try:
        cd = coordinator_data or {}
        coordinator_name  = (
            cd.get('coordinator_name') or event_data.get('coordinator_name')
            or event_data.get('created_by') or ''
        ).strip()
        coordinator_email = (
            cd.get('coordinator_email') or event_data.get('coordinator_email')
            or event_data.get('creator_email') or ''
        ).strip()
        chapter = event_data.get('chapter', '')
        mobile  = event_data.get('coordinator_mobile', '')

        apr_no     = apr_data.get('request_id', 'N/A')
        custom_apr = apr_data.get('custom_apr', '')

        artist_name = event_data.get('artist_name', 'N/A')
        art_form    = event_data.get('art_form', 'N/A')
        module_name = event_data.get('module_name', 'N/A')
        event_type  = event_data.get('event_type', 'single')
        attendees   = event_data.get('attendees', 0)

        # Build events list
        circuit_events = event_data.get('circuit_events') or []
        virasat_events = event_data.get('virasat_events') or []
        is_virasat = event_type == 'virasat' and bool(virasat_events)
        if is_virasat:
            events_list = virasat_events
        elif circuit_events:
            events_list = circuit_events
        else:
            events_list = [{
                'date':             event_data.get('event_date') or event_data.get('start_date', ''),
                'institution_name': event_data.get('institution_name', 'N/A'),
                'city':             event_data.get('city', ''),
                'state':            event_data.get('state', ''),
                'event_time':       event_data.get('event_time', ''),
                'module_name':      module_name,
            }]

        RED = (139, 0, 0)

        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.set_margins(15, 15, 15)
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        PAGE_W = pdf.w - 30  # usable width = 180 mm

        # ── Header ──────────────────────────────────────────────────────────
        pdf.set_font('Helvetica', 'B', 18)
        pdf.cell(PAGE_W, 10, 'SPIC MACAY',
                 new_x='LMARGIN', new_y='NEXT', align='C')

        pdf.set_font('Helvetica', '', 9)
        pdf.cell(PAGE_W, 5,
                 'Society for the Promotion of Indian Classical Music And Culture Amongst Youth',
                 new_x='LMARGIN', new_y='NEXT', align='C')

        pdf.ln(2)
        pdf.set_draw_color(*RED)
        pdf.set_line_width(0.8)
        _hline(pdf)
        pdf.ln(3)

        pdf.set_font('Helvetica', 'B', 13)
        pdf.cell(PAGE_W, 7, 'ARTIST PAYMENT REQUEST',
                 new_x='LMARGIN', new_y='NEXT', align='C')

        pdf.set_font('Helvetica', '', 10)
        apr_date = datetime.now().strftime('%d %b %Y')
        pdf.cell(PAGE_W, 6, f'APR No: {apr_no}     Date: {apr_date}',
                 new_x='LMARGIN', new_y='NEXT', align='C')

        if custom_apr:
            pdf.set_font('Helvetica', '', 8)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(PAGE_W, 5, f'Ref: {custom_apr}',
                     new_x='LMARGIN', new_y='NEXT', align='C')
            pdf.set_text_color(0, 0, 0)

        pdf.ln(3)
        pdf.set_line_width(0.4)
        _hline(pdf)
        pdf.ln(4)

        # ── Section 1: Coordinator ───────────────────────────────────────────
        _section_heading(pdf, PAGE_W, 'Section 1: Coordinator Details', RED)
        # Cols: Name(60) + Chapter(40) + Mobile(35) + Email(45) = 180
        cw = [60, 40, 35, 45]
        _table_header(pdf, cw, ['Coordinator Name', 'Chapter', 'Mobile No', 'Email'])
        _table_row(pdf, cw, [coordinator_name, chapter, mobile, coordinator_email])
        pdf.ln(5)

        # ── Section 2: Events ────────────────────────────────────────────────
        if is_virasat:
            cat_label = 'Virasat Series'
        elif event_type == 'circuit':
            cat_label = 'Circuit'
        else:
            cat_label = 'Single Event'
        _section_heading(pdf, PAGE_W, f'Section 2: Event Details  (Category: {cat_label})', RED)

        if is_virasat:
            # One host institution for the whole series — shown once, not per row.
            pdf.set_font('Helvetica', 'B', 9)
            venue_line = event_data.get('institution_name', 'N/A')
            loc = ', '.join(filter(None, [event_data.get('city', ''), event_data.get('state', '')]))
            if loc:
                venue_line += f'  ({loc})'
            pdf.cell(PAGE_W, 6, f'Host Institution: {venue_line}', new_x='LMARGIN', new_y='NEXT')
            pdf.ln(1)

            # Cols: Sl(8) + Date(24) + Module(38) + Artist(75) + Art Form(35) = 180
            ew = [8, 24, 38, 75, 35]
            _table_header(pdf, ew, ['Sl.', 'Date', 'Module', 'Artist', 'Art Form'])
            for idx, ev in enumerate(events_list, 1):
                ev_date = ev.get('date') or ev.get('start_date', '')
                try:
                    ev_date = datetime.strptime(ev_date, '%Y-%m-%d').strftime('%d %b %Y')
                except Exception:
                    pass
                _table_row(pdf, ew, [
                    str(idx),
                    ev_date,
                    ev.get('module_name') or module_name,
                    ev.get('artist_name', 'N/A'),
                    ev.get('art_form', ''),
                ])
        else:
            # Cols: Sl(10) + Date(28) + Module(42) + Institution(65) + City(35) = 180
            ew = [10, 28, 42, 65, 35]
            _table_header(pdf, ew, ['Sl.', 'Date', 'Module / Category', 'Institution', 'City'])
            for idx, ev in enumerate(events_list, 1):
                ev_date = ev.get('date') or ev.get('start_date', '')
                try:
                    ev_date = datetime.strptime(ev_date, '%Y-%m-%d').strftime('%d %b %Y')
                except Exception:
                    pass
                _table_row(pdf, ew, [
                    str(idx),
                    ev_date,
                    ev.get('module_name') or module_name,
                    ev.get('institution_name', 'N/A'),
                    ev.get('city', ''),
                ])
        pdf.ln(5)

        # ── Section 3: Artist ────────────────────────────────────────────────
        _section_heading(pdf, PAGE_W, 'Section 3: Artist Details', RED)
        # Cols: Role(35) + Name(85) + Art Form(60) = 180
        aw = [35, 85, 60]
        _table_header(pdf, aw, ['Role', 'Artist Name', 'Art Form'])
        if is_virasat:
            # Each performance has its own artist — list every distinct performer instead
            # of one "Main Artist" (there is no single main artist in a Virasat).
            seen = set()
            for ev in events_list:
                name = ev.get('artist_name', '')
                if not name or name in seen:
                    continue
                seen.add(name)
                _table_row(pdf, aw, ['Performer', name, ev.get('art_form', '')])
        else:
            _table_row(pdf, aw, ['Main Artist', artist_name, art_form])
            for acc in (event_data.get('accompanying_artists') or []):
                _table_row(pdf, aw, ['Accompanying', acc.get('name', ''), acc.get('art_form', '')])
        pdf.ln(8)

        # ── Footer ───────────────────────────────────────────────────────────
        pdf.set_draw_color(*RED)
        pdf.set_line_width(0.4)
        _hline(pdf)
        pdf.ln(4)

        pdf.set_font('Helvetica', 'B', 9)
        pdf.cell(PAGE_W, 5,
                 f'No. of Events: {len(events_list)}     Expected Attendees: {attendees}',
                 new_x='LMARGIN', new_y='NEXT')
        pdf.cell(PAGE_W, 5, 'Payment Required by Delhi A/c: Yes',
                 new_x='LMARGIN', new_y='NEXT')

        pdf.ln(6)
        pdf.set_font('Helvetica', '', 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(PAGE_W, 4,
                 'System-generated document  |  SPIC MACAY AI Agent',
                 new_x='LMARGIN', new_y='NEXT', align='C')
        pdf.set_text_color(0, 0, 0)

        return bytes(pdf.output())

    except Exception as e:
        logger.error(f"APR PDF generation failed: {e}", exc_info=True)
        return b''


def generate_payment_request_pdf(reminder_data: dict, event_data: dict, bank_config: dict = None) -> bytes:
    """
    Generate a short "Request for Payment" PDF asking a host institution to pay their
    program contribution — mirrors the layout of SPIC MACAY's existing Word-based
    Request for Payment documents (see Sample Request for Payments/ in the workspace).

    Args:
        reminder_data: {'amount': ..., 'coordinator_name': ..., 'chapter': ...}
        event_data:    {'institution_name', 'city', 'module_name', 'artist_name',
                         'accompanying_artists' (optional list), 'event_date'}
        bank_config:   optional {'bank_name', 'account_name', 'account_number', 'ifsc_code'};
                       falls back to SPIC MACAY HQ's account shown in the sample documents.

    Returns:
        PDF as bytes; empty bytes on failure.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        logger.error("fpdf2 not installed — cannot generate payment request PDF")
        return b''

    try:
        bank = bank_config or {}
        bank_name       = bank.get('bank_name', 'State Bank of India')
        bank_account_nm = bank.get('account_name', 'SPIC MACAY')
        bank_account_no = bank.get('account_number', '10773571902')
        bank_ifsc       = bank.get('ifsc_code', 'SBIN0011781')

        institution_name = event_data.get('institution_name', 'N/A')
        city              = event_data.get('city', '')
        module_name       = event_data.get('module_name', 'Program')
        artist_name       = event_data.get('artist_name', 'N/A')
        accompanying      = event_data.get('accompanying_artists') or []
        event_date        = event_data.get('event_date') or event_data.get('start_date', '')
        try:
            event_date = datetime.strptime(event_date, '%Y-%m-%d').strftime('%d %b %Y')
        except Exception:
            pass

        chapter          = reminder_data.get('chapter', '')
        coordinator_name = reminder_data.get('coordinator_name', '')
        amount           = reminder_data.get('amount')
        amount_str       = f"Rs {amount:,.0f}" if isinstance(amount, (int, float)) else (str(amount) if amount else 'N/A')

        performers = artist_name
        if accompanying:
            performers += ' with ' + ', '.join(a.get('name', '') for a in accompanying if a.get('name'))

        RED = (139, 0, 0)

        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.set_margins(15, 15, 15)
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        PAGE_W = pdf.w - 30  # 180 mm

        # ── Header ──────────────────────────────────────────────────────────
        pdf.set_font('Helvetica', 'B', 18)
        pdf.cell(PAGE_W, 10, 'SPIC MACAY', new_x='LMARGIN', new_y='NEXT', align='C')

        pdf.set_font('Helvetica', '', 9)
        pdf.cell(PAGE_W, 5,
                 'Society for the Promotion of Indian Classical Music And Culture Amongst Youth',
                 new_x='LMARGIN', new_y='NEXT', align='C')

        pdf.ln(2)
        pdf.set_draw_color(*RED)
        pdf.set_line_width(0.8)
        _hline(pdf)
        pdf.ln(3)

        pdf.set_font('Helvetica', 'B', 13)
        pdf.cell(PAGE_W, 7, 'REQUEST FOR PAYMENT', new_x='LMARGIN', new_y='NEXT', align='C')

        pdf.set_font('Helvetica', '', 10)
        inv_date = datetime.now().strftime('%d %b %Y')
        pdf.cell(PAGE_W, 6, f'Invoice Date: {inv_date}', new_x='LMARGIN', new_y='NEXT', align='C')

        pdf.ln(3)
        pdf.set_line_width(0.4)
        _hline(pdf)
        pdf.ln(4)

        # ── To ──────────────────────────────────────────────────────────────
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(PAGE_W, 6, 'TO,', new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(PAGE_W, 6, institution_name, new_x='LMARGIN', new_y='NEXT')
        if city:
            pdf.cell(PAGE_W, 6, city, new_x='LMARGIN', new_y='NEXT')
        pdf.ln(4)

        # ── Line items ──────────────────────────────────────────────────────
        _section_heading(pdf, PAGE_W, 'Contribution Details', RED)
        # Cols: Sl(10) + Description(100) + Date(35) + Amount(35) = 180
        cw = [10, 100, 35, 35]
        _table_header(pdf, cw, ['Sl.', 'Description', 'Date', 'Amount'])
        _table_row(pdf, cw, [
            '1',
            f'Contribution towards {module_name} by {performers}',
            event_date,
            amount_str,
        ])
        pdf.ln(3)

        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(PAGE_W, 6, f'Total: {amount_str}', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(6)

        # ── Bank details ────────────────────────────────────────────────────
        pdf.set_font('Helvetica', '', 10)
        deposit_line = f'Kindly deposit the contribution payment in the SPIC MACAY{" " + chapter if chapter else ""} Bank Account:'
        pdf.multi_cell(PAGE_W, 6, deposit_line)
        pdf.ln(1)

        pdf.set_font('Helvetica', '', 9)
        for label, val in [
            ('Bank Name', bank_name),
            ('Account Name', bank_account_nm),
            ('Account No', bank_account_no),
            ('IFSC Code', bank_ifsc),
        ]:
            pdf.cell(PAGE_W, 5.5, f'{label}: {val}', new_x='LMARGIN', new_y='NEXT')

        pdf.ln(8)

        # ── Signature ───────────────────────────────────────────────────────
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(PAGE_W, 6, 'Regards,', new_x='LMARGIN', new_y='NEXT')
        if coordinator_name:
            pdf.cell(PAGE_W, 6, f'({coordinator_name})', new_x='LMARGIN', new_y='NEXT')
        pdf.cell(PAGE_W, 6, f'SPIC MACAY{" " + chapter if chapter else ""}',
                 new_x='LMARGIN', new_y='NEXT')

        # ── Footer ──────────────────────────────────────────────────────────
        pdf.ln(6)
        pdf.set_draw_color(*RED)
        pdf.set_line_width(0.4)
        _hline(pdf)
        pdf.ln(4)
        pdf.set_font('Helvetica', '', 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(PAGE_W, 4,
                 'System-generated document  |  SPIC MACAY AI Agent',
                 new_x='LMARGIN', new_y='NEXT', align='C')
        pdf.set_text_color(0, 0, 0)

        return bytes(pdf.output())

    except Exception as e:
        logger.error(f"Payment request PDF generation failed: {e}", exc_info=True)
        return b''


def save_payment_request_pdf(pdf_bytes: bytes, event_id) -> str:
    """
    Save a Request for Payment PDF to app/static/pdfs/payment_request_<event_id>_<timestamp>.pdf.

    Returns:
        Absolute file path on success, '' on failure.
    """
    if not pdf_bytes:
        return ''
    try:
        os.makedirs(PDFS_DIR, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d%H%M%S')
        path = os.path.join(PDFS_DIR, f'payment_request_{event_id}_{stamp}.pdf')
        with open(path, 'wb') as fh:
            fh.write(pdf_bytes)
        logger.info(f"Payment request PDF saved: {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to save payment request PDF: {e}", exc_info=True)
        return ''


def save_apr_pdf(pdf_bytes: bytes, request_id: str) -> str:
    """
    Save PDF bytes to app/static/pdfs/<request_id>.pdf.

    Returns:
        Absolute file path on success, '' on failure.
    """
    if not pdf_bytes:
        return ''
    try:
        os.makedirs(PDFS_DIR, exist_ok=True)
        safe_id = request_id.replace('/', '_').replace('\\', '_')
        path = os.path.join(PDFS_DIR, f'{safe_id}.pdf')
        with open(path, 'wb') as fh:
            fh.write(pdf_bytes)
        logger.info(f"APR PDF saved: {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to save APR PDF: {e}", exc_info=True)
        return ''


def save_event_photos(photos: list, event_id) -> list:
    """
    Save optional event/program photos to app/static/event_photos/<event_id>/.

    Args:
        photos:   list of {'bytes': ..., 'filename': ..., 'mime_type': ...}
        event_id: the program's event_list.id

    Returns:
        List of paths relative to the static/ folder (e.g. 'event_photos/312/1_poster.jpg'),
        suitable for storing in event_list.image and for building URLs with url_for('static', ...).
    """
    if not photos:
        return []
    try:
        event_dir = os.path.join(EVENT_PHOTOS_DIR, str(event_id))
        os.makedirs(event_dir, exist_ok=True)

        saved_paths = []
        for idx, photo in enumerate(photos, 1):
            photo_bytes = photo.get('bytes')
            if not photo_bytes:
                continue
            raw_name = photo.get('filename') or f'photo_{idx}.jpg'
            safe_name = ''.join(c for c in raw_name if c.isalnum() or c in ('.', '_', '-')) or f'photo_{idx}.jpg'
            filename = f'{idx}_{safe_name}'
            full_path = os.path.join(event_dir, filename)
            with open(full_path, 'wb') as fh:
                fh.write(photo_bytes)
            saved_paths.append(f'event_photos/{event_id}/{filename}')

        logger.info(f"Saved {len(saved_paths)} event photo(s) for event {event_id}")
        return saved_paths
    except Exception as e:
        logger.error(f"Failed to save event photos for event {event_id}: {e}", exc_info=True)
        return []


def load_poster_bytes(image_field: str):
    """
    Given event_list.image (the comma-separated relative static/ paths written by
    save_event_photos), return the bytes of the saved program poster, if one was
    uploaded for this program — used to re-attach it to payment reminders sent later,
    possibly in a completely different conversation.

    Returns:
        Poster bytes, or None if no poster was saved for this program.
    """
    if not image_field:
        return None
    try:
        static_dir = os.path.join(_BASE_DIR, 'static')
        for rel_path in image_field.split(','):
            rel_path = rel_path.strip()
            if 'event_poster' not in rel_path:
                continue
            full_path = os.path.join(static_dir, *rel_path.split('/'))
            with open(full_path, 'rb') as fh:
                return fh.read()
        return None
    except Exception as e:
        logger.warning(f"Could not load saved poster from '{image_field}': {e}")
        return None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hline(pdf):
    """Draw a full-width horizontal rule at the current y position."""
    y = pdf.get_y()
    pdf.line(15, y, 195, y)


def _section_heading(pdf, page_w, title, color):
    """Dark-background section heading."""
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(*color)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(page_w, 7, f'  {title}', border=0,
             new_x='LMARGIN', new_y='NEXT', fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)


def _table_header(pdf, col_widths, labels):
    """Draw grey-background header row."""
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(230, 230, 230)
    last = len(labels) - 1
    for i, (w, lbl) in enumerate(zip(col_widths, labels)):
        nx = 'LMARGIN' if i == last else 'RIGHT'
        ny = 'NEXT'    if i == last else 'TOP'
        pdf.cell(w, 7, f' {lbl}', border=1,
                 new_x=nx, new_y=ny, fill=True)


def _table_row(pdf, col_widths, values):
    """Draw one plain data row."""
    pdf.set_font('Helvetica', '', 8)
    last = len(values) - 1
    for i, (w, val) in enumerate(zip(col_widths, values)):
        nx = 'LMARGIN' if i == last else 'RIGHT'
        ny = 'NEXT'    if i == last else 'TOP'
        pdf.cell(w, 7, f' {str(val or "")}', border=1,
                 new_x=nx, new_y=ny)
