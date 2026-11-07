"""Texture-free terrain shared by rendering, collision detection and the map."""
import math
import numpy as np
import json
from pathlib import Path

WATER = 15.0
MASK = 0xFFFFFFFF
TILE_SIZE = 160.0
CITY_RENDER_DISTANCE = 3000.0


def raw_terrain(x, z):
    return 100 + 130 * math.sin(x / 1700) * math.cos(z / 1500)


def ground_height(x, z):
    return max(raw_terrain(x, z), WATER)


def obstacle_height(x, z):
    height = ground_height(x, z)
    for building in BUILDINGS:
        if abs(x-building['x']) <= building['width']/2 and abs(z-building['z']) <= building['depth']/2:
            height = max(height,building['y']+building['height'])
    return height


def hash_u32(x, z, seed):
    h = ((x & MASK) * 0x8DA6B343 ^ (z & MASK) * 0xD8163841 ^ (seed & MASK) * 0xCB1AB31F) & MASK
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & MASK
    h ^= h >> 12
    h = (h * 0x297A2D39) & MASK
    h ^= h >> 15
    return h


def hash01(x, z, seed):
    return (hash_u32(x, z, seed) >> 8) / 16777216.0


def hash01_np(x, z, seed):
    x = np.asarray(x).astype(np.int64).astype(np.uint32)
    z = np.asarray(z).astype(np.int64).astype(np.uint32)
    with np.errstate(over='ignore'):
        h = x * np.uint32(0x8DA6B343) ^ z * np.uint32(0xD8163841) ^ np.uint32((seed * 0xCB1AB31F) & MASK)
        h ^= h >> np.uint32(15)
        h *= np.uint32(0x2C1B3C6D)
        h ^= h >> np.uint32(12)
        h *= np.uint32(0x297A2D39)
        h ^= h >> np.uint32(15)
    return (h >> np.uint32(8)).astype(np.float32) / np.float32(16777216.0)


def smoothstep_np(low, high, value):
    t = np.clip((value - low) / (high - low), 0, 1)
    return t * t * (3 - 2 * t)


def season_palette(season):
    # four field colours, forest, hedge
    return [
        [(0.30, 0.48, 0.20), (0.45, 0.55, 0.22), (0.62, 0.58, 0.30), (0.24, 0.40, 0.18), (0.10, 0.26, 0.12), (0.16, 0.30, 0.13)],
        [(0.66, 0.52, 0.22), (0.55, 0.40, 0.18), (0.46, 0.43, 0.20), (0.72, 0.60, 0.30), (0.50, 0.26, 0.10), (0.40, 0.28, 0.12)],
        [(0.86, 0.89, 0.92), (0.80, 0.84, 0.88), (0.90, 0.92, 0.94), (0.76, 0.80, 0.84), (0.42, 0.48, 0.46), (0.62, 0.66, 0.68)],
    ][season]



def raw_terrain_np(x, z):
    return 100 + 130 * np.sin(np.asarray(x) / 1700) * np.cos(np.asarray(z) / 1500)


def ground_height_np(x, z):
    return np.maximum(raw_terrain_np(x, z), WATER)


def land_color_np(x, z, distance, season, night):
    palette = np.array(season_palette(season), dtype=np.float32)
    i, j = np.floor(x / TILE_SIZE), np.floor(z / TILE_SIZE)
    pick = np.minimum((hash01_np(i, j, 41) * 4).astype(np.int32), 3)
    color = palette[pick] * (0.85 + 0.30 * hash01_np(i, j, 44))[..., None]
    water = raw_terrain_np(x, z) < WATER
    lake = np.array([0.75, 0.82, 0.88] if season == 2 else [0.10, 0.22, 0.32])
    return np.where(water[..., None], lake, color), np.zeros(np.shape(x), dtype=np.float32)


def glsl_source():
    colors = []
    for season in range(3):
        for rgb in season_palette(season)[:4]:
            colors.append('vec3(' + ','.join(str(float(v)) for v in rgb) + ')')
    return 'const float WATER = 15.0;\nconst vec3 FIELD_COLORS[12] = vec3[12](' + ','.join(colors) + ');\n' + GLSL_FUNCTIONS


BUILDING_CATALOG = json.loads((Path(__file__).parent/'assets'/'buildings'/'catalog.json').read_text(encoding='utf-8'))
CITY_CENTERS = ((0.0,1600.0),(2600.0,-900.0),(-2500.0,1000.0))
BUILDINGS = []
for city_index,(cx,cz) in enumerate(CITY_CENTERS):
    for row in range(3):
        for column in range(4):
            variant = ('short','medium','tall')[(row*4+column+city_index)%3]
            info = BUILDING_CATALOG[variant]
            x,z = cx+(column-1.5)*65,cz+(row-1)*70
            quarter_turn = (row+column)%2
            width,depth = (info['depth'],info['width']) if quarter_turn else (info['width'],info['depth'])
            level = max(ground_height(x+dx,z+dz) for dx in (-width/2,width/2) for dz in (-depth/2,depth/2))
            BUILDINGS.append(dict(x=x,y=level,z=z,width=width,depth=depth,height=info['height'],
                                  model=variant,heading=quarter_turn*math.pi/2,city=city_index))


GLSL_FUNCTIONS = r"""
uint hash_u(int x, int z, int seed) {
    uint h = uint(x) * 0x8DA6B343u ^ uint(z) * 0xD8163841u ^ uint(seed) * 0xCB1AB31Fu;
    h ^= h >> 15u;
    h *= 0x2C1B3C6Du;
    h ^= h >> 12u;
    h *= 0x297A2D39u;
    h ^= h >> 15u;
    return h;
}

float hash01(int x, int z, int seed) {
    return float(hash_u(x, z, seed) >> 8u) / 16777216.0;
}

float raw_terrain(vec2 p) {
    return 100.0 + 130.0 * sin(p.x / 1700.0) * cos(p.y / 1500.0);
}


float ground_height(vec2 p) { return max(raw_terrain(p), WATER); }
vec3 land_color(vec2 p, float dist, out float light) {
    ivec2 cell = ivec2(floor(p / 160.0));
    int pick = min(int(hash01(cell.x, cell.y, 41) * 4.0), 3);
    vec3 color = FIELD_COLORS[season * 4 + pick] * (0.85 + 0.30 * hash01(cell.x, cell.y, 44));
    if (raw_terrain(p) < WATER)
        color = season == 2 ? vec3(0.75,0.82,0.88) : vec3(0.10,0.22,0.32);
    light = 0.0;
    return color;
}
"""
