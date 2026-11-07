"""The world below the clouds: terrain, lakes, fields, roads, named cities and villages.

Everything here exists twice: plain Python (gameplay, collisions, CPU renderer) and GLSL
(glsl_source(), used by gpu_renderer.py). Hashes are integer-based so both agree exactly.
"""

import math

import numpy as np

CELL = 32.0           # building lot size in meters
VILLAGE_CELL = 2600.0  # at most one village per square of this size
WATER = 15.0          # lake surface height; raw terrain below this is water
MASK = 0xFFFFFFFF

# name, max building height, lot density, tall downtown (1) or even town (0),
# roof colour A, roof colour B, wall colour, window light colour
STYLES = [
    ('BRICK', 48.0, 0.78, 1.0, (0.56, 0.24, 0.17), (0.46, 0.33, 0.25), (0.55, 0.33, 0.26), (1.00, 0.78, 0.45)),
    ('GLASS', 270.0, 0.70, 1.0, (0.50, 0.54, 0.58), (0.38, 0.42, 0.47), (0.33, 0.45, 0.56), (0.75, 0.88, 1.00)),
    ('GARDEN', 16.0, 0.55, 0.0, (0.27, 0.42, 0.31), (0.52, 0.30, 0.22), (0.80, 0.76, 0.66), (1.00, 0.82, 0.55)),
    ('CAPITAL', 150.0, 0.82, 1.0, (0.62, 0.58, 0.50), (0.45, 0.45, 0.46), (0.72, 0.67, 0.57), (1.00, 0.86, 0.60)),
    ('HARBOR', 13.0, 0.50, 0.0, (0.86, 0.87, 0.88), (0.28, 0.42, 0.62), (0.90, 0.90, 0.86), (1.00, 0.84, 0.62)),
    ('SPIRE', 860.0, 0.60, 1.0, (0.85, 0.88, 0.92), (0.60, 0.66, 0.74), (0.86, 0.89, 0.93), (0.45, 0.95, 1.00)),
    ('VILLAGE', 11.0, 0.50, 0.0, (0.60, 0.25, 0.18), (0.36, 0.30, 0.27), (0.85, 0.80, 0.70), (1.00, 0.80, 0.50)),
]
VILLAGE_STYLE = 6

# name, x (east), z (north), radius, style, one-line description for the HUD
CITIES = [
    ('TROY', 0.0, 3400.0, 1300.0, 0, 'Brick river town and home base'),
    ('SKYPORT', 4450.0, 10300.0, 1700.0, 1, 'Glass towers above the haze'),
    ('NIMBUS HEIGHTS', 15400.0, 2600.0, 1150.0, 5, 'Spires that pierce the clouds'),
    ('ALBANY', 6800.0, -6400.0, 1600.0, 3, 'The capital, dense and busy'),
    ('LAKE GEORGE', -5500.0, -4500.0, 850.0, 4, 'Lakeside resort town'),
    ('SARATOGA', -7600.0, 2200.0, 950.0, 2, 'Gardens, porches and racetracks'),
]


