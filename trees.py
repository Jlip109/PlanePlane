"""Distance-culled tree sprites on dry green land, or snow trees below 32 F."""
import math
from pathlib import Path

import numpy as np
import pygame

import world
from camera import basis,matrices,project,view_angles,view_origin,SCREEN_SCALE


def tree_sites(atmosphere):
    x,z=atmosphere.position
    cold=atmosphere.temperature_f is not None and atmosphere.temperature_f<32
    sites=[]
    for i in range(math.floor(x/160)-10,math.floor(x/160)+11):
        for j in range(math.floor(z/160)-10,math.floor(z/160)+11):
            px=(i+.15+.7*world.hash01(i,j,220))*160
            pz=(j+.15+.7*world.hash01(i,j,221))*160
            if math.hypot(px-x,pz-z)>1500:continue
            if abs(px)<104 and any(abs(pz-center)<914 for center in world.RUNWAY_CENTERS):continue
            if any(world.raw_terrain(px+dx,pz+dz)<=world.WATER for dx,dz in ((0,0),(-8,-8),(8,8),(-8,8),(8,-8))):continue
            if any(abs(px-b['x'])<b['width']/2+12 and abs(pz-b['z'])<b['depth']/2+12 for b in world.BUILDINGS):continue
            color,_=world.land_color_np(px,pz,0,atmosphere.ground_mode,0,atmosphere.temperature_f)
            if not cold and not(color[1]>color[0]*1.03 and color[1]>color[2]*1.1):continue
            species=2 if cold else int(world.hash01(i,j,222)*2)
            height=18+world.hash01(i,j,223)*10
            sites.append((px,world.ground_height(px,pz),pz,species,height))
    return sites


class Trees:
    def __init__(self):
        self.sprites=[]
        for index,name in enumerate(('Tree.png','Tree2.png','Tree3.png')):
            sprite=pygame.image.load(str(Path(__file__).parent/'assets'/name)).convert_alpha()
            rgb=pygame.surfarray.array3d(sprite)
            alpha=pygame.surfarray.pixels_alpha(sprite)
            background=np.max(rgb,axis=2)<25
            if index<2:background|=np.min(rgb,axis=2)>235
            alpha[background]=0
            del alpha
            self.sprites.append(sprite)
        self.cache_key=None
        self.sites=[]
        self.resources=[]

    def update(self,atmosphere):
        key=(int(atmosphere.position[0]//160),int(atmosphere.position[1]//160),atmosphere.ground_mode,
             world.temperature_column(atmosphere.temperature_f) if atmosphere.temperature_f is not None else None,
             atmosphere.temperature_f is not None and atmosphere.temperature_f<32)
        if key!=self.cache_key:
            self.cache_key=key
            self.sites=tree_sites(atmosphere)

    def init_gpu(self,context):
        import moderngl
        self.program=context.program(vertex_shader='''#version 330
        uniform mat4 view_projection; in vec3 position; in vec2 uv; out vec2 texcoord;
        void main(){texcoord=uv;gl_Position=view_projection*vec4(position,1.0);}''',fragment_shader='''#version 330
        uniform sampler2D sprites; uniform float light; in vec2 texcoord; out vec4 color;
        void main(){vec4 s=texture(sprites,texcoord);if(s.a<0.45)discard;color=vec4(s.rgb*light,1.0);}''')
        atlas=pygame.Surface((384,128),pygame.SRCALPHA)
        for i,sprite in enumerate(self.sprites):atlas.blit(pygame.transform.smoothscale(sprite,(128,128)),(i*128,0))
        self.texture=context.texture(atlas.get_size(),4,pygame.image.tobytes(atlas,'RGBA',True))
        self.texture.build_mipmaps()
        self.texture.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
        self.texture.repeat_x=self.texture.repeat_y=False
        self.buffer=context.buffer(reserve=441*6*5*4,dynamic=True)
        self.vao=context.vertex_array(self.program,[(self.buffer,'3f 2f','position','uv')])
        self.resources=[self.vao,self.buffer,self.texture,self.program]

    def draw_gpu(self,renderer,atmosphere,size):
        import moderngl
        if not self.resources:self.init_gpu(renderer.context)
        self.update(atmosphere)
        right=np.array(basis(*view_angles(atmosphere))[0])
        rows=[]
        for x,y,z,species,height in self.sites:
            center=np.array([x,y,z])
            width=height*(.55 if species==1 else .85)
            corners=np.array([center-right*width/2,center+right*width/2,
                              center+right*width/2+[0,height,0],center-right*width/2+[0,height,0]])
            u0,u1=(species+.005)/3,(species+.995)/3
            uv=np.array([[u0,0],[u1,0],[u1,1],[u0,1]])
            rows.append(np.concatenate((corners,uv),axis=1)[[0,1,2,0,2,3]])
        if not rows:return
        data=np.concatenate(rows).astype('f4')
        self.buffer.write(data.tobytes())
        view,projection=matrices(atmosphere,size)
        self.program['view_projection'].write((projection@view).astype('f4').tobytes(order='F'))
        self.program['sprites']=5
        self.program['light']=.4+.6*max(0,float(atmosphere.sun_direction[1]))
        self.texture.use(5)
        renderer.context.disable(moderngl.BLEND)
        renderer.context.enable(moderngl.DEPTH_TEST)
        self.vao.render(moderngl.TRIANGLES,vertices=len(data))
        renderer.context.disable(moderngl.DEPTH_TEST)

    def draw_cpu(self,surface,atmosphere):
        self.update(atmosphere)
        eye=np.array(view_origin(atmosphere))
        for x,y,z,species,height in sorted(self.sites,key=lambda s:math.dist(eye,s[:3]),reverse=True):
            projected=project(atmosphere,(x,y,z),surface.get_size())
            if projected is None:continue
            px,py,depth=projected
            if depth<10 or depth>1500:continue
            obstructed=False
            for fraction in (.2,.4,.6,.8):
                p=eye*(1-fraction)+np.array([x,y+height/2,z])*fraction
                if p[1]<world.obstacle_height(p[0],p[2]):obstructed=True;break
            if obstructed:continue
            h=round(height/depth*surface.get_height()*SCREEN_SCALE)
            w=round(h*(.55 if species==1 else .85))
            if h<2 or w<1 or px+w<0 or px-w>surface.get_width():continue
            sprite=pygame.transform.smoothscale(self.sprites[species],(min(w,1000),min(h,1500)))
            surface.blit(sprite,(px-w/2,py-h))

    def close(self):
        for resource in self.resources:resource.release()
