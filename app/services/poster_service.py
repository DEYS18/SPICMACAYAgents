"""
Program Poster Generator — reproduces the SPIC MACAY house poster style used across the
chapters' printed and WhatsApp posters.

Layout, top to bottom, matching the reference posters in "Sample Poster Templates/":
    red border frame → society tagline strip → logo row (ministry block · SPIC MACAY
    wordmark · anniversary/sponsor mark) → "<chapter or institution> PRESENTS" →
    programme title → artist photograph → ornate-framed detail block (art form, artist
    name, date/time, venue, accompanists) → contact band → footer tagline.

Brand marks are loaded from app/static/img/brand/ (produced by tools/extract_brand_assets.py).
Any that are missing are simply skipped and the header rebalances, so the poster still
renders on a machine without them.

Used by the assistant's 'generate a poster' capability — always on request, never automatic.
"""
import io
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

# Portrait canvas at the reference posters' ~3:4 proportions
_W, _H = 1200, 1600

_YELLOW        = (247, 201, 72)
_YELLOW_LIGHT  = (253, 239, 184)
_YELLOW_GLOW   = (255, 250, 224)
_YELLOW_DEEP   = (232, 168, 0)
_RED           = (197, 26, 32)
_RED_DARK      = (139, 0, 0)
_MAROON        = (91, 20, 20)
_INK           = (26, 20, 10)
_WHITE         = (255, 255, 255)

_BRAND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'static', 'img', 'brand')
_ARTIST_PHOTO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'static', 'artist_photos')

# Windows ships Georgia/Arial, so nothing needs bundling on the deployment target.
# Elsewhere these paths simply miss and Pillow's default font is used.
_FONTS_DIR = r'C:\Windows\Fonts'
_FONT_PATHS = {
    'bold_serif':   os.path.join(_FONTS_DIR, 'georgiab.ttf'),
    'serif':        os.path.join(_FONTS_DIR, 'georgia.ttf'),
    'italic_serif': os.path.join(_FONTS_DIR, 'georgiai.ttf'),
    'bold_sans':    os.path.join(_FONTS_DIR, 'arialbd.ttf'),
    'sans':         os.path.join(_FONTS_DIR, 'arial.ttf'),
}

_TAGLINE = 'Society for the Promotion of Indian Classical Music And Culture Amongst Youth'
_FOOTER_TAGLINE = ('Have every child experience the inspiration and mysticism in '
                   'Indian and World Heritage')


def _font(kind: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(_FONT_PATHS.get(kind, _FONT_PATHS['sans']), size)
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def _load_brand(name: str):
    """Load a brand mark, or None when it hasn't been extracted yet."""
    from PIL import Image
    path = os.path.join(_BRAND_DIR, name)
    if not os.path.exists(path):
        logger.info(f"Brand asset {name} not present — that slot will be left empty")
        return None
    try:
        return Image.open(path).convert('RGBA')
    except Exception as e:
        logger.warning(f"Could not load brand asset {name}: {e}")
        return None


def _fit(img, box_w: int, box_h: int):
    """Scale to fit inside a box, preserving aspect ratio."""
    from PIL import Image
    scale = min(box_w / img.width, box_h / img.height)
    return img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                      Image.LANCZOS)


