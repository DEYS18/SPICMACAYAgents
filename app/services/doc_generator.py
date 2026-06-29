"""
Document Generator Service
==========================
Converts LLM-generated markdown content into downloadable Word (.docx) or PDF files,
styled with SPIC MACAY branding for the 12th International Convention at IIT Delhi.
"""

import io
import re
import unicodedata
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Brand colours ──────────────────────────────────────────────────────────── #
_RED_HEX = (0x8B, 0x00, 0x00)   # #8B0000
_GREY_HEX = (0x60, 0x60, 0x60)

# ── python-docx ────────────────────────────────────────────────────────────── #
try:
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    _HAS_DOCX = True
except Exception:
    _HAS_DOCX = False
    logger.warning("[doc_gen] python-docx not available; Word export disabled.")

# ── fpdf2 ──────────────────────────────────────────────────────────────────── #
try:
    from fpdf import FPDF
    _HAS_FPDF = True
except Exception:
    _HAS_FPDF = False
    logger.warning("[doc_gen] fpdf2 not available; PDF export disabled.")

_CONVENTION_FOOTER = "SPIC MACAY - 12th International Convention - IIT Delhi 2027"


# Characters that Helvetica (Latin-1) can't render → ASCII equivalents
_UNICODE_MAP = {
    '‘': "'",  '’': "'",  '‚': "'",  '‛': "'",
    '“': '"',  '”': '"',  '„': '"',  '‟': '"',
    '–': '-',  '—': '--', '―': '--', '−': '-',
    '…': '...', '•': '*', '‣': '>',  '⁃': '-',
    '●': '*',  '◦': 'o', '▪': '*',  '▫': 'o',
    '→': '->',  '←': '<-', '↔': '<->', '⇒': '=>',
    '⇐': '<=',  '✓': 'v',  '✔': 'v',  '✗': 'x',
    '✘': 'x',  '✕': 'x',
    '×': 'x',  '÷': '/',  '°': ' deg',
    '±': '+/-', '²': '2',  '³': '3',
    '©': '(C)', '®': '(R)', '™': '(TM)',
    '€': 'EUR', '£': 'GBP', '¥': 'JPY',
    ' ': ' ',  '​': '',   '‌': '',   '‍': '',
    ' ': ' ',  '﻿': '',   '⁠': '',
}

def _to_pdf_safe(text: str) -> str:
    """Replace Unicode characters unsupported by Helvetica (Latin-1) with ASCII equivalents."""
    for ch, rep in _UNICODE_MAP.items():
        text = text.replace(ch, rep)
    # Remove emoji and other symbol blocks
    text = re.sub(
        r'[\U00010000-\U0010ffff\U0001F300-\U0001F9FF☀-➿]',
        '', text
    )
    # Decompose accented characters (é → e + combining accent) then drop non-Latin-1
    text = unicodedata.normalize('NFKD', text)
    return text.encode('latin-1', errors='ignore').decode('latin-1').strip()


def _parse_md_lines(md: str):
    """
    Yield (type, text) tuples from markdown.
    Types: 'h1', 'h2', 'h3', 'bullet', 'numbered', 'hr', 'blank', 'para'
    """
    for line in md.splitlines():
        s = line.rstrip()
        if not s:
            yield ('blank', '')
        elif s.startswith('### '):
            yield ('h3', s[4:].strip())
        elif s.startswith('## '):
            yield ('h2', s[3:].strip())
        elif s.startswith('# '):
            yield ('h1', s[2:].strip())
        elif re.match(r'^[-*+] ', s):
            yield ('bullet', s[2:].strip())
        elif re.match(r'^\d+\. ', s):
            yield ('numbered', re.sub(r'^\d+\. ', '', s).strip())
        elif s.startswith('---'):
            yield ('hr', '')
        else:
            yield ('para', s)


def _add_md_runs(para, text: str):
    """Add runs with **bold** and *italic* inline markdown to a docx paragraph."""
    for chunk in re.split(r'(\*\*.*?\*\*|\*[^*]*?\*)', text):
        if chunk.startswith('**') and chunk.endswith('**'):
            para.add_run(chunk[2:-2]).bold = True
        elif chunk.startswith('*') and chunk.endswith('*'):
            para.add_run(chunk[1:-1]).italic = True
        else:
            para.add_run(chunk)