def smoothstep(low, high, value):
    t = min(max((value - low) / (high - low), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def raw_terrain(x, z):
    return 100 + 130 * math.sin(x / 1700) * math.cos(z / 1500)


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


CITY_LEVELS = [raw_terrain(x, z) for _, x, z, _, _, _ in CITIES]


def village_at(x, z):
    """(center_x, center_z, radius, level) of the village whose square contains (x, z), or None."""
    cx, cz = math.floor(x / VILLAGE_CELL), math.floor(z / VILLAGE_CELL)
    if hash01(cx, cz, 5) > 0.42:
        return None
    vx = (cx + 0.3 + 0.4 * hash01(cx, cz, 6)) * VILLAGE_CELL
    vz = (cz + 0.3 + 0.4 * hash01(cx, cz, 7)) * VILLAGE_CELL
    level = raw_terrain(vx, vz)
    if level < WATER + 10:
        return None
    for _, x0, z0, radius, _, _ in CITIES:
        if math.hypot(vx - x0, vz - z0) < radius + 1800:
            return None
    return vx, vz, 140 + 120 * hash01(cx, cz, 8), level


def settlement_at(x, z):
    """Settlement whose flattened area covers (x, z): (index, cx, cz, radius, level, style) or None.

    index is the CITIES index, or -1 for a village.
    """
    for index, (_, cx, cz, radius, style, _) in enumerate(CITIES):
        if math.hypot(x - cx, z - cz) < radius * 1.3:
            return index, cx, cz, radius, CITY_LEVELS[index], style
    village = village_at(x, z)
    if village and math.hypot(x - village[0], z - village[1]) < village[2] * 1.3:
        return (-1, *village, VILLAGE_STYLE)
    return None


def ground_height(x, z):
    height = raw_terrain(x, z)
    place = settlement_at(x, z)
    if place:
        _, cx, cz, radius, level, _ = place
        flat = 1 - smoothstep(radius * 0.9, radius * 1.3, math.hypot(x - cx, z - cz))
        height += (level - height) * flat
    return max(height, WATER)


def is_street(i, j, style):
    if style == VILLAGE_STYLE:
        return (j & 3) == 0
    return i % 5 == 0 or j % 5 == 0


def edge_scale(x, z, cx, cz, style):
    """Wobbly outline so towns aren't perfect circles."""
    angle = math.atan2(z - cz, x - cx)
    return 0.86 + 0.09 * math.sin(3 * angle + style) + 0.05 * math.sin(7 * angle + 2 * style)


def lot_height(i, j, place):
    _, cx, cz, radius, _, style = place
    if is_street(i, j, style):
        return 0.0
    x, z = (i + 0.5) * CELL, (j + 0.5) * CELL
    r = math.hypot(x - cx, z - cz) / (radius * edge_scale(x, z, cx, cz, style))
    if r > 1:
        return 0.0
    if style != VILLAGE_STYLE and hash01(i // 5, j // 5, 71) < 0.08:
        return 0.0  # park block
    _, max_height, density, tall = STYLES[style][:4]
    if hash01(i, j, 11 + style) > density * (1 - 0.45 * r * r):
        return 0.0
    profile = (1 - r) ** 1.6 if tall > 0.5 else 1 - 0.5 * r
    shape = hash01(i, j, 23)
    return max(6.0, max_height * profile * (0.25 + 0.75 * shape * shape))


def lot_margin(i, j):
    return 3 + 5 * hash01(i, j, 31)


def building_height(x, z):
    """Height above the settlement floor of the building at (x, z), 0 if there is none."""
    place = settlement_at(x, z)
    if not place:
        return 0.0
    i, j = math.floor(x / CELL), math.floor(z / CELL)
    margin = lot_margin(i, j)
    local_x, local_z = x - i * CELL, z - j * CELL
    if not (margin <= local_x <= CELL - margin and margin <= local_z <= CELL - margin):
        return 0.0
    return lot_height(i, j, place)


def obstacle_height(x, z):
    return ground_height(x, z) + building_height(x, z)


def nearest_city(x, z):
    """(index, distance) of the closest city center."""
    distances = [math.hypot(x - cx, z - cz) for _, cx, cz, _, _, _ in CITIES]
    index = min(range(len(CITIES)), key=distances.__getitem__)
    return index, distances[index]


def city_at(x, z):
    """Index of the city whose radius contains (x, z), or None."""
    index, distance = nearest_city(x, z)
    return index if distance < CITIES[index][3] else None


ROADS = [(i, (i + 1) % len(CITIES)) for i in range(len(CITIES))] + [(0, 3), (0, 2)]


# ---------------------------------------------------------------------------------------------
# numpy versions for the CPU renderer (arrays in, arrays out)

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


def settlements_np(x, z):
    """Per-point settlement data: (found, cx, cz, radius, level, style) arrays."""
    found = np.zeros(x.shape, bool)
    cx, cz, radius, level, style = (np.zeros(x.shape, np.float32) for _ in range(5))
    for index, (_, x0, z0, r0, s0, _) in enumerate(CITIES):
        inside = ~found & (np.hypot(x - x0, z - z0) < r0 * 1.3)
        found |= inside
        cx[inside], cz[inside], radius[inside], level[inside], style[inside] = x0, z0, r0, CITY_LEVELS[index], s0
    vcx, vcz = np.floor(x / VILLAGE_CELL), np.floor(z / VILLAGE_CELL)
    vx = (vcx + 0.3 + 0.4 * hash01_np(vcx, vcz, 6)) * VILLAGE_CELL
    vz = (vcz + 0.3 + 0.4 * hash01_np(vcx, vcz, 7)) * VILLAGE_CELL
    vr = 140 + 120 * hash01_np(vcx, vcz, 8)
    vlevel = raw_terrain_np(vx, vz)
    village = (~found & (hash01_np(vcx, vcz, 5) <= 0.42) & (vlevel >= WATER + 10)
               & (np.hypot(x - vx, z - vz) < vr * 1.3))
    for _, x0, z0, r0, _, _ in CITIES:
        village &= np.hypot(vx - x0, vz - z0) >= r0 + 1800
    found |= village
    cx[village], cz[village], radius[village] = vx[village], vz[village], vr[village]
    level[village], style[village] = vlevel[village], VILLAGE_STYLE
    return found, cx, cz, radius, level, style


def raw_terrain_np(x, z):
    return 100 + 130 * np.sin(x / 1700) * np.cos(z / 1500)


def ground_height_np(x, z, places=None):
    """places: settlements_np() for (roughly) these points, to skip recomputing it."""
    height = raw_terrain_np(x, z)
    found, cx, cz, radius, level, _ = places if places is not None else settlements_np(x, z)
    safe = np.maximum(radius, 1)
    flat = np.where(found, 1 - smoothstep_np(safe * 0.9, safe * 1.3, np.hypot(x - cx, z - cz)), 0)
    return np.maximum(height + (level - height) * flat, WATER)


def season_palette(season):
    # four field colours, forest, hedge
    return [
        [(0.30, 0.48, 0.20), (0.45, 0.55, 0.22), (0.62, 0.58, 0.30), (0.24, 0.40, 0.18), (0.10, 0.26, 0.12), (0.16, 0.30, 0.13)],
        [(0.66, 0.52, 0.22), (0.55, 0.40, 0.18), (0.46, 0.43, 0.20), (0.72, 0.60, 0.30), (0.50, 0.26, 0.10), (0.40, 0.28, 0.12)],
        [(0.86, 0.89, 0.92), (0.80, 0.84, 0.88), (0.90, 0.92, 0.94), (0.76, 0.80, 0.84), (0.42, 0.48, 0.46), (0.62, 0.66, 0.68)],
    ][season]


def land_color_np(x, z, distance, season, night, places=None):
    """Flat ground colour (fields, forest, lakes, roads, rooftops) and night-light emission."""
    palette = np.array(season_palette(season), np.float32)
    # Fields: rows of different widths, staggered like bricks.
    row = np.floor(z / 160)
    width = 140 + 140 * hash01_np(row, 0, 48)
    shifted = x + hash01_np(row, 0, 47) * width
    fx = np.floor(shifted / width)
    field_hash = hash01_np(fx, row, 41)
    pick = np.minimum((field_hash * 4).astype(np.int32), 3)
    stripes = np.sin(np.where(field_hash > 0.5, x, z) * 0.8) * (1 - smoothstep_np(120, 500, distance))
    color = palette[pick] * (0.93 + 0.07 * stripes)[..., None]
    edge = np.minimum(width / 2 - np.abs(shifted - (fx + 0.5) * width), 80 - np.abs(z - (row + 0.5) * 160))
    hedge = 1 - smoothstep_np(0, 4 + distance * 0.002, edge)
    color = color + (palette[5] - color) * (hedge * 0.6)[..., None]
    wobble = 0.22 * np.sin(x / 71 + np.sin(z / 53)) * np.sin(z / 67 + np.sin(x / 47))
    forest = smoothstep_np(0.55, 0.63, np.sin(x / 260 + np.sin(z / 390) * 1.7) * np.sin(z / 300 + np.sin(x / 450) * 1.3) + wobble)
    forest = np.maximum(forest, (hash01_np(fx, row, 46) < 0.08) * (1 - hedge))
    trees = 0.8 + 0.4 * hash01_np(np.floor(x / 7), np.floor(z / 7), 44) * (1 - smoothstep_np(300, 1500, distance))
    color = color + (palette[4] * trees[..., None] - color) * forest[..., None]
    far = smoothstep_np(1500, 7000, distance)[..., None]
    color = color + (palette[:4].mean(axis=0) * 0.7 + palette[4] * 0.3 - color) * far

    road = np.full(x.shape, 1e9, np.float32)
    for a, b in ROADS:
        ax, az, bx, bz = CITIES[a][1], CITIES[a][2], CITIES[b][1], CITIES[b][2]
        vx, vz = bx - ax, bz - az
        t = np.clip(((x - ax) * vx + (z - az) * vz) / (vx * vx + vz * vz), 0, 1)
        road = np.minimum(road, np.hypot(x - ax - vx * t, z - az - vz * t))
    road_mask = 1 - smoothstep_np(8, 10 + distance * 0.003, road)
    color = color + (np.array([0.30, 0.31, 0.33]) - color) * road_mask[..., None]
    light = road_mask * 0.25

    found, cx, cz, radius, level, style = places if places is not None else settlements_np(x, z)
    i, j = np.floor(x / CELL), np.floor(z / CELL)
    ii, jj = i.astype(np.int64), j.astype(np.int64)
    village = style == VILLAGE_STYLE
    street = np.where(village, (jj & 3) == 0, (np.mod(ii, 5) == 0) | (np.mod(jj, 5) == 0))
    lot_x, lot_z = (i + 0.5) * CELL, (j + 0.5) * CELL
    angle = np.arctan2(lot_z - cz, lot_x - cx)
    edge = 0.86 + 0.09 * np.sin(3 * angle + style) + 0.05 * np.sin(7 * angle + 2 * style)
    r = np.hypot(lot_x - cx, lot_z - cz) / np.maximum(radius * edge, 1)
    styles = style.astype(np.int32)
    density = np.array([s[2] for s in STYLES], np.float32)[styles] * (1 - 0.45 * r * r)
    park = ~village & (hash01_np(np.floor_divide(ii, 5), np.floor_divide(jj, 5), 71) < 0.08)
    built = found & ~street & ~park & (r <= 1) & (lot_hash_np(i, j, styles) <= density)
    margin = 3 + 5 * hash01_np(i, j, 31)
    lx, lz = x - i * CELL, z - j * CELL
    roof = built & (lx >= margin) & (lx <= CELL - margin) & (lz >= margin) & (lz <= CELL - margin)
    roof_a = np.array([s[4] for s in STYLES], np.float32)[styles]
    roof_b = np.array([s[5] for s in STYLES], np.float32)[styles]
    roof_color = np.where((hash01_np(i, j, 37) > 0.5)[..., None], roof_a, roof_b)
    if season == 2:
        roof_color = roof_color + (0.92 - roof_color) * 0.7
    inside = found & (r <= 1)
    paved = inside & street
    color = np.where(paved[..., None], np.array([0.27, 0.28, 0.30], np.float32), color)
    color = np.where(roof[..., None], roof_color, color)
    color = np.where((inside & ~street & ~roof & ~built)[..., None], color * 0.85 + np.array([0.05, 0.08, 0.03]), color)
    lamp = paved * (0.6 + 0.4 * (hash01_np(i, j, 53) > 0.5))
    windows = roof * (hash01_np(i, j, 51) < 0.35)
    light = np.maximum(light, np.maximum(lamp, windows * 0.8) * np.where(village, 0.5, 1.0))

    water = raw_terrain_np(x, z) < WATER
    water &= ~(found & (np.hypot(x - cx, z - cz) < radius * 1.3))
    lake = np.array([0.75, 0.82, 0.88] if season == 2 else [0.10, 0.22, 0.32], np.float32)
    color = np.where(water[..., None], lake, color)
    return color, light * (~water) * night


def lot_hash_np(i, j, styles):
    result = np.ones(i.shape, np.float32)
    for style in np.unique(styles):
        mask = styles == style
        result[mask] = hash01_np(i[mask], j[mask], 11 + int(style))
    return result


# ---------------------------------------------------------------------------------------------
# GLSL version

def _vec(values):
    return ', '.join(f'{float(v):.6f}' for v in values)


def glsl_source():
    n, s = len(CITIES), len(STYLES)
    city_a = ', '.join(f'vec4({_vec((x, z, r, CITY_LEVELS[i]))})' for i, (_, x, z, r, _, _) in enumerate(CITIES))
    city_b = ', '.join(f'vec4({_vec((st, STYLES[st][1], STYLES[st][2], STYLES[st][3]))})'
                       for _, _, _, _, st, _ in CITIES)
    roads = ', '.join(f'ivec2({a}, {b})' for a, b in ROADS)
    style_arrays = '\n'.join(
        f'const vec3 {name}[{s}] = vec3[{s}]({", ".join(f"vec3({_vec(style[k])})" for style in STYLES)});'
        for name, k in (('ROOF_A', 4), ('ROOF_B', 5), ('WALL', 6), ('WINDOW_LIGHT', 7)))
    style_b = ', '.join(f'vec4({_vec((i, st[1], st[2], st[3]))})' for i, st in enumerate(STYLES))
    return f"""
const float CELL = {CELL:.1f};
const float VILLAGE_CELL = {VILLAGE_CELL:.1f};
const float WATER = {WATER:.1f};
const int CITY_COUNT = {n};
const int VILLAGE_STYLE = {VILLAGE_STYLE};
const vec4 CITY_A[{n}] = vec4[{n}]({city_a});
const vec4 CITY_B[{n}] = vec4[{n}]({city_b});
const vec4 STYLE_B[{s}] = vec4[{s}]({style_b});
const int ROAD_COUNT = {len(ROADS)};
const ivec2 ROADS[{len(ROADS)}] = ivec2[{len(ROADS)}]({roads});
{style_arrays}
""" + GLSL_FUNCTIONS


GLSL_FUNCTIONS = """
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

bool village_at(vec2 p, out vec4 a) {
    ivec2 c = ivec2(floor(p / VILLAGE_CELL));
    if (hash01(c.x, c.y, 5) > 0.42) return false;
    vec2 center = (vec2(c) + 0.3 + 0.4 * vec2(hash01(c.x, c.y, 6), hash01(c.x, c.y, 7))) * VILLAGE_CELL;
    float level = raw_terrain(center);
    if (level < WATER + 10.0) return false;
    for (int i = 0; i < CITY_COUNT; ++i) {
        if (distance(center, CITY_A[i].xy) < CITY_A[i].z + 1800.0) return false;
    }
    a = vec4(center, 140.0 + 120.0 * hash01(c.x, c.y, 8), level);
    return true;
}

// a = (center x, center z, radius, floor level), b = (style, max height, density, tall)
bool settlement_at(vec2 p, out vec4 a, out vec4 b) {
    for (int i = 0; i < CITY_COUNT; ++i) {
        if (distance(p, CITY_A[i].xy) < CITY_A[i].z * 1.3) {
            a = CITY_A[i];
            b = CITY_B[i];
            return true;
        }
    }
    if (village_at(p, a) && distance(p, a.xy) < a.z * 1.3) {
        b = STYLE_B[VILLAGE_STYLE];
        return true;
    }
    return false;
}

float ground_height(vec2 p) {
    float h = raw_terrain(p);
    vec4 a, b;
    if (settlement_at(p, a, b)) {
        h = mix(h, a.w, 1.0 - smoothstep(a.z * 0.9, a.z * 1.3, distance(p, a.xy)));
    }
    return max(h, WATER);
}

int imod5(int i) {
    return i - 5 * int(floor(float(i) / 5.0));
}

bool is_street(ivec2 cell, int style) {
    if (style == VILLAGE_STYLE) return (cell.y & 3) == 0;
    return imod5(cell.x) == 0 || imod5(cell.y) == 0;
}

float edge_scale(vec2 p, vec4 a, int style) {
    float angle = atan(p.y - a.y, p.x - a.x);
    return 0.86 + 0.09 * sin(3.0 * angle + float(style)) + 0.05 * sin(7.0 * angle + 2.0 * float(style));
}

float lot_radius(ivec2 cell, vec4 a, int style) {
    vec2 center = (vec2(cell) + 0.5) * CELL;
    return distance(center, a.xy) / (a.z * edge_scale(center, a, style));
}

bool is_park(ivec2 cell, int style) {
    ivec2 block = ivec2(floor(vec2(cell) / 5.0));
    return style != VILLAGE_STYLE && hash01(block.x, block.y, 71) < 0.08;
}

float lot_height(ivec2 cell, vec4 a, vec4 b) {
    int style = int(b.x + 0.5);
    if (is_street(cell, style)) return 0.0;
    float r = lot_radius(cell, a, style);
    if (r > 1.0) return 0.0;
    if (is_park(cell, style)) return 0.0;
    if (hash01(cell.x, cell.y, 11 + style) > b.z * (1.0 - 0.45 * r * r)) return 0.0;
    float profile = b.w > 0.5 ? pow(1.0 - r, 1.6) : 1.0 - 0.5 * r;
    float shape = hash01(cell.x, cell.y, 23);
    return max(6.0, b.y * profile * (0.25 + 0.75 * shape * shape));
}

float lot_margin(ivec2 cell) {
    return 3.0 + 5.0 * hash01(cell.x, cell.y, 31);
}

vec3 season_color(int index) {
    // four field colours, forest, hedge for summer, autumn, winter
    vec3 summer[6] = vec3[6](vec3(0.30, 0.48, 0.20), vec3(0.45, 0.55, 0.22), vec3(0.62, 0.58, 0.30),
                             vec3(0.24, 0.40, 0.18), vec3(0.10, 0.26, 0.12), vec3(0.16, 0.30, 0.13));
    vec3 autumn[6] = vec3[6](vec3(0.66, 0.52, 0.22), vec3(0.55, 0.40, 0.18), vec3(0.46, 0.43, 0.20),
                             vec3(0.72, 0.60, 0.30), vec3(0.50, 0.26, 0.10), vec3(0.40, 0.28, 0.12));
    vec3 winter[6] = vec3[6](vec3(0.86, 0.89, 0.92), vec3(0.80, 0.84, 0.88), vec3(0.90, 0.92, 0.94),
                             vec3(0.76, 0.80, 0.84), vec3(0.42, 0.48, 0.46), vec3(0.62, 0.66, 0.68));
    if (season == 1) return autumn[index];
    if (season == 2) return winter[index];
    return summer[index];
}

// 1 if a nearby building blocks the sun from ground point p, else 0.
float building_shadow(vec2 p, vec4 a, vec4 b) {
    float flat_len = length(sun_direction.xz);
    if (sun_direction.y < 0.03 || flat_len < 1e-4) return 0.0;
    vec2 toward = sun_direction.xz / flat_len;
    float rise = sun_direction.y / flat_len;
    for (int k = 1; k <= 5; ++k) {
        float s = 7.0 * float(k * k) * 0.6 + 3.0;
        vec2 q = p + toward * s;
        ivec2 cell = ivec2(floor(q / CELL));
        float h = lot_height(cell, a, b);
        float m = lot_margin(cell);
        vec2 local = q - vec2(cell) * CELL;
        if (h > s * rise && all(greaterThanEqual(local, vec2(m))) && all(lessThanEqual(local, vec2(CELL - m)))) return 1.0;
    }
    return 0.0;
}

// Flat ground colour; light gets night-lamp emission (0..1).
vec3 land_color(vec2 p, float dist, out float light) {
    // Fields: rows of different widths, staggered like bricks.
    int row = int(floor(p.y / 160.0));
    float width = 140.0 + 140.0 * hash01(row, 0, 48);
    float shifted = p.x + hash01(row, 0, 47) * width;
    int fx = int(floor(shifted / width));
    float field_hash = hash01(fx, row, 41);
    int pick = min(int(field_hash * 4.0), 3);
    vec3 color = season_color(pick) * (0.93 + 0.07 * sin((field_hash > 0.5 ? p.x : p.y) * 0.8) * (1.0 - smoothstep(120.0, 500.0, dist)));
    float edge = min(width * 0.5 - abs(shifted - (float(fx) + 0.5) * width), 80.0 - abs(p.y - (float(row) + 0.5) * 160.0));
    float hedge = 1.0 - smoothstep(0.0, 4.0 + dist * 0.002, edge);
    color = mix(color, season_color(5), hedge * 0.6);
    float wobble = 0.22 * sin(p.x / 71.0 + sin(p.y / 53.0)) * sin(p.y / 67.0 + sin(p.x / 47.0));
    float forest = smoothstep(0.55, 0.63, sin(p.x / 260.0 + sin(p.y / 390.0) * 1.7) * sin(p.y / 300.0 + sin(p.x / 450.0) * 1.3) + wobble);
    forest = max(forest, step(hash01(fx, row, 46), 0.08) * (1.0 - hedge));
    ivec2 tree = ivec2(floor(p / 7.0));
    float trees = 0.8 + 0.4 * hash01(tree.x, tree.y, 44) * (1.0 - smoothstep(300.0, 1500.0, dist));
    color = mix(color, season_color(4) * trees, forest);
    vec3 average = (season_color(0) + season_color(1) + season_color(2) + season_color(3)) * 0.175 + season_color(4) * 0.3;
    color = mix(color, average, smoothstep(1500.0, 7000.0, dist));

    float road = 1e9;
    for (int k = 0; k < ROAD_COUNT; ++k) {
        vec2 a = CITY_A[ROADS[k].x].xy;
        vec2 v = CITY_A[ROADS[k].y].xy - a;
        float t = clamp(dot(p - a, v) / dot(v, v), 0.0, 1.0);
        road = min(road, distance(p, a + v * t));
    }
    float road_mask = 1.0 - smoothstep(8.0, 10.0 + dist * 0.003, road);
    color = mix(color, vec3(0.30, 0.31, 0.33), road_mask);
    light = road_mask * 0.25;

    vec4 a, b;
    bool found = settlement_at(p, a, b);
    if (found && distance(p, a.xy) < a.z * 1.1) {
        ivec2 cell = ivec2(floor(p / CELL));
        int style = int(b.x + 0.5);
        float r = lot_radius(cell, a, style);
        bool street = r <= 1.0 && is_street(cell, style);
        bool built = !street && r <= 1.0 && !is_park(cell, style) && hash01(cell.x, cell.y, 11 + style) <= b.z * (1.0 - 0.45 * r * r);
        float margin = lot_margin(cell);
        vec2 local = p - vec2(cell) * CELL;
        bool roof = built && all(greaterThanEqual(local, vec2(margin))) && all(lessThanEqual(local, vec2(CELL - margin)));
        float dim = style == VILLAGE_STYLE ? 0.5 : 1.0;
        if (street) {
            color = vec3(0.27, 0.28, 0.30);
            light = max(light, (0.6 + 0.4 * step(0.5, hash01(cell.x, cell.y, 53))) * dim);
        } else if (roof) {
            color = (hash01(cell.x, cell.y, 37) > 0.5 ? ROOF_A[style] : ROOF_B[style]) * (0.85 + 0.3 * hash01(cell.x, cell.y, 43));
            if (season == 2) color = mix(color, vec3(0.92), 0.7);
            light = max(light, step(hash01(cell.x, cell.y, 51), 0.35) * 0.8 * dim);
        } else if (!built && r <= 1.0) {
            color = mix(color, season_color(4) * (0.85 + 0.3 * hash01(int(floor(p.x / 6.0)), int(floor(p.y / 6.0)), 45)), 0.55);
        }
        if (!roof && dist < 3000.0) color *= 1.0 - 0.45 * smoothstep(-0.12, 0.35, sun_direction.y) * building_shadow(p, a, b);
    }
    if (raw_terrain(p) < WATER && !(found && distance(p, a.xy) < a.z * 1.3)) {
        color = season == 2 ? vec3(0.75, 0.82, 0.88) : vec3(0.10, 0.22, 0.32);
        light = 0.0;
    }
    return color;
}

// March the ray through the settlement's lot grid; returns true on the first building hit.
bool trace_settlement(vec3 o, vec3 d, float t0, float t1, vec4 a, vec4 b,
                      out float t_hit, out vec3 normal, out ivec2 hit_cell, out float hit_height) {
    vec3 p = o + d * t0;
    ivec2 cell = ivec2(floor(p.xz / CELL));
    ivec2 step_dir = ivec2(d.x >= 0.0 ? 1 : -1, d.z >= 0.0 ? 1 : -1);
    vec2 dir = vec2(abs(d.x) < 1e-6 ? 1e-6 : d.x, abs(d.z) < 1e-6 ? 1e-6 : d.z);
    vec2 next_edge = (vec2(cell) + vec2(step_dir.x > 0 ? 1.0 : 0.0, step_dir.y > 0 ? 1.0 : 0.0)) * CELL;
    vec2 t_max = t0 + (next_edge - p.xz) / dir;
    vec2 t_delta = abs(vec2(CELL) / dir);
    vec3 inv = 1.0 / vec3(dir.x, abs(d.y) < 1e-6 ? 1e-6 : d.y, dir.y);
    float t_enter = t0;
    for (int i = 0; i < 160; ++i) {
        if (t_enter > t1) break;
        float h = lot_height(cell, a, b);
        if (h > 0.0) {
            float m = lot_margin(cell);
            vec3 lo = vec3(vec2(cell) * CELL + m, a.w).xzy;
            vec3 hi = vec3(vec2(cell + 1) * CELL - m, a.w + h).xzy;
            vec3 ta = (lo - o) * inv, tb = (hi - o) * inv;
            vec3 tn = min(ta, tb), tf = max(ta, tb);
            float near = max(max(tn.x, tn.y), tn.z);
            float far = min(min(tf.x, tf.y), tf.z);
            if (near <= far && far > 0.0 && near <= t1) {
                t_hit = max(near, 0.0);
                if (near == tn.x) normal = vec3(-sign(d.x), 0.0, 0.0);
                else if (near == tn.y) normal = vec3(0.0, -sign(d.y), 0.0);
                else normal = vec3(0.0, 0.0, -sign(d.z));
                hit_cell = cell;
                hit_height = h;
                return true;
            }
        }
        if (t_max.x < t_max.y) {
            t_enter = t_max.x;
            t_max.x += t_delta.x;
            cell.x += step_dir.x;
        } else {
            t_enter = t_max.y;
            t_max.y += t_delta.y;
            cell.y += step_dir.y;
        }
    }
    return false;
}
"""
