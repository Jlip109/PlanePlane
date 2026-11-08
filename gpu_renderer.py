"""OpenGL atmosphere renderer. Textures stay on the GPU between frames."""

from pathlib import Path
import math

import moderngl
import numpy as np

import world
from camera import view_angles, view_origin
from plane import plane_rotation, shadow_inverse


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
uniform bool wireframe;
uniform sampler2D aircraft_shadow;
uniform bool shadow_enabled;
uniform vec3 aircraft_position;
uniform vec2 shadow_size;
uniform mat2 shadow_inverse;
uniform vec4 layers[4]; // elevation, opacity, wind multiplier, texture offset
"""

SHADER_MAIN = """
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
        surface = ground * (ambient + sun_light * max(0.0, dot(normal, sun_direction)));
        if (shadow_enabled && sun_direction.y > 0.08) {
            float height = max(0.0, aircraft_position.y - p.y);
            vec2 delta = world + sun_direction.xz / sun_direction.y * height - aircraft_position.xz;
            vec2 local = shadow_inverse * delta;
            vec2 shadow_uv = local / shadow_size + 0.5;
            if (all(greaterThanEqual(shadow_uv, vec2(0.0))) && all(lessThanEqual(shadow_uv, vec2(1.0)))) {
                float softness = 0.12 + height * 0.015;
                float lod = clamp(log2(1.0 + softness * 256.0 / min(shadow_size.x,shadow_size.y)),0.0,8.0);
                float shade = textureLod(aircraft_shadow,shadow_uv,lod).r;
                surface *= 1.0 - shade * 0.55 / (1.0+height/700.0) * (1.0-cover*0.65);
            }
        }
        if (wireframe) {
            vec2 grid = world / 160.0;
            vec2 edge = abs(fract(grid - 0.5) - 0.5) / max(fwidth(grid), vec2(0.0001));
            float line = 1.0 - smoothstep(0.45, 1.3, min(edge.x, edge.y));
            surface = mix(vec3(0.015, 0.03, 0.045), vec3(0.25, 0.85, 0.66), line);
        }
        emit = vec3(1.0, 0.72, 0.38) * lamp * night * 0.9;
        scene_t = distance;
        ground_point = world;
        hit = true;
    }

    if (hit) {
        // Aerial perspective: exponential haze, warmer toward the sun.
        float range = scene_t * length(dir3);
        float haze = max(1.0 - exp(-range / (14000.0 - cover * 5000.0)), smoothstep(7000.0, 20000.0, range));
        vec3 haze_color = sky + sun_color * pow(max(0.0, alignment), 6.0) * 0.18 * visibility;
        sky = mix(surface, haze_color, haze) + emit * (1.0 - haze * 0.7);
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
    gl_FragDepth = hit ? clamp(0.5 + 0.5 * (20001.0 / 19999.0 - 40000.0 / (19999.0 * max(scene_t,1.0))),0.0,1.0) : 1.0;
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
    vec4 color = texture(hud, vec2(uv.x, 1.0 - uv.y));
    frag_color = vec4(color.rgb * color.a, color.a);
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
out vec3 world_position;
void main() {
    world_position = rotation * in_position + plane_center;
    vec3 p = world_position - camera_origin;
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
in vec3 world_position;
uniform vec3 sun_direction;
uniform float unlit;
uniform bool clip_terrain;
out vec4 frag_color;
void main() {
    float ground = max(15.0,100.0+130.0*sin(world_position.x/1700.0)*cos(world_position.z/1500.0));
    if (clip_terrain && world_position.y < ground) discard;
    float daylight = smoothstep(-0.12, 0.35, sun_direction.y);
    float light = 0.24 + daylight * (0.35 + 0.41 * max(0.0, dot(normalize(normal), sun_direction)));
    frag_color = vec4(color * mix(light, 1.0, unlit), 1.0);
}
"""


class GPURenderer:
    def __init__(self, pygame, offscreen=False):
        self.pg = pygame
        # Headless runs draw into an owned framebuffer: hidden windows may have no readable back buffer.
        self.offscreen = offscreen
        self.target = None
        self.context = moderngl.create_context(require=330)
        self.context.depth_func = '<='
        self.city_resources = []
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
        self.scene_depth = None
        self.slow_time = 0.0
        self.fast_time = 0.0
        self.plane_program = None
        self.plane_buffer = None
        self.plane_vao = None
        self.shadow_texture = None
        self.shadow_size = (1.0,1.0)
        self.gate_vao = None
        self.gate_buffer = None
        assets = Path(__file__).parent / 'assets'
        self.cloud = self.load_texture(assets / 'Cloud.png')
        self.palette = self.load_texture(assets / 'skycolors.png')
        self.program['cloud_texture'] = 0
        self.program['sky_palette'] = 1
        self.hud_program['hud'] = 2
        self.hud_texture = None
        self.panel_texture = None

    def set_plane(self, plane):
        if self.plane_program is None:
            self.plane_program = self.context.program(vertex_shader=PLANE_VERTEX_SHADER,
                                                       fragment_shader=PLANE_FRAGMENT_SHADER)
        for resource in (self.plane_vao,self.plane_buffer,self.shadow_texture):
            if resource is not None:
                resource.release()
        self.shadow_texture = self.context.texture((256,256),1,
            (plane.shadow_levels[0]*255).astype('u1').tobytes())
        self.shadow_texture.build_mipmaps()
        self.shadow_texture.repeat_x = self.shadow_texture.repeat_y = False
        self.shadow_texture.filter = (moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
        self.shadow_size = tuple(plane.shadow_size)
        data = np.concatenate((plane.positions, plane.normals, plane.colors), axis=1).astype('f4')
        self.plane_buffer = self.context.buffer(data.tobytes())
        self.plane_vao = self.context.vertex_array(
            self.plane_program, [(self.plane_buffer, '3f 3f 3f', 'in_position', 'in_normal', 'in_color')])

    def draw_gates(self, mesh, atmosphere, size):
        if mesh is None or self.plane_program is None:
            return
        positions, normals, colors = mesh
        data = np.concatenate(mesh, axis=1).astype('f4').tobytes()
        if self.gate_buffer is None:
            self.gate_buffer = self.context.buffer(reserve=len(data), dynamic=True)
            self.gate_vao = self.context.vertex_array(self.plane_program,
                [(self.gate_buffer, '3f 3f 3f', 'in_position', 'in_normal', 'in_color')])
        if self.gate_buffer.size < len(data):
            self.gate_buffer.orphan(len(data))
        self.gate_buffer.write(data)
        program = self.plane_program
        program['rotation'].write(np.eye(3, dtype='f4').tobytes())
        program['plane_center'] = (0,0,0)
        program['camera_origin'] = view_origin(atmosphere)
        program['camera_angles'] = view_angles(atmosphere)
        program['aspect'] = size[0] / size[1]
        program['sun_direction'] = tuple(atmosphere.sun_direction)
        program['unlit'] = 1.0
        program['clip_terrain'] = False
        self.context.enable(moderngl.DEPTH_TEST)
        self.context.wireframe = atmosphere.wireframe
        self.gate_vao.render(moderngl.TRIANGLES, vertices=len(positions))
        self.context.wireframe = False
        self.context.disable(moderngl.DEPTH_TEST)

    def clear_depth(self, size):
        target = self.target if self.offscreen else self.context.screen
        target.color_mask = (False,False,False,False)
        target.clear(depth=1.0)
        target.color_mask = (True,True,True,True)
        target.use()
        self.context.viewport = (0,0,*size)

    def set_cities(self, batches):
        for _,vao,buffer in self.city_resources:
            vao.release()
            buffer.release()
        self.city_resources = []
        for center,mesh in batches:
            data = np.concatenate(mesh,axis=1).astype('f4').tobytes()
            buffer = self.context.buffer(data)
            vao = self.context.vertex_array(self.plane_program,
                [(buffer,'3f 3f 3f','in_position','in_normal','in_color')])
            self.city_resources.append((center,vao,buffer))

    def draw_cities(self, atmosphere, size):
        if not self.city_resources:
            return
        origin = view_origin(atmosphere)
        program = self.plane_program
        program['rotation'].write(np.eye(3,dtype='f4').tobytes())
        program['plane_center'] = (0,0,0)
        program['camera_origin'] = origin
        program['camera_angles'] = view_angles(atmosphere)
        program['aspect'] = size[0]/size[1]
        program['sun_direction'] = tuple(atmosphere.sun_direction)
        program['unlit'] = 0.0
        program['clip_terrain'] = True
        self.context.enable(moderngl.DEPTH_TEST)
        self.context.wireframe = atmosphere.wireframe
        for center,vao,_ in self.city_resources:
            if math.hypot(center[0]-origin[0],center[1]-origin[2]) <= world.CITY_RENDER_DISTANCE+200:
                vao.render(moderngl.TRIANGLES)
        self.context.wireframe = False
        self.context.disable(moderngl.DEPTH_TEST)

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
        program['unlit'] = 0.0
        program['clip_terrain'] = False
        self.context.enable(moderngl.DEPTH_TEST)
        self.context.wireframe = atmosphere.wireframe
        self.plane_vao.render(moderngl.TRIANGLES)
        self.context.wireframe = False
        self.context.disable(moderngl.DEPTH_TEST)

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

    def adapt(self, fps, dt, target_fps=60):
        """Lower the sky's render scale when the frame rate sags, raise it again when there is headroom."""
        if fps <= 0:
            return
        self.slow_time = self.slow_time + dt if fps < target_fps * 0.8 else 0.0
        self.fast_time = self.fast_time + dt if fps >= target_fps * 58 / 60 else 0.0
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
            for resource in (self.scene_fbo, self.scene_texture, self.scene_depth):
                if resource is not None:
                    resource.release()
            self.scene_texture = self.context.texture(scaled, 3)
            self.scene_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.scene_depth = self.context.depth_renderbuffer(scaled)
            self.scene_fbo = self.context.framebuffer([self.scene_texture],self.scene_depth)
        return scaled

    def render(self, atmosphere, size, world_mesh=None):
        self.bind_target(size)
        self.clear_depth(size)
        if self.scale < 0.999:
            scaled = self.scene_target(size)
            self.scene_fbo.use()
            self.scene_fbo.clear(depth=1.0)
            self.context.viewport = (0, 0, *scaled)
            self.draw_sky(atmosphere, scaled)
            self.bind_target(size)
            target = self.target if self.offscreen else self.context.screen
            self.context.copy_framebuffer(target,self.scene_fbo)
            self.bind_target(size)
            self.context.viewport = (0, 0, *size)
            self.context.disable(moderngl.BLEND)
            self.scene_texture.use(3)
            self.scene_quad.render(moderngl.TRIANGLE_STRIP)
        else:
            self.bind_target(size)
            self.context.viewport = (0, 0, *size)
            self.draw_sky(atmosphere, size)
        # The aircraft always renders at full resolution, on top of the sky.
        self.draw_cities(atmosphere,size)
        self.draw_gates(world_mesh, atmosphere, size)
        self.draw_plane(atmosphere, size)

    def draw_sky(self, atmosphere, size):
        self.context.disable(moderngl.BLEND)
        self.cloud.use(0)
        self.palette.use(1)
        if self.shadow_texture is not None:
            self.shadow_texture.use(4)
        heading, pitch = view_angles(atmosphere)
        camera_x, camera_y, camera_z = atmosphere.camera
        uniforms = {
            'resolution': size, 'position': (camera_x, camera_z),
            'drift': tuple(atmosphere.drift), 'altitude': camera_y, 'season': atmosphere.ground_mode,
            'temperature_grass': atmosphere.temperature_f is not None,
            'temperature_f': atmosphere.temperature_f if atmosphere.temperature_f is not None else 0.0,
            'heading': heading, 'pitch': pitch, 'time': atmosphere.elapsed,
            'phase': atmosphere.phase, 'cover': atmosphere.cover,
            'sun_direction': tuple(atmosphere.sun_direction), 'moon_direction': tuple(atmosphere.moon_direction),
            'aircraft_shadow': 4, 'shadow_enabled': self.shadow_texture is not None,
            'aircraft_position': (atmosphere.position[0],atmosphere.altitude,atmosphere.position[1]),
            'shadow_size': self.shadow_size,
            'wireframe': atmosphere.wireframe,
        }
        for name, value in uniforms.items():
            self.program[name].value = value
        self.program['shadow_inverse'].write(shadow_inverse(atmosphere).tobytes(order='F'))
        self.program['layers'].write(np.array(atmosphere.cloud_layers(), dtype='f4').tobytes())
        self.context.enable(moderngl.DEPTH_TEST)
        self.quad.render(moderngl.TRIANGLE_STRIP)
        self.context.disable(moderngl.DEPTH_TEST)

    def draw_shade(self, top, bottom, left):
        self.shade_program['strength'].value = (top, bottom, left)
        self.context.enable(moderngl.BLEND)
        self.context.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.shade_quad.render(moderngl.TRIANGLE_STRIP)

    def draw_hud(self, surface, viewport=None):
        """Upload straight-alpha pixels directly and premultiply them on the GPU."""
        size = surface.get_size()
        name = 'panel_texture' if viewport is not None else 'hud_texture'
        texture = getattr(self, name)
        if texture is None or texture.size != size:
            if texture is not None:
                texture.release()
            texture = self.context.texture(size, 4)
            setattr(self, name, texture)
        if surface.get_shifts() == (16, 8, 0, 24):
            texture.swizzle = 'BGRA'
            texture.write(surface.get_buffer())
        else:
            texture.swizzle = 'RGBA'
            texture.write(self.pg.image.tobytes(surface, 'RGBA'))
        texture.use(2)
        previous_viewport = self.context.viewport
        if viewport is not None:
            self.context.viewport = viewport
        self.context.enable(moderngl.BLEND)
        self.context.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.hud_quad.render(moderngl.TRIANGLE_STRIP)
        self.context.viewport = previous_viewport

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
        for _,vao,buffer in self.city_resources:
            vao.release()
            buffer.release()
        for resource in [self.quad, self.hud_quad, self.shade_quad, self.shade_program, self.scene_quad,
                         self.scene_program, self.scene_fbo, self.scene_texture, self.scene_depth, self.vertices, self.program, self.hud_program,
                         self.plane_vao, self.plane_buffer, self.plane_program, self.gate_vao, self.gate_buffer,
                         self.cloud, self.palette, self.hud_texture, self.panel_texture, self.target, self.shadow_texture]:
            if resource is not None:
                resource.release()
        self.context.release()
