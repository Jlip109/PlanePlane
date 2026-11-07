"""OpenGL atmosphere renderer. Textures stay on the GPU between frames."""

import math
from pathlib import Path

import moderngl
import numpy as np

from camera import view_angles, view_origin
from plane import plane_rotation


VERTEX_SHADER = """
#version 330
in vec2 in_position;
out vec2 uv;
void main() {
    uv = in_position * 0.5 + 0.5;
    gl_Position = vec4(in_position, 0.0, 1.0);
}
"""

ATMOSPHERE_SHADER = """
#version 330
in vec2 uv;
out vec4 frag_color;
uniform sampler2D cloud_texture;
uniform sampler2D sky_palette;
uniform vec2 resolution;
uniform vec2 position;
uniform vec2 drift;
uniform float altitude;
uniform float heading;
uniform float pitch;
uniform float phase;
uniform float cover;
uniform vec3 sun_direction;
uniform vec3 moon_direction;
uniform float time;
uniform vec3 ground_color;
uniform vec4 layers[4]; // elevation, opacity, wind multiplier, texture offset

float terrain_height(vec2 p) {
    return 100.0 + 130.0 * sin(p.x / 1700.0) * cos(p.y / 1500.0);
}

void main() {
    // Keep the original 16:9 field of view, including when resized.
    vec2 screen = (uv - 0.5) * vec2(resolution.x / resolution.y, 1.0) / 0.924444;
    float dy = screen.y * cos(pitch) + sin(pitch);
    float forward = cos(pitch) - screen.y * sin(pitch);
    vec2 ray = vec2(screen.x * cos(heading) + forward * sin(heading),
                    forward * cos(heading) - screen.x * sin(heading));
    vec2 palette_uv = (vec2(clamp(phase, 0.0, 1.0),
        clamp(1.0 - dy / 0.65, 0.0, 1.0)) * 63.0 + 0.5) / 64.0;
    vec3 sky = texture(sky_palette, palette_uv).rgb;
    sky = mix(sky, vec3((sky.r + sky.g + sky.b) / 3.0), cover * 0.68);
    sky *= 1.0 - cover * 0.21;

    vec3 direction = normalize(vec3(ray.x, dy, ray.y));
    float alignment = dot(direction, sun_direction);
    float disk = smoothstep(cos(0.025), cos(0.019), alignment);
    float glow = exp((alignment - 1.0) * 160.0) * 0.25;
    float visibility = smoothstep(-0.035, 0.02, sun_direction.y);
    vec3 sun_color = vec3(1.0, (205.0 + 45.0 * max(0.0, sun_direction.y)) / 255.0,
        (125.0 + 110.0 * max(0.0, sun_direction.y)) / 255.0);
    sky = mix(sky, sun_color, disk * visibility) + sun_color * glow * visibility;

    // Moon opposite the sun, plus hashed stars; both must match star_field() in main.py.
    float night_sky = smoothstep(0.55, 1.0, phase);
    if (night_sky > 0.0) {
        float moon = smoothstep(cos(0.022), cos(0.017), dot(direction, moon_direction)) * night_sky * (1.0 - cover * 0.6);
        sky = mix(sky, vec3(226.0, 232.0, 240.0) / 255.0, moon);
        vec2 angular = vec2(atan(direction.z, direction.x), asin(clamp(direction.y, -1.0, 1.0))) * 180.0;
        vec2 cell = floor(angular);
        float hashed = fract(sin(cell.x * 12.9898 + cell.y * 78.233) * 43758.5453);
        float twinkle = 0.75 + 0.25 * sin(time * 3.0 + hashed * 400.0);
        float spot = 1.0 - smoothstep(0.14, 0.27, length(fract(angular) - 0.5));
        sky += step(0.996, hashed) * spot * smoothstep(0.0, 0.12, direction.y) * twinkle * night_sky
            * (1.0 - cover * 0.9) * 230.0 / 255.0;
    }

    // Intersect the terrain height field, then draw antialiased world-space grid lines.
    if (dy < -0.008) {
        float distance = (100.0 - altitude) / dy;
        for (int step = 0; step < 4; ++step) {
            vec2 world = position + ray * distance;
            distance = max(0.0, (terrain_height(world) - altitude) / dy);
        }
        vec2 world = position + ray * distance;
        vec2 grid = world / 420.0;
        vec2 edge = abs(fract(grid - 0.5) - 0.5) / max(fwidth(grid), vec2(0.0001));
        float line = 1.0 - smoothstep(0.45, 1.3, min(edge.x, edge.y));
        vec3 normal = normalize(vec3(-130.0 / 1700.0 * cos(world.x / 1700.0) * cos(world.y / 1500.0),
            1.0, 130.0 / 1500.0 * sin(world.x / 1700.0) * sin(world.y / 1500.0)));
        float daylight = smoothstep(-0.12, 0.35, sun_direction.y);
        float light = 0.09 + daylight * (0.45 + 0.46 * max(0.0, dot(normal, sun_direction)));
        vec3 ground = ground_color * light * (1.0 - line * 0.28);
        sky = mix(ground, sky, smoothstep(2500.0, 18000.0, distance));
    }

    float night = smoothstep(0.55, 1.0, phase);
    float sunset = exp(-pow((phase - 0.48) / 0.17, 2.0));
    vec3 cloud_color = vec3(220.0, 228.0, 234.0) / 255.0 * (1.0 - night * 0.79);
    cloud_color = mix(cloud_color, vec3(242.0, 167.0, 134.0) / 255.0, sunset * 0.30);
    for (int i = 0; i < 4; ++i) {
        vec4 layer = layers[i];
        float delta = layer.x - altitude;
        if (abs(dy) > 0.008 && delta / dy > 0.0) {
            float distance = min(delta / dy, 20000.0);
            vec2 world = position + ray * distance - drift * layer.z;
            vec2 texel = world / 11.0 + vec2(layer.w, layer.w * 2.0);
            // Mirror each repeat to match the CPU renderer's seamless sampling.
            texel = 255.0 - abs(mod(texel, 510.0) - 255.0);
            float density = texture(cloud_texture, (texel + 0.5) / 256.0).r;
            float threshold = 0.83 - cover * 0.53 + layer.x / 3000.0 * 0.09;
            float alpha = smoothstep(threshold - 0.06, threshold + 0.20, density);
            alpha *= layer.y * (1.0 - smoothstep(6000.0, 18000.0, distance));
            sky = mix(sky, cloud_color * (0.70 + density * 0.30), alpha);
        }
        float fog = exp(-pow(delta / 95.0, 2.0)) * cover * layer.y * 0.75;
        sky = mix(sky, cloud_color, fog);
    }
    frag_color = vec4(sky, 1.0);
}
"""

