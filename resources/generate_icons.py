"""
One-off script: generates the small arrow/chevron PNG icons the stylesheet
references but that were never actually created. Run once to populate
resources/icons/. Not part of the app itself.
"""

import os
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons")
os.makedirs(OUT_DIR, exist_ok=True)

COLOR_DEFAULT = (102, 109, 128, 255)  # #666d80 (Text Secondary)
COLOR_HOVER = (74, 71, 214, 255)      # #4a47d6 (Accent)
SUPERSAMPLE = 4  # draw big, downsample for clean anti-aliased edges


def _new_canvas(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int]:
    bw, bh = w * SUPERSAMPLE, h * SUPERSAMPLE
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), bw, bh


def _save(img: Image.Image, w: int, h: int, name: str) -> None:
    img = img.resize((w, h), Image.LANCZOS)
    img.save(os.path.join(OUT_DIR, name))
    print("wrote", name)


def triangle_up(w: int, h: int, color, name: str) -> None:
    img, draw, bw, bh = _new_canvas(w, h)
    draw.polygon([(bw * 0.1, bh * 0.75), (bw * 0.9, bh * 0.75), (bw * 0.5, bh * 0.15)], fill=color)
    _save(img, w, h, name)


def triangle_down(w: int, h: int, color, name: str) -> None:
    img, draw, bw, bh = _new_canvas(w, h)
    draw.polygon([(bw * 0.1, bh * 0.25), (bw * 0.9, bh * 0.25), (bw * 0.5, bh * 0.85)], fill=color)
    _save(img, w, h, name)


def triangle_left(w: int, h: int, color, name: str) -> None:
    img, draw, bw, bh = _new_canvas(w, h)
    draw.polygon([(bw * 0.8, bh * 0.1), (bw * 0.8, bh * 0.9), (bw * 0.2, bh * 0.5)], fill=color)
    _save(img, w, h, name)


def triangle_right(w: int, h: int, color, name: str) -> None:
    img, draw, bw, bh = _new_canvas(w, h)
    draw.polygon([(bw * 0.2, bh * 0.1), (bw * 0.2, bh * 0.9), (bw * 0.8, bh * 0.5)], fill=color)
    _save(img, w, h, name)


def chevron_right(w: int, h: int, color, name: str) -> None:
    """Tree-branch 'collapsed' indicator — thin chevron, not a filled triangle."""
    img, draw, bw, bh = _new_canvas(w, h)
    stroke = max(2, bw // 10)
    draw.line(
        [(bw * 0.35, bh * 0.2), (bw * 0.68, bh * 0.5), (bw * 0.35, bh * 0.8)],
        fill=color, width=stroke, joint="curve",
    )
    _save(img, w, h, name)


def chevron_down(w: int, h: int, color, name: str) -> None:
    """Tree-branch 'expanded' indicator."""
    img, draw, bw, bh = _new_canvas(w, h)
    stroke = max(2, bw // 10)
    draw.line(
        [(bw * 0.2, bh * 0.35), (bw * 0.5, bh * 0.68), (bw * 0.8, bh * 0.35)],
        fill=color, width=stroke, joint="curve",
    )
    _save(img, w, h, name)


# Spin box up/down arrows
triangle_up(9, 6, COLOR_DEFAULT, "spin_up.png")
triangle_up(9, 6, COLOR_HOVER, "spin_up_hover.png")
triangle_down(9, 6, COLOR_DEFAULT, "spin_down.png")
triangle_down(9, 6, COLOR_HOVER, "spin_down_hover.png")

# Tab-bar overflow-scroll left/right arrows
triangle_left(8, 12, COLOR_DEFAULT, "tab_left.png")
triangle_left(8, 12, COLOR_HOVER, "tab_left_hover.png")
triangle_right(8, 12, COLOR_DEFAULT, "tab_right.png")
triangle_right(8, 12, COLOR_HOVER, "tab_right_hover.png")

# Combo box dropdown arrow
triangle_down(10, 6, COLOR_DEFAULT, "combo_down.png")

# Tree branch expand/collapse indicators
chevron_right(12, 12, COLOR_DEFAULT, "tree_closed.png")
chevron_down(12, 12, COLOR_DEFAULT, "tree_open.png")

print("done")
