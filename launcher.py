"""Username, RGB and server selection before any network connection is opened."""
import pygame

from plane import PLANE_MODELS
from scores import Scores

DEFAULT_SERVER = 'wss://planeplane.onrender.com'


def rgb(text):
    try:
        values = tuple(int(v.strip()) for v in text.split(','))
    except ValueError:
        raise ValueError('RGB needs three integers, e.g. 255, 0, 0') from None
    if len(values)!=3 or any(not 0<=v<=255 for v in values):
        raise ValueError('RGB values must each be 0 to 255')
    return values


class Profile:
    def __init__(self, args):
        self.args = args
        self.scores = Scores()
        self.values = [args.name or self.scores.get('username',''),args.color or self.scores.get('rgb','220, 220, 220'),
                       args.connect or self.scores.get('server',DEFAULT_SERVER)]
        self.fields = [pygame.Rect(70,125+i*95,660,44) for i in range(3)]
        self.buttons = [(pygame.Rect(70,490,320,48),'create','CREATE LOBBY'),
                        (pygame.Rect(410,490,320,48),'join','JOIN LOBBY'),
                        (pygame.Rect(70,550,320,42),'free','Offline Free Roam'),
                        (pygame.Rect(410,550,320,42),'practice','Offline Practice Rings')]
        self.model = args.plane or self.scores.get('plane_model','classic')
        if self.model not in PLANE_MODELS:
            self.model = 'classic'
        self.focus = 0
        self.error = ''

    def select(self, mode):
        intent=mode if mode in ('create','join') else 'join'
        if mode in ('create','join'):mode='ffa'
        name=self.values[0].strip()
        if not name or len(name)>24:
            self.error='Choose a username from 1 to 24 characters.'
            return False
        try:
            color=rgb(self.values[1])
        except ValueError as error:
            self.error=str(error)
            return False
        self.args.name=name
        self.args.color=','.join(str(v) for v in color)
        self.args.plane=self.model
        self.args.mode=mode
        if mode=='ffa':
            self.args.lobby_action='browse'
            self.args.lobby_intent=intent
        self.args.connect=self.values[2].strip() if mode=='ffa' else None
        if mode=='ffa' and not self.args.connect:
            self.error='Enter the multiplayer server address.'
            return False
        self.scores.data.update(username=name,rgb=self.args.color,server=self.values[2],plane_model=self.model)
        self.scores.save()
        return True

    def handle(self,event):
        if event.type==pygame.TEXTINPUT:
            self.values[self.focus]+=event.text[:200-len(self.values[self.focus])]
        if event.type==pygame.KEYDOWN:
            if event.key==pygame.K_BACKSPACE:
                self.values[self.focus]=self.values[self.focus][:-1]
            if event.key==pygame.K_TAB:
                self.focus=(self.focus+1)%3
            if event.key==pygame.K_RETURN and self.select('join'):
                return True
            if event.key==pygame.K_a and event.mod&pygame.KMOD_CTRL:
                self.values[self.focus]=''
        if event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
            for i,rect in enumerate(self.fields):
                if rect.collidepoint(event.pos):self.focus=i
            if pygame.Rect(70,415,660,44).collidepoint(event.pos):
                names=list(PLANE_MODELS)
                self.model=names[(names.index(self.model)+1)%len(names)]
            for rect,mode,_ in self.buttons:
                if rect.collidepoint(event.pos) and self.select(mode):return True
        return False

    def draw(self,screen):
        screen.fill((10,18,28))
        font=pygame.font.SysFont('Segoe UI',22)
        small=pygame.font.SysFont('Segoe UI',17)
        def text(s,pos,color=(225,235,243),f=font):screen.blit(f.render(s,True,color),pos)
        text('PLANE² · Join the skies',(70,35))
        for i,(rect,label) in enumerate(zip(self.fields,('Username','Plane RGB · 0–255 per channel','Online server'))):
            text(label,(rect.x,rect.y-27),f=small)
            pygame.draw.rect(screen,(35,51,66),rect,border_radius=6)
            pygame.draw.rect(screen,(244,179,78) if i==self.focus else (65,85,100),rect,2,border_radius=6)
            text(self.values[i][-55:],(rect.x+12,rect.y+7))
        text('Aircraft: '+PLANE_MODELS[self.model][0]+'  ·  Click to change',(70,421))
        for rect,_,label in self.buttons:
            pygame.draw.rect(screen,(45,94,124),rect,border_radius=6)
            text(label,(rect.x+15,rect.y+8),f=small)
        text(self.error or 'Three lobbies · 24 racers each · Solo practice does not save scores.',(70,615),(244,179,78),small)


def launch(args):
    pygame.display.init()
    pygame.font.init()
    screen=pygame.display.set_mode((800,670))
    pygame.display.set_caption('Plane² · Pilot sign-in')
    profile=Profile(args)
    pygame.key.start_text_input()
    clock=pygame.time.Clock()
    try:
        while True:
            for event in pygame.event.get():
                if event.type==pygame.QUIT or event.type==pygame.KEYDOWN and event.key==pygame.K_ESCAPE:return False
                if profile.handle(event):return True
            profile.draw(screen)
            pygame.display.flip()
            clock.tick(60)
    finally:
        pygame.key.stop_text_input()
        pygame.display.quit()