HUD_SHADER = """
#version 330
in vec2 uv;
out vec4 frag_color;
uniform sampler2D hud;
void main() {
    frag_color = texture(hud, vec2(uv.x, 1.0 - uv.y));
}
"""

PLANE_VERTEX_SHADER = """
#version 330
in vec3 in_position;
in vec3 in_normal;
in vec3 in_color;
uniform mat3 rotation;
uniform vec3 plane_center;
uniform vec3 camera_origin;
uniform vec2 camera_angles;
uniform float aspect;
out vec3 normal;
out vec3 color;
void main() {
    vec3 p = rotation * in_position + plane_center - camera_origin;
    float sh = sin(camera_angles.x), ch = cos(camera_angles.x);
    float sp = sin(camera_angles.y), cp = cos(camera_angles.y);
    float depth = p.x * sh * cp + p.y * sp + p.z * ch * cp;
    float side = p.x * ch - p.z * sh;
    float up = -p.x * sh * sp + p.y * cp - p.z * ch * sp;
    // Perspective projection with a one-metre near plane and 20 km far plane.
    gl_Position = vec4(side * 1.848888 / aspect, up * 1.848888,
                       depth * 20001.0 / 19999.0 - 40000.0 / 19999.0, depth);
    normal = rotation * in_normal;
    color = in_color;
}
"""

PLANE_FRAGMENT_SHADER = """
#version 330
in vec3 normal;
in vec3 color;
uniform vec3 sun_direction;
out vec4 frag_color;
void main() {
    float daylight = smoothstep(-0.12, 0.35, sun_direction.y);
    float light = 0.24 + daylight * (0.35 + 0.41 * max(0.0, dot(normalize(normal), sun_direction)));
    frag_color = vec4(color * light, 1.0);
}
"""


