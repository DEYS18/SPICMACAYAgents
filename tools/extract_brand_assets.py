"""
One-off utility: lift the SPIC MACAY brand marks out of the reference posters in
"Sample Poster Templates/" and write them to app/static/img/brand/ as transparent PNGs.

The marks only exist inside flattened JPEG posters, so the background is keyed out by
flood-filling inward from the border. That keeps saturated interior colours (the emblem's
green and saffron, the red bindu) which a plain colour-distance key would eat.

Re-run only when better source posters arrive; the generator reads the PNGs, not this script.
    python tools/extract_brand_assets.py
"""
import os
import sys
from collections import deque

from PIL import Image

SRC_DIR = 'Sample Poster Templates'
OUT_DIR = os.path.join('app', 'static', 'img', 'brand')

# (output name, source poster, crop box, flood tolerance)
ASSETS = [
    ('spicmacay_wordmark.png',
     '728704513_1720681949066618_3641471722211711803_n.jpg', (380, 235, 1065, 460), 60),
    # Higher tolerance here clears the bokeh mottling behind the ministry text, but pushed
    # further it starts eating the emblem's pale lion detail
    ('ministry_block.png',
     '630134242_18454142077102682_7744373694082872680_n.jpg', (28, 58, 315, 232), 90),
    ('anniversary_badge.png',
     '630134242_18454142077102682_7744373694082872680_n.jpg', (880, 70, 1010, 200), 52),
    ('sponsor_srf.png',
     '658405460_18461851705102682_2470799328143034208_n.jpg', (843, 72, 1020, 168), 52),
]


def key_out_background(img: Image.Image, tolerance: int) -> Image.Image:
    """Make border-connected background pixels transparent, leaving the mark itself intact."""
    img = img.convert('RGBA')
    w, h = img.size
    px = img.load()

    seeds = (
        [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] +
        [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    )
    # Average the corners rather than trusting one pixel, which may sit on a stray artifact
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    seen = bytearray(w * h)
    queue = deque()
    for x, y in seeds:
        r, g, b, _ = px[x, y]
        if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) <= tolerance:
            idx = y * w + x
            if not seen[idx]:
                seen[idx] = 1
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                idx = ny * w + nx
                if not seen[idx]:
                    r, g, b, _ = px[nx, ny]
                    if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) <= tolerance:
                        seen[idx] = 1
                        queue.append((nx, ny))

    return img


def main() -> int:
    if not os.path.isdir(SRC_DIR):
        print(f"Source posters not found at {SRC_DIR!r} — run from the project root.")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    for name, source, box, tolerance in ASSETS:
        path = os.path.join(SRC_DIR, source)
        if not os.path.exists(path):
            print(f"  skip {name}: source poster missing ({source})")
            continue
        asset = key_out_background(Image.open(path).crop(box), tolerance)
        asset.save(os.path.join(OUT_DIR, name))
        opaque = sum(1 for p in asset.get_flattened_data() if p[3] > 0)
        print(f"  wrote {name}  {asset.size}  {opaque * 100 // (asset.width * asset.height)}% opaque")

    print(f"Brand assets written to {OUT_DIR}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
