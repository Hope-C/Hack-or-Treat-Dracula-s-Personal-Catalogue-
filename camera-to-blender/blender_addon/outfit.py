"""
Dress a Tripo avatar in 3D garments.

Garments are built from the avatar's own body shape, so they fit any scan:
- shells (shirts, waistcoats, trousers, sleeves) are body regions pushed outward
- lofts (capes, coat skirts, collars) are rings that fall from the shoulders or hips
- accessories (cravats, bow ties, chains) are small shapes at the neck

Proportions assume a standing, Z-up, full-body avatar (what Tripo returns).
Which way it faces is detected from the shoulder line and where the feet point.
"""
import math
from bisect import bisect_left, bisect_right

import bpy
import bmesh
from mathutils import Matrix, Vector

OUTFIT_COLLECTION = "Dracula Outfit"
AVATAR_PROP = "dracula_avatar"
FLIP_PROP = "dracula_flip_front"  # scene flag: the avatar's front was guessed wrong

# Fabric looks. Colors are linear-ish RGB taken from the catalogue palette.
FABRICS = {
    "velvet":   dict(color="#5c0f1d", roughness=0.75, sheen=1.0),
    "silk":     dict(color="#9e1b32", roughness=0.30, sheen=0.4),
    "jacquard": dict(color="#5a189a", roughness=0.40, sheen=0.4),
    "leather":  dict(color="#121214", roughness=0.35),
    "tweed":    dict(color="#6b5440", roughness=0.95),
    "knit":     dict(color="#6b5440", roughness=0.95, sheen=0.3),
    "cashmere": dict(color="#a89f91", roughness=0.90, sheen=0.5),
    "merino":   dict(color="#2e2b33", roughness=0.90, sheen=0.3),
    "wool":     dict(color="#1c1a20", roughness=0.90),
    "denim":    dict(color="#15151a", roughness=0.90),
    "cotton":   dict(color="#f1e6d6", roughness=0.80),
    "tee":      dict(color="#0b0a0d", roughness=0.85),
    "gothic":   dict(color="#141018", roughness=0.60, sheen=0.3),
    "brocade":  dict(color="#7a1426", roughness=0.45, sheen=0.5),
    "silver":   dict(color="#c0c0c8", roughness=0.20, metallic=1.0),
}

# (keywords, garment kind, fabric) checked in order, first match wins
GARMENT_RULES = [
    (("cape", "cloak"), "cape", None),
    (("waistcoat", "vest"), "vest", None),
    (("overcoat",), "long_coat", None),
    (("frock", "tailcoat"), "frock_coat", None),
    (("coat", "blazer", "jacket"), "jacket", None),
    (("turtleneck", "mock-neck"), "turtleneck", None),
    (("tee", "t-shirt"), "tee", "tee"),
    (("shirt", "knit", "sweater"), "shirt", "cotton"),
    (("trouser", "denim", "jeans", "pants"), "trousers", "wool"),
    (("cravat", "jabot", "scarf"), "cravat", "silk"),
    (("bow",), "bow_tie", "silk"),
    (("chain", "necklace", "pendant", "medallion"), "chains", "silver"),
]

FABRIC_KEYWORDS = [
    "velvet", "silk", "jacquard", "leather", "tweed", "cashmere", "merino",
    "denim", "silver", "knit", "gothic", "wool",
]

# Where each kind sits on the body, as fractions of avatar height.
# offset = gap between skin and garment, so layers stack in the right order.
SHELLS = {
    "shirt":      dict(top=0.83, bottom=0.48, sleeve=0.49, arms=True,  offset=0.006),
    "tee":        dict(top=0.82, bottom=0.48, sleeve=0.66, arms=True,  offset=0.006),
    "turtleneck": dict(top=0.86, bottom=0.48, sleeve=0.49, arms=True,  offset=0.007),
    "vest":       dict(top=0.78, bottom=0.50, sleeve=None, arms=False, offset=0.011),
    "jacket":     dict(top=0.83, bottom=0.44, sleeve=0.49, arms=True,  offset=0.016, open=True),
    "frock_coat": dict(top=0.84, bottom=0.48, sleeve=0.49, arms=True,  offset=0.016, open=True, skirt=0.28),
    "long_coat":  dict(top=0.85, bottom=0.48, sleeve=0.48, arms=True,  offset=0.018, open=True, skirt=0.20),
    "trousers":   dict(top=0.54, bottom=0.035, offset=0.006),
}

