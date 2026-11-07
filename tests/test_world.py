import math

import numpy as np
import pytest

import world

PROBE_SHADER = """
#version 330
uniform int season;
uniform vec3 sun_direction;
uniform ivec2 origin;
uniform vec4 city_a;
uniform vec4 city_b;
uniform vec2 probe_origin;
out vec4 result;
""" + world.glsl_source() + """
void main() {
    ivec2 cell = origin + ivec2(gl_FragCoord.xy);
    vec2 p = probe_origin + floor(gl_FragCoord.xy) * 37.0;
    result = vec4(lot_height(cell, city_a, city_b), lot_margin(cell), ground_height(p), 0.0);
}
"""
VERTEX = """
#version 330
in vec2 in_position;
void main() { gl_Position = vec4(in_position, 0.0, 1.0); }
"""


@pytest.fixture(scope='module')
def gl():
    moderngl = pytest.importorskip('moderngl')
    context = None
    for options in ({}, {'backend': 'egl'}):
        try:
            context = moderngl.create_standalone_context(require=330, **options)
            break
        except Exception as error:
            reason = error
    if context is None:
        pytest.skip(f'no standalone OpenGL 3.3 context: {reason}')
    yield context
    context.release()


def run_probe(gl, city, origin, probe_origin, size=64):
    program = gl.program(vertex_shader=VERTEX, fragment_shader=PROBE_SHADER)
    quad = gl.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], 'f4').tobytes())
    vao = gl.vertex_array(program, [(quad, '2f', 'in_position')])
    target = gl.texture((size, size), 4, dtype='f4')
    fbo = gl.framebuffer([target])
    _, cx, cz, radius, style, _ = city
    level = world.CITY_LEVELS[world.CITIES.index(city)]
    program['origin'] = origin
    program['probe_origin'] = probe_origin
    program['city_a'] = (cx, cz, radius, level)
    program['city_b'] = (style, *world.STYLES[style][1:4])
    fbo.use()
    vao.render(5)  # triangle strip
    data = np.frombuffer(fbo.read(components=4, dtype='f4'), 'f4').reshape(size, size, 4)
    for resource in (fbo, target, vao, quad, program):
        resource.release()
    return data, (0, cx, cz, radius, level, style)


@pytest.mark.parametrize('city_index', range(len(world.CITIES)))
def test_gpu_and_python_build_the_same_city(gl, city_index):
    city = world.CITIES[city_index]
    origin = (int(city[1] // world.CELL) - 32, int(city[2] // world.CELL) - 32)
    probe_origin = (city[1] - 1200, city[2] - 1200)
    data, place = run_probe(gl, city, origin, probe_origin)
    for y in range(64):
        for x in range(64):
            i, j = origin[0] + x, origin[1] + y
            assert data[y, x, 0] == pytest.approx(world.lot_height(i, j, place), abs=0.02), (i, j)
            assert data[y, x, 1] == pytest.approx(world.lot_margin(i, j), abs=1e-4)
            px, pz = probe_origin[0] + x * 37.0, probe_origin[1] + y * 37.0
            assert data[y, x, 2] == pytest.approx(world.ground_height(px, pz), abs=0.05), (px, pz)


def test_numpy_versions_match_python():
    rng = np.random.default_rng(1)
    x = rng.uniform(-20000, 20000, 400)
    z = rng.uniform(-20000, 20000, 400)
    x[:50] = world.CITIES[0][1] + rng.uniform(-1500, 1500, 50)
    z[:50] = world.CITIES[0][2] + rng.uniform(-1500, 1500, 50)
    expected = np.array([world.ground_height(a, b) for a, b in zip(x, z)])
    assert np.allclose(world.ground_height_np(x, z), expected, atol=0.01)
    for seed in (5, 41, 71):
        cells = rng.integers(-5000, 5000, (100, 2))
        got = world.hash01_np(cells[:, 0], cells[:, 1], seed)
        assert np.array_equal(got, [world.hash01(int(a), int(b), seed) for a, b in cells])


def test_every_city_is_on_dry_flat_ground():
    for index, (name, cx, cz, radius, _, _) in enumerate(world.CITIES):
        level = world.CITY_LEVELS[index]
        assert level > world.WATER + 10, name
        for angle in np.linspace(0, math.tau, 24, endpoint=False):
            for scale in (0, 0.5, 0.85):
                x, z = cx + math.cos(angle) * radius * scale, cz + math.sin(angle) * radius * scale
                assert world.ground_height(x, z) == pytest.approx(level), name


def test_cities_have_buildings_and_streets():
    for index, (name, cx, cz, radius, style, _) in enumerate(world.CITIES):
        place = (index, cx, cz, radius, world.CITY_LEVELS[index], style)
        heights = [world.lot_height(i, j, place)
                   for i in range(int((cx - radius) // 32), int((cx + radius) // 32), 3)
                   for j in range(int((cz - radius) // 32), int((cz + radius) // 32), 3)]
        assert sum(h > 0 for h in heights) > 20, name
        assert max(heights) <= world.STYLES[style][1] + 1e-6


def test_obstacles_include_buildings():
    city = world.CITIES[1]
    place = (1, city[1], city[2], city[3], world.CITY_LEVELS[1], city[4])
    i0, j0 = int(city[1] // 32), int(city[2] // 32)
    for i in range(i0 - 10, i0 + 10):
        for j in range(j0 - 10, j0 + 10):
            height = world.lot_height(i, j, place)
            if height > 50:
                x, z = (i + 0.5) * world.CELL, (j + 0.5) * world.CELL
                assert world.obstacle_height(x, z) == pytest.approx(world.CITY_LEVELS[1] + height)
                return
    pytest.fail('expected a tall downtown building')


def test_villages_are_deterministic_and_clear_of_cities():
    found = 0
    for cx in range(-10, 10):
        for cz in range(-10, 10):
            village = world.village_at((cx + 0.5) * world.VILLAGE_CELL, (cz + 0.5) * world.VILLAGE_CELL)
            if village:
                found += 1
                vx, vz, radius, level = village
                assert level >= world.WATER + 10
                for _, x, z, r, _, _ in world.CITIES:
                    assert math.hypot(vx - x, vz - z) >= r + 1800
    assert found > 20
