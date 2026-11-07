"""Free Roam, Ring Mode, pause and results screens."""

import pygame

import ui

TITLE_ITEMS = [('free', 'Free Roam'), ('rings', 'Ring Mode'), ('aircraft', 'Aircraft'), ('quit', 'Quit')]
VISIBLE_TITLE_ITEMS = TITLE_ITEMS
ONLINE_TITLE_ITEMS = TITLE_ITEMS[:2] + [('race', 'Ring Race')] + TITLE_ITEMS[2:]
PAUSE_ITEMS = [('resume', 'Resume'), ('restart', 'Restart'), ('title', 'Main Menu'),
               ('frame_limit', 'Frame cap'), ('quit', 'Quit Game')]
CONFIRM = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)
UP = (pygame.K_UP, pygame.K_w)
DOWN = (pygame.K_DOWN, pygame.K_s)


class Menu:
    def __init__(self, game, fonts):
        self.game = game
        self.fonts = fonts
        self.title_index = 0
        self.pause_index = 0
        self.hit_areas = []
        self.slider_areas = []
        self.dragging_slider = None
        self.age = 0.0

    def update(self, dt):
        self.age += dt

    def title_items(self):
        return ONLINE_TITLE_ITEMS if 'race' in self.game.modes else VISIBLE_TITLE_ITEMS

    def to_hud(self, pos):
        scale, ox, oy = self.game.hud_transform
        return (pos[0] - ox) / scale, (pos[1] - oy) / scale

    # ------------------------------------------------------------------ input

    def handle_event(self, event, state):
        """Returns an action string or None."""
        if state == 'paused':
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.dragging_slider = None
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                point = self.to_hud(event.pos)
                for key,rect in self.slider_areas:
                    if rect.inflate(12,24).collidepoint(point):
                        self.dragging_slider = key
                        self.move_slider(key,point[0])
                        return None
            if event.type == pygame.MOUSEMOTION and self.dragging_slider:
                if event.buttons[0]:
                    self.move_slider(self.dragging_slider,self.to_hud(event.pos)[0])
                    return None
                self.dragging_slider = None
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
        if state == 'title' and key in (pygame.K_LEFT,pygame.K_RIGHT):
            if self.title_items()[self.title_index][0] == 'aircraft':
                return 'aircraft'
        if state == 'paused' and key in (pygame.K_LEFT, pygame.K_RIGHT):
            if PAUSE_ITEMS[self.pause_index][0] == 'frame_limit':
                return 'fps_down' if key == pygame.K_LEFT else 'fps_up'
        if state == 'title':
            if key in UP or key in DOWN:
                self.title_index = (self.title_index + (1 if key in DOWN else -1)) % len(self.title_items())
                self.game.sound('tick')
            elif key in CONFIRM:
                return self.confirm(state)
            elif key == pygame.K_ESCAPE:
                return 'quit'
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
        current = {'title': self.title_index, 'pause': self.pause_index}.get(kind)
        if current != index:
            self.game.sound('tick')
        if kind == 'title':
            self.title_index = index
        elif kind == 'pause':
            self.pause_index = index

    def confirm(self, state):
        self.game.sound('select')
        if state == 'title':
            return self.title_items()[self.title_index][0]
        if state == 'paused':
            return PAUSE_ITEMS[self.pause_index][0]
        if state == 'results':
            return 'restart'
        return None

    # ------------------------------------------------------------------ drawing

    def draw(self, surface, state):
        self.hit_areas = []
        self.slider_areas = []
        if state == 'title':
            self.draw_title(surface)
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
        for index, (key, name) in enumerate(self.title_items()):
            if key == 'aircraft':
                from plane import PLANE_MODELS
                name += '  ' + PLANE_MODELS[self.game.atmosphere.plane_id][0]
            selected = index == self.title_index
            ui.text(surface, name, fonts.h2, ui.TEXT if selected else ui.MUTED, (x, y))
            if selected:
                pygame.draw.rect(surface, ui.ACCENT, (x - 20, y + 5, 4, 22), border_radius=2)
            self.hit_areas.append((index, pygame.Rect(x - 24, y - 6, 300, 40), 'title'))
            y += 44
        self.draw_title_card(surface, self.title_items()[self.title_index][0])
        ui.hint_row(surface, [('↑ ↓', 'Select'), ('ENTER', 'Start'), ('ESC', 'Quit')], fonts, (x, 690))

    def draw_title_card(self, surface, key):
        if key not in self.game.modes:
            return
        mode = self.game.modes[key]
        box = pygame.Rect(744, 300, 440, 230)
        ui.panel(surface, box)
        ui.text(surface, mode.name, self.fonts.h1, ui.TEXT, (box.left + 32, box.top + 32))
        ui.paragraph(surface, mode.description, self.fonts.body, ui.MUTED,
                     (box.left + 32, box.top + 96), box.width - 64)
        if mode.best_text():
            ui.text(surface, mode.best_text(), self.fonts.small, ui.TEXT, (box.left + 32, box.bottom - 30), 'bottomleft')

    def draw_pause(self, surface):
        fonts = self.fonts
        dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        dim.fill((4, 8, 14, 130))
        surface.blit(dim, (0, 0))
        box = pygame.Rect(260,115,760,490)
        ui.panel(surface, box, (9, 18, 27, 230))
        ui.label(surface, 'Paused', fonts.tiny, (box.left + 36, box.top + 30), ui.ACCENT)
        y = box.top + 64
        for index, (key, name) in enumerate(PAUSE_ITEMS):
            selected = index == self.pause_index
            if key == 'frame_limit':
                name += f'  {self.game.frame_limit}' if self.game.frame_limit else '  Uncapped'
            ui.text(surface, name, fonts.h2, ui.TEXT if selected else ui.MUTED, (box.left + 36, y))
            if selected:
                pygame.draw.rect(surface, ui.ACCENT, (box.left + 20, y + 5, 4, 22), border_radius=2)
            self.hit_areas.append((index, pygame.Rect(box.left + 16, y - 6, 300, 40), 'pause'))
            y += 48
        ui.label(surface,'Flight tuning',fonts.tiny,(640,145),ui.ACCENT)
        tuning = self.game.atmosphere.flight_tuning
        for index,(key,label) in enumerate((('climb','Climb · W/S + mouse'),('acceleration','Acceleration'),('steering','Steering · A/D + mouse'))):
            y = 193+index*105
            ui.text(surface,label,fonts.body,ui.TEXT,(640,y))
            ui.text(surface,str(tuning[key]),fonts.mono,ui.ACCENT,(980,y),'topright')
            rect = pygame.Rect(640,y+40,340,8)
            pygame.draw.rect(surface,(55,68,80),rect,border_radius=4)
            x = rect.left+round(rect.width*tuning[key]/100)
            pygame.draw.rect(surface,ui.ACCENT,(rect.left,rect.top,max(1,x-rect.left),rect.height),border_radius=4)
            pygame.draw.circle(surface,ui.TEXT,(x,rect.centery),9)
            self.slider_areas.append((key,rect))
        values = f"V{tuning['climb']}  A{tuning['acceleration']}  S{tuning['steering']}"
        ui.text(surface,values,fonts.mono,ui.ACCENT,(640,535))
        ui.text(surface,'Drag sliders. Higher values respond faster.',fonts.small,ui.MUTED,(640,572))

    def move_slider(self, key, x):
        rect = next(rect for name,rect in self.slider_areas if name == key)
        self.game.set_tuning(key,(x-rect.left)/rect.width*100)

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