TORSO_HALF_WIDTH = 0.12   # |x| beyond this (in heights) is arm, not torso
HIP_HALF_WIDTH = 0.10     # keeps hanging hands out of the trousers
HANDS_TOP = 0.50
HANDS_BOTTOM = 0.36


def classify(name):
    """Return (kind, fabric) for a catalogue garment name, or (None, None)."""
    low = name.lower()
    for keywords, kind, default_fabric in GARMENT_RULES:
        if any(k in low for k in keywords):
            fabric = next((f for f in FABRIC_KEYWORDS if f in low), None)
            if kind in ("vest",) and fabric is None:
                fabric = "brocade"
            if kind in ("jacket", "frock_coat", "long_coat", "cape") and fabric is None:
                fabric = "gothic"
            if kind == "chains":
                fabric = "silver"
            return kind, fabric or default_fabric or "wool"
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Avatar analysis
# ─────────────────────────────────────────────────────────────────────────────
VOXELS_PER_HEIGHT = 220  # remesh resolution; Tripo scans can be ~800k verts, garments need far less


def merged_world_mesh(objects):
    """
    One light, watertight mesh of the avatar in world space.

    A voxel remesh is much faster than decimating a raw scan, welds its UV seams
    (so pushing along normals can't tear it) and irons out small scan noise.
    """
    bm = bmesh.new()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        tmp = bpy.data.objects.new("_avatar_tmp", obj.data)
        tmp.matrix_world = obj.matrix_world
        bpy.context.scene.collection.objects.link(tmp)
        mod = tmp.modifiers.new("Remesh", "REMESH")
        mod.mode = "VOXEL"
        mod.voxel_size = max(obj.dimensions) / VOXELS_PER_HEIGHT / max(obj.scale)
        depsgraph.update()
        mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph))
        bpy.data.objects.remove(tmp, do_unlink=True)
        mesh.transform(obj.matrix_world)
        bm.from_mesh(mesh)
        bpy.data.meshes.remove(mesh)
    if not bm.verts:
        bm.free()
        raise ValueError("Avatar has no vertices")
    mesh = bpy.data.meshes.new("_avatar_tmp")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


