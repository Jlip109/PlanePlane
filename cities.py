"""Cached batches of the supplied residential meshes, culled by distance."""

from pathlib import Path
import math

import numpy as np

import world
from camera import view_origin

DRAW_DISTANCE = world.CITY_RENDER_DISTANCE


class CityScene:
    def __init__(self):
        self.models = {}
        root = Path(__file__).parent/'assets'/'buildings'
        for key,info in world.BUILDING_CATALOG.items():
            with np.load(root/info['file'],allow_pickle=False) as data:
                self.models[key] = tuple(data[name].astype('f4') for name in ('positions','normals','colors'))
        self.batches = []
        for city,center in enumerate(world.CITY_CENTERS):
            meshes = [self.transform(building) for building in world.BUILDINGS if building['city']==city]
            mesh = tuple(np.concatenate([item[i] for item in meshes]).astype('f4') for i in range(3))
            self.batches.append((center,mesh))
        self.proxy_batches = []
        for city,center in enumerate(world.CITY_CENTERS):
            meshes = [self.proxy(building) for building in world.BUILDINGS if building['city']==city]
            mesh = tuple(np.concatenate([item[i] for item in meshes]).astype('f4') for i in range(3))
            self.proxy_batches.append((center,mesh))

    def transform(self, building):
        vertices,normals,colors = self.models[building['model']]
        c,s = math.cos(building['heading']),math.sin(building['heading'])
        rotation = np.array([[c,0,s],[0,1,0],[-s,0,c]],dtype='f4')
        offset = np.array([building['x'],building['y'],building['z']])
        return vertices@rotation.T+offset,normals@rotation.T,colors

    def proxy(self, building):
        x,y,z = building['x'],building['y'],building['z']
        w,h,d = building['width']/2,building['height'],building['depth']/2
        corners = np.array([[x-w,y,z-d],[x+w,y,z-d],[x+w,y,z+d],[x-w,y,z+d],
                            [x-w,y+h,z-d],[x+w,y+h,z-d],[x+w,y+h,z+d],[x-w,y+h,z+d]])
        faces = [(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7)]
        positions,normals,colors = [],[],[]
        for a,b,c,d in faces:
            triangle = corners[[a,b,c,a,c,d]]
            normal = np.cross(corners[b]-corners[a],corners[c]-corners[a])
            normal /= np.linalg.norm(normal)
            positions.extend(triangle)
            normals.extend([normal]*6)
            colors.extend([(.69,.64,.55)]*6)
        return tuple(np.asarray(values,dtype='f4') for values in (positions,normals,colors))

    def cpu_mesh(self, atmosphere):
        x,_,z = view_origin(atmosphere)
        visible = []
        for index,(center,mesh) in enumerate(self.batches):
            distance = math.hypot(center[0]-x,center[1]-z)
            if distance < DRAW_DISTANCE:
                visible.append(mesh if distance < 700 else self.proxy_batches[index][1])
        if not visible:
            return None
        positions,normals,colors = tuple(np.concatenate([mesh[i] for mesh in visible]) for i in range(3))
        sun = atmosphere.sun_direction
        daylight = float(np.clip((sun[1]+.12)/.47,0,1))
        light = .24+daylight*(.35+.41*np.maximum(0,normals@sun))
        return positions,normals,colors*light[:,None]
