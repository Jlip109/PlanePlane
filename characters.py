"""The cast: pilots you can fly as, tower controllers for each city and courier passengers.

Portraits are flat vector illustrations drawn with pygame at 4x and scaled down for smooth edges.
"""

from collections import deque
import math

import pygame

import ui

SKIN = [(244, 214, 186), (230, 185, 148), (196, 140, 100), (150, 98, 66), (104, 68, 46)]


class Character:
    def __init__(self, name, role, skin, hair, hair_color, jacket, accent, gear='', beard=False, **extra):
        self.name, self.role = name, role
        self.skin, self.hair, self.hair_color = SKIN[skin], hair, hair_color
        self.jacket, self.accent, self.gear, self.beard = jacket, accent, gear, beard
        self.__dict__.update(extra)
        self._portraits = {}

    def portrait(self, size):
        image = self._portraits.get(size)
        if image is None:
            image = pygame.transform.smoothscale(draw_portrait(self), (size, size))
            self._portraits[size] = image
        return image


PILOTS = [
    Character('Amara Okafor', 'NIMBUS', 3, 'bun', (24, 20, 22), (38, 58, 92), (124, 182, 222), 'goggles',
              quote='Clouds are just slow weather. Let’s see what’s on the other side.',
              perk='Balanced in every way', speed=1.0, handling=1.0, boost=1.0),
    Character('Diego Ramírez', 'TAILWIND', 1, 'short', (52, 36, 28), (118, 44, 40), (236, 196, 120), 'goggles',
              beard=True, quote='If you’re not early, you’re not trying.',
              perk='Fastest cruise, wider turns', speed=1.14, handling=0.85, boost=0.95),
    Character('Mei Chen', 'CIRRUS', 0, 'long', (20, 18, 24), (30, 102, 106), (226, 236, 232), 'goggles',
              quote='Tight turns, clean lines, no wasted fuel.',
              perk='Sharpest handling', speed=0.96, handling=1.3, boost=1.0),
    Character('Hank Whitaker', 'GRUMPY', 1, 'bald', (176, 172, 166), (92, 82, 52), (196, 64, 52), 'scarf',
              beard=True, quote='Forty years up here. The sky still surprises me.',
              perk='Longest boost', speed=1.0, handling=0.9, boost=1.4),
]

TOWERS = {
    'TROY': Character('Rosa Delgado', 'TROY TOWER', 2, 'curly', (40, 28, 24), (60, 70, 84), (242, 180, 92), 'headset',
                      flavor='Welcome home. The river’s calm and the brick is warm.'),
    'SKYPORT': Character('Felix Park', 'SKYPORT TOWER', 0, 'short', (30, 28, 30), (46, 54, 70), (132, 200, 214), 'headset',
                         flavor='Mind the glass towers. They’re taller than they look.'),
    'NIMBUS HEIGHTS': Character('Inès Varga', 'NIMBUS CONTROL', 1, 'long', (120, 60, 40), (54, 48, 70), (180, 150, 230),
                                'headset', flavor='The spires reach the clouds here. Fly between them, not into them.'),
    'ALBANY': Character('Marcus Bell', 'ALBANY APPROACH', 4, 'buzz', (24, 22, 22), (40, 44, 52), (242, 180, 92), 'headset',
                        flavor='Capital airspace. Busy, but you’re cleared to look around.'),
    'LAKE GEORGE': Character('June Albright', 'LAKE GEORGE RADIO', 0, 'bun', (196, 150, 90), (60, 92, 110), (240, 240, 230),
                             'headset', flavor='Watch the sun on the water. It’s the best view in the state.'),
    'SARATOGA': Character('Sam Ortiz', 'SARATOGA FIELD', 2, 'short', (36, 30, 26), (70, 90, 62), (230, 200, 120), 'headset',
                          beard=True, flavor='Gardens below, racetrack to the east. Easy does it.'),
}

