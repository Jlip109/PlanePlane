import numpy as np
import pygame
import pytest

from main import Atmosphere
from plane import PlaneModel


def test_gate_and_aircraft_share_gpu_depth(monkeypatch):
    pygame.display.quit()
    monkeypatch.delenv('SDL_VIDEODRIVER', raising=False)
    pygame.display.init()
    renderer = None
    try:
        from gpu_renderer import GPURenderer

        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
        pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
        try:
            pygame.display.set_mode((640, 360), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
            renderer = GPURenderer(pygame, offscreen=True)
        except (RuntimeError, pygame.error) as error:
            pytest.skip(f'OpenGL unavailable: {error}')
        renderer.set_plane(PlaneModel())
        atmosphere = Atmosphere(pygame)
        atmosphere.third_person = True
        size = (640, 360)

        def image(mesh=None):
            renderer.render(atmosphere, size, mesh)
            return pygame.surfarray.array3d(renderer.screenshot(size)).astype(int)

        aircraft = image()
        vao = renderer.plane_vao
        renderer.plane_vao = None
        background = image()
        renderer.plane_vao = vao
        mask = np.max(np.abs(aircraft - background), axis=2) > 5
        assert mask.sum() > 100

        def square(z):
            vertices = np.array([[-25,-25,z], [25,-25,z], [25,25,z],
                                 [-25,-25,z], [25,25,z], [-25,25,z]], dtype='f4')
            vertices[:, 1] += atmosphere.altitude
            return vertices, np.tile([0,0,-1], (6,1)).astype('f4'), np.tile([1,0,0], (6,1)).astype('f4')

        behind = image(square(40))
        assert np.array_equal(behind[mask], aircraft[mask])
        front = image(square(-25))
        red = (front[..., 0] > 240) & (front[..., 1] < 10) & (front[..., 2] < 10)
        assert red[mask].mean() > 0.95
        assert renderer.context.error == 'GL_NO_ERROR'
    finally:
        if renderer is not None:
            renderer.close()
        pygame.display.quit()
