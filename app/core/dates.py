"""
Dates and times the way coordinators actually say them (reviewer comment DC1).

Accepts 15-10-2026, 15/10/26, 15 Oct 2026, October 15th, "next Friday", "kal",
"१५ अक्टूबर" and more. Always returns ISO for storage plus an unambiguous read-back
("15 Oct 2026 (Thu)"). Numeric dates are read day-first, as is usual in India.
"""
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Optional

_MONTH_WORDS = {
    1: ['jan', 'january', 'janvari', 'जनवरी'], 2: ['feb', 'february', 'farvari', 'फरवरी', 'फ़रवरी'],
    3: ['mar', 'march', 'मार्च'], 4: ['apr', 'april', 'अप्रैल', 'एप्रिल'], 5: ['may', 'मई'],
    6: ['jun', 'june', 'जून'], 7: ['jul', 'july', 'जुलाई', 'जुलै'], 8: ['aug', 'august', 'अगस्त', 'ऑगस्ट'],
    9: ['sep', 'sept', 'september', 'सितंबर', 'सितम्बर', 'सप्टेंबर'],
    10: ['oct', 'october', 'अक्टूबर', 'अक्तूबर', 'ऑक्टोबर'],
    11: ['nov', 'november', 'नवंबर', 'नवम्बर', 'नोव्हेंबर'], 12: ['dec', 'december', 'दिसंबर', 'दिसम्बर', 'डिसेंबर'],
}
MONTHS = {w: m for m, ws in _MONTH_WORDS.items() for w in ws}
_MONTH_RE = '|'.join(sorted((re.escape(w) for w in MONTHS), key=len, reverse=True))
_WD_WORDS = {
    0: ['monday', 'mon', 'somvar', 'somwar', 'सोमवार'], 1: ['tuesday', 'tue', 'tues', 'mangalvar', 'mangalwar', 'मंगलवार'],
    2: ['wednesday', 'wed', 'budhvar', 'budhwar', 'बुधवार'],
    3: ['thursday', 'thu', 'thur', 'thurs', 'guruvar', 'guruwar', 'गुरुवार', 'बृहस्पतिवार'],
    4: ['friday', 'fri', 'shukravar', 'shukrawar', 'शुक्रवार'], 5: ['saturday', 'sat', 'shanivar', 'shaniwar', 'शनिवार'],
    6: ['sunday', 'sun', 'ravivar', 'raviwar', 'itvar', 'itwar', 'रविवार', 'इतवार'],
}
WEEKDAYS = {w: d for d, ws in _WD_WORDS.items() for w in ws}
_TODAY = {'today', 'aaj', 'आज', 'tonight'}
_TOMORROW = {'tomorrow', 'tmrw', 'tmr', 'kal', 'कल'}
_DAY_AFTER = {'parso', 'parson', 'परसों', 'परसो'}
_NEXT = {'next', 'agle', 'agla', 'अगले', 'अगला'}
_LAST = {'last', 'pichhle', 'pichle', 'पिछले', 'previous'}
_DEV_DIGITS = str.maketrans('०१२३४५६७८९', '0123456789')


@dataclass
class ParsedDate:
    iso: str
    display: str
    ambiguous: bool = False
    note: str = ''

    def to_dict(self):
        return asdict(self)


def display_date(d) -> str:
    d = _as_date(d)
    return f"{d.day} {d.strftime('%b %Y (%a)')}" if d else ''


def format_date(value, fmt: str = '%d-%b-%Y') -> str:
    d = _as_date(value)
    return d.strftime(fmt) if d else (str(value) if value else '')


def _as_date(value) -> Optional[date]:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _result(d: date, ambiguous=False, note='') -> ParsedDate:
    return ParsedDate(d.isoformat(), display_date(d), ambiguous, note)


def _make(y, m, d, today, ambiguous=False, note=''):
    if y is None:
        best = None
        for yy in (today.year - 1, today.year, today.year + 1):
            try:
                cand = date(yy, m, d)
            except ValueError:
                continue
            key = (abs((cand - today).days), cand < today)
            if best is None or key < best[0]:
                best = (key, cand)
        return _result(best[1], ambiguous, note) if best else None
    try:
        return _result(date(y, m, d), ambiguous, note)
    except ValueError:
        return None


def _year(s):
    if not s:
        return None
    y = int(s)
    return y + 2000 if y < 100 else y