# ── Word (.docx) ──────────────────────────────────────────────────────────── #

def generate_docx(title: str, content_md: str) -> Optional[bytes]:
    """Generate a branded Word document from markdown content. Returns bytes."""
    if not _HAS_DOCX:
        return None
    try:
        doc = Document()
        red = RGBColor(*_RED_HEX)
        grey = RGBColor(*_GREY_HEX)

        # Page margins
        for sec in doc.sections:
            sec.top_margin = Cm(2.2)
            sec.bottom_margin = Cm(2.2)
            sec.left_margin = Cm(2.8)
            sec.right_margin = Cm(2.8)

        # ── Header ──────────────────────────────────────────────────────────
        hdr = doc.sections[0].header
        hp = hdr.paragraphs[0] if hdr.paragraphs else hdr.add_paragraph()
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        hr = hp.add_run(
            "SPIC MACAY  •  Society for the Promotion of Indian Classical Music "
            "And Culture Amongst Youth"
        )
        hr.font.size = Pt(8)
        hr.font.color.rgb = red
        hr.bold = True

        # ── Title ───────────────────────────────────────────────────────────
        tp = doc.add_paragraph()
        tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        tp.paragraph_format.space_before = Pt(6)
        tp.paragraph_format.space_after = Pt(6)
        tr = tp.add_run(title)
        tr.bold = True
        tr.font.size = Pt(20)
        tr.font.color.rgb = red

        # thin red rule
        rule = doc.add_paragraph()
        rule.paragraph_format.space_after = Pt(10)
        rr = rule.add_run('─' * 80)
        rr.font.size = Pt(8)
        rr.font.color.rgb = red

        # ── Body ────────────────────────────────────────────────────────────
        for kind, text in _parse_md_lines(content_md):
            clean = _to_pdf_safe(text)   # keep emojis in Word (usually fine)
            clean = text                  # actually Word handles emoji well

            if kind == 'h1':
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(14)
                p.paragraph_format.space_after = Pt(4)
                r = p.add_run(clean)
                r.bold = True; r.font.size = Pt(16); r.font.color.rgb = red

            elif kind == 'h2':
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(12)
                p.paragraph_format.space_after = Pt(3)
                r = p.add_run(clean)
                r.bold = True; r.font.size = Pt(13); r.font.color.rgb = red

            elif kind == 'h3':
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(8)
                p.paragraph_format.space_after = Pt(2)
                r = p.add_run(clean)
                r.bold = True; r.font.size = Pt(11); r.font.color.rgb = RGBColor(0xA0, 0x20, 0x20)

            elif kind == 'bullet':
                p = doc.add_paragraph(style='List Bullet')
                _add_md_runs(p, text)

            elif kind == 'numbered':
                p = doc.add_paragraph(style='List Number')
                _add_md_runs(p, text)

            elif kind == 'hr':
                p = doc.add_paragraph()
                p.add_run('─' * 80).font.size = Pt(8)

            elif kind == 'blank':
                doc.add_paragraph().paragraph_format.space_after = Pt(2)

            else:  # para
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(4)
                _add_md_runs(p, text)

        # ── Footer ──────────────────────────────────────────────────────────
        ftr = doc.sections[0].footer
        fp = ftr.paragraphs[0] if ftr.paragraphs else ftr.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fr = fp.add_run(_CONVENTION_FOOTER)
        fr.font.size = Pt(8)
        fr.font.color.rgb = grey

        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"[doc_gen] Word generation failed: {e}")
        return None


# ── PDF (.pdf) ────────────────────────────────────────────────────────────── #

_PDF_L  = 20          # left margin mm
_PDF_R  = 20          # right margin mm
_PDF_T  = 15          # top margin mm
_PDF_W  = 210         # A4 width mm
_PDF_CW = _PDF_W - _PDF_L - _PDF_R   # 170 mm printable width


