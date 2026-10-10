"""
Text that the classic PDF documents (APR, Request for Payment invoice, documents) can always print.

They use fpdf's built-in Helvetica, which holds only Latin-1 characters. One curly apostrophe ("St. Xavier’s",
typed automatically by phones and Word), an en dash, an accented letter or the rupee sign made fpdf raise an
error, the document came out empty and the email went without its attachment. SafeFPDF makes such text
printable just before it reaches the font, so the documents keep exactly their look and always print.
"""
import unicodedata

_MAP = {'\u2018': "'", '\u2019': "'", '\u201a': "'", '\u201b': "'", '\u2032': "'", '\u201c': '"', '\u201d': '"', '\u201e': '"',
        '\u2033': '"', '\u2013': '-', '\u2014': '-', '\u2015': '-', '\u2212': '-', '\u2026': '...', '\u00a0': ' ', '\u202f': ' ',
        '\u2009': ' ', '\u20b9': 'Rs.', '\u2022': '-', '\u00b7': '-', '\u200b': '', '\u200c': '', '\u200d': '', '\ufeff': '',
        '\u2122': '(TM)', '\u20ac': 'EUR'}


def pdf_text(value) -> str:
    """Printable with the PDF core fonts (Latin-1), keeping meaning: quotes, dashes, Rs., accents, Indian scripts."""
    if value is None:
        return ''
    s = ''.join(_MAP.get(ch, ch) for ch in str(value))
    try:
        s.encode('latin-1')
        return s
    except UnicodeEncodeError:
        pass
    try:                                              # Indian scripts: the same transliteration the database writes use
        from app.core.text_utils import latin1_safe
        s = ''.join(_MAP.get(ch, ch) for ch in latin1_safe(s))
    except Exception:
        pass
    out = []
    for ch in s:
        try:
            ch.encode('latin-1')
            out.append(ch)
        except UnicodeEncodeError:
            base = ''.join(c for c in unicodedata.normalize('NFKD', ch) if not unicodedata.combining(c))
            out.append(base if base and all(ord(c) < 256 for c in base) else '?')
    return ''.join(out)


def safe_fpdf_class():
    """fpdf's FPDF, with text made printable whenever a core font (Helvetica, Times, Courier) is in use."""
    from fpdf import FPDF

    class SafeFPDF(FPDF):
        def normalize_text(self, text):
            if not getattr(self, 'is_ttf_font', False):
                text = pdf_text(text)
            return super().normalize_text(text)
    return SafeFPDF
