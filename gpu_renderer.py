"""OpenGL atmosphere renderer. Textures stay on the GPU between frames."""

from pathlib import Path

import moderngl
import numpy as np

import world
from camera import view_angles


VERTEX_SHADER = """
#version 330
in vec2 in_position;
out vec2 uv;
void main() {
    uv = in_position * 0.5 + 0.5;
    gl_Position = vec4(in_position, 0.0, 1.0);
}
"""

SHADER_HEAD = """
#version 330
in vec2 uv;
out vec4 frag_color;
uniform sampler2D cloud_texture;
uniform sampler2D sky_palette;
uniform vec2 resolution;
uniform vec2 position;  // camera x/z
uniform vec2 drift;
uniform float altitude;  // camera height
uniform float heading;
uniform float pitch;
uniform float phase;
uniform float cover;
uniform vec3 sun_direction;
uniform vec3 moon_direction;
uniform float time;
uniform int season;
uniform vec4 layers[4]; // elevation, opacity, wind multiplier, texture offset
"""

SHADER_MAIN = """
// How much sunlight reaches world point p through the cloud decks above it.
float cloud_shadow(vec3 p) {
    if (sun_direction.y < 0.05) return 1.0;
    float light = 1.0;
    for (int i = 0; i < 4; ++i) {
        vec4 layer = layers[i];
        if (layer.x <= p.y) continue;
        vec2 q = p.xz + sun_direction.xz / sun_direction.y * (layer.x - p.y) - drift * layer.z;
        vec2 texel = q / 11.0 + vec2(layer.w, layer.w * 2.0);
        texel = 255.0 - abs(mod(texel, 510.0) - 255.0);
        float density = texture(cloud_texture, (texel + 0.5) / 256.0).r;
        float threshold = 0.83 - cover * 0.53 + layer.x / 3000.0 * 0.09;
        light *= 1.0 - smoothstep(threshold - 0.06, threshold + 0.20, density) * layer.y * 0.9;
    }
    return light;
}

// Nearest building hit among the cities the ray crosses and the villages near it.
bool trace_buildings(vec3 o, vec3 d, float t_limit, vec2 ground_point,
                     out float t_best, out vec3 n_best, out ivec2 cell_best, out float h_best, out vec4 a_best, out vec4 b_best) {
    t_best = t_limit;
    bool found = false;
    vec4 a, b;
    for (int i = 0; i < CITY_COUNT + 2; ++i) {
        if (i < CITY_COUNT) {
            a = CITY_A[i];
            b = CITY_B[i];
        } else {
            // the villages around the camera and around where the ray lands
            if (!village_at(i == CITY_COUNT ? o.xz : ground_point, a)) continue;
            if (i == CITY_COUNT + 1 && village_at(o.xz, b) && b.xy == a.xy) continue;
            b = STYLE_B[VILLAGE_STYLE];
        }
        vec2 oc = o.xz - a.xy;
        float qa = dot(d.xz, d.xz), qb = dot(oc, d.xz), qc = dot(oc, oc) - a.z * a.z;
        float disc = qb * qb - qa * qc;
        if (disc < 0.0 || qa < 1e-9) continue;
        float s = sqrt(disc);
        float t0 = (-qb - s) / qa, t1 = (-qb + s) / qa;
        float top = a.w + b.y + 1.0;
        if (abs(d.y) > 1e-6) {
            float ta = (a.w - o.y) / d.y, tb = (top - o.y) / d.y;
            t0 = max(t0, min(ta, tb));
            t1 = min(t1, max(ta, tb));
        } else if (o.y < a.w || o.y > top) {
            continue;
        }
        t0 = max(t0, 0.0);
        t1 = min(t1, t_best);
        float t;
        vec3 n;
        ivec2 cell;
        float h;
        if (t0 < t1 && trace_settlement(o, d, t0, t1, a, b, t, n, cell, h) && t < t_best) {
            t_best = t; n_best = n; cell_best = cell; h_best = h; a_best = a; b_best = b;
            found = true;
        }
    }
    return found;
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
        vec2 cell = floor(vec2(atan(direction.z, direction.x), asin(clamp(direction.y, -1.0, 1.0))) * 180.0);
        float hashed = fract(sin(cell.x * 12.9898 + cell.y * 78.233) * 43758.5453);
        float twinkle = 0.75 + 0.25 * sin(time * 3.0 + hashed * 400.0);
        sky += step(0.996, hashed) * smoothstep(0.0, 0.12, direction.y) * twinkle * night_sky
            * (1.0 - cover * 0.9) * 230.0 / 255.0;
    }

    float daylight = smoothstep(-0.12, 0.35, sun_direction.y);
    float night = smoothstep(0.55, 1.0, phase);
    // Warm low sun, white high sun; overcast skies trade direct light for soft ambient.
    vec3 sun_light = mix(vec3(1.0, 0.58, 0.34), vec3(1.0, 0.96, 0.90), smoothstep(0.02, 0.4, sun_direction.y))
        * daylight * (1.0 - cover * 0.55);
    vec3 ambient = mix(vec3(0.06, 0.075, 0.13) * (1.0 - cover * 0.5), vec3(0.36, 0.42, 0.52) * (0.85 + cover * 0.35), daylight);
    vec3 origin = vec3(position.x, altitude, position.y);
    vec3 dir3 = vec3(ray.x, dy, ray.y);
    float scene_t = 1e9;
    bool hit = false;
    vec3 surface = vec3(0.0);
    vec3 emit = vec3(0.0);
    vec2 ground_point = position;

    // Ground: iterate onto the height field, then fields, forests, lakes, roads and rooftops.
    if (dy < -0.008) {
        float distance = (100.0 - altitude) / dy;
        for (int step = 0; step < 4; ++step) {
            vec2 world = position + ray * distance;
            distance = max(0.0, (ground_height(world) - altitude) / dy);
        }
        vec2 world = position + ray * distance;
        float lamp;
        vec3 ground = land_color(world, distance, lamp);
        float e = 6.0 + distance * 0.004;
        vec3 normal = normalize(vec3(ground_height(world - vec2(e, 0.0)) - ground_height(world + vec2(e, 0.0)), 2.0 * e,
                                     ground_height(world - vec2(0.0, e)) - ground_height(world + vec2(0.0, e))));
        vec3 p = vec3(world.x, altitude + dy * distance, world.y);
        surface = ground * (ambient + sun_light * max(0.0, dot(normal, sun_direction)) * cloud_shadow(p));
        if (raw_terrain(world) < WATER && ground_height(world) <= WATER + 0.01 && season != 2) {
            // Lakes: Fresnel mix of deep water and the reflected sky, with a sun glint.
            vec2 ripple = vec2(sin(world.x * 0.09 + time * 1.3), sin(world.y * 0.11 - time)) * 0.015
                * (1.0 - smoothstep(300.0, 2000.0, distance));
            vec3 reflected = reflect(direction, normalize(vec3(ripple.x, 1.0, ripple.y)));
            vec2 reflect_uv = (vec2(clamp(phase, 0.0, 1.0), clamp(1.0 - reflected.y / 0.65, 0.0, 1.0)) * 63.0 + 0.5) / 64.0;
            vec3 sky_reflection = texture(sky_palette, reflect_uv).rgb * (1.0 - cover * 0.3);
            float fresnel = 0.08 + 0.92 * pow(1.0 - max(0.0, reflected.y), 4.0);
            surface = mix(vec3(0.03, 0.09, 0.12) * (ambient + sun_light * 0.4), sky_reflection, fresnel)
                + sun_color * pow(max(0.0, dot(reflected, sun_direction)), 220.0) * visibility * (1.0 - cover);
        }
        emit = vec3(1.0, 0.72, 0.38) * lamp * night * 0.9;
        scene_t = distance;
        ground_point = world;
        hit = true;
    }

    // Buildings: march the lot grid of any city or village the ray passes over.
    float t_hit;
    vec3 n_hit;
    ivec2 cell_hit;
    float h_hit;
    vec4 a_hit, b_hit;
    if (trace_buildings(origin, dir3, min(scene_t, 9000.0), ground_point, t_hit, n_hit, cell_hit, h_hit, a_hit, b_hit)) {
        vec3 p = origin + dir3 * t_hit;
        int style = int(b_hit.x + 0.5);
        bool glassy = style == 1 || style == 5;
        vec3 direct = sun_light * max(0.0, dot(n_hit, sun_direction)) * cloud_shadow(p);
        float range = t_hit * length(dir3);
        vec3 color;
        emit = vec3(0.0);
        float m = lot_margin(cell_hit);
        vec2 local = p.xz - vec2(cell_hit) * CELL;
        if (n_hit.y > 0.5) {
            color = (hash01(cell_hit.x, cell_hit.y, 37) > 0.5 ? ROOF_A[style] : ROOF_B[style])
                * (0.85 + 0.3 * hash01(cell_hit.x, cell_hit.y, 43));
            if (season == 2) color = mix(color, vec3(0.92), 0.7);
            // darker parapet around the roof edge
            float rim = min(min(local.x - m, CELL - m - local.x), min(local.y - m, CELL - m - local.y));
            color *= 0.75 + 0.25 * smoothstep(0.4, 1.4, rim);
            color *= ambient + direct;
            vec2 center = (vec2(cell_hit) + 0.5) * CELL;
            if (h_hit > 110.0 && distance(p.xz, center) < 2.5) {
                emit = vec3(1.0, 0.1, 0.05) * step(0.5, fract(time * 0.8 + hash01(cell_hit.x, cell_hit.y, 61)));
            }
        } else {
            vec3 wall = WALL[style] * (0.82 + 0.36 * hash01(cell_hit.x, cell_hit.y, 43));
            float u = abs(n_hit.x) > 0.5 ? p.z : p.x;
            float v = p.y - a_hit.w;
            vec2 w = vec2(u / (glassy ? 3.0 : 4.0), v / 3.6);
            vec2 f = fract(w);
            float fade = 1.0 - smoothstep(350.0, 1600.0, range);
            vec2 pane = glassy ? vec2(0.06, 0.12) : vec2(0.22, 0.28);
            float window = step(pane.x, f.x) * step(f.x, 1.0 - pane.x) * step(pane.y, f.y) * step(f.y, 0.86) * step(3.0, v);
            // Glass reflects the sky; brick and stone windows stay dark.
            vec3 view_reflect = reflect(direction, n_hit);
            vec2 sky_uv = (vec2(clamp(phase, 0.0, 1.0), clamp(1.0 - view_reflect.y / 0.65, 0.0, 1.0)) * 63.0 + 0.5) / 64.0;
            vec3 sky_reflection = texture(sky_palette, sky_uv).rgb * (1.0 - cover * 0.3);
            vec3 glass = mix(wall * 0.3 * (ambient + direct), sky_reflection * (0.35 + 0.65 * daylight), glassy ? 0.38 : 0.2);
            vec3 lit_wall = wall * (ambient + direct);
            color = mix(lit_wall, glass, mix(glassy ? 0.55 : 0.3, window * (glassy ? 0.8 : 0.9), fade));
            color *= 0.72 + 0.28 * smoothstep(0.0, 10.0, v);
            ivec2 wi = ivec2(floor(w)) + cell_hit * 41;
            float lit = mix(0.3, step(hash01(wi.x, wi.y, 51), 0.4) * window, fade);
            vec3 tint = mix(WINDOW_LIGHT[style], vec3(0.85, 0.9, 1.0), step(0.8, hash01(wi.x, wi.y, 52)));
            emit = tint * lit * night * 0.85;
        }
        surface = color;
        scene_t = t_hit;
        hit = true;
    }
    if (hit) {
        // Aerial perspective: exponential haze, warmer toward the sun.
        float range = scene_t * length(dir3);
        float haze = max(1.0 - exp(-range / (14000.0 - cover * 5000.0)), smoothstep(7000.0, 20000.0, range));
        vec3 haze_color = sky + sun_color * pow(max(0.0, alignment), 6.0) * 0.18 * visibility;
        sky = mix(surface, haze_color, haze) + emit * (1.0 - haze * 0.7);
    } else if (night > 0.0 && direction.y < 0.25) {
        // City glow on the horizon at night.
        for (int i = 0; i < CITY_COUNT; ++i) {
            vec3 to_city = vec3(CITY_A[i].x - position.x, CITY_A[i].w + 60.0 - altitude, CITY_A[i].y - position.y);
            float d = length(to_city);
            float near = pow(max(0.0, dot(direction, to_city / d)), 400.0 * CITY_A[i].z / max(d, 1.0) + 40.0);
            sky += vec3(1.0, 0.62, 0.32) * near * night * 0.35 * smoothstep(40000.0, 4000.0, d);
        }
    }

    float sunset = exp(-pow((phase - 0.48) / 0.17, 2.0));
    vec3 cloud_color = vec3(220.0, 228.0, 234.0) / 255.0 * (1.0 - night * 0.79);
    cloud_color = mix(cloud_color, vec3(242.0, 167.0, 134.0) / 255.0, sunset * 0.30);
    for (int i = 0; i < 4; ++i) {
        vec4 layer = layers[i];
        float delta = layer.x - altitude;
        // Only cloud layers in front of whatever surface this pixel already hit.
        if (abs(dy) > 0.008 && delta / dy > 0.0 && delta / dy < scene_t) {
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

ATMOSPHERE_SHADER = SHADER_HEAD + world.glsl_source() + SHADER_MAIN

SHADE_SHADER = """
#version 330
in vec2 uv;
out vec4 frag_color;
uniform vec3 strength; // top, bottom, left
void main() {
    float v = 1.0 - uv.y;
    float alpha = max(strength.x * pow(max(0.0, 1.0 - v / 0.19), 1.7),
                      strength.y * pow(max(0.0, (v - 0.78) / 0.22), 1.7));
    alpha = 1.0 - (1.0 - alpha) * (1.0 - strength.z * pow(max(0.0, 1.0 - uv.x / 0.62), 1.6));
    frag_color = vec4(0.024, 0.047, 0.078, alpha);
}
"""

SCENE_SHADER = """
#version 330
in vec2 uv;
out vec4 frag_color;
uniform sampler2D scene;
void main() {
    frag_color = texture(scene, uv);
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
    def __init__(self, pygame, offscreen=False):
        self.pg = pygame
        # Headless runs draw into an owned framebuffer: hidden windows may have no readable back buffer.
        self.offscreen = offscreen
        self.target = None
        self.context = moderngl.create_context(require=330)
        self.name = self.context.info['GL_RENDERER']
        self.program = self.context.program(vertex_shader=VERTEX_SHADER, fragment_shader=ATMOSPHERE_SHADER)
        self.hud_program = self.context.program(vertex_shader=VERTEX_SHADER, fragment_shader=HUD_SHADER)
        self.shade_program = self.context.program(vertex_shader=VERTEX_SHADER, fragment_shader=SHADE_SHADER)
        self.scene_program = self.context.program(vertex_shader=VERTEX_SHADER, fragment_shader=SCENE_SHADER)
        self.scene_program['scene'] = 3
        vertices = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        self.vertices = self.context.buffer(vertices.tobytes())
        self.quad = self.context.vertex_array(self.program, [(self.vertices, '2f', 'in_position')])
        self.hud_quad = self.context.vertex_array(self.hud_program, [(self.vertices, '2f', 'in_position')])
        self.shade_quad = self.context.vertex_array(self.shade_program, [(self.vertices, '2f', 'in_position')])
        self.scene_quad = self.context.vertex_array(self.scene_program, [(self.vertices, '2f', 'in_position')])
        # Dynamic resolution: the sky can render below window size on slower GPUs.
        self.scale = 1.0
        self.scene_texture = None
        self.scene_fbo = None
        self.slow_time = 0.0
        self.fast_time = 0.0
        assets = Path(__file__).parent / 'assets'
        self.cloud = self.load_texture(assets / 'Cloud.png')
        self.palette = self.load_texture(assets / 'skycolors.png')
        self.program['cloud_texture'] = 0
        self.program['sky_palette'] = 1
        self.hud_program['hud'] = 2
        self.hud_texture = None

    def load_texture(self, path):
        surface = self.pg.image.load(path)  # main.Atmosphere already checked the assets exist
        texture = self.context.texture(surface.get_size(), 3, self.pg.image.tobytes(surface, 'RGB'))
        texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        texture.repeat_x = texture.repeat_y = False
        return texture

    def bind_target(self, size):
        if not self.offscreen:
            self.context.screen.use()
            return
        if self.target is None or self.target.size != size:
            if self.target is not None:
                self.target.release()
            self.target = self.context.simple_framebuffer(size)
        self.target.use()

    def adapt(self, fps, dt):
        """Lower the sky's render scale when the frame rate sags, raise it again when there is headroom."""
        if fps <= 0:
            return
        self.slow_time = self.slow_time + dt if fps < 48 else 0.0
        self.fast_time = self.fast_time + dt if fps >= 58 else 0.0
        if self.slow_time > 1.5 and self.scale > 0.5:
            self.scale = round(max(0.5, self.scale - 0.125), 3)
            self.slow_time = 0.0
            self.fast_time = -6.0  # wait before trying to climb back up
        elif self.fast_time > 6.0 and self.scale < 1.0:
            self.scale = round(min(1.0, self.scale + 0.125), 3)
            self.fast_time = 0.0

    def scene_target(self, size):
        scaled = (max(1, int(size[0] * self.scale)), max(1, int(size[1] * self.scale)))
        if self.scene_texture is None or self.scene_texture.size != scaled:
            for resource in (self.scene_fbo, self.scene_texture):
                if resource is not None:
                    resource.release()
            self.scene_texture = self.context.texture(scaled, 3)
            self.scene_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.scene_fbo = self.context.framebuffer([self.scene_texture])
        return scaled

    def render(self, atmosphere, size):
        if self.scale < 0.999:
            scaled = self.scene_target(size)
            self.scene_fbo.use()
            self.context.viewport = (0, 0, *scaled)
            self.draw_sky(atmosphere, scaled)
            self.bind_target(size)
            self.context.viewport = (0, 0, *size)
            self.context.disable(moderngl.BLEND)
            self.scene_texture.use(3)
            self.scene_quad.render(moderngl.TRIANGLE_STRIP)
            return
        self.bind_target(size)
        self.context.viewport = (0, 0, *size)
        self.draw_sky(atmosphere, size)

    def draw_sky(self, atmosphere, size):
        self.context.disable(moderngl.BLEND)
        self.cloud.use(0)
        self.palette.use(1)
        heading, pitch = view_angles(atmosphere)
        camera_x, camera_y, camera_z = atmosphere.camera
        uniforms = {
            'resolution': size, 'position': (camera_x, camera_z),
            'drift': tuple(atmosphere.drift), 'altitude': camera_y, 'season': atmosphere.ground_mode,
            'heading': heading, 'pitch': pitch, 'time': atmosphere.elapsed,
            'phase': atmosphere.phase, 'cover': atmosphere.cover,
            'sun_direction': tuple(atmosphere.sun_direction), 'moon_direction': tuple(atmosphere.moon_direction),
        }
        for name, value in uniforms.items():
            self.program[name].value = value
        self.program['layers'].write(np.array(atmosphere.cloud_layers(), dtype='f4').tobytes())
        self.quad.render(moderngl.TRIANGLE_STRIP)

    def draw_shade(self, top, bottom, left):
        self.shade_program['strength'].value = (top, bottom, left)
        self.context.enable(moderngl.BLEND)
        self.context.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.shade_quad.render(moderngl.TRIANGLE_STRIP)

    def draw_hud(self, surface):
        """Composite an overlay whose colours are premultiplied by alpha."""
        size = surface.get_size()
        if self.hud_texture is None or self.hud_texture.size != size:
            if self.hud_texture is not None:
                self.hud_texture.release()
            self.hud_texture = self.context.texture(size, 4)
        self.hud_texture.write(self.pg.image.tobytes(surface, 'RGBA'))
        self.hud_texture.use(2)
        self.context.enable(moderngl.BLEND)
        self.context.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.hud_quad.render(moderngl.TRIANGLE_STRIP)

    def screenshot(self, size):
        if self.offscreen and self.target is not None:
            pixels = self.target.read(components=3, alignment=1)
            return self.pg.image.frombytes(pixels, self.target.size, 'RGB', True)
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
        for resource in [self.quad, self.hud_quad, self.shade_quad, self.shade_program, self.scene_quad,
                         self.scene_program, self.scene_fbo, self.scene_texture, self.vertices, self.program, self.hud_program,
                         self.cloud, self.palette, self.hud_texture, self.target]:
            if resource is not None:
                resource.release()
        self.context.release()
