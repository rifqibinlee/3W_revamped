"""
Indoor coverage simulation — coherent 2-D wave field.

Uses an image-source / ray-tracing method that preserves phase so that
interference fringes, standing waves, and material / frequency differences
are clearly visible.  No GPU or Sionna required; runs in pure NumPy.

Physics
-------
  E_total(x,y) = Σ_tx  [ E_direct(tx→xy)
                         + Σ_wall  E_reflected(tx-image→xy)
                         + Σ_wall₁,wall₂  E_double_refl(…)  ]

Each contribution is a complex phasor:
  E = A · T_walls · exp(-j·k·r) / √r       (2-D cylindrical spreading)

where
  k  = 2π·f / c                            wavenumber
  r  = path length                          metres
  T_walls = Π T_i(material, f, θ_i)        ITU-R P.2040 transmission product
  A  = √(P_tx / Z₀)                        antenna amplitude (isotropic)

Power → RSRP:
  P_rx = |E|² · (λ/4π)² · Z₀
       = |E|² · (c/4π·f)²
  RSRP_dBm = 10·log₁₀(P_rx) + 30
"""

from __future__ import annotations

import base64
import io
import logging
import math
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

WALL_THICKNESS_M = 0.2
_C               = 3e8          # speed of light, m/s
_Z0              = 377.0        # free-space impedance, Ω


# ── Material parameters (ITU-R P.2040-3, Table 3) ────────────────────────────
# epsilon_r = a·f^b,  sigma = c·f^d   (f in GHz)
_ITU_PARAMS: dict[str, tuple[float, float, float, float]] = {
    "concrete":     (5.31,  0.0,    0.0326, 0.8095),
    "brick":        (3.75,  0.0,    0.038,  0.0),
    "plasterboard": (2.94,  0.0,    0.0116, 0.7076),
    "wood":         (1.99,  0.0,    0.0047, 1.0718),
    "glass":        (6.27,  0.0,    0.0043, 1.1925),
    "metal":        (1e6,   0.0,    1e7,    0.0),
}


@dataclass
class IndoorWall:
    x0: float; y0: float
    x1: float; y1: float
    height_m: float = 3.0
    material: str   = "concrete"


@dataclass
class IndoorTx:
    x: float; y: float
    height_m: float  = 1.5
    power_dbm: float = 20.0
    azimuth_deg: float = 0.0


# ── ITU-R material helpers ────────────────────────────────────────────────────

def _complex_permittivity(material: str, freq_hz: float) -> complex:
    a, b, c, d = _ITU_PARAMS.get(material, _ITU_PARAMS["concrete"])
    f_ghz = freq_hz / 1e9
    eps_r  = a * (f_ghz ** b) if b else a
    sigma  = c * (f_ghz ** d) if d else c
    eps_0  = 8.854e-12
    return complex(eps_r, -sigma / (2 * math.pi * freq_hz * eps_0))


def _rt_coefficients(material: str, freq_hz: float, thickness_m: float = WALL_THICKNESS_M
                     ) -> tuple[float, float]:
    """
    Normal-incidence reflection (R_amp) and transmission (T_amp) amplitude
    coefficients for a dielectric slab of given thickness.

    Uses thin-slab approximation from ITU-R P.2040:
      R_amp = |Γ|,  T_amp = (1 − |Γ|²)^0.5 · exp(−α·d)
    where α is the absorption coefficient inside the slab.
    """
    eps = _complex_permittivity(material, freq_hz)
    n   = np.sqrt(eps + 0j)               # complex refractive index

    # Fresnel reflection at normal incidence
    gamma = (1.0 - n) / (1.0 + n)
    R_amp = abs(gamma)

    # Absorption inside the slab
    alpha = 2 * math.pi * freq_hz * abs(n.imag) / _C
    T_power = max(0.0, (1 - R_amp**2) * math.exp(-2 * alpha * thickness_m))
    T_amp   = math.sqrt(T_power)

    return float(R_amp), float(T_amp)


# ── Vectorised geometry helpers ───────────────────────────────────────────────

