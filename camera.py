"""Shared camera math so the CPU renderer, GPU renderer, aircraft and overlays agree."""

import math

import world

# Pixels per unit of screen-space ray offset, as a fraction of window height.
SCREEN_SCALE = 0.924444
CHASE_BACK = 48.0
CHASE_UP = 14.0
CHASE_TILT = -0.14


def view_angles(atmosphere):
    t = atmosphere.elapsed
    shake = math.sin(t * 9) * atmosphere.wind * atmosphere.cover * 0.00012 * (1 + atmosphere.risk / 100)
    shake += atmosphere.storm * 0.006 * math.sin(t * 17) * math.sin(t * 5.3)
    shake += atmosphere.impact * 0.03 * math.sin(t * 41)
    # Chase view looks slightly down at the aircraft; the cockpit tilts a little with climbs and dives.
    offset = CHASE_TILT if atmosphere.third_person else 0.4 * atmosphere.flight_pitch
    return atmosphere.heading + atmosphere.look_yaw, atmosphere.pitch + shake + offset


def _view_origin(atmosphere):
    x, y, z = atmosphere.position[0], atmosphere.altitude, atmosphere.position[1]
    if atmosphere.third_person:
        # The chase camera orbits the aircraft while flight coordinates stay at the plane.
        heading, pitch = view_angles(atmosphere)
        sh, ch, sp, cp = math.sin(heading), math.cos(heading), math.sin(pitch), math.cos(pitch)
        x -= sh * cp * CHASE_BACK + sh * sp * CHASE_UP
        y += -sp * CHASE_BACK + cp * CHASE_UP
        z -= ch * cp * CHASE_BACK + ch * sp * CHASE_UP
        clearance = 5.0
    else:
        y += 1.2
        clearance = 3.0
    # Never let the camera dip into the ground or a rooftop.
    return x, max(y, world.obstacle_height(x, z) + clearance), z


def view_origin(atmosphere):
    """Camera position (x, y, z), cached until anything that moves the camera changes."""
    key = (atmosphere.position[0], atmosphere.position[1], atmosphere.altitude, atmosphere.heading,
           atmosphere.look_yaw, atmosphere.pitch, atmosphere.third_person, atmosphere.elapsed,
           atmosphere.flight_pitch, atmosphere.impact, atmosphere.wind, atmosphere.cover, atmosphere.storm,
           atmosphere.risk)
    cached = atmosphere.__dict__.get('_camera')
    if cached is None or cached[0] != key:
        cached = (key, _view_origin(atmosphere))
        atmosphere.__dict__['_camera'] = cached
    return cached[1]


def project(atmosphere, point, size):
    """World (x, altitude, z) -> window pixel (x, y, depth), or None if behind the camera."""
    heading, pitch = view_angles(atmosphere)
    width, height = size
    cx, cy, cz = view_origin(atmosphere)
    rx, ry, rz = point[0] - cx, point[1] - cy, point[2] - cz
    sh, ch, sp, cp = math.sin(heading), math.cos(heading), math.sin(pitch), math.cos(pitch)
    depth = rx * sh * cp + ry * sp + rz * ch * cp
    if depth < 0.5:
        return None
    sx = (rx * ch - rz * sh) / depth
    sy = (-rx * sh * sp + ry * cp - rz * ch * sp) / depth
    k = height * SCREEN_SCALE
    return width / 2 + sx * k, height / 2 - sy * k, depth