def _background():
    """Warm radial glow with soft bokeh, as on the reference posters."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    ys, xs = np.mgrid[0:_H, 0:_W].astype('float32')
    # Glow centred slightly above the middle, where the artist photograph sits
    dx = (xs - _W * 0.5) / (_W * 0.85)
    dy = (ys - _H * 0.42) / (_H * 0.75)
    dist = np.clip(np.sqrt(dx * dx + dy * dy), 0.0, 1.0)[..., None]

    inner = np.array(_YELLOW_GLOW, dtype='float32').reshape(1, 1, 3)
    outer = np.array(_YELLOW_DEEP, dtype='float32').reshape(1, 1, 3)
    mid = np.array(_YELLOW, dtype='float32').reshape(1, 1, 3)

    near = inner * (1 - dist / 0.55) + mid * (dist / 0.55)
    far = mid * (1 - (dist - 0.55) / 0.45) + outer * ((dist - 0.55) / 0.45)
    grad = np.where(dist < 0.55, near, far).astype('uint8')

    img = Image.fromarray(grad, mode='RGB')

    bokeh = Image.new('RGBA', (_W, _H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bokeh)
    for cx, cy, r, a in [
        (0.16, 0.30, 0.085, 70), (0.83, 0.24, 0.065, 60), (0.28, 0.63, 0.075, 55),
        (0.72, 0.70, 0.055, 50), (0.50, 0.20, 0.050, 45), (0.10, 0.78, 0.045, 40),
        (0.90, 0.55, 0.040, 40), (0.40, 0.85, 0.035, 35),
    ]:
        px, py, pr = cx * _W, cy * _H, r * _W
        bd.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(255, 255, 255, a))
    bokeh = bokeh.filter(ImageFilter.GaussianBlur(40))
    img = Image.alpha_composite(img.convert('RGBA'), bokeh).convert('RGB')
    return img


def _text_w(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _centered(draw, cx, y, text, font, fill, letter_spacing=0):
    if letter_spacing:
        widths = [_text_w(draw, ch, font) + letter_spacing for ch in text]
        x = cx - (sum(widths) - letter_spacing) / 2
        for ch, w in zip(text, widths):
            draw.text((x, y), ch, font=font, fill=fill)
            x += w
        return
    draw.text((cx - _text_w(draw, text, font) / 2, y), text, font=font, fill=fill)


def _wrap(draw, text, font, max_width):
    words = (text or '').split()
    if not words:
        return []
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


def _fit_font(draw, text, kind, max_width, start_size, min_size):
    """Largest size at which the text fits on one line, down to min_size."""
    size = start_size
    while size > min_size:
        f = _font(kind, size)
        if _text_w(draw, text, f) <= max_width:
            return f
        size -= 2
    return _font(kind, min_size)


def _meander_corner(draw, x, y, dx, dy, color, unit=9, thickness=4):
    """
    One corner of the interlocking-key border that frames the detail block on the
    reference posters. `dx`/`dy` of ±1 orient it into each of the four corners.
    """
    def line(x0, y0, x1, y1):
        draw.line([(x + dx * x0 * unit, y + dy * y0 * unit),
                   (x + dx * x1 * unit, y + dy * y1 * unit)],
                  fill=color, width=thickness)

    # Outer L
    line(0, 0, 6, 0)
    line(0, 0, 0, 6)
    # Inner spiral, giving the Greek-key look
    line(2, 2, 5, 2)
    line(2, 2, 2, 5)
    line(5, 2, 5, 4)
    line(2, 5, 4, 5)
    line(4, 4, 5, 4)
    line(4, 4, 4, 5)


def _ornate_frame(draw, x0, y0, x1, y1, color, unit=9):
    """Double rule plus meander corners — the detail block's surround."""
    draw.rectangle([x0, y0, x1, y1], outline=color, width=3)
    draw.rectangle([x0 + 10, y0 + 10, x1 - 10, y1 - 10], outline=color, width=1)
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        _meander_corner(draw, cx, cy, dx, dy, color, unit=unit)


def _load_artist_photo(program_data: dict):
    """
    Resolve the artist photograph, preferring an explicit path/bytes and otherwise
    falling back to the stored per-artist image.
    """
    from PIL import Image

    raw = program_data.get('artist_photo_bytes')
    if raw:
        try:
            return Image.open(io.BytesIO(raw)).convert('RGB')
        except Exception as e:
            logger.warning(f"Could not read supplied artist photo bytes: {e}")

    path = program_data.get('artist_photo_path') or stored_artist_photo_path(
        program_data.get('artist_id')
    )
    if path and os.path.exists(path):
        try:
            return Image.open(path).convert('RGB')
        except Exception as e:
            logger.warning(f"Could not open artist photo {path}: {e}")
    return None