class GPURenderer:
    def __init__(self, pygame):
        self.pg = pygame
        self.context = moderngl.create_context(require=330)
        self.name = self.context.info['GL_RENDERER']
        self.program = self.context.program(vertex_shader=VERTEX_SHADER, fragment_shader=ATMOSPHERE_SHADER)
        self.hud_program = self.context.program(vertex_shader=VERTEX_SHADER, fragment_shader=HUD_SHADER)
        vertices = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        self.vertices = self.context.buffer(vertices.tobytes())
        self.quad = self.context.vertex_array(self.program, [(self.vertices, '2f', 'in_position')])
        self.hud_quad = self.context.vertex_array(self.hud_program, [(self.vertices, '2f', 'in_position')])
        assets = Path(__file__).parent / 'assets'
        self.cloud = self.load_texture(assets / 'Cloud.png')
        self.palette = self.load_texture(assets / 'skycolors.png')
        self.program['cloud_texture'] = 0
        self.program['sky_palette'] = 1
        self.hud_program['hud'] = 2
        self.hud_texture = None
        self.plane_program = None
        self.plane_buffer = None
        self.plane_vao = None

    def set_plane(self, plane):
        self.plane_program = self.context.program(vertex_shader=PLANE_VERTEX_SHADER,
                                                   fragment_shader=PLANE_FRAGMENT_SHADER)
        data = np.concatenate((plane.positions, plane.normals, plane.colors), axis=1).astype('f4')
        self.plane_buffer = self.context.buffer(data.tobytes())
        self.plane_vao = self.context.vertex_array(self.plane_program,
            [(self.plane_buffer, '3f 3f 3f', 'in_position', 'in_normal', 'in_color')])

    def draw_plane(self, atmosphere, size):
        if self.plane_vao is None or not atmosphere.third_person:
            return
        program = self.plane_program
        program['rotation'].write(plane_rotation(atmosphere).tobytes(order='F'))
        program['plane_center'] = (atmosphere.position[0], atmosphere.altitude, atmosphere.position[1])
        program['camera_origin'] = view_origin(atmosphere)
        program['camera_angles'] = view_angles(atmosphere)
        program['aspect'] = size[0] / size[1]
        program['sun_direction'] = tuple(atmosphere.sun_direction)
        # Clear only depth, retaining the atmosphere already rendered into the colour buffer.
        self.context.screen.color_mask = (False, False, False, False)
        self.context.screen.clear(depth=1.0)
        self.context.screen.color_mask = (True, True, True, True)
        self.context.screen.use()
        self.context.enable(moderngl.DEPTH_TEST)
        self.plane_vao.render(moderngl.TRIANGLES)
        self.context.disable(moderngl.DEPTH_TEST)

    def load_texture(self, path):
        surface = self.pg.image.load(path)
        texture = self.context.texture(surface.get_size(), 3, self.pg.image.tobytes(surface, 'RGB'))
        texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        texture.repeat_x = texture.repeat_y = False
        return texture

    def render(self, atmosphere, size):
        self.context.viewport = (0, 0, *size)
        self.context.disable(moderngl.BLEND)
        self.cloud.use(0)
        self.palette.use(1)
        heading, pitch = view_angles(atmosphere)
        origin = view_origin(atmosphere)
        uniforms = {
            'resolution': size, 'position': (origin[0], origin[2]),
            'drift': tuple(atmosphere.drift), 'altitude': origin[1],
            'heading': heading, 'pitch': pitch, 'time': atmosphere.elapsed,
            'phase': atmosphere.phase, 'cover': atmosphere.cover,
            'sun_direction': tuple(atmosphere.sun_direction), 'moon_direction': tuple(atmosphere.moon_direction),
            'ground_color': atmosphere.ground_color,
        }
        for name, value in uniforms.items():
            self.program[name].value = value
        layers = []
        for base, opacity, speed, seed in [(850, .52, .85, 24), (1450, .43, 1, 97),
                                           (2150, .32, 1.23, 161), (3000, .20, 1.5, 233)]:
            elevation = base + math.sin(atmosphere.elapsed * .065 + seed) * (35 + atmosphere.cover * 65)
            layers.append((elevation, opacity, speed, seed))
        layers.sort(key=lambda layer: abs(layer[0] - atmosphere.altitude), reverse=True)
        self.program['layers'].write(np.array(layers, dtype='f4').tobytes())
        self.quad.render(moderngl.TRIANGLE_STRIP)
        self.draw_plane(atmosphere, size)

    def draw_hud(self, surface):
        size = surface.get_size()
        if self.hud_texture is None or self.hud_texture.size != size:
            if self.hud_texture is not None:
                self.hud_texture.release()
            self.hud_texture = self.context.texture(size, 4)
        self.hud_texture.write(self.pg.image.tobytes(surface, 'RGBA'))
        self.hud_texture.use(2)
        self.context.enable(moderngl.BLEND)
        self.context.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.hud_quad.render(moderngl.TRIANGLE_STRIP)

    def screenshot(self, size):
        # Read an owned framebuffer to avoid default-buffer readback errors on Windows.
        capture = self.context.simple_framebuffer(size)
        try:
            self.context.copy_framebuffer(capture, self.context.screen)
            pixels = capture.read(components=3, alignment=1)
        finally:
            capture.release()
            self.context.screen.use()
            self.context.viewport = (0, 0, *size)
        return self.pg.image.frombytes(pixels, size, 'RGB', True)

    def close(self):
        for resource in [self.quad, self.hud_quad, self.vertices, self.program, self.hud_program,
                         self.cloud, self.palette, self.hud_texture]:
            if resource is not None:
                resource.release()
        for resource in [self.plane_vao, self.plane_buffer, self.plane_program]:
            if resource is not None:
                resource.release()
        self.context.release()
