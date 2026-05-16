import os
import json
import urllib.request
import urllib.parse
import shutil
import tempfile
import zipfile
import fnmatch
from pathlib import Path

CACHE_DIR = Path(os.environ.get("APPDATA", "")) / "AIBridge" / "materials"

_BASE_URL = "https://ambientcg.com/api/v2/full_json"

# Resolution preference order — first match wins
_RESOLUTION_PREFERENCE = [
    "2K-PNG", "2K-JPG", "1K-PNG", "1K-JPG",
    "4K-PNG", "4K-JPG", "512-PNG", "512-JPG",
]

# Map patterns to texture slot names
_MAP_PATTERNS = {
    "albedo":       ["*_Color*", "*_AmbientColor*"],
    "roughness":    ["*_Roughness*"],
    "normal":       ["*_NormalGL*", "*_Normal*"],
    "metallic":     ["*_Metalness*"],
    "ao":           ["*_AmbientOcclusion*", "*_ao*"],
    "displacement": ["*_Displacement*"],
}


def _fetch_json(url: str) -> dict:
    """Fetch a URL and return parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": "RhinoAIBridge/4.7"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_materials(keyword: str, limit: int = 5) -> list[dict]:
    """Search AmbientCG for PBR material assets matching keyword.

    Returns a list of candidate dicts with keys:
      asset_id, display_name, physical_size_m, resolutions_available, preview_url
    """
    params = urllib.parse.urlencode({
        "type": "Material",
        "include": "downloadData,previewData",
        "sort": "Popular",
        "q": keyword,
        "limit": limit,
    })
    url = f"{_BASE_URL}?{params}"
    data = _fetch_json(url)

    results = []
    for asset in data.get("foundAssets", []):
        dims = asset.get("dimensionsInMeters", [1.0, 1.0])
        size_m = float(dims[0]) if dims else 1.0

        # Collect available resolutions
        resolutions = []
        for entry in (
            asset.get("downloadFolders", {})
                 .get("default", {})
                 .get("downloadFileArray", [])
        ):
            attr = entry.get("downloadAttribute", "")
            if attr:
                resolutions.append(attr)

        # Best preview image
        preview_url = ""
        previews = asset.get("previewData", {})
        if previews:
            for k in ("512-PNG", "256-PNG"):
                if k in previews:
                    preview_url = previews[k]
                    break
            if not preview_url:
                vals = list(previews.values())
                if vals:
                    preview_url = vals[0]

        results.append({
            "asset_id": asset.get("assetId", ""),
            "display_name": asset.get("displayName", ""),
            "physical_size_m": size_m,
            "resolutions_available": resolutions,
            "preview_url": preview_url,
        })

    return results


def get_material_info(asset_id: str) -> dict:
    """Get full info for a specific asset including download URLs and real-world dimensions."""
    params = urllib.parse.urlencode({
        "type": "Material",
        "include": "downloadData,previewData",
        "q": asset_id,
        "limit": 1,
    })
    url = f"{_BASE_URL}?{params}"
    data = _fetch_json(url)

    assets = data.get("foundAssets", [])
    if not assets:
        return {}

    # Find exact match
    for asset in assets:
        if asset.get("assetId", "").lower() == asset_id.lower():
            return asset

    # Fallback to first result
    return assets[0]


def _pick_download_entry(download_file_array: list[dict], resolution: str) -> dict | None:
    """Find the best matching download entry for the requested resolution."""
    # Build preference list starting with the requested resolution
    pref_attr = f"{resolution}-PNG"
    pref_attr_jpg = f"{resolution}-JPG"

    ordered = [pref_attr, pref_attr_jpg] + [
        p for p in _RESOLUTION_PREFERENCE
        if p not in (pref_attr, pref_attr_jpg)
    ]

    attr_map = {
        entry.get("downloadAttribute", ""): entry
        for entry in download_file_array
        if entry.get("downloadAttribute")
    }

    for attr in ordered:
        if attr in attr_map:
            return attr_map[attr]

    # Last resort: return first entry
    return download_file_array[0] if download_file_array else None


def _map_files_to_slots(extracted_files: list[Path]) -> dict[str, str]:
    """Match extracted image files to PBR map slots by filename patterns."""
    slots = {}
    image_exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr"}

    for slot, patterns in _MAP_PATTERNS.items():
        if slot in slots:
            continue
        for pattern in patterns:
            for f in extracted_files:
                if f.suffix.lower() in image_exts and fnmatch.fnmatch(f.name, pattern):
                    slots[slot] = str(f)
                    break
            if slot in slots:
                break

    return slots


def download_material(asset_id: str, resolution: str = "2K") -> dict:
    """Download PBR texture maps for an asset.

    Returns dict with:
      asset_id, display_name, physical_size_m, local_paths, resolution_used, already_cached
    """
    cache_dir = CACHE_DIR / asset_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Check cache — if any image files exist, treat as cached
    existing_images = [
        f for f in cache_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr"}
    ]

    info = get_material_info(asset_id)
    dims = info.get("dimensionsInMeters", [1.0, 1.0])
    physical_size_m = float(dims[0]) if dims else 1.0
    display_name = info.get("displayName", asset_id)

    if existing_images:
        local_paths = _map_files_to_slots(existing_images)
        return {
            "asset_id": asset_id,
            "display_name": display_name,
            "physical_size_m": physical_size_m,
            "local_paths": local_paths,
            "resolution_used": resolution,
            "already_cached": True,
        }

    # Find download entry
    download_file_array = (
        info.get("downloadFolders", {})
            .get("default", {})
            .get("downloadFileArray", [])
    )
    if not download_file_array:
        raise ValueError(f"No download files found for asset {asset_id}")

    entry = _pick_download_entry(download_file_array, resolution)
    if not entry:
        raise ValueError(f"No suitable download entry found for asset {asset_id} at {resolution}")

    download_url = entry.get("fullDownloadPath", "")
    resolution_used = entry.get("downloadAttribute", resolution)

    if not download_url:
        raise ValueError(f"Download URL missing for asset {asset_id}")

    # Download zip to temp file
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        req = urllib.request.Request(download_url, headers={"User-Agent": "RhinoAIBridge/4.7"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, "wb") as out:
            shutil.copyfileobj(resp, out)

        # Extract zip
        with zipfile.ZipFile(tmp_path, "r") as zf:
            zf.extractall(cache_dir)

    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # Collect extracted image files
    extracted = [
        f for f in cache_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr"}
    ]

    local_paths = _map_files_to_slots(extracted)

    return {
        "asset_id": asset_id,
        "display_name": display_name,
        "physical_size_m": physical_size_m,
        "local_paths": local_paths,
        "resolution_used": resolution_used,
        "already_cached": False,
    }


def compute_uv_repeat(physical_size_m: float, model_unit_system: str) -> float:
    """Compute UV repeat factor so 1 UV unit = physical_size in model units.

    model_unit_system: "Millimeters", "Centimeters", "Meters", "Feet", "Inches", etc.
    Returns repeat factor (e.g., if model is in mm and tile is 1m, repeat = 1000)
    """
    unit_to_meters = {
        "Millimeters": 0.001,
        "Centimeters": 0.01,
        "Meters": 1.0,
        "Feet": 0.3048,
        "Inches": 0.0254,
    }

    unit_size_m = unit_to_meters.get(model_unit_system, 1.0)

    if physical_size_m <= 0:
        return 1.0

    # physical_size_m in model units = physical_size_m / unit_size_m
    # UV repeat = tile_size_in_model_units
    return physical_size_m / unit_size_m
