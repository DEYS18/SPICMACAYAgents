"""
Rendering: governed email templates (sandboxed Jinja) and APR / Request for Payment PDFs.

PDFs are drawn with reportlab and the bundled DejaVu fonts, so names with curly quotes,
accents or the rupee sign never break a document. (The previous fpdf/Helvetica code raised
on any character outside Latin-1 and quietly emailed the APR without its PDF.) Layouts are
JSON documents stored in the governance store and edited in Admin > Templates.
"""
import html as _html
import io
import json
import logging
import os
import re
from datetime import datetime

from jinja2 import FunctionLoader, TemplateError, meta as jmeta
from jinja2.sandbox import SandboxedEnvironment

from app.core import dates as dt
from app.core import text_utils as tu

logger = logging.getLogger(__name__)
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIRS = [os.path.join(APP_DIR, 'static', 'fonts'), '/usr/share/fonts/truetype/dejavu', r'C:\Windows\Fonts']
LOGO = os.path.join(APP_DIR, 'static', 'img', 'brand', 'spicmacay_wordmark.png')


def org_context(setting) -> dict:
    site = setting('org.website', 'https://www.spicmacay.org')
    return {'name': setting('org.name', 'SPIC MACAY'), 'tagline': setting('org.tagline', ''),
            'website': site, 'website_short': re.sub(r'^https?://', '', site).rstrip('/'),
            'info_email': setting('org.info_email', ''), 'registered_office': setting('org.registered_office', ''),
            'pan': setting('org.pan', ''), 'tan': setting('org.tan', '')}


def bank_context(setting) -> dict:
    return {k: setting(f'bank.{k}', '') for k in ('bank_name', 'branch', 'account_name', 'account_number', 'ifsc')}


def html_to_text(html: str) -> str:
    s = re.sub(r'(?is)<(style|script|head)[^>]*>.*?</\1>', '', html or '')
    s = re.sub(r'(?i)<br\s*/?>|</p>|</tr>|</h\d>|</li>', '\n', s)
    s = re.sub(r'(?i)<li[^>]*>', '- ', s)
    s = re.sub(r'(?i)</td>', '  ', s)
    s = _html.unescape(re.sub(r'<[^>]+>', '', s))
    s = re.sub(r'[ \t]+', ' ', s)
    return re.sub(r'\n\s*\n\s*\n+', '\n\n', '\n'.join(line.strip() for line in s.splitlines())).strip()


def _add_filters(env):
    env.filters['inr'] = tu.inr
    env.filters['words'] = tu.amount_in_words
    env.filters['dmy'] = lambda v, fmt='%d-%b-%Y': dt.format_date(v, fmt)
    env.filters['dash'] = lambda v: v if v not in (None, '') else '-'


class TemplateRenderer:
    def __init__(self, governance):
        self.gov = governance
        self.env = SandboxedEnvironment(loader=FunctionLoader(self._load), autoescape=True)
        self.text_env = SandboxedEnvironment(autoescape=False)
        _add_filters(self.env)
        _add_filters(self.text_env)

    def _load(self, name):
        t = self.gov.get_template(name)
        if not t or t.get('body') is None:
            return None
        return t['body'], name, lambda: False          # always re-read: admins edit live

    def render_email(self, key, ctx, override: dict = None) -> dict:
        t = override or self.gov.get_template(key)
        if not t:
            raise KeyError(f'No template {key}')
        tpl = self.env.from_string(t['body']) if override else self.env.get_template(key)
        html = tpl.render(**ctx)
        subject = self.text_env.from_string(t.get('subject') or '').render(**ctx)
        text_src = (t.get('meta') or {}).get('text')
        text = self.text_env.from_string(text_src).render(**ctx) if text_src else html_to_text(html)
        return {'subject': re.sub(r'\s+', ' ', subject).strip(), 'html': html, 'text': text}

    def text(self, source, ctx) -> str:
        if not source or ('{' not in source):
            return source or ''
        try:
            return self.text_env.from_string(source).render(**ctx)
        except TemplateError as e:
            logger.warning('Template text failed (%s): %s', e, source[:80])
            return source

    def validate(self, body, subject=None, ctx=None, autoescape=True) -> dict:
        env = self.env if autoescape else self.text_env
        try:
            parsed = env.parse(body or '')
            undeclared = sorted(jmeta.find_undeclared_variables(parsed))
            if ctx is not None:
                env.from_string(body or '').render(**ctx)
                if subject:
                    self.text_env.from_string(subject).render(**ctx)
            return {'ok': True, 'undeclared': undeclared}
        except TemplateError as e:
            return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'line': getattr(e, 'lineno', None)}
        except Exception as e:  # sandbox security errors and the like
            return {'ok': False, 'error': f'{type(e).__name__}: {e}'}

    def layout(self, key, fallback: dict = None) -> dict:
        t = self.gov.get_template(key)
        try:
            return json.loads(t['body']) if t and t.get('body') else (fallback or {})
        except ValueError:
            logger.error('Layout %s is not valid JSON; using the default', key)
            return fallback or {}


