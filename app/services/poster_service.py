"""
Program Poster Generator — a SPIC MACAY branded poster (JPEG) built from the same
program details collected for an APR, drawn programmatically (no external template
image or logo file needed). Used by the 'generate a poster' capability of the APR
assistant — always on request, never automatic.
"""
import os
import io
import logging

logger = logging.getLogger(__name__)

# Poster canvas — portrait, matches the aspect ratio of SPIC MACAY's usual WhatsApp/print posters
_W, _H = 1200, 1500

# Brand palette — same as the web portal (see app/static/css/style.css)
_YELLOW       = (247, 201, 72)
_YELLOW_LIGHT = (253, 239, 184)
_YELLOW_DEEP  = (232, 168, 0)
_RED          = (179, 22, 28)
_RED_DARK     = (139, 0, 0)
_INK          = (61, 43, 0)
_WHITE        = (255, 255, 255)
_MAROON_PILL  = (91, 20, 20)

# This app is deployed on Windows (Waitress) — Arial/Georgia ship with every Windows
# install, so no font files need to be bundled. Falls back to Pillow's built-in font
# elsewhere (e.g. local dev on macOS/Linux) if these paths don't exist.
_FONTS_DIR = r'C:\Windows\Fonts'
_FONT_PATHS = {
    'bold_serif': os.path.join(_FONTS_DIR, 'georgiab.ttf'),
    'serif':      os.path.join(_FONTS_DIR, 'georgia.ttf'),
    'bold_sans':  os.path.join(_FONTS_DIR, 'arialbd.ttf'),
    'sans':       os.path.join(_FONTS_DIR, 'arial.ttf'),
}


def _font(kind: str, size: int):
    from PIL import ImageFont
    path = _FONT_PATHS.get(kind, _FONT_PATHS['sans'])
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def _gradient(w, h, top_rgb, bottom_rgb):
    import numpy as np
    from PIL import Image
    top = np.array(top_rgb, dtype=float).reshape(1, 1, 3)
    bottom = np.array(bottom_rgb, dtype=float).reshape(1, 1, 3)
    t = np.linspace(0, 1, h).reshape(h, 1, 1)
    grad = (top * (1 - t) + bottom * t)
    grad = np.repeat(grad, w, axis=1).astype('uint8')
    return Image.fromarray(grad, mode='RGB')


