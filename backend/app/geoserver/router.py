from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.geoserver import service

router = APIRouter(prefix="/geoserver-admin", tags=["geoserver-admin"])


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"GeoServer error: {exc}") from exc


# ── workspaces ────────────────────────────────────────────────────────────────

@router.get("/workspaces")
def get_workspaces() -> list[dict]:
    return _wrap(service.list_workspaces)


# ── layers ────────────────────────────────────────────────────────────────────

@router.get("/layers")
def get_layers() -> list[dict]:
    return _wrap(service.list_layers)


class LayerUpdate(BaseModel):
    enabled: bool | None = None
    default_style: str | None = None


@router.put("/layers/{layer_name:path}")
def put_layer(layer_name: str, body: LayerUpdate) -> dict:
    _wrap(service.update_layer, layer_name, body.enabled, body.default_style)
    return {"ok": True}


# ── styles ────────────────────────────────────────────────────────────────────

@router.get("/styles")
def get_styles() -> list[dict]:
    return _wrap(service.list_styles)


@router.get("/styles/{style_name}/sld")
def get_style_sld(style_name: str, workspace: str | None = None) -> dict:
    sld = _wrap(service.get_style_sld, style_name, workspace)
    return {"sld": sld}


class StyleSldBody(BaseModel):
    sld: str
    workspace: str | None = None


@router.put("/styles/{style_name}")
def put_style_sld(style_name: str, body: StyleSldBody) -> dict:
    _wrap(service.update_style_sld, style_name, body.workspace, body.sld)
    return {"ok": True}


@router.post("/styles/{style_name}")
def post_style(style_name: str, body: StyleSldBody) -> dict:
    _wrap(service.create_style, style_name, body.workspace, body.sld)
    return {"ok": True}


# ── datastores & publish ──────────────────────────────────────────────────────

@router.get("/workspaces/{workspace}/datastores")
def get_datastores(workspace: str) -> list[dict]:
    return _wrap(service.list_datastores, workspace)


@router.get("/workspaces/{workspace}/datastores/{datastore}/available")
def get_available_featuretypes(workspace: str, datastore: str) -> list[str]:
    return _wrap(service.list_available_featuretypes, workspace, datastore)


class PublishBody(BaseModel):
    workspace: str
    datastore: str
    native_name: str
    title: str = ""


@router.post("/publish")
def publish(body: PublishBody) -> dict:
    _wrap(service.publish_layer, body.workspace, body.datastore, body.native_name, body.title)
    return {"ok": True}
