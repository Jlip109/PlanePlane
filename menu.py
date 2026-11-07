"""Title, pilot select, controls, pause and results screens."""

import pygame

import characters
import ui

TITLE_ITEMS = [('free', 'Free Flight'), ('rings', 'Ring Run'), ('courier', 'Sky Courier'),
               ('pilot', 'Choose Pilot'), ('controls', 'Controls'), ('quit', 'Quit')]
PAUSE_ITEMS = [('resume', 'Resume'), ('restart', 'Restart'), ('title', 'Main Menu'), ('quit', 'Quit Game')]
CONFIRM = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
UP = (pygame.K_UP, pygame.K_w)
DOWN = (pygame.K_DOWN, pygame.K_s)
LEFT = (pygame.K_LEFT, pygame.K_a)
RIGHT = (pygame.K_RIGHT, pygame.K_d)


class Menu:
    def __init__(self, game, fonts):
        self.game = game
        self.fonts = fonts
        self.title_index = 0
        self.pause_index = 0
        self.pilot_choice = game.pilot_index
        self.hit_areas = []
        self.age = 0.0

    def update(self, dt):
        self.age += dt

    def to_hud(self, pos):
        scale, ox, oy = self.game.hud_transform
        return (pos[0] - ox) / scale, (pos[1] - oy) / scale

    # ------------------------------------------------------------------ input

    def handle_event(self, event, state):
        """Returns an action string or None."""
        if event.type == pygame.MOUSEMOTION:
            for index, rect, kind in self.hit_areas:
                if rect.collidepoint(self.to_hud(event.pos)):
                    self.select(kind, index)
            return None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for index, rect, kind in self.hit_areas:
                if rect.collidepoint(self.to_hud(event.pos)):
                    self.select(kind, index)
                    return self.confirm(state)
            return None
        if event.type != pygame.KEYDOWN:
            return None
        key = event.key
        if state == 'title':
            if key in UP or key in DOWN:
                self.title_index = (self.title_index + (1 if key in DOWN else -1)) % len(TITLE_ITEMS)
                self.game.sound('tick')
            elif key in CONFIRM:
                return self.confirm(state)
            elif key == pygame.K_ESCAPE:
                return 'quit'
        elif state == 'pilots':
            if key in LEFT or key in RIGHT:
                self.pilot_choice = (self.pilot_choice + (1 if key in RIGHT else -1)) % len(characters.PILOTS)
                self.game.sound('tick')
            elif key in CONFIRM:
                return self.confirm(state)
            elif key == pygame.K_ESCAPE:
                self.pilot_choice = self.game.pilot_index
                return 'title'
        elif state == 'controls':
            if key in CONFIRM or key in (pygame.K_ESCAPE, pygame.K_h):
                return 'title'
        elif state == 'paused':
            if key in UP or key in DOWN:
                self.pause_index = (self.pause_index + (1 if key in DOWN else -1)) % len(PAUSE_ITEMS)
                self.game.sound('tick')
            elif key in CONFIRM:
                return self.confirm(state)
            elif key == pygame.K_ESCAPE:
                return 'resume'
        elif state == 'results':
            if key in CONFIRM:
                return 'restart'
            if key == pygame.K_ESCAPE:
                return 'title'
        return None

    def select(self, kind, index):
        current = {'title': self.title_index, 'pilot': self.pilot_choice, 'pause': self.pause_index}.get(kind)
        if current != index:
            self.game.sound('tick')
        if kind == 'title':
            self.title_index = index
        elif kind == 'pilot':
            self.pilot_choice = index
        elif kind == 'pause':
            self.pause_index = index

    def confirm(self, state):
        self.game.sound('select')
        if state == 'title':
            return TITLE_ITEMS[self.title_index][0]
        if state == 'pilots':
            return 'pilot_chosen'
        if state == 'paused':
            return PAUSE_ITEMS[self.pause_index][0]
        if state == 'results':
            return 'restart'
        return None

    # ------------------------------------------------------------------ drawing

    def draw(self, surface, state):
        self.hit_areas = []
        if state == 'title':
            self.draw_title(surface)
        elif state == 'pilots':
            self.draw_pilots(surface)
        elif state == 'controls':
            self.game.hud.draw_controls(surface)
        elif state == 'paused':
            self.draw_pause(surface)
        elif state == 'results':
            self.draw_results(surface)

    def draw_title(self, surface):
        fonts = self.fonts
        intro = ui.ease(self.age / 1.2)
        x = 96
        ui.label(surface, 'HackRPI 2026  ·  In the Clouds', fonts.tiny, (x, 112), ui.ACCENT, alpha=255 * intro)
        ui.text(surface, 'PLANE²', fonts.display, ui.TEXT, (x - 4, 128), tracking=6, alpha=255 * intro)
        ui.text(surface, 'A flight through a living sky.', fonts.body, ui.MUTED, (x, 236), alpha=255 * intro)
        y = 300
        for index, (key, name) in enumerate(TITLE_ITEMS):
            selected = index == self.title_index
            ui.text(surface, name, fonts.h2, ui.TEXT if selected else ui.MUTED, (x, y))
            if selected:
                pygame.draw.rect(surface, ui.ACCENT, (x - 20, y + 5, 4, 22), border_radius=2)
            self.hit_areas.append((index, pygame.Rect(x - 24, y - 6, 300, 40), 'title'))
            y += 44
        self.draw_title_card(surface, TITLE_ITEMS[self.title_index][0])
        ui.hint_row(surface, [('↑ ↓', 'Select'), ('ENTER', 'Start'), ('ESC', 'Quit')], fonts, (x, 690))

    def draw_title_card(self, surface, key):
        fonts = self.fonts
        box = pygame.Rect(744, 300, 440, 272)
        pilot = characters.PILOTS[self.game.pilot_index]
        if key in self.game.modes:
            mode = self.game.modes[key]
            ui.panel(surface, box)
            ui.label(surface, 'Mode', fonts.tiny, (box.left + 32, box.top + 28), ui.ACCENT)
            ui.text(surface, mode.name, fonts.h1, ui.TEXT, (box.left + 32, box.top + 46))
            ui.paragraph(surface, mode.description, fonts.body, ui.MUTED, (box.left + 32, box.top + 104), box.width - 64)
            ui.text(surface, mode.best_text(), fonts.small, ui.TEXT, (box.left + 32, box.bottom - 30), 'bottomleft')
            surface.blit(pilot.portrait(40), (box.right - 72, box.bottom - 60))
        elif key == 'pilot':
            ui.panel(surface, box)
            surface.blit(pilot.portrait(112), (box.left + 32, box.top + 32))
            ui.label(surface, pilot.role, fonts.tiny, (box.left + 164, box.top + 44), ui.ACCENT)
            ui.text(surface, pilot.name, fonts.h2, ui.TEXT, (box.left + 164, box.top + 62))
            ui.text(surface, pilot.perk, fonts.small, ui.MUTED, (box.left + 164, box.top + 96))
            ui.paragraph(surface, f'“{pilot.quote}”', fonts.body, ui.MUTED, (box.left + 32, box.top + 172),
                         box.width - 64)
        elif key == 'controls':
            ui.panel(surface, box)
            ui.label(surface, 'Quick start', fonts.tiny, (box.left + 32, box.top + 28), ui.ACCENT)
            rows = [('W  S', 'Climb and descend'), ('A  D', 'Turn'), ('SPACE', 'Boost'), ('H', 'All controls in flight')]
            y = box.top + 64
            for cap, action in rows:
                rect = ui.key_cap(surface, cap, fonts, (box.left + 32, y))
                ui.text(surface, action, fonts.body, ui.MUTED, (box.left + 140, rect.centery), 'midleft')
                y += 44

    def draw_pilots(self, surface):
        fonts = self.fonts
        ui.label(surface, 'Choose your pilot', fonts.tiny, (640, 92), ui.ACCENT, 'midtop')
        ui.text(surface, 'Who’s flying today?', fonts.h1, ui.TEXT, (640, 112), 'midtop')
        card_w, gap = 236, 24
        left = 640 - (card_w * 4 + gap * 3) // 2
        for index, pilot in enumerate(characters.PILOTS):
            selected = index == self.pilot_choice
            box = pygame.Rect(left + index * (card_w + gap), 196 - (8 if selected else 0), card_w, 330)
            ui.panel(surface, box, ui.PANEL if selected else ui.PANEL_SOFT,
                     border=(*ui.ACCENT, 255) if selected else ui.LINE)
            surface.blit(pilot.portrait(112), (box.centerx - 56, box.top + 24))
            ui.label(surface, pilot.role, fonts.tiny, (box.centerx, box.top + 150), ui.ACCENT, 'midtop')
            ui.text(surface, pilot.name, fonts.h2, ui.TEXT if selected else ui.MUTED, (box.centerx, box.top + 168), 'midtop')
            y = box.top + 218
            for stat, value in (('Speed', pilot.speed), ('Handling', pilot.handling), ('Boost', pilot.boost)):
                ui.label(surface, stat, fonts.tiny, (box.left + 24, y))
                ui.bar(surface, (box.left + 24, y + 18, box.width - 48, 4), (value - 0.6) / 0.9,
                       ui.ACCENT if selected else ui.MUTED)
                y += 34
            self.hit_areas.append((index, box, 'pilot'))
        pilot = characters.PILOTS[self.pilot_choice]
        ui.text(surface, f'“{pilot.quote}”', fonts.body, ui.MUTED, (640, 560), 'midtop')
        ui.hint_row(surface, [('← →', 'Choose'), ('ENTER', 'Confirm'), ('ESC', 'Back')], fonts, (640, 690),
                    'midbottom')

    def draw_pause(self, surface):
        fonts = self.fonts
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((4, 8, 14, 130))
        surface.blit(dim, (0, 0))
        box = pygame.Rect(640 - 180, 200, 360, 300)
        ui.panel(surface, box, (9, 18, 27, 230))
        ui.label(surface, 'Paused', fonts.tiny, (box.left + 36, box.top + 30), ui.ACCENT)
        y = box.top + 64
        for index, (key, name) in enumerate(PAUSE_ITEMS):
            selected = index == self.pause_index
            ui.text(surface, name, fonts.h2, ui.TEXT if selected else ui.MUTED, (box.left + 36, y))
            if selected:
                pygame.draw.rect(surface, ui.ACCENT, (box.left + 20, y + 5, 4, 22), border_radius=2)
            self.hit_areas.append((index, pygame.Rect(box.left + 16, y - 6, box.width - 32, 40), 'pause'))
            y += 48

    def draw_results(self, surface):
        summary = self.game.mode.summary if self.game.mode else None
        if not summary:
            return
        fonts = self.fonts
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((4, 8, 14, 110))
        surface.blit(dim, (0, 0))
        box = pygame.Rect(640 - 240, 170, 480, 360)
        ui.panel(surface, box, (9, 18, 27, 232))
        ui.label(surface, summary['title'], fonts.tiny, (box.left + 40, box.top + 34), ui.ACCENT)
        ui.text(surface, f'{summary["score"]:,}', fonts.display, ui.TEXT, (box.left + 36, box.top + 52))
        if summary['record']:
            ui.label(surface, 'New personal best', fonts.tiny, (box.right - 40, box.top + 34), ui.GOOD, 'topright')
        y = box.top + 170
        for name, value in summary['lines']:
            ui.text(surface, name, fonts.body, ui.MUTED, (box.left + 40, y))
            ui.text(surface, value, fonts.mono, ui.TEXT, (box.right - 40, y), 'topright')
            pygame.draw.line(surface, (255, 255, 255, 30), (box.left + 40, y + 34), (box.right - 40, y + 34))
            y += 46
        ui.hint_row(surface, [('ENTER', 'Fly again'), ('ESC', 'Main menu')], fonts, (640, box.bottom - 24), 'midbottom')