class Body:
    """
    The avatar's surface in a canonical frame: shoulders along X, facing -Y, Z up.
    Garments are built in this frame; `to_world` puts them back on the avatar.
    """

    def __init__(self, objects, flip=False):
        mesh = merged_world_mesh(objects)
        self.bm = bmesh.new()
        self.bm.from_mesh(mesh)
        bpy.data.meshes.remove(mesh)

        zs = [v.co.z for v in self.bm.verts]
        self.z0 = min(zs)
        self.h = max(zs) - self.z0
        self._index()

        torso = self.band(0.55, 0.78)
        self.cx = sum(p.x for p in torso) / len(torso)
        self.cy = sum(p.y for p in torso) / len(torso)

        # Shoulder line = main horizontal axis of the chest-and-arms band
        sxx = sum((p.x - self.cx) ** 2 for p in torso)
        syy = sum((p.y - self.cy) ** 2 for p in torso)
        sxy = sum((p.x - self.cx) * (p.y - self.cy) for p in torso)
        angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
        center = Vector((self.cx, self.cy, 0))
        to_canon = Matrix.Translation(center) @ Matrix.Rotation(-angle, 4, "Z") @ Matrix.Translation(-center)
        bmesh.ops.transform(self.bm, matrix=to_canon, verts=self.bm.verts)
        self._index()

        # The head sits forward of the chest (hair hangs behind, the face juts out).
        # Turn the body round if the head leans to +Y, or if the user flipped it.
        head = self.band(0.86, 0.95) or torso
        head_back = sum(p.y for p in head) / len(head) > self.cy
        if head_back != bool(flip):
            turn = Matrix.Translation(center) @ Matrix.Rotation(math.pi, 4, "Z") @ Matrix.Translation(-center)
            bmesh.ops.transform(self.bm, matrix=turn, verts=self.bm.verts)
            to_canon = turn @ to_canon
            self._index()

        self.front = -1.0
        self.to_world = to_canon.inverted()
        self.bm.normal_update()

    def _index(self):
        """Points sorted by height, for fast band lookups."""
        self.pts = sorted((v.co.copy() for v in self.bm.verts), key=lambda p: p.z)
        self.zs = [p.z for p in self.pts]

    def z(self, frac):
        return self.z0 + frac * self.h

    def band(self, lo, hi):
        return self.pts[bisect_left(self.zs, self.z(lo)):bisect_right(self.zs, self.z(hi))]

    def free(self):
        self.bm.free()

    def ring_radii(self, frac, bins, angles, band=0.02, max_dx=None):
        """Body envelope radius around the center axis at one height, per angle."""
        best = [0.0] * bins
        step = 2 * math.pi / bins
        for p in self.band(frac - band, frac + band):
            dx, dy = p.x - self.cx, (p.y - self.cy) * -self.front  # +dy = back
            if max_dx is not None and abs(dx) > max_dx:
                continue
            r = math.hypot(dx, dy)
            i = int((math.atan2(dy, dx) % (2 * math.pi)) / step) % bins
            if r > best[i]:
                best[i] = r
        # Fill empty bins from their nearest filled neighbours
        filled = [i for i in range(bins) if best[i] > 0]
        if not filled:
            return [self.h * 0.1 for _ in angles]
        out = []
        for a in angles:
            i = int((a % (2 * math.pi)) / step) % bins
            if best[i] == 0:
                i = min(filled, key=lambda j: min(abs(j - i), bins - abs(j - i)))
            out.append(best[i])
        return out

    def point(self, angle, radius, z):
        """World point at an angle around the body axis (+90 deg = back)."""
        return Vector((
            self.cx + math.cos(angle) * radius,
            self.cy + math.sin(angle) * radius * -self.front,
            z,
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Garment builders (each returns a bmesh in world space)
# ─────────────────────────────────────────────────────────────────────────────
def build_shell(body, spec):
    """Cut a region out of the body surface and push it outward."""
    bm = body.bm.copy()
    h, cx = body.h, body.cx
    top, bottom = body.z(spec["top"]), body.z(spec["bottom"])
    is_trousers = "arms" not in spec
    sleeve = body.z(spec["sleeve"]) if spec.get("sleeve") else None

    def keep(co):
        if not (bottom <= co.z <= top):
            return False
        dx = abs(co.x - cx)
        if spec.get("open") and co.y < body.cy:
            # Open front: a V that widens into lapels, showing what's underneath
            t = min(1.0, max(0.0, ((co.z - body.z0) / h - 0.50) / 0.32))
            if dx < h * (0.022 + 0.045 * t):
                return False
        if is_trousers:
            in_hands = body.z(HANDS_BOTTOM) <= co.z <= body.z(HANDS_TOP)
            return not (in_hands and dx > h * HIP_HALF_WIDTH)
        if dx <= h * TORSO_HALF_WIDTH:
            return True
        return spec["arms"] and sleeve is not None and co.z >= sleeve

    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not keep(v.co)], context="VERTS")
    offset = h * spec["offset"]
    for v in bm.verts:
        v.co += v.normal * offset
    return bm


def add_loft(bm, body, rows, angles, closed):
    """Add a sheet through rings of (z, radii) to bm. rows run top to bottom."""
    grid = [[bm.verts.new(body.point(a, r, z)) for a, r in zip(angles, radii)] for z, radii in rows]
    cols = len(angles) if closed else len(angles) - 1
    for i in range(len(rows) - 1):
        for j in range(cols):
            k = (j + 1) % len(angles)
            bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][k], grid[i][k]))


def draped_rows(body, top, bottom, angles, margin, flare, steps=24, max_dx=None):
    """Rings that fall straight down from `top`, never cutting back into the body."""
    rows, envelope = [], None
    for s in range(steps + 1):
        t = s / steps
        frac = top + (bottom - top) * t
        radii = body.ring_radii(frac, 48, angles, max_dx=max_dx)
        envelope = radii if envelope is None else [max(a, b) for a, b in zip(envelope, radii)]
        rows.append((body.z(frac), [r + body.h * (margin + flare * t * t) for r in envelope]))
    return rows


