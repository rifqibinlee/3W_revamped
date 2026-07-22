from pydantic import BaseModel, Field


class MapBounds(BaseModel):
    south: float
    west: float
    north: float
    east: float


class SimulateRequest(BaseModel):
    bounds: MapBounds
    frequency_mhz: int = 1800
    resolution_m: int = 50
    tx_power_dbm: float = 43.0
    include_buildings: bool = False
    model: str = "hata"          # hata | tr38901_uma | tr38901_rma | spm | freespace | sionna
    monte_carlo: bool = False    # add log-normal shadow fading (σ=8 dB)


class CoverageFeature(BaseModel):
    lat: float
    lng: float
    rsrp_dbm: float
    serving_site_id: str
    nlos: bool = False


class BuildingFeature(BaseModel):
    """GeoJSON-ready polygon ring (lng, lat pairs) with height for 3D rendering."""
    ring: list[tuple[float, float]]
    height_m: float


class IndoorWallIn(BaseModel):
    x0: float; y0: float
    x1: float; y1: float
    height_m: float = 3.0
    material: str = "concrete"   # concrete | brick | plasterboard | wood | glass | metal


class IndoorTxIn(BaseModel):
    x: float; y: float
    height_m: float = 1.5
    power_dbm: float = 20.0
    azimuth_deg: float = 0.0


class IndoorSimulateRequest(BaseModel):
    walls: list[IndoorWallIn]
    tx_list: list[IndoorTxIn]
    floor_origin_lat: float          # SW corner latitude
    floor_origin_lng: float          # SW corner longitude
    floor_width_m: float
    floor_height_m: float
    frequency_mhz: int = 2400        # 2400 (WiFi) or 5800 or cellular band
    resolution_m: float = 0.5
    rx_height_m: float = 1.0


class IndoorCoveragePoint(BaseModel):
    """One grid cell in local floor-plan coordinates (metres from SW corner)."""
    x: float; y: float
    rsrp_dbm: float
    sinr_db: float
    serving_tx: int   # index into tx_list


class IndoorSimulateResponse(BaseModel):
    points: list[IndoorCoveragePoint]
    engine: str = "sionna-indoor"
    nx: int; ny: int
    floor_width_m: float; floor_height_m: float
    floor_origin_lat: float; floor_origin_lng: float
    simulation_time_s: float
    image_b64: str | None = None
    sinr_image_b64: str | None = None
    rsrp_min: float | None = None
    rsrp_max: float | None = None
    sinr_min: float | None = None
    sinr_max: float | None = None


class SimulateResponse(BaseModel):
    features: list[CoverageFeature]
    buildings: list[BuildingFeature] = []
    engine: str  # "sionna" | "hata" | "sionna+buildings" | "hata+buildings"
    num_sites: int
    num_buildings: int = 0
    simulation_time_s: float
    image_b64: str | None = None          # RSRP heatmap (plasma)
    sinr_image_b64: str | None = None     # SINR heatmap (RdYlGn)
    delay_spread_image_b64: str | None = None  # RMS delay spread (YlOrRd)
