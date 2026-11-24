"""
三套坐标互转：栅格像素 (px, py) <-> 点云 (x, y, 米) <-> 经纬度 (lon, lat)

约定：
- 栅格图像第 0 行 = 北，第 0 列 = 西（正北朝上）；px 向右增大，py 向下增大；
- 栅格左上角像素对应点云坐标 (grid_origin_x, grid_origin_y)；
- 像素 <-> 点云：x = origin_x + px * res，y = origin_y - py * res；
- 像素 <-> 经纬度：按 bounds 线性铺满整幅图，px 取 [0, grid_width]，py 取 [0, grid_height]；
- 因此「点云 <-> 经纬度」也隐含成立（经 bounds + grid 两级换算），前提是 bounds 与点云的地理朝向一致。
"""
from typing import Dict, Optional


def has_grid(map_obj) -> bool:
    """栅格与点云的映射信息是否齐全"""
    return None not in (map_obj.grid_origin_x, map_obj.grid_origin_y, map_obj.grid_resolution) \
        and bool(map_obj.grid_resolution) and bool(map_obj.grid_width) and bool(map_obj.grid_height)


def has_bounds(map_obj) -> bool:
    """区域经纬度是否齐全"""
    return None not in (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max) \
        and map_obj.lon_max > map_obj.lon_min and map_obj.lat_max > map_obj.lat_min


def px_to_pc(map_obj, px: float, py: float):
    """栅格像素 -> 点云 (x, y)"""
    res = float(map_obj.grid_resolution)
    return float(map_obj.grid_origin_x) + px * res, float(map_obj.grid_origin_y) - py * res


def pc_to_px(map_obj, x: float, y: float):
    """点云 (x, y) -> 栅格像素"""
    res = float(map_obj.grid_resolution)
    return (x - float(map_obj.grid_origin_x)) / res, (float(map_obj.grid_origin_y) - y) / res


def px_to_lonlat(map_obj, px: float, py: float):
    """栅格像素 -> 经纬度（按 bounds 线性铺满整幅图）"""
    w = float(map_obj.grid_width)
    h = float(map_obj.grid_height)
    lon = map_obj.lon_min + (px / w) * (map_obj.lon_max - map_obj.lon_min)
    lat = map_obj.lat_max - (py / h) * (map_obj.lat_max - map_obj.lat_min)
    return lon, lat


def lonlat_to_px(map_obj, lon: float, lat: float):
    """经纬度 -> 栅格像素"""
    w = float(map_obj.grid_width)
    h = float(map_obj.grid_height)
    px = (lon - map_obj.lon_min) / (map_obj.lon_max - map_obj.lon_min) * w
    py = (map_obj.lat_max - lat) / (map_obj.lat_max - map_obj.lat_min) * h
    return px, py


def pc_to_lonlat(map_obj, x: float, y: float):
    """点云 -> 经纬度（经栅格中转；需要 grid + bounds 都齐全）"""
    px, py = pc_to_px(map_obj, x, y)
    return px_to_lonlat(map_obj, px, py)


def lonlat_to_pc(map_obj, lon: float, lat: float):
    """经纬度 -> 点云（经栅格中转；需要 grid + bounds 都齐全）"""
    px, py = lonlat_to_px(map_obj, lon, lat)
    return px_to_pc(map_obj, px, py)


def convert(map_obj, *, px: Optional[float] = None, py: Optional[float] = None,
            x: Optional[float] = None, y: Optional[float] = None,
            lon: Optional[float] = None, lat: Optional[float] = None) -> Dict[str, Optional[float]]:
    """给定任意一套坐标（像素 / 点云 / 经纬度），返回能算出来的全部坐标

    至少传一对完整的坐标；无法换算的值返回 None。
    """
    grid_ok = has_grid(map_obj)
    bounds_ok = has_bounds(map_obj)

    if px is not None and py is not None:
        if grid_ok:
            x, y = px_to_pc(map_obj, px, py)
        if bounds_ok and grid_ok:
            lon, lat = px_to_lonlat(map_obj, px, py)
    elif x is not None and y is not None:
        if grid_ok:
            px, py = pc_to_px(map_obj, x, y)
            if bounds_ok:
                lon, lat = px_to_lonlat(map_obj, px, py)
    elif lon is not None and lat is not None:
        if bounds_ok and grid_ok:
            px, py = lonlat_to_px(map_obj, lon, lat)
            x, y = px_to_pc(map_obj, px, py)

    return {
        "px": None if px is None else round(float(px), 3),
        "py": None if py is None else round(float(py), 3),
        "x": None if x is None else round(float(x), 3),
        "y": None if y is None else round(float(y), 3),
        "lon": None if lon is None else round(float(lon), 7),
        "lat": None if lat is None else round(float(lat), 7),
    }