"""Visual language for menus and the HUD: one palette, one type scale and a few drawing helpers.

Everything is drawn on the fixed 1280x720 HUD surface, which main.py scales to the window.
"""

import math

import pygame

from units import FEET_PER_METRE

WIDTH, HEIGHT = 1280, 720

INK = (9, 18, 27)
PANEL = (9, 18, 27, 200)
PANEL_SOFT = (9, 18, 27, 150)
LINE = (255, 255, 255, 40)
TEXT = (238, 241, 236)
MUTED = (150, 166, 170)
DIM = (96, 112, 118)
ACCENT = (242, 180, 92)
COOL = (132, 200, 214)
ALERT = (232, 98, 80)
GOOD = (136, 210, 152)

TEXT_FAMILY = 'bahnschrift,segoeui,helveticaneue,helvetica,dejavusans,arial'
MONO_FAMILY = 'consolas,dejavusansmono,menlo,couriernew'


class Fonts:
    """The type scale. Bahnschrift on Windows, sensible fallbacks elsewhere."""

    def __init__(self):
        text = lambda size, bold=False: pygame.font.SysFont(TEXT_FAMILY, size, bold=bold)
        mono = lambda size: pygame.font.SysFont(MONO_FAMILY, size)
        self.display = text(88, bold=True)
        self.h1 = text(40, bold=True)
        self.h2 = text(24, bold=True)
        self.body = text(18)
        self.small = text(15)
        self.tiny = text(12, bold=True)
        self.mono = mono(20)
        self.mono_small = mono(15)


_cache = {}


def render(text, font, color, tracking=0):
    """Cached text surface; tracking adds letter spacing in pixels (used for small caps labels)."""
    key = (text, id(font), color, tracking)
    surface = _cache.get(key)
    if surface is None:
        if len(_cache) > 600:
            _cache.clear()
        if tracking and text:
            glyphs = [font.render(char, True, color[:3]) for char in text]
            width = sum(glyph.get_width() for glyph in glyphs) + tracking * (len(glyphs) - 1)
            surface = pygame.Surface((max(1, width), font.get_height()), pygame.SRCALPHA)
            x = 0
            for glyph in glyphs:
                surface.blit(glyph, (x, 0))
                x += glyph.get_width() + tracking
        else:
            surface = font.render(text, True, color[:3])
        _cache[key] = surface
    return surface


def text(surface, value, font, color, pos, anchor='topleft', tracking=0, alpha=255, shadow=False):
    image = render(str(value), font, tuple(color[:3]), tracking)
    rect = image.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
    if shadow:
        # A soft offset shadow keeps text legible straight over bright clouds.
        dark = render(str(value), font, (4, 8, 14), tracking).copy()
        dark.set_alpha(int(150 * alpha / 255))
        surface.blit(dark, rect.move(1, 1))
        surface.blit(dark, rect.move(0, 2))
    if alpha < 255:
        image = image.copy()
        image.set_alpha(max(0, int(alpha)))
    surface.blit(image, rect)
    return rect


def label(surface, value, font, pos, color=MUTED, anchor='topleft', alpha=255, shadow=False):
    """Small spaced capitals, the voice of every caption."""
    return text(surface, str(value).upper(), font, color, pos, anchor, tracking=2, alpha=alpha, shadow=shadow)


def wrap(value, font, width):
    lines, line = [], ''
    for word in str(value).split():
        trial = f'{line} {word}'.strip()
        if font.size(trial)[0] <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def paragraph(surface, value, font, color, pos, width, spacing=6, alpha=255):
    y = pos[1]
    for line in wrap(value, font, width):
        text(surface, line, font, color, (pos[0], y), alpha=alpha)
        y += font.get_height() + spacing
    return y