# ── PDF engine ───────────────────────────────────────────────────────────────
_FONTS = None
_SAFE = {'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '-',
         '\u20b9': 'Rs ', '\u2022': '-', '\u00a0': ' '}


def _font_path(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def _fonts():
    global _FONTS
    if _FONTS:
        return _FONTS
    try:
        from reportlab.lib.fonts import addMapping
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        reg, bold = _font_path('DejaVuSans.ttf'), _font_path('DejaVuSans-Bold.ttf')
        ital = _font_path('DejaVuSans-Oblique.ttf') or reg
        if reg and bold:
            for name, path in (('SMSans', reg), ('SMSans-Bold', bold), ('SMSans-Italic', ital), ('SMSans-BoldItalic', bold)):
                pdfmetrics.registerFont(TTFont(name, path))
            addMapping('SMSans', 0, 0, 'SMSans'); addMapping('SMSans', 1, 0, 'SMSans-Bold')
            addMapping('SMSans', 0, 1, 'SMSans-Italic'); addMapping('SMSans', 1, 1, 'SMSans-BoldItalic')
            _FONTS = ('SMSans', 'SMSans-Bold', 'SMSans-Italic', True)
            return _FONTS
    except Exception as e:
        logger.warning('Unicode font unavailable, falling back to Helvetica: %s', e)
    _FONTS = ('Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique', False)
    return _FONTS


def _safe(text, unicode_ok):
    s = '' if text is None else str(text)
    if not unicode_ok:
        for a, b in _SAFE.items():
            s = s.replace(a, b)
        s = s.encode('latin-1', 'replace').decode('latin-1')
    return s


def _p(text, unicode_ok):
    return _html.escape(_safe(text, unicode_ok), quote=False).replace('\n', '<br/>')


class PdfRenderer:
    def __init__(self, text_render):
        self.text = text_render

    def _doc(self, buf, layout, title):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate
        page = layout.get('page', {})
        size = landscape(A4) if page.get('orientation') == 'landscape' else A4
        m = float(page.get('margin_mm', 12)) * mm
        return SimpleDocTemplate(buf, pagesize=size, leftMargin=m, rightMargin=m, topMargin=m,
                                 bottomMargin=m + 9 * mm, title=title, author='SPIC MACAY')

    def _styles(self, layout):
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        font, bold, ital, uni = _fonts()
        st = layout.get('style', {})
        fs = float(st.get('font_size', 9))
        accent = colors.HexColor(st.get('accent', '#8B0000'))

        def ps(name, f, size, align=0, color=None):
            return ParagraphStyle(name, fontName=f, fontSize=size, leading=size * 1.3, alignment=align,
                                  textColor=color or colors.black)
        return {'uni': uni, 'font': font, 'fs': fs, 'accent': accent,
                'grid': colors.HexColor(st.get('grid', '#BDBDBD')), 'fill': colors.HexColor(st.get('header_fill', '#F2F2F2')),
                'body': ps('body', font, fs), 'cell': ps('cell', font, fs), 'head': ps('head', bold, fs),
                'bold': ps('bold', bold, fs), 'title': ps('title', bold, fs + 4, 1),
                'subtitle': ps('sub', font, fs + .5, 1, colors.HexColor('#555555')),
                'section': ps('sec', bold, fs + .5, 0, accent), 'right': ps('right', font, fs, 2)}

    def _logo(self, width_mm=34):
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image
        if not os.path.exists(LOGO):
            return None
        iw, ih = ImageReader(LOGO).getSize()
        img = Image(LOGO, width=width_mm * mm, height=width_mm * mm * ih / iw)
        img.hAlign = 'CENTER'
        return img

    def _canvas(self, layout, ctx, st):
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as rl
        footer, text = layout.get('footer', {}), self.text
        margin = float(layout.get('page', {}).get('margin_mm', 12)) * mm

        def draw(c, page, pages):
            w, _ = c._pagesize
            vals = dict(ctx, page=page, pages=pages)
            y = margin * 0.55 + 3 * mm
            c.setStrokeColor(st['grid']); c.setLineWidth(0.4)
            c.line(margin, y + 4 * mm, w - margin, y + 4 * mm)
            c.setFont(st['font'], 7.5); c.setFillColorRGB(0.35, 0.35, 0.35)
            for pos, fn in (('left', lambda s: c.drawString(margin, y, s)),
                            ('center', lambda s: c.drawCentredString(w / 2, y, s)),
                            ('right', lambda s: c.drawRightString(w - margin, y, s))):
                if footer.get(pos):
                    fn(_safe(text(footer[pos], vals), st['uni']))

        class NumberedCanvas(rl.Canvas):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self._pages = []

            def showPage(self):
                self._pages.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                total = len(self._pages)
                for i, state in enumerate(self._pages, 1):
                    self.__dict__.update(state)
                    draw(self, i, total)
                    rl.Canvas.showPage(self)
                rl.Canvas.save(self)
        return NumberedCanvas

    def _table(self, cols, rows, ctx, st, width):
        from reportlab.platypus import Paragraph, Table, TableStyle
        total = sum(float(c.get('width', 10)) for c in cols) or 1
        data = [[Paragraph(_p(self.text(c.get('label', ''), ctx), st['uni']), st['head']) for c in cols]]
        for row in rows:
            data.append([Paragraph(_p(self.text(c['template'], dict(ctx, row=row)) if c.get('template')
                                      else ('' if row.get(c['key']) is None else row.get(c['key'])), st['uni']), st['cell'])
                         for c in cols])
        t = Table(data, colWidths=[width * float(c.get('width', 10)) / total for c in cols], repeatRows=1)
        t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, st['grid']), ('BACKGROUND', (0, 0), (-1, 0), st['fill']),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 3),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('LEFTPADDING', (0, 0), (-1, -1), 4),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 4)]))
        return t

    def _header(self, story, layout, ctx, st):
        from reportlab.platypus import HRFlowable, Paragraph, Spacer
        hdr = layout.get('header', {})
        if hdr.get('show_logo', True):
            logo = self._logo()
            if logo:
                story.append(logo)
        story.append(Paragraph(_p(self.text(hdr.get('title', ''), ctx), st['uni']), st['title']))
        sub = self.text(hdr.get('subtitle', ''), ctx).strip()
        if sub:
            story.append(Paragraph(_p(sub, st['uni']), st['subtitle']))
        story.append(Spacer(1, 3))
        story.append(HRFlowable(width='100%', thickness=0.8, color=st['accent'], spaceAfter=6))

    def render_apr(self, layout: dict, ctx: dict) -> bytes:
        from reportlab.platypus import Paragraph, Spacer
        buf = io.BytesIO()
        doc = self._doc(buf, layout, f"APR {ctx.get('apr', {}).get('number', '')}")
        st = self._styles(layout)
        story = []
        self._header(story, layout, ctx, st)
        for sec in layout.get('sections', []):
            if not sec.get('enabled', True):
                continue
            kind = sec.get('type', 'table')
            if kind == 'table':
                cols = [c for c in sec.get('columns', []) if c.get('enabled', True)]
                rows = ctx.get(sec.get('source') or sec.get('id')) or []
                if not cols or (not rows and sec.get('hide_if_empty')):
                    continue
                if sec.get('title'):
                    story.append(Paragraph(_p(sec['title'] + ':', st['uni']), st['section']))
                story.append(self._table(cols, rows, ctx, st, doc.width))
                story.append(Spacer(1, 8))
            elif kind == 'lines':
                for line in sec.get('lines', []):
                    txt = self.text(line, ctx).strip()
                    if txt:
                        story.append(Paragraph(_p(txt, st['uni']), st['body']))
                story.append(Spacer(1, 6))
            elif kind == 'notes':
                notes = (ctx.get('program') or {}).get('notes')
                if notes:
                    story.append(Paragraph(_p(f"{sec.get('title') or 'Notes'}: {notes}", st['uni']), st['body']))
        doc.build(story, canvasmaker=self._canvas(layout, ctx, st))
        return buf.getvalue()

    def render_rfp(self, layout: dict, ctx: dict) -> bytes:
        from reportlab.platypus import Paragraph, Spacer
        buf = io.BytesIO()
        doc = self._doc(buf, layout, 'Request for Payment')
        st = self._styles(layout)
        story = []
        self._header(story, dict(layout, header=dict(layout.get('header', {}), subtitle='')), ctx, st)
        hdr = layout.get('header', {})
        story.append(Paragraph(_p(f"{hdr.get('invoice_label', 'INV DATE:')} {ctx.get('invoice_date', '')}", st['uni']), st['right']))
        story.append(Spacer(1, 6))
        inst = ctx.get('institution') or {}
        story.append(Paragraph(_p(layout.get('to_label', 'TO,'), st['uni']), st['bold']))
        story.append(Paragraph(_p(inst.get('name', ''), st['uni']), st['bold']))
        if inst.get('city'):
            story.append(Paragraph(_p(inst['city'], st['uni']), st['body']))
        story.append(Spacer(1, 8))
        cols = [c for c in layout.get('columns', []) if c.get('enabled', True)]
        story.append(self._table(cols, ctx.get('line_items') or [], ctx, st, doc.width))
        story.append(Spacer(1, 8))
        for i, line in enumerate(layout.get('after_table', [])):
            txt = self.text(line, ctx).strip()
            if txt:
                story.append(Paragraph(_p(txt, st['uni']), st['bold'] if i < 2 else st['body']))
        story.append(Spacer(1, 10))
        for line in layout.get('bank_block', []):
            txt = self.text(line, ctx).strip()
            if txt:
                story.append(Paragraph(_p(txt, st['uni']), st['body']))
        story.append(Spacer(1, 16))
        for line in layout.get('signature', []):
            txt = self.text(line, ctx).strip()
            if txt:
                story.append(Paragraph(_p(txt, st['uni']), st['body']))
        doc.build(story, canvasmaker=self._canvas(layout, ctx, st))
        return buf.getvalue()
