"""Shared camera math so the CPU renderer, GPU renderer and overlays agree."""

import math

# Pixels per unit of screen-space ray offset, as a fraction of window height.
SCREEN_SCALE = 0.924444


def terrain_height(x, z):
    return 100 + 130 * math.sin(x / 1700) * math.cos(z / 1500)


def view_angles(atmosphere):
    t = atmosphere.elapsed
    shake = math.sin(t * 9) * atmosphere.wind * atmosphere.cover * 0.00012 * (1 + atmosphere.risk / 100)
    shake += atmosphere.storm * 0.006 * math.sin(t * 17) * math.sin(t * 5.3)
    return atmosphere.heading + atmosphere.look_yaw, atmosphere.pitch + shake


def project(atmosphere, point, size):
    """World (x, altitude, z) -> window pixel (x, y, depth), or None if behind the camera."""
    heading, pitch = view_angles(atmosphere)
    width, height = size
    rx = point[0] - atmosphere.position[0]
    ry = point[1] - atmosphere.altitude
    rz = point[2] - atmosphere.position[1]
    sh, ch, sp, cp = math.sin(heading), math.cos(heading), math.sin(pitch), math.cos(pitch)
    depth = rx * sh * cp + ry * sp + rz * ch * cp
    if depth < 1:
        return None
    sx = (rx * ch - rz * sh) / depth
    sy = (-rx * sh * sp + ry * cp - rz * ch * sp) / depth
    k = height * SCREEN_SCALE
    return width / 2 + sx * k, height / 2 - sy * k, depth