def _prep(text: str) -> str:
    s = str(text).strip().lower().translate(_DEV_DIGITS)
    s = re.sub(r'(\d+)\s*(st|nd|rd|th)\b', r'\1', s)
    s = re.sub(r'(\d)\s+of\s+', r'\1 ', s)
    s = s.replace(',', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def _relative(s: str, today: date) -> Optional[ParsedDate]:
    toks = s.split()
    padded = f' {s} '
    if ' day after tomorrow ' in padded:
        return _result(today + timedelta(days=2))
    if any(t in _DAY_AFTER for t in toks):
        return _result(today + timedelta(days=2), True, 'परसों/parso can also mean the day before yesterday.')
    if ' day before yesterday ' in padded:
        return _result(today - timedelta(days=2))
    if any(t in _TODAY for t in toks):
        return _result(today)
    if 'yesterday' in toks:
        return _result(today - timedelta(days=1))
    if any(t in _TOMORROW for t in toks):
        amb = any(t in ('kal', 'कल') for t in toks)
        return _result(today + timedelta(days=1), amb, 'कल/kal can also mean yesterday.' if amb else '')
    m = re.search(r'(?:in|after)\s+(\d{1,3})\s+days?', s) or \
        re.search(r'(\d{1,3})\s+(?:din|दिन)\s+(?:baad|bad|बाद)', s)
    if m:
        return _result(today + timedelta(days=int(m.group(1))))
    if re.search(r'\d', s):
        return None
    for i, t in enumerate(toks):
        if t in WEEKDAYS:
            wd, mod = WEEKDAYS[t], (toks[i - 1] if i else '')
            delta = (wd - today.weekday()) % 7
            if mod in _LAST:
                return _result(today - timedelta(days=(7 - delta) % 7 or 7))
            if mod in _NEXT:
                delta = delta or 7
                nxt = today + timedelta(days=delta)
                return _result(nxt, True, f'Taken as the coming one; the following week would be {display_date(nxt + timedelta(days=7))}.')
            return _result(today + timedelta(days=delta))
    return None


def parse_date(text, today: Optional[date] = None) -> Optional[ParsedDate]:
    if text is None or text == '':
        return None
    if isinstance(text, (date, datetime)):
        return _result(_as_date(text))
    today = today or date.today()
    s = _prep(text)
    rel = _relative(s, today)
    if rel:
        return rel
    m = re.search(r'(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)', s)
    if m:
        return _make(int(m[1]), int(m[2]), int(m[3]), today)
    m = re.search(r'(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?!\d)', s)
    if m:
        d, mo, y = int(m[1]), int(m[2]), _year(m[3])
        note = ''
        if mo > 12 and d <= 12:
            d, mo, note = mo, d, 'Read as month/day because the second number is above 12.'
        amb = d <= 12 and mo <= 12 and d != mo
        return _make(y, mo, d, today, amb, note or ('Read day-first (Indian style).' if amb else ''))
    yr = r'(?:\s*[-/ .]?\s*(\d{4}|\d{2}(?![\d:.]|\s*[ap]\.?m)))?'
    m = re.search(rf'(?<!\d)(\d{{1,2}})\s*[-/ .]?\s*({_MONTH_RE})(?![a-z])\.?' + yr, s)
    if m:
        return _make(_year(m[3]), MONTHS[m[2]], int(m[1]), today)
    m = re.search(rf'(?<![a-z])({_MONTH_RE})(?![a-z])\.?\s*[-/ ]?\s*(\d{{1,2}})(?!\d)(?:\s*[-/ ]?\s*(\d{{4}}))?', s)
    if m:
        return _make(_year(m[3]), MONTHS[m[1]], int(m[2]), today)
    m = re.search(r'(?<!\d)(\d{1,2})[-/.](\d{1,2})(?![-/.\d])', s)
    if m:
        d, mo = int(m[1]), int(m[2])
        if mo > 12 and d <= 12:
            d, mo = mo, d
        return _make(None, mo, d, today, d <= 12 and mo <= 12 and d != mo, 'Read day-first (Indian style).')
    return None


# ── Times ────────────────────────────────────────────────────────────────────
_T = r'(\d{1,2})(?:\s*[:.]\s*(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?|hrs|baje|बजे)?'
_AM_WORDS = ('subah', 'सुबह', 'morning')
_PM_WORDS = ('shaam', 'sham', 'शाम', 'evening', 'raat', 'रात', 'night', 'dopahar', 'दोपहर', 'afternoon')


def _mer(tok):
    if not tok:
        return None
    t = tok.replace('.', '').replace(' ', '')
    return 'am' if t.startswith('a') else 'pm' if t.startswith('p') else None


def _to24(h, mi, mer, period):
    h, mi = int(h), int(mi or 0)
    if h > 23 or mi > 59:
        return None
    amb = False
    mer = mer or period
    if mer == 'pm' and h < 12:
        h += 12
    elif mer == 'am' and h == 12:
        h = 0
    elif mer is None and 1 <= h <= 11:
        amb = True
        if h <= 6:
            h += 12
    return h, mi, amb


def format_time(hhmm, style: str = '12h') -> str:
    if not hhmm:
        return ''
    try:
        t = datetime.strptime(str(hhmm)[:5], '%H:%M')
    except ValueError:
        return str(hhmm)
    if style == '24h':
        return t.strftime('%H:%M')
    return t.strftime('%I:%M %p').lstrip('0').lower()


def parse_time(text) -> Optional[dict]:
    if not text:
        return None
    s = _prep(text)
    period = 'am' if any(w in s for w in _AM_WORDS) else 'pm' if any(w in s for w in _PM_WORDS) else None
    m = re.search(_T + r'\s*(?:-|\u2013|\u2014|to|till|until|se|से)\s*' + _T, s)
    if m:
        m1, m2 = _mer(m[3]), _mer(m[6])
        if m1 is None and m2:
            h1, h2 = int(m[1]), int(m[4])
            m1 = 'am' if (m2 == 'pm' and (h2 == 12 or h1 > h2)) else m2
        a, b = _to24(m[1], m[2], m1, period), _to24(m[4], m[5], m2, period)
        if a and b:
            start, end = f'{a[0]:02d}:{a[1]:02d}', f'{b[0]:02d}:{b[1]:02d}'
            return {'start': start, 'end': end, 'ambiguous': a[2] or b[2],
                    'display': f'{format_time(start)} \u2013 {format_time(end)}'}
    m = re.search(_T, s)
    if m:
        a = _to24(m[1], m[2], _mer(m[3]), period)
        if a:
            start = f'{a[0]:02d}:{a[1]:02d}'
            return {'start': start, 'end': None, 'ambiguous': a[2], 'display': format_time(start)}
    return None


def time_range_display(start, end=None, style='12h') -> str:
    if not start:
        return ''
    return format_time(start, style) + (f' - {format_time(end, style)}' if end else '')