def build_cape(body, length):
    bm = bmesh.new()
    # Back half plus a little wrap round the front of each shoulder
    angles = [-0.35 + (math.pi + 0.7) * i / 32 for i in range(33)]
    add_loft(bm, body, draped_rows(body, 0.82, length, angles, margin=0.024, flare=0.05), angles, closed=False)
    # The high standing collar, rising behind the head
    collar_angles = [0.35 + (math.pi - 0.7) * i / 20 for i in range(21)]
    neck = body.ring_radii(0.83, 48, collar_angles)
    rows = [(body.z(0.82 + 0.08 * t), [r + body.h * (0.02 + 0.035 * t) for r in neck]) for t in (0, 0.33, 0.66, 1.0)]
    add_loft(bm, body, list(reversed(rows)), collar_angles, closed=False)
    return bm


def build_coat(body, spec):
    bm = build_shell(body, spec)
    if spec.get("skirt"):
        # All the way round except a gap at the front (front is -90 deg)
        gap = 0.3
        angles = [-math.pi / 2 + gap + (2 * math.pi - 2 * gap) * i / 40 for i in range(41)]
        rows = draped_rows(body, spec["bottom"] + 0.02, spec["skirt"], angles,
                           margin=spec["offset"], flare=0.025, steps=16)
        add_loft(bm, body, rows, angles, closed=False)
    return bm


def neck_front(body):
    """Point on the front of the neck, just under the chin."""
    pts = [p for p in body.band(0.80, 0.84) if abs(p.x - body.cx) < body.h * 0.06] or body.band(0.78, 0.86)
    y = min(p.y for p in pts) if body.front < 0 else max(p.y for p in pts)
    return Vector((body.cx, y, body.z(0.815)))


def add_blob(bm, center, size):
    """Ellipsoid at center with half-extents size (x, y, z)."""
    geom = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=1.0)
    m = Matrix.Translation(center) @ Matrix.Diagonal((*size, 1.0))
    bmesh.ops.transform(bm, matrix=m, verts=geom["verts"])


def add_torus(bm, center, major, minor, tilt, front, segs=48, sides=8):
    ring = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        ring.append([bm.verts.new((
            center.x + math.cos(a) * (major + minor * math.cos(b)),
            center.y + math.sin(a) * (major + minor * math.cos(b)),
            center.z + minor * math.sin(b),
        )) for b in (2 * math.pi * j / sides for j in range(sides))])
    for i in range(segs):
        for j in range(sides):
            bm.faces.new((ring[i][j], ring[(i + 1) % segs][j], ring[(i + 1) % segs][(j + 1) % sides], ring[i][(j + 1) % sides]))
    # Tilt so the front of the chain hangs lower than the back
    rot = Matrix.Translation(center) @ Matrix.Rotation(-tilt * front, 4, "X") @ Matrix.Translation(-center)
    bmesh.ops.transform(bm, matrix=rot, verts=[v for r in ring for v in r])


