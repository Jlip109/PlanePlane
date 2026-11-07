"""OpenGL atmosphere renderer. Textures stay on the GPU between frames."""

import math
from pathlib import Path

import moderngl
import numpy as np


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
        shake = math.sin(atmosphere.elapsed * 9) * atmosphere.wind * atmosphere.cover * 0.00012
        shake *= 1 + atmosphere.risk / 100
        uniforms = {
            'resolution': size, 'position': tuple(atmosphere.position),
            'drift': tuple(atmosphere.drift), 'altitude': atmosphere.altitude,
            'heading': atmosphere.heading + atmosphere.look_yaw, 'pitch': atmosphere.pitch + shake,
            'phase': atmosphere.phase, 'cover': atmosphere.cover,
            'sun_direction': tuple(atmosphere.sun_direction), 'ground_color': atmosphere.ground_color,
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
        self.context.release()
