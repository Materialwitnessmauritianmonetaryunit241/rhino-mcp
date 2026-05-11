"""Architectural defaults and validation."""
ARCH_DEFAULTS = {
    "wall_height": 3000.0, "wall_thickness": 200.0, "slab_thickness": 200.0,
    "column_width": 400.0, "column_depth": 400.0, "column_height": 3000.0,
    "door_width": 900.0, "door_height": 2100.0, "window_width": 1200.0,
    "window_height": 1500.0, "window_sill_height": 900.0, "roof_thickness": 200.0,
}
LAYER_MAP = {
    "wall": "Wall", "slab": "Slab", "column": "Column", "beam": "Beam",
    "opening": "Opening", "roof": "Roof", "stair": "Stair", "furniture": "Furniture",
    "site": "Site", "grid": "Grid", "annotation": "Annotation",
}