PASSENGERS = [
    Character('Grandpa Joe', 'PASSENGER', 1, 'bald', (210, 208, 204), (120, 84, 60), (220, 200, 150), beard=True,
              ask='My granddaughter turns eight today. The cake must reach {dest} in one piece!',
              thanks='Not a crumb out of place. You’re a legend.'),
    Character('Dr. Priya Shah', 'PASSENGER', 2, 'bun', (26, 22, 24), (230, 234, 236), (90, 160, 190),
              ask='These vaccines need to reach the {dest} clinic before the evening shift.',
              thanks='Right on time. The clinic thanks you.'),
    Character('Luna Moreau', 'BAKER', 0, 'long', (190, 120, 70), (200, 120, 90), (250, 236, 210),
              ask='Fresh sourdough for the {dest} farmers market. Still warm!',
              thanks='Still warm! You can have the first loaf.'),
    Character('Coach Rivera', 'PASSENGER', 3, 'short', (28, 24, 22), (40, 70, 140), (240, 240, 240),
              ask='Team jerseys for tonight’s game in {dest}. No pressure.',
              thanks='Kickoff saved. Front row seats are yours.'),
    Character('Theo, age 9', 'YOUNG SCIENTIST', 1, 'curly', (110, 70, 40), (230, 160, 40), (60, 80, 120),
              ask='My robot is going to the {dest} science fair. Please don’t crash.',
              thanks='It still works! Best pilot ever.'),
    Character('Ms. Hart', 'LIBRARIAN', 0, 'bun', (150, 150, 156), (110, 60, 80), (230, 210, 200), gear='glasses',
              ask='Rare books for the {dest} library. Handle with care, please.',
              thanks='Not a page bent. Wonderful flying.'),
    Character('Ollie Brandt', 'FLORIST', 2, 'curly', (60, 40, 30), (70, 120, 80), (240, 170, 190),
              ask='Wedding flowers for {dest}. The ceremony starts soon!',
              thanks='They’re perfect. The bride will cry. Happily.'),
    Character('Captain Ruiz', 'FERRY CAPTAIN', 3, 'short', (200, 198, 192), (30, 40, 70), (240, 210, 120), beard=True,
              ask='Spare parts for the {dest} ferry. We’re stuck without them.',
              thanks='The ferry runs tonight thanks to you.'),
]


def shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color[:3])