def _ray_wall_params(
    sx: float, sy: float,
    gx: np.ndarray, gy: np.ndarray,
    wx0: float, wy0: float, wx1: float, wy1: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    For each grid point (gx[i,j], gy[i,j]) returns (t, s) such that
      (sx,sy) + t·(gx-sx, gy-sy) == (wx0,wy0) + s·(wx1-wx0, wy1-wy0)
    t in (0,1) → the ray hits the wall between source and receiver.
    s in [0,1] → the hit is within the finite wall segment.
    """
    rdx = gx - sx;  rdy = gy - sy      # ray direction (vectorised)
    wdx = wx1 - wx0; wdy = wy1 - wy0   # wall direction (scalar)

    denom = rdx * wdy - rdy * wdx      # (ny,nx)
    tiny  = 1e-12
    safe  = np.where(np.abs(denom) > tiny, denom, tiny)

    ox = wx0 - sx;  oy = wy0 - sy
    t  = (ox * wdy - oy * wdx) / safe
    s  = (ox * rdy - oy * rdx) / safe
    return t, s


def _mirror_point(px: float, py: float,
                  wx0: float, wy0: float,
                  wx1: float, wy1: float) -> tuple[float, float]:
    """Mirror point P across the infinite line through (wx0,wy0)→(wx1,wy1)."""
    wdx = wx1 - wx0;  wdy = wy1 - wy0
    len2 = wdx**2 + wdy**2
    if len2 < 1e-12:
        return px, py
    t = ((px - wx0) * wdx + (py - wy0) * wdy) / len2
    fx = wx0 + t * wdx;  fy = wy0 + t * wdy   # foot of perpendicular
    return 2*fx - px, 2*fy - py


# ── Per-TX field computation ──────────────────────────────────────────────────

def _tx_field(
    tx: IndoorTx,
    walls: list[IndoorWall],
    GX: np.ndarray, GY: np.ndarray,
    k: float, freq_hz: float,
    max_reflections: int = 2,
) -> np.ndarray:
    """
    Compute complex E-field contribution from one transmitter at all grid points,
    including direct path and up to max_reflections-order specular bounces.
    """
    tx_amp = math.sqrt(10 ** ((tx.power_dbm - 30) / 10))  # √Watts (isotropic)
    E = np.zeros(GX.shape, dtype=np.complex128)

    # ── Direct path ──────────────────────────────────────────────────────
    dx = GX - tx.x;  dy = GY - tx.y
    r  = np.hypot(dx, dy) + 1e-9

    # Product of transmission coefficients through each wall the direct ray crosses
    T_direct = np.ones(GX.shape, dtype=np.float64)
    for w in walls:
        t_param, s_param = _ray_wall_params(tx.x, tx.y, GX, GY,
                                             w.x0, w.y0, w.x1, w.y1)
        crosses = (t_param > 1e-4) & (t_param < 1 - 1e-4) & (s_param >= 0) & (s_param <= 1)
        _, T_amp = _rt_coefficients(w.material, freq_hz)
        T_direct[crosses] *= T_amp

    E += tx_amp * T_direct * np.exp(-1j * k * r) / np.sqrt(r)

    # ── Specular reflections (image-source method) ────────────────────────
    # We iterate over walls; each image source represents one bounce.
    def _add_reflection(src_x: float, src_y: float, src_amp: float,
                        bounce_wall: IndoorWall, depth: int) -> None:
        nonlocal E
        R_amp, _ = _rt_coefficients(bounce_wall.material, freq_hz)
        if R_amp < 0.02:
            return

        # Image of source across bounce_wall
        ix, iy = _mirror_point(src_x, src_y,
                               bounce_wall.x0, bounce_wall.y0,
                               bounce_wall.x1, bounce_wall.y1)

        # Path from image to grid: must actually cross the bounce_wall segment
        t_b, s_b = _ray_wall_params(ix, iy, GX, GY,
                                     bounce_wall.x0, bounce_wall.y0,
                                     bounce_wall.x1, bounce_wall.y1)
        valid = (t_b > 1e-4) & (t_b < 1 - 1e-4) & (s_b >= 0) & (s_b <= 1)
        if not np.any(valid):
            return

        dx2 = GX - ix;  dy2 = GY - iy
        r2  = np.hypot(dx2, dy2) + 1e-9

        # Reflection flips the sign (phase shift π for R from denser medium)
        E_refl = (-R_amp * src_amp
                  * np.exp(-1j * k * r2) / np.sqrt(r2))
        E += np.where(valid, E_refl, 0.0)

        # Recurse for higher-order bounces
        if depth < max_reflections:
            for w2 in walls:
                if w2 is bounce_wall:
                    continue
                _add_reflection(ix, iy, R_amp * src_amp, w2, depth + 1)

    for w in walls:
        _add_reflection(tx.x, tx.y, tx_amp, w, 1)

    return E


# ── Main entry point ──────────────────────────────────────────────────────────

def simulate_indoor(
    walls: list[IndoorWall],
    tx_list: list[IndoorTx],
    floor_width_m: float,
    floor_height_m: float,
    frequency_mhz: int = 2400,
    resolution_m: float = 0.5,
    rx_height_m: float = 1.0,
    add_floor_ceiling: bool = True,     # kept for API compatibility
    max_reflections: int = 2,
) -> dict:
    """
    Coherent 2-D wave field indoor simulation.

    Returns a dict with rsrp_grid, sinr_grid, image_b64, sinr_image_b64, nx, ny,
    rsrp_min/max, sinr_min/max.
    """
    freq_hz = frequency_mhz * 1e6
    lam     = _C / freq_hz
    k       = 2 * math.pi / lam

    nx = max(4, int(math.ceil(floor_width_m  / resolution_m)))
    ny = max(4, int(math.ceil(floor_height_m / resolution_m)))
    cell_w = floor_width_m  / nx
    cell_h = floor_height_m / ny

    # Grid of receiver positions (centre of each cell)
    xs = (np.arange(nx) + 0.5) * cell_w
    ys = (np.arange(ny) + 0.5) * cell_h
    GX, GY = np.meshgrid(xs, ys)       # (ny, nx)

    # ── Per-TX coherent field ─────────────────────────────────────────────
    E_per_tx: list[np.ndarray] = []
    for tx in tx_list:
        E = _tx_field(tx, walls, GX, GY, k, freq_hz, max_reflections)
        E_per_tx.append(E)

    # ── RSRP: best-server (coherent per TX, incoherent between TXs) ──────
    # Each TX's received power in Watts
    lam_factor = (lam / (4 * math.pi)) ** 2   # Friis isotropic receive factor
    rsrp_w_per_tx = np.array([np.abs(E)**2 * lam_factor * _Z0
                               for E in E_per_tx])   # (n_tx, ny, nx)

    tx_power_w = np.array([10 ** ((t.power_dbm - 30) / 10) for t in tx_list])
    # Normalise so absolute level is consistent with TX power
    for i in range(len(tx_list)):
        peak = rsrp_w_per_tx[i].max()
        if peak > 0:
            rsrp_w_per_tx[i] *= tx_power_w[i] / peak

    rsrp_dbm_per_tx = 10 * np.log10(np.clip(rsrp_w_per_tx, 1e-30, None)) + 30
    best_rsrp = rsrp_dbm_per_tx.max(axis=0)     # (ny, nx)
    best_idx  = rsrp_dbm_per_tx.argmax(axis=0)

    # ── SINR ─────────────────────────────────────────────────────────────
    noise_w    = 10 ** ((-97.0 - 30) / 10)
    serving_w  = rsrp_w_per_tx.max(axis=0)
    total_w    = rsrp_w_per_tx.sum(axis=0)
    sinr_grid  = 10 * np.log10(
        np.clip(serving_w / (total_w - serving_w + noise_w), 1e-10, None)
    )

    # ── Colormap: auto-scale to highlight variation ───────────────────────
    rsrp_peak  = float(best_rsrp.max())
    rsrp_floor = rsrp_peak - 40.0
    sinr_peak  = float(sinr_grid.max())
    sinr_floor = max(float(sinr_grid.min()), sinr_peak - 40.0)

    return {
        "rsrp_grid":      best_rsrp,
        "sinr_grid":      sinr_grid,
        "best_tx_idx":    best_idx,
        "image_b64":      _heatmap_b64(best_rsrp, vmin=rsrp_floor, vmax=rsrp_peak, cmap="plasma"),
        "sinr_image_b64": _heatmap_b64(sinr_grid,  vmin=sinr_floor, vmax=sinr_peak, cmap="RdYlGn"),
        "rsrp_min": round(rsrp_floor, 1),
        "rsrp_max": round(rsrp_peak,  1),
        "sinr_min": round(sinr_floor, 1),
        "sinr_max": round(sinr_peak,  1),
        "nx": nx,
        "ny": ny,
    }


# ── Heatmap renderer ──────────────────────────────────────────────────────────

def _heatmap_b64(grid: np.ndarray, vmin: float, vmax: float, cmap: str) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import Normalize

        norm   = Normalize(vmin=vmin, vmax=vmax)
        cm_obj = plt.get_cmap(cmap)
        rgba   = cm_obj(norm(np.flipud(grid)))
        # Keep alpha proportional to relative signal strength (0 at floor, 0.85 at peak)
        rel    = (np.flipud(grid) - vmin) / max(vmax - vmin, 1e-6)
        rgba[..., 3] = np.clip(rel * 0.9, 0.0, 0.88)

        h, w = grid.shape
        fig, ax = plt.subplots(figsize=(max(w / 50, 0.5), max(h / 50, 0.5)), dpi=150)
        ax.imshow(rgba, aspect="equal", interpolation="bilinear")
        ax.axis("off")
        fig.tight_layout(pad=0)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0, transparent=True)
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception as exc:
        log.warning("Heatmap render failed: %s", exc)
        return ""
