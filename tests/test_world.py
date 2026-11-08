import numpy as np
import pytest
import world

VERTEX = """
#version 330
in vec2 in_position;
void main() { gl_Position = vec4(in_position, 0.0, 1.0); }
"""
PROBE_SHADER = """
#version 330
uniform int season;
out vec4 result;
""" + world.glsl_source() + """
void main() {
    vec2 p = (gl_FragCoord.xy - 16.0) * 137.0;
    float light;
    result = vec4(land_color(p, 100.0, light), ground_height(p));
}
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



@pytest.mark.parametrize('season', [0, 1, 2])
@pytest.mark.parametrize('temperature', [None,100,68,31,0])
def test_gpu_and_cpu_terrain_agree(gl, season, temperature):
    program = gl.program(vertex_shader=VERTEX, fragment_shader=PROBE_SHADER)
    quad = gl.buffer(np.array([-1,-1,1,-1,-1,1,1,1], dtype='f4').tobytes())
    vao = gl.vertex_array(program, [(quad, '2f', 'in_position')])
    target = gl.texture((32,32), 4, dtype='f4')
    fbo = gl.framebuffer([target]); fbo.use()
    program['season'] = season
    program['temperature_grass'] = temperature is not None
    program['temperature_f'] = temperature or 0
    vao.render(5)
    pixels = np.frombuffer(fbo.read(components=4, dtype='f4'), dtype='f4').reshape(32,32,4)
    y,x = np.mgrid[:32,:32]
    x,z = (x+.5-16)*137, (y+.5-16)*137
    colors,_ = world.land_color_np(x,z,np.ones(x.shape),season,0,temperature)
    assert np.allclose(pixels[:,:,:3],colors,atol=1e-5)
    assert np.allclose(pixels[:,:,3],world.ground_height_np(x,z),atol=.002)
    for resource in (fbo,target,vao,quad,program): resource.release()


def test_terrain_is_the_only_collision_surface():
    for x,z in [(0,3400),(4450,10300),(15400,2600),(-5500,-4500)]:
        assert world.obstacle_height(x,z) == max(world.raw_terrain(x,z),world.WATER)


def test_square_has_one_color():
    x,z = np.array([100.,110.,170.]),np.array([100.,110.,100.])
    color,_ = world.land_color_np(x,z,np.ones(3),0,0)
    assert np.array_equal(color[0],color[1])
    assert not np.array_equal(color[0],color[2])