def stored_artist_photo_path(artist_id) -> str:
    """Path of the saved photo for an artist, or '' when none has been stored."""
    if not artist_id:
        return ''
    for ext in ('jpg', 'png', 'jpeg'):
        path = os.path.join(_ARTIST_PHOTO_DIR, f'{artist_id}.{ext}')
        if os.path.exists(path):
            return path
    return ''


def save_artist_photo(photo_bytes: bytes, artist_id) -> str:
    """
    Store an artist's photograph under their directory ID so later posters for the same
    artist reuse it without asking again. Returns the saved path, or '' on failure.
    """
    if not photo_bytes or not artist_id:
        return ''
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(photo_bytes))
        img = img.convert('RGB')
        # Cap the stored size — posters never need more, and originals can be huge
        img.thumbnail((1400, 1400), Image.LANCZOS)

        os.makedirs(_ARTIST_PHOTO_DIR, exist_ok=True)
        for ext in ('png', 'jpeg'):
            stale = os.path.join(_ARTIST_PHOTO_DIR, f'{artist_id}.{ext}')
            if os.path.exists(stale):
                os.remove(stale)

        path = os.path.join(_ARTIST_PHOTO_DIR, f'{artist_id}.jpg')
        img.save(path, format='JPEG', quality=90)
        logger.info(f"Stored artist photo for artist {artist_id}: {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to store artist photo for {artist_id}: {e}", exc_info=True)
        return ''


