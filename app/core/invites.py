"""
Calendar invites (.ics) for the APR email, as the previous app attached one. Written by hand (RFC 5545) so no
extra package is needed. Times are India Standard Time, which has no daylight saving, so they are converted to
UTC exactly; an event without a time becomes an all-day entry. METHOD:PUBLISH adds the events to a calendar
without asking anyone to RSVP.
"""
from datetime import date, datetime, timedelta, timezone

IST = timedelta(hours=5, minutes=30)


def _esc(text) -> str:
    return (str(text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n'))


def _fold(line: str) -> str:
    """Lines longer than 75 octets are folded with a leading space, as the standard asks."""
    out, cur = [], b''
    for ch in line:
        b = ch.encode('utf-8')
        if len(cur) + len(b) > 73:
            out.append(cur.decode('utf-8'))
            cur = b' ' + b
        else:
            cur += b
    out.append(cur.decode('utf-8'))
    return '\r\n'.join(out)


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _as_time(v):
    try:
        h, m = str(v).split(':')[:2]
        return int(h), int(m)
    except (TypeError, ValueError):
        return None


def build_ics(events: list, uid_prefix: str, today: date = None) -> tuple:
    """events: [{'date': 'YYYY-MM-DD', 'start_time': 'HH:MM', 'end_time': 'HH:MM', 'summary', 'location', 'description'}].
    Only events from today on are included. Returns (ics_bytes, count); (b'', 0) when nothing is upcoming."""
    today = today or date.today()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//SPIC MACAY//APR Assistant//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    n = 0
    for i, e in enumerate(events, 1):
        d = _as_date(e.get('date'))
        if not d or d < today:
            continue
        n += 1
        lines += ['BEGIN:VEVENT', f'UID:{uid_prefix}-{i}@spicmacay.org', f'DTSTAMP:{stamp}']
        st = _as_time(e.get('start_time'))
        if st:
            start = datetime(d.year, d.month, d.day, *st) - IST
            et = _as_time(e.get('end_time'))
            end = (datetime(d.year, d.month, d.day, *et) - IST) if et else start + timedelta(hours=2)
            if end <= start:
                end = start + timedelta(hours=2)
            lines += [f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}"]
        lines += [f"SUMMARY:{_esc(e.get('summary'))}", f"LOCATION:{_esc(e.get('location'))}",
                  f"DESCRIPTION:{_esc(e.get('description'))}", 'STATUS:CONFIRMED', 'TRANSP:OPAQUE', 'END:VEVENT']
    if not n:
        return b'', 0
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(_fold(x) for x in lines) + '\r\n').encode('utf-8'), n
