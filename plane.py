"""Shared aircraft mesh and CPU rendering for the chase camera."""

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from camera import SCREEN_SCALE, view_angles, view_origin, project_polygon

PLANE_MODELS = {'classic': ('Original', 'plane_mesh.npz'), 'f15': ('F-15', 'f15_mesh.npz'),
                'odd': ('Plane Odd', 'odd_mesh.npz')}


def remote_aircraft_mesh(players, models, atmosphere):
    positions, normals, colors = [], [], []
    for player in players:
        center = np.array([player['x'],player['y'],player['z']])
        if np.linalg.norm(center-np.array(view_origin(atmosphere))) > 8000:
            continue
        model = models[player['model']]
        rotation = plane_rotation(SimpleNamespace(**player))
        normal = model.normals @ rotation.T
        light = .45 + .55 * np.maximum(0,normal @ atmosphere.sun_direction)
        positions.append(model.positions @ rotation.T + center)
        normals.append(normal)
        tint = np.array(player.get('color',(220,220,220)),dtype=float)/220
        colors.append(np.clip(model.base_colors*tint,0,1) * light[:,None])
    if not positions:
        return None
    return tuple(np.concatenate(values).astype('f4') for values in (positions,normals,colors))


def plane_rotation(atmosphere):
    heading, pitch, bank = atmosphere.heading, atmosphere.flight_pitch, atmosphere.bank
    sh, ch = math.sin(heading), math.cos(heading)
    sp, cp = math.sin(pitch), math.cos(pitch)
    sb, cb = math.sin(bank), math.cos(bank)
    yaw = np.array([[ch, 0, sh], [0, 1, 0], [-sh, 0, ch]])
    climb = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])
    roll = np.array([[cb, -sb, 0], [sb, cb, 0], [0, 0, 1]])
    return (yaw @ climb @ roll).astype(np.float32)


def shadow_inverse(atmosphere):
    rotation = plane_rotation(atmosphere)
    sun = atmosphere.sun_direction
    projection = rotation[[0,2]][:,[0,2]] - np.outer(
        sun[[0,2]] / max(float(sun[1]),0.08),rotation[1,[0,2]])
    if abs(float(np.linalg.det(projection))) < 0.02:
        return np.linalg.pinv(projection).astype('f4')
    return np.linalg.inv(projection).astype('f4')