def _draw_header(img, draw, presenter: str) -> int:
    """Border, tagline strip and logo row. Returns the y to continue drawing from."""
    # Red frame with an inset rounded yellow panel
    draw.rectangle([0, 0, _W - 1, _H - 1], outline=_RED, width=16)
    draw.rounded_rectangle([16, 16, _W - 17, _H - 17], radius=26, outline=_RED, width=3)

    y = 34
    f_tag = _font('bold_sans', 21)
    _centered(draw, _W // 2, y, _TAGLINE, f_tag, _RED_DARK)
    y += 40

    # Logo row — the wordmark is the anchor; side marks are optional
    row_top, row_h = y, 128
    wordmark = _load_brand('spicmacay_wordmark.png')
    if wordmark:
        wm = _fit(wordmark, 470, row_h)
        img.paste(wm, (_W // 2 - wm.width // 2, row_top + (row_h - wm.height) // 2), wm)
    else:
        _centered(draw, _W // 2, row_top + 34, 'SPIC MACAY',
                  _font('bold_serif', 58), _INK, letter_spacing=4)

    ministry = _load_brand('ministry_block.png')
    if ministry:
        mb = _fit(ministry, 250, row_h - 8)
        img.paste(mb, (52, row_top + (row_h - mb.height) // 2), mb)

    badge = _load_brand('anniversary_badge.png')
    if badge:
        bd_img = _fit(badge, 130, row_h - 8)
        img.paste(bd_img, (_W - 62 - bd_img.width, row_top + (row_h - bd_img.height) // 2), bd_img)

    y = row_top + row_h + 16

    f_presents = _fit_font(draw, presenter, 'bold_serif', _W - 220, 38, 22)
    for line in _wrap(draw, presenter, f_presents, _W - 220):
        _centered(draw, _W // 2, y, line, f_presents, _RED_DARK)
        y += f_presents.size + 8
    return y + 6


def _draw_footer(draw, chapter: str, contact: str):
    """Contact band and closing tagline. Returns the y the band starts at."""
    band_h = 58
    band_y0 = _H - 108
    draw.rectangle([18, band_y0, _W - 19, band_y0 + band_h], fill=_RED_DARK)

    contact_line = contact.strip() if contact else 'For more info visit us at www.spicmacay.org'
    _centered(draw, _W // 2, band_y0 + 8, contact_line, _font('bold_sans', 21), _WHITE)
    _centered(draw, _W // 2, band_y0 + 33,
              f'SPIC MACAY{" " + chapter if chapter else ""}  •  www.spicmacay.org',
              _font('sans', 17), _YELLOW_LIGHT)

    _centered(draw, _W // 2, band_y0 + band_h + 12, _FOOTER_TAGLINE,
              _font('bold_sans', 17), _RED_DARK)
    return band_y0


# Grading and panel markup carried on directory records — meaningful to the office,
# meaningless (and unsightly) to an audience reading a poster.
_ART_FORM_NOISE = re.compile(
    r'''(?ix)
    \s*(?:[-–—,:/(\[]\s*)?      # optional separator or opening bracket
    (?:
        list\s*[-–—]?\s*[abc]\d?      # List A, List-B, List B1
      | grade\s*[-–—]?\s*[abc]\d?     # Grade A
      | categ(?:ory)?\s*[-–—]?\s*[abc]\d?
      | cat\.?\s*[-–—]?\s*[abc]\d?
      | (?:s{1,2}na|ysna)             # SNA / SSNA / YSNA panel tags
      | tier\s*[-–—]?\s*[abc]\d?
    )
    \s*[)\]]?                    # optional closing bracket
    ''')

# Internal module names that read awkwardly on a poster
_MODULE_DISPLAY = {
    'full concert': 'Concert',
    'workshops': 'Workshop',
    'workshop demonstration': 'Workshop Demonstration',
    'virtual demonstrations': 'Virtual Demonstration',
    'virtual interactions': 'Virtual Interaction',
}


def clean_art_form(value: str) -> str:
    """
    Strip directory grading markup from an art form for display.

    "Hindustani Vocal (List A)" -> "Hindustani Vocal". Genuine parenthetical detail
    such as "Talk (Literature)" is left alone — only grading tags are removed.
    """
    text = (value or '').strip()
    if not text:
        return ''
    cleaned = _ART_FORM_NOISE.sub('', text)
    # Tidy up whatever punctuation the removal left behind
    cleaned = re.sub(r'\(\s*\)|\[\s*\]', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip(' \t-–—,:;/')
    return cleaned or text


def display_module_name(value: str) -> str:
    """Present a module the way an audience would read it — a concert is just a Concert."""
    text = (value or '').strip()
    if not text:
        return ''
    return _MODULE_DISPLAY.get(text.lower(), text)


def generate_program_poster(program_data: dict) -> bytes:
    """
    Build a SPIC MACAY house-style poster.

    Args:
        program_data: {institution_name, artist_name, art_form, module_name, start_date,
                       event_time, venue, city, state, chapter, contact,
                       coordinator_name, accompanying_artists (list of names), artist_id,
                       artist_photo_bytes / artist_photo_path (optional)}

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
        artist_name = program_data.get('artist_name') or 'Artist Name'
        art_form = clean_art_form(program_data.get('art_form'))
        module_name = display_module_name(program_data.get('module_name') or 'Concert')
        venue = program_data.get('venue') or institution_name
        city = program_data.get('city') or ''
        state = program_data.get('state') or ''
        chapter = (program_data.get('chapter') or '').strip()
        contact = (program_data.get('contact') or '').strip()
        accompanying = program_data.get('accompanying_artists') or []

        event_date = program_data.get('start_date') or ''
        try:
            event_date = datetime.strptime(str(event_date)[:10], '%Y-%m-%d').strftime('%d %B %Y')
        except ValueError:
            pass
        event_time = program_data.get('event_time') or ''

        img = _background()
        draw = ImageDraw.Draw(img)

        presenter = f'{chapter or institution_name} PRESENTS'
        y = _draw_header(img, draw, presenter)

        # Programme title — the module, e.g. "Hindustani Vocal Recital"
        f_title = _fit_font(draw, module_name, 'bold_serif', _W - 220, 58, 32)
        for line in _wrap(draw, module_name, f_title, _W - 220):
            _centered(draw, _W // 2, y, line, f_title, _INK)
            y += f_title.size + 10
        y += 10

        band_y0 = _draw_footer(draw, chapter, contact)

        # ── Detail block, measured bottom-up so the photo can take the slack ──
        inner_w = _W - 240
        f_artist = _fit_font(draw, artist_name, 'bold_serif', inner_w - 40, 72, 36)
        artist_lines = _wrap(draw, artist_name, f_artist, inner_w - 40)

        f_form = _font('bold_serif', 42)
        f_date = _font('bold_serif', 40)
        f_venue = _font('serif', 32)
        f_acc = _font('serif', 28)
        f_coord = _font('serif', 27)

        # Venue strings usually already carry the town, and city can repeat state
        # ("Delhi, Delhi"), so append each part only when it adds something new
        venue_line = venue
        for part in (city, state):
            if part and part.lower() not in venue_line.lower():
                venue_line += f', {part}'
        venue_lines = _wrap(draw, f'Venue: {venue_line}', f_venue, inner_w - 60)

        acc_lines = []
        if accompanying:
            names = [a if isinstance(a, str) else a.get('name', '') for a in accompanying]
            acc_lines = _wrap(draw, 'Accompanied by: ' + ', '.join(n for n in names if n),
                              f_acc, inner_w - 60)

        coordinator = (program_data.get('coordinator_name') or '').strip()
        coord_lines = _wrap(draw, f'Coordinator: {coordinator}', f_coord,
                            inner_w - 60) if coordinator else []

        detail_h = 34
        if art_form:
            detail_h += f_form.size + 16
        detail_h += len(artist_lines) * (f_artist.size + 12) + 10
        if acc_lines:
            detail_h += len(acc_lines) * (f_acc.size + 8) + 8
        if event_date:
            detail_h += f_date.size + 16
        detail_h += len(venue_lines) * (f_venue.size + 8) + 30
        if coord_lines:
            detail_h += len(coord_lines) * (f_coord.size + 6) + 6

        detail_y1 = band_y0 - 22
        detail_y0 = detail_y1 - detail_h
        detail_x0, detail_x1 = 110, _W - 110

        # ── Artist photograph fills whatever space is left between title and details ──
        photo = _load_artist_photo(program_data)
        photo_top, photo_bottom = y, detail_y0 - 22
        avail_h = photo_bottom - photo_top

        if photo and avail_h > 180:
            frame_w = _W - 260
            fitted = _fit(photo.convert('RGBA'), frame_w, avail_h - 16)
            px = _W // 2 - fitted.width // 2
            py = photo_top + (avail_h - fitted.height) // 2
            draw.rectangle([px - 7, py - 7, px + fitted.width + 6, py + fitted.height + 6],
                           fill=_WHITE)
            img.paste(fitted, (px, py), fitted)
            draw.rectangle([px - 7, py - 7, px + fitted.width + 6, py + fitted.height + 6],
                           outline=_RED, width=3)
        elif avail_h > 160:
            # No photograph on file — a soft emblem watermark reads better than a gap
            emblem = _load_brand('spicmacay_wordmark.png')
            if emblem:
                wm = _fit(emblem, _W - 420, avail_h - 60)
                faded = wm.copy()
                faded.putalpha(wm.getchannel('A').point(lambda a: int(a * 0.16)))
                img.paste(faded, (_W // 2 - faded.width // 2,
                                  photo_top + (avail_h - faded.height) // 2), faded)

        # ── Detail block ───────────────────────────────────────────────────────
        _ornate_frame(draw, detail_x0, detail_y0, detail_x1, detail_y1, _RED_DARK)

        cy = detail_y0 + 30
        if art_form:
            _centered(draw, _W // 2, cy, f'- {art_form.upper()} -', f_form, _MAROON)
            cy += f_form.size + 16

        for line in artist_lines:
            _centered(draw, _W // 2, cy, line, f_artist, _RED_DARK)
            cy += f_artist.size + 12
        cy += 10

        for line in acc_lines:
            _centered(draw, _W // 2, cy, line, f_acc, _INK)
            cy += f_acc.size + 8
        if acc_lines:
            cy += 8

        if event_date:
            date_line = event_date + (f'  |  {event_time}' if event_time else '')
            _centered(draw, _W // 2, cy, date_line, f_date, _INK)
            cy += f_date.size + 16

        for line in venue_lines:
            _centered(draw, _W // 2, cy, line, f_venue, _INK)
            cy += f_venue.size + 8

        if coord_lines:
            cy += 6
            for line in coord_lines:
                _centered(draw, _W // 2, cy, line, f_coord, _MAROON)
                cy += f_coord.size + 6

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