def blend_rect(surface, color, rect, radius=0, width=0):
    """Rounded rectangle alpha-blended onto the surface (pygame.draw would overwrite the alpha)."""
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return rect
    if len(color) == 3 or color[3] == 255:
        pygame.draw.rect(surface, color, rect, width, border_radius=radius)
        return rect
    shape = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(shape, color, shape.get_rect(), width, border_radius=radius)
    surface.blit(shape, rect.topleft)
    return rect


def panel(surface, rect, color=PANEL, radius=12, border=LINE):
    blend_rect(surface, color, rect, radius)
    if border:
        blend_rect(surface, border, rect, radius, 1)


def bar(surface, rect, value, color=ACCENT, back=(255, 255, 255, 34)):
    x, y, w, h = rect
    blend_rect(surface, back, rect, h // 2)
    filled = int(w * min(max(value, 0.0), 1.0))
    if filled > 0:
        blend_rect(surface, color, (x, y, max(filled, h), h), h // 2)


def cap_width(key, fonts):
    return max(26, render(key, fonts.tiny, TEXT, 1).get_width() + 14)


def key_cap(surface, key, fonts, pos, anchor='topleft'):
    """A keyboard key drawn as a small outlined cap."""
    image = render(key, fonts.tiny, TEXT, 1)
    rect = pygame.Rect(0, 0, cap_width(key, fonts), 24)
    setattr(rect, anchor, pos)
    blend_rect(surface, (255, 255, 255, 22), rect, 5)
    blend_rect(surface, (255, 255, 255, 90), rect, 5, 1)
    surface.blit(image, image.get_rect(center=rect.center))
    return rect


def hint_row(surface, items, fonts, pos, anchor='bottomleft'):
    """'KEY action  KEY action' row; returns its width."""
    x, y = pos
    widths = [cap_width(key, fonts) + 8 + fonts.small.size(action)[0] + 22 for key, action in items]
    total = sum(widths) - 22
    if anchor.endswith('right'):
        x -= total
    elif anchor.startswith('mid'):
        x -= total // 2
    for (key, action), width in zip(items, widths):
        cap = key_cap(surface, key, fonts, (x, y - 24))
        text(surface, action, fonts.small, MUTED, (cap.right + 8, cap.centery), 'midleft')
        x += width
    return total


def scene_shade(size, top, bottom, left):
    """Dark gradients laid over the 3D scene (not the HUD) so text stays readable on bright skies.

    Strengths are 0..1. Returns an RGBA surface of the window size.
    """
    width, height = size
    column = pygame.Surface((1, 256), pygame.SRCALPHA)
    for y in range(256):
        v = y / 255
        alpha = max(top * max(0.0, 1 - v / 0.19) ** 1.7, bottom * max(0.0, (v - 0.78) / 0.22) ** 1.7)
        column.set_at((0, y), (6, 12, 20, int(255 * alpha)))
    shade = pygame.transform.smoothscale(column, (max(1, width), max(1, height)))
    if left > 0:
        row = pygame.Surface((256, 1), pygame.SRCALPHA)
        for x in range(256):
            row.set_at((x, 0), (6, 12, 20, int(255 * left * max(0.0, 1 - x / 255 / 0.62) ** 1.6)))
        shade.blit(pygame.transform.smoothscale(row, (max(1, width), max(1, height))), (0, 0))
    return shade


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def fade_in_out(age, duration, fade=0.5):
    """0..1 envelope for timed banners."""
    if age < 0 or age > duration:
        return 0.0
    return ease(min(age / fade, (duration - age) / fade, 1.0))


def compass_label(degrees):
    return {0: 'N', 90: 'E', 180: 'S', 270: 'W'}.get(degrees % 360, f'{degrees % 360:03d}'[:2])


def bearing(from_x, from_z, to_x, to_z):
    """Compass bearing in radians (0 = north/+z, clockwise)."""
    return math.atan2(to_x - from_x, to_z - from_z)


def format_distance(meters):
    miles = meters / 1609.344
    return f'{miles:.1f} mi' if miles >= 0.1 else f'{meters * FEET_PER_METRE:,.0f} ft'