def _pdf_header(pdf) -> None:
    """Draw the branded page header; called after each add_page()."""
    pdf.set_xy(_PDF_L, 8)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(*_RED_HEX)
    pdf.cell(_PDF_CW, 6,
             "SPIC MACAY  -  Society for the Promotion of Indian Classical Music And Culture Amongst Youth",
             align='C')
    pdf.set_draw_color(*_RED_HEX)
    pdf.set_line_width(0.3)
    y = pdf.get_y() + 7
    pdf.line(_PDF_L, y, _PDF_W - _PDF_R, y)


def _pdf_footer(pdf) -> None:
    """Draw the branded page footer at the bottom of the page."""
    pdf.set_xy(_PDF_L, -12)
    pdf.set_font('Helvetica', 'I', 7)
    pdf.set_text_color(*_GREY_HEX)
    pdf.cell(_PDF_CW, 5, _CONVENTION_FOOTER, align='C')


def generate_pdf(title: str, content_md: str) -> Optional[bytes]:
    """Generate a branded PDF from markdown content. Returns bytes."""
    if not _HAS_FPDF:
        return None
    try:
        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.set_margins(_PDF_L, _PDF_T, _PDF_R)
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        _pdf_header(pdf)

        # Reset cursor to content start (below header area)
        pdf.set_xy(_PDF_L, _PDF_T + 8)

        # ── Title ─────────────────────────────────────────────────────────
        pdf.set_font('Helvetica', 'B', 18)
        pdf.set_text_color(*_RED_HEX)
        pdf.set_x(_PDF_L)
        pdf.multi_cell(_PDF_CW, 10, _to_pdf_safe(title), align='C')
        pdf.ln(3)
        pdf.set_draw_color(*_RED_HEX)
        pdf.set_line_width(0.5)
        pdf.line(_PDF_L, pdf.get_y(), _PDF_W - _PDF_R, pdf.get_y())
        pdf.ln(6)

        # ── Body ──────────────────────────────────────────────────────────
        for kind, text in _parse_md_lines(content_md):
            clean = _to_pdf_safe(text)
            if not clean and kind not in ('blank', 'hr'):
                continue

            # Ensure x is always at left margin before each cell
            pdf.set_x(_PDF_L)

            if kind == 'h1':
                pdf.set_font('Helvetica', 'B', 14)
                pdf.set_text_color(*_RED_HEX)
                pdf.ln(4)
                pdf.set_x(_PDF_L)
                pdf.multi_cell(_PDF_CW, 7, clean)
                pdf.ln(1)

            elif kind == 'h2':
                pdf.set_font('Helvetica', 'B', 12)
                pdf.set_text_color(*_RED_HEX)
                pdf.ln(3)
                pdf.set_x(_PDF_L)
                pdf.multi_cell(_PDF_CW, 6, clean)
                pdf.ln(1)

            elif kind == 'h3':
                pdf.set_font('Helvetica', 'B', 10)
                pdf.set_text_color(0xA0, 0x20, 0x20)
                pdf.ln(2)
                pdf.set_x(_PDF_L)
                pdf.multi_cell(_PDF_CW, 6, clean)

            elif kind in ('bullet', 'numbered'):
                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(0x33, 0x33, 0x33)
                prefix = '*  ' if kind == 'bullet' else '->  '
                plain = re.sub(r'\*\*?(.*?)\*\*?', r'\1', clean)
                pdf.set_x(_PDF_L)
                pdf.multi_cell(_PDF_CW, 5.5, prefix + plain)

            elif kind == 'hr':
                pdf.ln(2)
                pdf.set_draw_color(0xCC, 0xCC, 0xCC)
                pdf.set_line_width(0.2)
                pdf.line(_PDF_L, pdf.get_y(), _PDF_W - _PDF_R, pdf.get_y())
                pdf.ln(4)

            elif kind == 'blank':
                pdf.ln(3)

            else:
                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(0x33, 0x33, 0x33)
                plain = re.sub(r'\*\*?(.*?)\*\*?', r'\1', clean)
                pdf.set_x(_PDF_L)
                pdf.multi_cell(_PDF_CW, 5.5, plain)
                pdf.ln(1)

        _pdf_footer(pdf)
        return bytes(pdf.output())

    except Exception as e:
        logger.error(f"[doc_gen] PDF generation failed: {e}")
        return None