class PlaneModel:
    def __init__(self, model_id='classic'):
        self.model_id = model_id
        path = Path(__file__).parent / 'assets' / PLANE_MODELS[model_id][1]
        with np.load(path, allow_pickle=False) as mesh:
            self.positions = mesh['positions'].astype(np.float32)
            self.normals = mesh['normals'].astype(np.float32)
            self.colors = mesh['colors'].astype(np.float32)
        self.base_colors = self.colors.copy()
        self.shadow_size = np.maximum(np.abs(self.positions[:,[0,2]]).max(axis=0) * 8, 1)
        self.shadow_levels = self.make_shadow()

    def set_color(self, color):
        self.colors = np.clip(self.base_colors*np.array(color,dtype='f4')/220,0,1).astype('f4')

    def make_shadow(self):
        import pygame
        surface = pygame.Surface((256,256))
        surface.fill((0,0,0))
        vertices = (self.positions[:,[0,2]] / self.shadow_size + .5) * 255
        for triangle in vertices.reshape(-1,3,2):
            pygame.draw.polygon(surface,(255,255,255),triangle.tolist())
        mask = pygame.surfarray.array3d(surface)[:,:,0].T.copy().astype(np.float32) / 255
        levels = [mask]
        while len(mask) > 1:
            mask = (mask[::2,::2] + mask[1::2,::2] + mask[::2,1::2] + mask[1::2,1::2]) / 4
            levels.append(mask)
        return levels

    def shadow_at(self, x, z, atmosphere):
        """Sample the same mip-blurred silhouette used by the GPU ground shader."""
        import world
        sun = atmosphere.sun_direction
        if sun[1] <= 0.08:
            return np.zeros(np.shape(x))
        height = np.maximum(0, atmosphere.altitude - world.ground_height_np(x,z))
        dx = x + sun[0] / sun[1] * height - atmosphere.position[0]
        dz = z + sun[2] / sun[1] * height - atmosphere.position[1]
        inverse = shadow_inverse(atmosphere)
        u = (dx*inverse[0,0]+dz*inverse[0,1]) / self.shadow_size[0] + .5
        v = (dx*inverse[1,0]+dz*inverse[1,1]) / self.shadow_size[1] + .5
        lod = np.clip(np.log2(1 + (0.12+height*.015)*256/self.shadow_size.min()),0,8)
        result = np.zeros(np.shape(x))
        for level, mask in enumerate(self.shadow_levels):
            weight = np.maximum(0,1-np.abs(lod-level))
            size = len(mask)
            valid = (u>=0)&(u<=1)&(v>=0)&(v<=1)&(weight>0)
            px = np.clip(u*size-.5,0,size-1)
            py = np.clip(v*size-.5,0,size-1)
            ix,iy = px.astype(int),py.astype(int)
            jx,jy = np.minimum(ix+1,size-1),np.minimum(iy+1,size-1)
            fx,fy = px-ix,py-iy
            sample = (mask[iy,ix]*(1-fx)+mask[iy,jx]*fx)*(1-fy)
            sample += (mask[jy,ix]*(1-fx)+mask[jy,jx]*fx)*fy
            result += sample * weight * valid
        return result * 0.55 / (1+height/700) * (1-atmosphere.cover*.65)

    def draw_world(self, surface, atmosphere, world_mesh=None):
        if not atmosphere.third_person and world_mesh is None:
            return
        import pygame

        rotation = plane_rotation(atmosphere)
        center = np.array([atmosphere.position[0], atmosphere.altitude, atmosphere.position[1]])
        vertices = self.positions @ rotation.T + center
        normals = self.normals @ rotation.T
        base_colors = self.colors
        unlit = np.zeros(len(vertices))
        if not atmosphere.third_person:
            vertices, normals, base_colors = (np.empty((0,3)) for _ in range(3))
            unlit = np.empty(0)
        if world_mesh is not None:
            gate_vertices, gate_normals, gate_colors = world_mesh
            vertices = np.concatenate((vertices, gate_vertices))
            normals = np.concatenate((normals, gate_normals))
            base_colors = np.concatenate((base_colors, gate_colors))
            unlit = np.concatenate((unlit, np.ones(len(gate_vertices))))
        world_vertices = vertices.reshape(-1,3,3)
        vertices = vertices - np.array(view_origin(atmosphere))
        heading, pitch = view_angles(atmosphere)
        sh, ch, sp, cp = math.sin(heading), math.cos(heading), math.sin(pitch), math.cos(pitch)
        x, y, z = vertices.T
        depth = x * sh * cp + y * sp + z * ch * cp
        side = x * ch - z * sh
        up = -x * sh * sp + y * cp - z * ch * sp
        width, height = surface.get_size()
        pixels = np.stack((width / 2 + side / np.maximum(depth, 1) * height * SCREEN_SCALE,
                           height / 2 - up / np.maximum(depth, 1) * height * SCREEN_SCALE), axis=1)
        triangles = pixels.reshape(-1, 3, 2)
        depths = depth.reshape(-1, 3)
        normals = normals.reshape(-1, 3, 3).mean(axis=1)
        daylight = np.clip((float(atmosphere.sun_direction[1]) + 0.12) / 0.47, 0, 1)
        light = 0.24 + daylight * (0.35 + 0.41 * np.maximum(0, normals @ atmosphere.sun_direction))
        emissive = unlit.reshape(-1,3).mean(axis=1)
        light = light * (1-emissive) + emissive
        colors = base_colors.reshape(-1, 3, 3).mean(axis=1) * light[:, None]
        colors = np.clip(colors * 255, 0, 255).astype(np.uint8)
        for index in np.argsort(depths.mean(axis=1))[::-1]:
            points = triangles[index].tolist()
            if depths[index].min() <= 1:
                points = project_polygon(atmosphere, world_vertices[index], (width,height))
            if len(points) >= 3:
                pygame.draw.polygon(surface, tuple(int(channel) for channel in colors[index]), points, 1 if atmosphere.wireframe else 0)
