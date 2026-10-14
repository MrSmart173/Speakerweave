"""Builds the mixing matrix from the incoming channels to the speaker roles.

Three steps:
  1. direct      a role that exists on both sides is passed straight through
  2. fold down   an incoming channel the room has no speaker for is shared
                 between the nearest roles that do exist (centre into front
                 left + right, rears into sides, and so on)
  3. upmix       a role the room has but the source does not is derived from
                 the nearest incoming channels (stereo spread to surrounds)
Plus bass redirect: the subwoofer also receives the lows of every main channel.
"""
from __future__ import annotations

import numpy as np

from .model import OFF, ROLE_ANGLES, is_shaker, is_sub

G = 0.7071  # -3 dB

# For a source channel with no matching speaker role: ordered alternatives,
# the first alternative whose targets all exist in the room wins.
FOLD = {
    "FC": [[("FL", G), ("FR", G)]],
    "SL": [[("BL", 1.0)], [("BC", G)], [("FL", G)]],
    "SR": [[("BR", 1.0)], [("BC", G)], [("FR", G)]],
    "BL": [[("BC", G)], [("SL", 1.0)], [("FL", G)]],
    "BR": [[("BC", G)], [("SR", 1.0)], [("FR", G)]],
    "BC": [[("BL", G), ("BR", G)], [("SL", G), ("SR", G)], [("FL", 0.5), ("FR", 0.5)]],
    "FL": [[("FC", G)]],
    "FR": [[("FC", G)]],
}

# For a room role the source does not carry: where to derive it from.
UPMIX = {
    "FC": [[("FL", 0.5), ("FR", 0.5)]],
    "FL": [[("FC", G)]],
    "FR": [[("FC", G)]],
    "SL": [[("BL", G)], [("FL", G)], [("FC", 0.5)]],
    "SR": [[("BR", G)], [("FR", G)], [("FC", 0.5)]],
    "BL": [[("SL", G)], [("FL", G)], [("FC", 0.5)]],
    "BR": [[("SR", G)], [("FR", G)], [("FC", 0.5)]],
    "BC": [[("BL", 0.5), ("BR", 0.5)], [("SL", 0.5), ("SR", 0.5)], [("FL", 0.35), ("FR", 0.35)]],
}


def _first_possible(alternatives, available):
    for alt in alternatives:
        if all(role in available for role, _ in alt):
            return alt
    return []


def _angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _nearest(role: str, room_roles) -> list:
    """For layouts the fold table does not cover (custom positions): the room
    position closest in direction, or the two closest shared when they are
    equally close."""
    want = ROLE_ANGLES.get(role)
    mains = [r for r in room_roles if r in ROLE_ANGLES and not is_sub(r)]
    if want is None or not mains:
        return []
    mains.sort(key=lambda r: _angle_gap(ROLE_ANGLES[r], want))
    best = _angle_gap(ROLE_ANGLES[mains[0]], want)
    ties = [r for r in mains if _angle_gap(ROLE_ANGLES[r], want) - best < 1.0]
    if len(ties) >= 2:
        return [(ties[0], G), (ties[1], G)]
    return [(mains[0], 1.0)]


def shaker_row(source_roles: list[str], gain: float) -> np.ndarray:
    """What a bass shaker feels of the source: the bass channel in full and the
    other channels at half level (the shaker's own frequency range keeps only the
    low notes of them)."""
    row = np.zeros(len(source_roles))
    for i, role in enumerate(source_roles):
        if role == "LFE":
            row[i] = 1.0
        elif role != OFF:
            row[i] = 0.5
    return row * gain


def build_matrix(source_roles: list[str], room_roles: list[str], shaker_gain: float = 0.0,
                 **options) -> np.ndarray:
    """Returns M with shape (len(room_roles), len(source_roles)).
    bus = block @ M.T gives one signal per room role. Every subwoofer position
    (Subwoofer, Subwoofer 2, ...) gets the same signal. A bass shaker gets the
    game's bass at shaker_gain (0 = only the effects sent to it)."""
    core = []
    for role in room_roles:
        if is_shaker(role):
            continue
        role = "LFE" if is_sub(role) else role
        if role not in core:
            core.append(role)
    m = _build(source_roles, core, **options) if core else np.zeros((0, len(source_roles)))
    rows = [shaker_row(source_roles, shaker_gain) if is_shaker(r)
            else m[core.index("LFE" if is_sub(r) else r)] for r in room_roles]
    return np.array(rows, dtype=np.float64).reshape(len(room_roles), len(source_roles))


def _build(source_roles: list[str], room_roles: list[str], *, upmix: bool = True,
           bass_redirect: bool = True, bass_redirect_db: float = -6.0,
           lfe_to_mains: bool = True) -> np.ndarray:
    n_room, n_src = len(room_roles), len(source_roles)
    m = np.zeros((n_room, n_src), dtype=np.float64)
    room_index = {r: i for i, r in enumerate(room_roles)}
    src_index: dict[str, int] = {}
    for i, r in enumerate(source_roles):
        if r != OFF and r not in src_index:
            src_index[r] = i

    # 1. direct
    for role, s in src_index.items():
        if role in room_index:
            m[room_index[role], s] = 1.0

    # 2. fold down what the room cannot play
    for role, s in src_index.items():
        if role in room_index:
            continue
        if role == "LFE":
            if lfe_to_mains:
                targets = [t for t in ("FL", "FR") if t in room_index]
                if not targets:                      # no front pair: share it over every speaker
                    targets = [t for t in room_index if t != "LFE"]
                gain = 0.5 * np.sqrt(2.0 / len(targets)) if targets else 0.0
                for target in targets:
                    m[room_index[target], s] += gain
            continue
        targets = _first_possible(FOLD.get(role, []), room_index) or _nearest(role, room_index)
        for target, gain in targets:
            m[room_index[target], s] += gain

    # 3. upmix roles that are still silent
    if upmix:
        for role, r in room_index.items():
            if role == "LFE" or np.any(m[r] != 0.0):
                continue
            for src, gain in _first_possible(UPMIX.get(role, []), src_index):
                m[r, src_index[src]] += gain

    # bass redirect: the sub's own low pass keeps only the low notes
    if bass_redirect and "LFE" in room_index:
        g = 10.0 ** (bass_redirect_db / 20.0)
        for role, s in src_index.items():
            if role != "LFE":
                m[room_index["LFE"], s] += g
    return m
