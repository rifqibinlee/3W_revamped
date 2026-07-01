"""Proxy service for the GeoServer REST API.

All calls use basic auth with the admin credentials from config.
Returns plain dicts/lists — the router serialises to JSON.
"""

from typing import Any

import httpx

from app.core.config import settings


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=f"{settings.geoserver_url}/rest",
        auth=(settings.geoserver_admin_user, settings.geoserver_admin_password),
        headers={"Accept": "application/json"},
        timeout=10.0,
    )


def _gs(path: str) -> Any:
    with _client() as c:
        r = c.get(path)
        r.raise_for_status()
        return r.json()


def _gs_put(path: str, body: Any, content_type: str = "application/json") -> None:
    with _client() as c:
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        r = c.put(path, json=body if content_type == "application/json" else None,
                  content=body if content_type != "application/json" else None,
                  headers=headers)
        r.raise_for_status()


def _gs_put_xml(path: str, body: str) -> None:
    with httpx.Client(
        base_url=f"{settings.geoserver_url}/rest",
        auth=(settings.geoserver_admin_user, settings.geoserver_admin_password),
        timeout=10.0,
    ) as c:
        r = c.put(path, content=body.encode(), headers={"Content-Type": "application/xml"})
        r.raise_for_status()


def _gs_post(path: str, body: Any) -> Any:
    with _client() as c:
        r = c.post(path, json=body)
        r.raise_for_status()
        return r.headers.get("Location", "")


def _gs_post_xml(path: str, body: str) -> str:
    with httpx.Client(
        base_url=f"{settings.geoserver_url}/rest",
        auth=(settings.geoserver_admin_user, settings.geoserver_admin_password),
        timeout=10.0,
    ) as c:
        r = c.post(path, content=body.encode(), headers={"Content-Type": "application/xml"})
        r.raise_for_status()
        return r.headers.get("Location", "")


def _gs_delete(path: str) -> None:
    with _client() as c:
        r = c.delete(path)
        r.raise_for_status()


# ── workspaces ────────────────────────────────────────────────────────────────

def list_workspaces() -> list[dict]:
    data = _gs("/workspaces")
    items = data.get("workspaces") or {}
    return [{"name": w["name"]} for w in (items.get("workspace") or [])]


# ── layers ────────────────────────────────────────────────────────────────────

def list_layers() -> list[dict]:
    """All published layers across all workspaces with enriched metadata."""
    data = _gs("/layers")
    raw = (data.get("layers") or {}).get("layer") or []
    out = []
    for item in raw:
        try:
            detail = _gs(f"/layers/{item['name']}")["layer"]
            style = detail.get("defaultStyle") or {}
            out.append({
                "name": item["name"],
                "title": detail.get("title", item["name"]),
                "abstract": detail.get("abstract", ""),
                "enabled": detail.get("enabled", True),
                "type": detail.get("type", ""),
                "default_style": style.get("name", ""),
                "default_style_workspace": style.get("workspace", ""),
            })
        except Exception:
            out.append({"name": item["name"], "title": item["name"], "abstract": "",
                        "enabled": True, "type": "", "default_style": "", "default_style_workspace": ""})
    return out


def update_layer(layer_name: str, enabled: bool | None, default_style: str | None) -> None:
    """Patch a layer's enabled flag and/or default style."""
    body: dict[str, Any] = {"layer": {}}
    if enabled is not None:
        body["layer"]["enabled"] = enabled
    if default_style is not None:
        body["layer"]["defaultStyle"] = {"name": default_style}
    _gs_put(f"/layers/{layer_name}", body)


# ── styles ────────────────────────────────────────────────────────────────────

def list_styles() -> list[dict]:
    out = []
    # global styles
    data = _gs("/styles")
    for s in ((data.get("styles") or {}).get("style") or []):
        out.append({"name": s["name"], "workspace": None})
    # workspace styles
    for ws in list_workspaces():
        try:
            data = _gs(f"/workspaces/{ws['name']}/styles")
            for s in ((data.get("styles") or {}).get("style") or []):
                out.append({"name": s["name"], "workspace": ws["name"]})
        except Exception:
            pass
    return out


def get_style_sld(style_name: str, workspace: str | None) -> str:
    path = f"/workspaces/{workspace}/styles/{style_name}.sld" if workspace else f"/styles/{style_name}.sld"
    with httpx.Client(
        base_url=f"{settings.geoserver_url}/rest",
        auth=(settings.geoserver_admin_user, settings.geoserver_admin_password),
        timeout=10.0,
    ) as c:
        r = c.get(path, headers={"Accept": "application/vnd.ogc.sld+xml"})
        r.raise_for_status()
        return r.text


def update_style_sld(style_name: str, workspace: str | None, sld: str) -> None:
    path = f"/workspaces/{workspace}/styles/{style_name}" if workspace else f"/styles/{style_name}"
    _gs_put_xml(path, sld)


def create_style(style_name: str, workspace: str | None, sld: str) -> None:
    if workspace:
        path = f"/workspaces/{workspace}/styles"
    else:
        path = "/styles"
    # create the style entry first
    meta = {"style": {"name": style_name, "filename": f"{style_name}.sld"}}
    _gs_put(path + f"/{style_name}", meta)  # will 404 first time, so POST
    try:
        _gs_post(path, meta)
    except Exception:
        pass
    # upload the SLD
    _gs_put_xml(path + f"/{style_name}", sld)


# ── datastores & publish ──────────────────────────────────────────────────────

def list_datastores(workspace: str) -> list[dict]:
    data = _gs(f"/workspaces/{workspace}/datastores")
    items = (data.get("dataStores") or {}).get("dataStore") or []
    return [{"name": d["name"]} for d in items]


def list_available_featuretypes(workspace: str, datastore: str) -> list[str]:
    data = _gs(f"/workspaces/{workspace}/datastores/{datastore}/featuretypes?list=available")
    items = (data.get("list") or {}).get("string") or []
    return items if isinstance(items, list) else [items]


def publish_layer(workspace: str, datastore: str, native_name: str, title: str) -> None:
    body = {
        "featureType": {
            "name": native_name,
            "nativeName": native_name,
            "title": title or native_name,
        }
    }
    _gs_post(f"/workspaces/{workspace}/datastores/{datastore}/featuretypes", body)
