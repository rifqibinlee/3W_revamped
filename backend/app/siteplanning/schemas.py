from pydantic import BaseModel


class CameraSpec(BaseModel):
    camera_type: str
    hfov_deg: float
    range_m: float
    unit_price_rm: float


class CctvRunRequest(BaseModel):
    building: dict
    parking: dict
    poles: dict
    cameras: list[CameraSpec]
    offsets: list[float]


class SubstationIn(BaseModel):
    osm_id: str = ""
    name: str = "Substation"
    lat: float
    lng: float


class GensetRouteRequest(BaseModel):
    site_lat: float
    site_lng: float
    substations: list[SubstationIn]
    max_road_dist_m: int = 2000
    graph_buffer_m: int = 2500