def build_accessory(body, kind):
    bm = bmesh.new()
    h, f = body.h, body.front
    p = neck_front(body)
    if kind == "cravat":
        out = Vector((0, f * h * 0.012, 0))
        add_blob(bm, p + out, (h * 0.012, h * 0.008, h * 0.009))  # knot
        for side in (-1, 1):  # two folds hanging from the knot, splayed slightly
            add_blob(bm, p + out + Vector((side * h * 0.008, 0, -h * 0.03)), (h * 0.013, h * 0.005, h * 0.03))
    elif kind == "bow_tie":
        for side in (-1, 1):
            add_blob(bm, p + Vector((side * h * 0.022, f * h * 0.008, 0)), (h * 0.02, h * 0.007, h * 0.012))
        add_blob(bm, p + Vector((0, f * h * 0.01, 0)), (h * 0.007, h * 0.007, h * 0.008))
    elif kind == "chains":
        # Neck width only: ignore hair and shoulders further out
        radii = sorted(body.ring_radii(0.83, 48, [i * math.pi / 8 for i in range(16)], max_dx=h * 0.045))
        neck_r = radii[len(radii) // 2]
        for k, drop in enumerate((0.0, 0.02, 0.04)):
            center = Vector((body.cx, body.cy, body.z(0.805 - drop)))
            add_torus(bm, center, neck_r + h * (0.012 + drop * 0.6), h * 0.0022, 0.5 + 0.12 * k, f)
    return bm


# ─────────────────────────────────────────────────────────────────────────────
# Scene plumbing
# ─────────────────────────────────────────────────────────────────────────────
def hex_to_rgba(hex_color):
    hex_color = hex_color.lstrip("#")
    srgb = [int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, 1.0)


def fabric_material(fabric):
    name = f"Dracula {fabric.title()}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    look = FABRICS[fabric]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    mat.diffuse_color = hex_to_rgba(look["color"])
    if bsdf:
        bsdf.inputs["Base Color"].default_value = hex_to_rgba(look["color"])
        bsdf.inputs["Roughness"].default_value = look["roughness"]
        bsdf.inputs["Metallic"].default_value = look.get("metallic", 0.0)
        sheen = bsdf.inputs.get("Sheen Weight") or bsdf.inputs.get("Sheen")
        if sheen:
            sheen.default_value = look.get("sheen", 0.0)
    return mat


def outfit_collection():
    coll = bpy.data.collections.get(OUTFIT_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(OUTFIT_COLLECTION)
        bpy.context.scene.collection.children.link(coll)
    return coll


def remove_outfit():
    coll = bpy.data.collections.get(OUTFIT_COLLECTION)
    if not coll:
        return 0
    count = 0
    for obj in list(coll.objects):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        count += 1
    return count


def tag_avatar(objects):
    """Mark freshly imported meshes as the avatar (untagging any older one)."""
    meshes = [o for o in objects if o.type == "MESH"]
    if not meshes:
        return
    for obj in bpy.data.objects:
        if AVATAR_PROP in obj:
            del obj[AVATAR_PROP]
    for obj in meshes:
        obj[AVATAR_PROP] = True


def find_avatar():
    tagged = [o for o in bpy.context.scene.objects if o.get(AVATAR_PROP) and o.type == "MESH"]
    if tagged:
        return tagged
    # Fallback: the biggest mesh in the scene that isn't a garment
    outfit = bpy.data.collections.get(OUTFIT_COLLECTION)
    meshes = [o for o in bpy.context.scene.objects
              if o.type == "MESH" and not (outfit and o.name in outfit.objects)]
    return [max(meshes, key=lambda o: len(o.data.vertices))] if meshes else []


def make_object(name, bm, fabric, thickness, smooth, coll, matrix):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.materials.append(fabric_material(fabric))
    obj = bpy.data.objects.new(name, mesh)
    obj.matrix_world = matrix
    coll.objects.link(obj)
    if smooth:
        mod = obj.modifiers.new("Soften", "SMOOTH")
        mod.factor, mod.iterations = 0.6, smooth
    if thickness:
        mod = obj.modifiers.new("Fabric", "SOLIDIFY")
        mod.thickness, mod.offset = thickness, 0.0
    return obj


def dress(garment_names):
    """Replace the current outfit with these garments. Returns (dressed, skipped) names."""
    avatar = find_avatar()
    if not avatar:
        raise RuntimeError("No avatar in the scene. Import a Tripo model first.")

    remove_outfit()
    coll = outfit_collection()
    body = Body(avatar, flip=bpy.context.scene.get(FLIP_PROP, False))
    dressed, skipped = [], []
    try:
        for name in garment_names:
            kind, fabric = classify(name)
            if kind is None:
                skipped.append(name)
                continue
            if kind == "cape":
                short = "structured" in name.lower() or "short" in name.lower()
                bm, thick, smooth = build_cape(body, 0.40 if short else 0.10), body.h * 0.004, 0
            elif kind in ("jacket", "frock_coat", "long_coat"):
                bm, thick, smooth = build_coat(body, SHELLS[kind]), body.h * 0.004, 4
            elif kind in SHELLS:
                bm, thick, smooth = build_shell(body, SHELLS[kind]), body.h * 0.003, 4
            else:
                bm, thick, smooth = build_accessory(body, kind), 0, 0
            make_object(name, bm, fabric, thick, smooth, coll, body.to_world)
            dressed.append(name)
    finally:
        body.free()
    return dressed, skipped
