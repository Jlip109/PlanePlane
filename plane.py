"""Shared aircraft mesh and CPU rendering for the chase camera."""

import math
from pathlib import Path

import numpy as np

from camera import SCREEN_SCALE, view_angles, view_origin


def plane_rotation(atmosphere):
    heading, pitch, bank = atmosphere.heading, atmosphere.flight_pitch, atmosphere.bank
    sh, ch = math.sin(heading), math.cos(heading)
    sp, cp = math.sin(pitch), math.cos(pitch)
    sb, cb = math.sin(bank), math.cos(bank)
    yaw = np.array([[ch, 0, sh], [0, 1, 0], [-sh, 0, ch]])
    climb = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])
    roll = np.array([[cb, -sb, 0], [sb, cb, 0], [0, 0, 1]])
    return (yaw @ climb @ roll).astype(np.float32)


class PlaneModel:
    def __init__(self):
        path = Path(__file__).parent / 'assets' / 'plane_mesh.npz'
        with np.load(path, allow_pickle=False) as mesh:
            self.positions = mesh['positions'].astype(np.float32)
            self.normals = mesh['normals'].astype(np.float32)
            self.colors = mesh['colors'].astype(np.float32)

    def draw_world(self, surface, atmosphere):
        if not atmosphere.third_person:
            return
        import pygame

        rotation = plane_rotation(atmosphere)
        center = np.array([atmosphere.position[0], atmosphere.altitude, atmosphere.position[1]])
        vertices = self.positions @ rotation.T + center - np.array(view_origin(atmosphere))
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
        normals = (self.normals @ rotation.T).reshape(-1, 3, 3).mean(axis=1)
        daylight = np.clip((float(atmosphere.sun_direction[1]) + 0.12) / 0.47, 0, 1)
        light = 0.24 + daylight * (0.35 + 0.41 * np.maximum(0, normals @ atmosphere.sun_direction))
        colors = self.colors.reshape(-1, 3, 3).mean(axis=1) * light[:, None]
        colors = np.clip(colors * 255, 0, 255).astype(np.uint8)
        for index in np.argsort(depths.mean(axis=1))[::-1]:
            if depths[index].min() <= 1:
                continue
            pygame.draw.polygon(surface, tuple(int(channel) for channel in colors[index]), triangles[index].tolist())
