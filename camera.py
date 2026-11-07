"""Shared camera math so the CPU renderer, GPU renderer and overlays agree."""

import math

import world

# Pixels per unit of screen-space ray offset, as a fraction of window height.
SCREEN_SCALE = 0.924444
def view_angles(atmosphere):
    t = atmosphere.elapsed
    shake = math.sin(t * 9) * atmosphere.wind * atmosphere.cover * 0.00012 * (1 + atmosphere.risk / 100)
    shake += atmosphere.storm * 0.006 * math.sin(t * 17) * math.sin(t * 5.3)
    shake += atmosphere.impact * 0.03 * math.sin(t * 41)
    # The view tilts a little with climbs and dives so they feel like more than an altitude number.
    return atmosphere.heading + atmosphere.look_yaw, atmosphere.pitch + shake + 0.4 * atmosphere.flight_pitch


def compute_camera(atmosphere):
    """Camera (x, y, z): the pilot's seat, kept clear of the ground and rooftops."""
    x, z = atmosphere.position[0], atmosphere.position[1]
    return x, max(atmosphere.altitude + 1.2, world.obstacle_height(x, z) + 3.0), z


def project(atmosphere, point, size):
    """World (x, altitude, z) -> window pixel (x, y, depth), or None if behind the camera."""
    heading, pitch = view_angles(atmosphere)
    width, height = size
    cx, cy, cz = atmosphere.camera
    rx, ry, rz = point[0] - cx, point[1] - cy, point[2] - cz
    sh, ch, sp, cp = math.sin(heading), math.cos(heading), math.sin(pitch), math.cos(pitch)
    depth = rx * sh * cp + ry * sp + rz * ch * cp
    if depth < 0.5:
        return None
    sx = (rx * ch - rz * sh) / depth
    sy = (-rx * sh * sp + ry * cp - rz * ch * sp) / depth
    k = height * SCREEN_SCALE
    return width / 2 + sx * k, height / 2 - sy * k, depth