def _text_w(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _centered_text(draw, cx, y, text, font, fill, letter_spacing=0):
    if letter_spacing:
        # Pillow has no native letter-spacing — draw glyph by glyph
        widths = [_text_w(draw, ch, font) + letter_spacing for ch in text]
        total = sum(widths) - letter_spacing
        x = cx - total / 2
        for ch, w in zip(text, widths):
            draw.text((x, y), ch, font=font, fill=fill)
            x += w
        return
    w = _text_w(draw, text, font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def _wrap_to_width(draw, text, font, max_width):
    words = text.split()
    if not words:
        return ['']
    lines, line = [], words[0]
    for word in words[1:]:
        trial = f'{line} {word}'
        if _text_w(draw, trial, font) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def _quad_bezier(p0, p1, p2, n=24):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    return pts


def _draw_eye_emblem(draw, cx, cy, size, outline=(20, 20, 20), bindu=None, width_scale=0.02):
    """A simple lens/eye emblem with a bindu — the same motif as the web header's SVG
    logo, redrawn with plain polygon/ellipse primitives (no image asset needed)."""
    half = size / 2
    top, bottom = (cx, cy - half), (cx, cy + half)
    right_ctrl, left_ctrl = (cx + half * 0.85, cy), (cx - half * 0.85, cy)
    pts = _quad_bezier(top, right_ctrl, bottom) + _quad_bezier(bottom, left_ctrl, top)
    draw.polygon(pts, outline=outline, width=max(2, int(size * width_scale)))
    r = size * 0.11
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=bindu or _RED)


def _draw_corner_frame(draw, x0, y0, x1, y1, color, thickness=3, corner=26):
    """Ornamental corner-bracket border, echoing the sample posters' framed schedule box."""
    for (cx, cy, dx, dy) in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
        draw.line([(cx, cy), (cx + dx * corner, cy)], fill=color, width=thickness)
        draw.line([(cx, cy), (cx, cy + dy * corner)], fill=color, width=thickness)
    draw.rectangle([x0, y0, x1, y1], outline=color, width=1)


def generate_program_poster(program_data: dict) -> bytes:
    """
    Build a SPIC MACAY branded poster from program details — no photo (this is generated
    from text details alone, not an uploaded image), just the same yellow/red visual
    language as the official posters.

    Args:
        program_data: {institution_name, artist_name, art_form, module_name, start_date,
                        event_time, venue, city, state, accompanying_artists (optional
                        list of names), chapter (optional)}

    Returns:
        JPEG bytes; empty bytes on failure (e.g. Pillow not installed).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error("Pillow not installed — cannot generate poster")
        return b''

    try:
        institution_name = program_data.get('institution_name') or 'SPIC MACAY'
        artist_name       = program_data.get('artist_name', 'Artist Name')
        art_form          = program_data.get('art_form', '')
        module_name       = program_data.get('module_name', 'Concert')
        venue             = program_data.get('venue') or institution_name
        city              = program_data.get('city', '')
        state             = program_data.get('state', '')
        chapter           = program_data.get('chapter', '')
        accompanying      = program_data.get('accompanying_artists') or []

        event_date = program_data.get('start_date', '')
        try:
            from datetime import datetime
            event_date = datetime.strptime(event_date, '%Y-%m-%d').strftime('%A, %d %B %Y')
        except Exception:
            pass
        event_time = program_data.get('event_time', '')

        img = _gradient(_W, _H, _YELLOW_LIGHT, _YELLOW)
        draw = ImageDraw.Draw(img)

        # Top red band
        draw.rectangle([0, 0, _W, 14], fill=_RED)

        y = 46
        _draw_eye_emblem(draw, _W // 2, y + 38, 72)
        y += 96

        f_wordmark = _font('bold_serif', 56)
        _centered_text(draw, _W // 2, y, 'SPIC MACAY', f_wordmark, _INK, letter_spacing=4)
        y += 68

        f_tagline = _font('sans', 17)
        tagline = 'Society for the Promotion of Indian Classical Music And Culture Amongst Youth'
        for line in _wrap_to_width(draw, tagline, f_tagline, _W - 160):
            _centered_text(draw, _W // 2, y, line, f_tagline, _INK)
            y += 24
        y += 10

        f_presents = _font('bold_serif', 30)
        presents_line = f'{institution_name} Presents'
        for line in _wrap_to_width(draw, presents_line, f_presents, _W - 140):
            _centered_text(draw, _W // 2, y, line, f_presents, _RED_DARK)
            y += 40
        y += 18

        # ── Framed content card ─────────────────────────────────────────────
        card_x0, card_y0, card_x1 = 90, y, _W - 90
        card_y1 = _H - 210
        draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1],
                                radius=18, fill=(255, 255, 255, 255), outline=None)
        _draw_corner_frame(draw, card_x0, card_y0, card_x1, card_y1, _RED, thickness=3, corner=30)

        cy = card_y0 + 50

        # Art-form / module pill, e.g. "- KATHAK -" or "- CONCERT -"
        pill_label = f'- {(art_form or module_name).upper()} -'
        f_pill = _font('bold_sans', 26)
        pill_w = _text_w(draw, pill_label, f_pill) + 70
        pill_h = 54
        pill_x0 = _W // 2 - pill_w // 2
        draw.rounded_rectangle(
            [pill_x0, cy, pill_x0 + pill_w, cy + pill_h], radius=pill_h // 2, fill=_MAROON_PILL
        )
        _centered_text(draw, _W // 2, cy + 12, pill_label, f_pill, _WHITE)
        cy += pill_h + 40

        # Artist name — large, serif, wraps if long
        f_artist = _font('bold_serif', 52)
        for line in _wrap_to_width(draw, artist_name, f_artist, card_x1 - card_x0 - 60):
            _centered_text(draw, _W // 2, cy, line, f_artist, _RED_DARK)
            cy += 62
        cy += 6

        if module_name and art_form and module_name.lower() != art_form.lower():
            f_module = _font('sans', 24)
            _centered_text(draw, _W // 2, cy, module_name, f_module, _INK)
            cy += 34

        if accompanying:
            f_acc = _font('sans', 20)
            acc_line = 'Accompanied by: ' + ', '.join(accompanying)
            for line in _wrap_to_width(draw, acc_line, f_acc, card_x1 - card_x0 - 60):
                _centered_text(draw, _W // 2, cy, line, f_acc, _INK)
                cy += 28
            cy += 10

        cy += 20
        draw.line([(card_x0 + 60, cy), (card_x1 - 60, cy)], fill=_YELLOW_DEEP, width=2)
        cy += 30

        f_date = _font('bold_sans', 30)
        if event_date:
            date_line = event_date + (f'  |  {event_time}' if event_time else '')
            for line in _wrap_to_width(draw, date_line, f_date, card_x1 - card_x0 - 60):
                _centered_text(draw, _W // 2, cy, line, f_date, _RED_DARK)
                cy += 38
            cy += 8

        f_venue = _font('sans', 24)
        venue_line = venue
        loc = ', '.join(filter(None, [city, state]))
        if loc:
            venue_line += f', {loc}'
        for line in _wrap_to_width(draw, venue_line, f_venue, card_x1 - card_x0 - 60):
            _centered_text(draw, _W // 2, cy, line, f_venue, _INK)
            cy += 30

        # No photo in a text-generated poster — fill the remaining card space with a
        # soft watermark emblem instead of leaving it empty.
        remaining = card_y1 - cy
        if remaining > 140:
            wm_size = min(remaining - 50, 280)
            wm_cy = cy + remaining / 2 + 10
            _draw_eye_emblem(draw, _W // 2, wm_cy, wm_size,
                              outline=(232, 210, 150), bindu=(240, 210, 160), width_scale=0.012)

        # ── Footer band ──────────────────────────────────────────────────────
        draw.rectangle([0, _H - 150, _W, _H], fill=_RED_DARK)
        f_footer = _font('bold_sans', 24)
        footer_top = f'Join the movement  •  Volunteer with us'
        _centered_text(draw, _W // 2, _H - 118, footer_top, f_footer, _WHITE)

        f_footer2 = _font('sans', 20)
        footer_bottom = f'SPIC MACAY{" " + chapter if chapter else ""}   •   www.spicmacay.org'
        _centered_text(draw, _W // 2, _H - 78, footer_bottom, f_footer2, _YELLOW_LIGHT)

        f_footer3 = _font('sans', 15)
        _centered_text(
            draw, _W // 2, _H - 40,
            'Have every child experience the inspiration and mysticism in Indian heritage',
            f_footer3, _YELLOW_LIGHT
        )

        buf = io.BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=92)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Poster generation failed: {e}", exc_info=True)
        return b''


def save_poster(poster_bytes: bytes, event_id) -> str:
    """Save a generated poster to app/static/pdfs/poster_<event_id>_<timestamp>.jpg."""
    if not poster_bytes:
        return ''
    try:
        from app.services.pdf_service import PDFS_DIR
        from datetime import datetime
        os.makedirs(PDFS_DIR, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d%H%M%S')
        path = os.path.join(PDFS_DIR, f'poster_{event_id}_{stamp}.jpg')
        with open(path, 'wb') as fh:
            fh.write(poster_bytes)
        logger.info(f"Generated poster saved: {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to save generated poster: {e}", exc_info=True)
        return ''
