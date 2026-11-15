"""Primitive mesh vertices and faces, independent of Blender context and operators."""

import math


def _build_cube_pydata(
    size: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    half = size / 2.0
    verts = [
        (-half, -half, -half),
        (half, -half, -half),
        (half, half, -half),
        (-half, half, -half),
        (-half, -half, half),
        (half, -half, half),
        (half, half, half),
        (-half, half, half),
    ]
    faces: list[tuple[int, ...]] = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return verts, faces


def _build_plane_pydata(
    size: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    half = size / 2.0
    verts = [
        (-half, -half, 0.0),
        (half, -half, 0.0),
        (half, half, 0.0),
        (-half, half, 0.0),
    ]
    return verts, [(0, 1, 2, 3)]


def _build_cylinder_pydata(
    size: float, segments: int = 24
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    radius = size / 2.0
    half_depth = size / 2.0
    verts: list[tuple[float, float, float]] = []
    for ring_z in (-half_depth, half_depth):
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            verts.append((radius * math.cos(angle), radius * math.sin(angle), ring_z))

    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append((i, nxt, segments + nxt, segments + i))
    faces.append(tuple(range(segments - 1, -1, -1)))
    faces.append(tuple(range(segments, 2 * segments)))
    return verts, faces


def _build_cone_pydata(
    size: float, segments: int = 24
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    radius = size / 2.0
    half_depth = size / 2.0
    verts: list[tuple[float, float, float]] = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), -half_depth))
    apex_index = len(verts)
    verts.append((0.0, 0.0, half_depth))

    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append((i, nxt, apex_index))
    faces.append(tuple(range(segments - 1, -1, -1)))
    return verts, faces


def _build_uv_sphere_pydata(
    size: float, segments: int = 24, rings: int = 12
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    radius = size / 2.0
    verts: list[tuple[float, float, float]] = [(0.0, 0.0, radius)]
    for ring in range(1, rings):
        phi = math.pi * ring / rings
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        for seg in range(segments):
            theta = 2.0 * math.pi * seg / segments
            verts.append(
                (
                    radius * sin_phi * math.cos(theta),
                    radius * sin_phi * math.sin(theta),
                    radius * cos_phi,
                )
            )
    bottom_index = len(verts)
    verts.append((0.0, 0.0, -radius))

    faces: list[tuple[int, ...]] = []
    for seg in range(segments):
        nxt = (seg + 1) % segments
        faces.append((0, 1 + nxt, 1 + seg))

    for ring in range(rings - 2):
        ring_start = 1 + ring * segments
        next_start = ring_start + segments
        for seg in range(segments):
            nxt = (seg + 1) % segments
            faces.append(
                (
                    ring_start + seg,
                    ring_start + nxt,
                    next_start + nxt,
                    next_start + seg,
                )
            )

    last_ring_start = 1 + (rings - 2) * segments
    for seg in range(segments):
        nxt = (seg + 1) % segments
        faces.append((last_ring_start + seg, last_ring_start + nxt, bottom_index))
    return verts, faces


def _build_torus_pydata(
    size: float, major_segments: int = 24, minor_segments: int = 12
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    major_radius = size * 0.35
    minor_radius = size * 0.15
    verts: list[tuple[float, float, float]] = []
    for major in range(major_segments):
        major_angle = 2.0 * math.pi * major / major_segments
        cos_major = math.cos(major_angle)
        sin_major = math.sin(major_angle)
        for minor in range(minor_segments):
            minor_angle = 2.0 * math.pi * minor / minor_segments
            ring = major_radius + minor_radius * math.cos(minor_angle)
            verts.append(
                (
                    ring * cos_major,
                    ring * sin_major,
                    minor_radius * math.sin(minor_angle),
                )
            )

    faces: list[tuple[int, ...]] = []
    for major in range(major_segments):
        major_next = (major + 1) % major_segments
        for minor in range(minor_segments):
            minor_next = (minor + 1) % minor_segments
            v0 = major * minor_segments + minor
            v1 = major * minor_segments + minor_next
            v2 = major_next * minor_segments + minor_next
            v3 = major_next * minor_segments + minor
            faces.append((v0, v1, v2, v3))
    return verts, faces


def build_primitive_pydata(
    mesh_type: str, size: float
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    builders = {
        "cube": _build_cube_pydata,
        "sphere": _build_uv_sphere_pydata,
        "cylinder": _build_cylinder_pydata,
        "plane": _build_plane_pydata,
        "cone": _build_cone_pydata,
        "torus": _build_torus_pydata,
    }
    builder = builders.get(mesh_type)
    if builder is None:
        raise ValueError(f"Unknown mesh type: {mesh_type}. Options: {list(builders.keys())}")
    return builder(size)