def draw_portrait(person):
    """Flat illustrated bust in a circle; drawn at 256 px."""
    s = 256
    art = pygame.Surface((s, s), pygame.SRCALPHA)
    back = shade(person.accent, 0.55)
    art.fill(back)
    pygame.draw.circle(art, shade(person.accent, 0.7), (s // 2, s // 2 + 40), 150)

    skin, hair = person.skin, person.hair_color
    cx, head_y = s // 2, 118
    if person.hair == 'long':
        pygame.draw.ellipse(art, hair, (cx - 48, head_y - 50, 96, 150))
    # shoulders and collar
    pygame.draw.ellipse(art, person.jacket, (cx - 100, 196, 200, 140))
    pygame.draw.rect(art, shade(skin, 0.86), (cx - 15, head_y + 28, 30, 44))
    pygame.draw.polygon(art, shade(person.jacket, 1.35), [(cx - 30, 204), (cx, 236), (cx + 30, 204), (cx, 214)])
    pygame.draw.polygon(art, shade(skin, 0.86), [(cx - 15, 200), (cx, 222), (cx + 15, 200)])
    if person.gear == 'scarf':
        pygame.draw.ellipse(art, person.accent, (cx - 40, 188, 80, 30))
        pygame.draw.polygon(art, shade(person.accent, 0.85), [(cx + 8, 206), (cx + 30, 252), (cx + 12, 256), (cx - 2, 212)])
    # head
    pygame.draw.ellipse(art, shade(skin, 0.9), (cx - 41, head_y - 6, 14, 24))
    pygame.draw.ellipse(art, shade(skin, 0.9), (cx + 27, head_y - 6, 14, 24))
    pygame.draw.ellipse(art, skin, (cx - 34, head_y - 44, 68, 86))
    # hair
    if person.hair in ('short', 'bun', 'long', 'buzz'):
        cap = (cx - 37, head_y - 50, 74, 48)
        color = hair if person.hair != 'buzz' else shade(hair, 1.0)
        pygame.draw.ellipse(art, color, cap)
        if person.hair == 'buzz':
            pygame.draw.ellipse(art, skin, (cx - 30, head_y - 30, 60, 30))
        else:
            pygame.draw.polygon(art, color, [(cx - 34, head_y - 20), (cx - 10, head_y - 34), (cx + 30, head_y - 30),
                                             (cx + 35, head_y - 12), (cx + 36, head_y - 34), (cx - 36, head_y - 34)])
        if person.hair == 'bun':
            pygame.draw.circle(art, hair, (cx, head_y - 56), 17)
    elif person.hair == 'curly':
        for k in range(13):
            angle = math.pi + k * math.pi / 12
            pygame.draw.circle(art, hair, (cx + int(math.cos(angle) * 34), head_y - 12 + int(math.sin(angle) * 40)), 15)
    # face
    eye = (34, 28, 28)
    for side in (-1, 1):
        pygame.draw.ellipse(art, eye, (cx + side * 14 - 5, head_y - 2, 10, 8))
        brow = hair if person.hair != 'bald' else shade(skin, 0.6)
        pygame.draw.line(art, brow, (cx + side * 8, head_y - 11), (cx + side * 22, head_y - 13), 4)
    pygame.draw.line(art, shade(skin, 0.78), (cx, head_y + 4), (cx - 3, head_y + 16), 3)
    pygame.draw.arc(art, shade(skin, 0.55), (cx - 11, head_y + 14, 22, 14), math.pi + 0.35, 2 * math.pi - 0.35, 3)
    if person.beard:
        beard = shade(hair, 1.0) if person.hair != 'bald' else person.hair_color
        pygame.draw.polygon(art, beard, [(cx - 32, head_y + 6), (cx - 22, head_y + 34), (cx, head_y + 44),
                                         (cx + 22, head_y + 34), (cx + 32, head_y + 6), (cx + 20, head_y + 24),
                                         (cx, head_y + 28), (cx - 20, head_y + 24)])
        pygame.draw.ellipse(art, beard, (cx - 16, head_y + 15, 32, 9))
    if person.gear == 'glasses':
        for side in (-1, 1):
            pygame.draw.circle(art, (40, 36, 40), (cx + side * 14, head_y + 2), 11, 3)
        pygame.draw.line(art, (40, 36, 40), (cx - 3, head_y + 1), (cx + 3, head_y + 1), 3)
    if person.gear == 'goggles':
        pygame.draw.line(art, shade(person.jacket, 0.6), (cx - 36, head_y - 24), (cx + 36, head_y - 24), 7)
        for side in (-1, 1):
            pygame.draw.circle(art, (196, 156, 84), (cx + side * 15, head_y - 25), 13)
            pygame.draw.circle(art, (126, 176, 196), (cx + side * 15, head_y - 25), 9)
            pygame.draw.circle(art, (236, 246, 250), (cx + side * 15 - 3, head_y - 28), 3)
    if person.gear == 'headset':
        pygame.draw.arc(art, (44, 46, 52), (cx - 44, head_y - 58, 88, 96), 0.1, math.pi - 0.1, 7)
        for side in (-1, 1):
            pygame.draw.ellipse(art, (52, 54, 60), (cx + side * 40 - 9, head_y - 10, 18, 28))
        pygame.draw.line(art, (52, 54, 60), (cx - 38, head_y + 12), (cx - 14, head_y + 30), 4)
        pygame.draw.circle(art, (52, 54, 60), (cx - 12, head_y + 31), 5)

    # Crop in so the face fills the frame, then cut the circle.
    art = pygame.transform.smoothscale(art.subsurface((30, 26, 196, 196)), (s, s))
    mask = pygame.Surface((s, s), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (s // 2, s // 2), s // 2)
    art.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return art


class Radio:
    """Queued radio calls shown with a portrait and typed-out text."""

    SPEED = 55  # characters per second

    def __init__(self):
        self.queue = deque()
        self.current = None
        self.age = 0.0

    def say(self, speaker, message, hold=4.0, urgent=False):
        call = (speaker, message, hold + len(message) / self.SPEED)
        if urgent:
            self.queue.clear()
            self.current, self.age = call, 0.0
        elif not self.queue or self.queue[-1][1] != message:
            self.queue.append(call)

    def clear(self):
        self.queue.clear()
        self.current = None

    def update(self, dt):
        if self.current and self.age >= self.current[2]:
            self.current = None
        if self.current is None and self.queue:
            self.current, self.age = self.queue.popleft(), 0.0
        self.age += dt

    def draw(self, surface, fonts, bottom=696):
        if not self.current:
            return
        speaker, message, duration = self.current
        alpha = 255 * ui.fade_in_out(self.age, duration, 0.3)
        if alpha <= 1:
            return
        width = 560
        lines = ui.wrap(message, fonts.body, width - 112)
        height = 52 + len(lines) * 24
        box = pygame.Rect(640 - width // 2, bottom - height, width, height)
        layer = pygame.Surface(box.size, pygame.SRCALPHA)
        ui.panel(layer, (0, 0, *box.size))
        layer.blit(speaker.portrait(64), (16, 16))
        ui.label(layer, f'{speaker.role}  ·  {speaker.name}', fonts.tiny, (96, 16), ui.ACCENT)
        shown = int(self.age * self.SPEED)
        y = 38
        for line in lines:
            visible = line[:max(0, shown)]
            shown -= len(line) + 1
            if visible:
                ui.text(layer, visible, fonts.body, ui.TEXT, (96, y))
            y += 24
        layer.set_alpha(int(alpha))
        surface.blit(layer, box)
