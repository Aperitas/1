"""
三套坐标互转：栅格像素 (px, py) <-> 点云米 (x, y) <-> 经纬度 (lon, lat)

=====================================================================
一、像素 -> 点云：统一用 2x3 仿射矩阵表示
=====================================================================

    x = a*px + b*py + c
    y = d*px + e*py + f

矩阵来源按优先级取：

1) `tf_affine`（JSON [a,b,c,d,e,f]）—— 前端自己解算（如三点对齐）后直接传；
2) 三轴便捷参数：`tf_scale` / `tf_rot_deg`(yaw) / `tf_pitch_deg` / `tf_roll_deg` / `tf_tx` / `tf_ty`
   其中 scale/tx/ty 为空时分别回退到 `grid_resolution` / `grid_origin_x` / `grid_origin_y`；
3) 都没有时按「grid 生成的相似变换」处理（等价 yaw=pitch=roll=0）。

镜像：map.grid_flip_x / grid_flip_y 会把 px / py 取反（等价于图像左右/上下翻转），
    因此自动体现在像素->点云里；此时 grid_origin_x / grid_origin_y 是「翻转后图像左上角」的点云坐标。

三轴 -> 仿射的推导（与 docs/map-guide.md §15 一致）：

    图像平面点取 (u, v, 0)，其中 u = s*px、v = -s*py（图像 y 向下、点云 y 向上）；
    依次绕 Z(yaw) / Y(pitch) / X(roll) 旋转：R = Rz(yaw) * Ry(pitch) * Rx(roll)；
    正交俯视只取结果的 X、Y 分量（z 丢弃），再加上平移 (tx, ty)。

    展开后：
        a =  s*cos(y)*cos(p)
        b = -s*(cos(y)*sin(r)*sin(p) - sin(y)*cos(r))
        c =  tx
        d =  s*sin(y)*cos(p)
        e = -s*(sin(y)*sin(r)*sin(p) + cos(y)*cos(r))
        f =  ty

    校验：pitch=roll=0 时退化为纯相似变换：
        a = s*cos(y), b = s*sin(y), d = s*sin(y), e = -s*cos(y)

=====================================================================
二、像素 <-> 经纬度：图像铺满 bounds
=====================================================================

    lon = lon_min + px / grid_width  * (lon_max - lon_min)
    lat = lat_max - py / grid_height * (lat_max - lat_min)

图像约定：第 0 行 = 北，第 0 列 = 西（正北朝上）。bounds 只决定「图贴到地图上的位置」，
与「像素 <-> 点云」的变换互相独立（方案 A：拖图不会自动改 bounds）。
"""
import json
import math
from typing import Dict, List, Optional

M_PER_DEG_LAT = 111320.0


def euler_to_affine(scale: float, yaw_deg: float = 0.0, pitch_deg: float = 0.0,
                    roll_deg: float = 0.0, tx: float = 0.0, ty: float = 0.0) -> List[float]:
    """三轴角（度）+ 等比缩放 + 平移 -> 2x3 仿射 [a,b,c,d,e,f]（推导见模块注释）"""
    y = math.radians(yaw_deg)
    p = math.radians(pitch_deg)
    r = math.radians(roll_deg)
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)

    a = scale * cy * cp
    b = -scale * (cy * sr * sp - sy * cr)
    d = scale * sy * cp
    e = -scale * (sy * sr * sp + cy * cr)
    return [a, b, tx, d, e, ty]


def get_affine(map_obj) -> Optional[Dict[str, object]]:
    """解析当前地图生效的「像素 -> 点云」仿射变换

    返回 dict（信息不全返回 None）：
        a,b,c,d,e,f : 仿射参数
        mode        : affine（直接存了矩阵） / euler（三轴） / similarity（只有 yaw） / grid（回退到点云处理生成值）
        source      : tf / grid（是否用过 tf_* 字段）
        scale, yaw_deg, pitch_deg, roll_deg, tx, ty : 便于前端展示的等价参数
    """
    # 1) 前端直接传的仿射矩阵，优先级最高
    raw = getattr(map_obj, "tf_affine", None)
    if raw:
        try:
            vals = json.loads(raw) if isinstance(raw, str) else list(raw)
            if isinstance(vals, list) and len(vals) == 6:
                a, b, c, d, e, f = [float(v) for v in vals]
                return {
                    "a": a, "b": b, "c": c, "d": d, "e": e, "f": f,
                    "mode": "affine", "source": "tf",
                    "scale": math.hypot(a, d), "yaw_deg": math.degrees(math.atan2(d, a)),
                    "pitch_deg": 0.0, "roll_deg": 0.0, "tx": c, "ty": f,
                    "flip_x": bool(getattr(map_obj, "grid_flip_x", False)),
                    "flip_y": bool(getattr(map_obj, "grid_flip_y", False)),
                }
        except Exception:
            pass  # 脏数据当作没设置，继续走三轴/回退逻辑

    # 2) 三轴 / 相似参数（scale、tx、ty 允许回退到点云处理生成的值）
    scale = map_obj.tf_scale if map_obj.tf_scale else map_obj.grid_resolution
    tx = map_obj.tf_tx if map_obj.tf_tx is not None else map_obj.grid_origin_x
    ty = map_obj.tf_ty if map_obj.tf_ty is not None else map_obj.grid_origin_y
    if not scale or tx is None or ty is None:
        return None

    yaw = float(map_obj.tf_rot_deg or 0.0)
    pitch = float(getattr(map_obj, "tf_pitch_deg", None) or 0.0)
    roll = float(getattr(map_obj, "tf_roll_deg", None) or 0.0)
    a, b, c, d, e, f = euler_to_affine(float(scale), yaw, pitch, roll, float(tx), float(ty))

    # 镜像：flip_x 让 px 取反（a、d 变号）；flip_y 让 py 取反（b、e 变号）
    flip_x = bool(getattr(map_obj, "grid_flip_x", False))
    flip_y = bool(getattr(map_obj, "grid_flip_y", False))
    if flip_x:
        a, d = -a, -d
    if flip_y:
        b, e = -b, -e

    any_tf = any(v is not None for v in (
        map_obj.tf_scale, map_obj.tf_rot_deg, map_obj.tf_tx, map_obj.tf_ty,
        getattr(map_obj, "tf_pitch_deg", None), getattr(map_obj, "tf_roll_deg", None),
    ))
    if pitch or roll:
        mode = "euler"
    elif any_tf:
        mode = "similarity"
    else:
        mode = "grid"

    return {
        "a": a, "b": b, "c": c, "d": d, "e": e, "f": f,
        "mode": mode, "source": "tf" if any_tf else "grid",
        "scale": float(scale), "yaw_deg": yaw, "pitch_deg": pitch, "roll_deg": roll,
        "tx": float(tx), "ty": float(ty),
        "flip_x": flip_x, "flip_y": flip_y,
    }


def get_transform(map_obj) -> Optional[Dict[str, object]]:
    """兼容旧调用：返回 {"scale","rot_deg","tx","ty","source","mode","affine"}"""
    aff = get_affine(map_obj)
    if aff is None:
        return None
    return {
        "scale": aff["scale"],
        "rot_deg": aff["yaw_deg"],
        "pitch_deg": aff["pitch_deg"],
        "roll_deg": aff["roll_deg"],
        "tx": aff["tx"],
        "ty": aff["ty"],
        "source": aff["source"],
        "mode": aff["mode"],
        "affine": [aff["a"], aff["b"], aff["c"], aff["d"], aff["e"], aff["f"]],
        "flip_x": bool(aff.get("flip_x", False)),
        "flip_y": bool(aff.get("flip_y", False)),
    }


def has_grid(map_obj) -> bool:
    """像素 <-> 点云 是否可换算（有变换 + 图像宽高）"""
    return get_affine(map_obj) is not None and bool(map_obj.grid_width) and bool(map_obj.grid_height)


def has_bounds(map_obj) -> bool:
    """经纬度 <-> 像素 是否可换算（区域四角齐全）"""
    return None not in (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max) \
        and map_obj.lon_max > map_obj.lon_min and map_obj.lat_max > map_obj.lat_min


def px_to_pc(map_obj, px: float, py: float):
    """栅格像素 -> 点云 (x, y)"""
    aff = get_affine(map_obj)
    if aff is None:
        raise ValueError("地图缺少「像素->点云」变换信息，请先做点云处理或设置 transform")
    x = aff["a"] * float(px) + aff["b"] * float(py) + aff["c"]
    y = aff["d"] * float(px) + aff["e"] * float(py) + aff["f"]
    return x, y


def pc_to_px(map_obj, x: float, y: float):
    """点云 (x, y) -> 栅格像素（2x2 部分求逆）"""
    aff = get_affine(map_obj)
    if aff is None:
        raise ValueError("地图缺少「像素->点云」变换信息，请先做点云处理或设置 transform")
    a, b, c, d, e, f = aff["a"], aff["b"], aff["c"], aff["d"], aff["e"], aff["f"]
    det = a * e - b * d
    if abs(det) < 1e-12:
        raise ValueError("变换矩阵不可逆（det≈0），请检查 scale / 旋转角")
    dx = float(x) - c
    dy = float(y) - f
    px = (e * dx - b * dy) / det
    py = (-d * dx + a * dy) / det
    return px, py


def px_to_lonlat(map_obj, px: float, py: float):
    """栅格像素 -> 经纬度（按 bounds 铺满整幅图）"""
    w = float(map_obj.grid_width)
    h = float(map_obj.grid_height)
    lon = map_obj.lon_min + (float(px) / w) * (map_obj.lon_max - map_obj.lon_min)
    lat = map_obj.lat_max - (float(py) / h) * (map_obj.lat_max - map_obj.lat_min)
    return lon, lat


def lonlat_to_px(map_obj, lon: float, lat: float):
    """经纬度 -> 栅格像素"""
    w = float(map_obj.grid_width)
    h = float(map_obj.grid_height)
    px = (float(lon) - map_obj.lon_min) / (map_obj.lon_max - map_obj.lon_min) * w
    py = (map_obj.lat_max - float(lat)) / (map_obj.lat_max - map_obj.lat_min) * h
    return px, py


def pc_to_lonlat(map_obj, x: float, y: float):
    """点云 -> 经纬度（经栅格中转：pc -> px -> lonlat）"""
    px, py = pc_to_px(map_obj, x, y)
    return px_to_lonlat(map_obj, px, py)


def lonlat_to_pc(map_obj, lon: float, lat: float):
    """经纬度 -> 点云（经栅格中转：lonlat -> px -> pc）"""
    px, py = lonlat_to_px(map_obj, lon, lat)
    return px_to_pc(map_obj, px, py)


def corners_pc(map_obj) -> Optional[Dict[str, Dict[str, float]]]:
    """图像四角在点云坐标系里的位置（lt=左上 / rt=右上 / rb=右下 / lb=左下）"""
    aff = get_affine(map_obj)
    if aff is None or not map_obj.grid_width or not map_obj.grid_height:
        return None
    w = float(map_obj.grid_width)
    h = float(map_obj.grid_height)

    def _at(px, py):
        x = aff["a"] * px + aff["b"] * py + aff["c"]
        y = aff["d"] * px + aff["e"] * py + aff["f"]
        return {"x": round(x, 3), "y": round(y, 3)}

    return {"lt": _at(0, 0), "rt": _at(w, 0), "rb": _at(w, h), "lb": _at(0, h)}


def corners_lonlat(map_obj) -> Optional[Dict[str, Dict[str, float]]]:
    """图像四角按 bounds 铺满后的经纬度（等价于 bounds 四角）"""
    if not has_bounds(map_obj):
        return None
    w = float(map_obj.grid_width or 1)
    h = float(map_obj.grid_height or 1)
    corners = {
        "lt": px_to_lonlat(map_obj, 0, 0),
        "rt": px_to_lonlat(map_obj, w, 0),
        "rb": px_to_lonlat(map_obj, w, h),
        "lb": px_to_lonlat(map_obj, 0, h),
    }
    return {k: {"lon": round(v[0], 8), "lat": round(v[1], 8)} for k, v in corners.items()}


def transform_check(map_obj, warn_ratio: float = 0.05) -> Dict[str, object]:
    """变换自检：图像在两个轴上的物理尺寸 vs bounds 换算尺寸

    用于发现「图被拖动/旋转过、但 bounds 没跟着改」——这类情况经纬度展示会偏，
    但车端用的「像素 <-> 点云」不受影响。
    """
    aff = get_affine(map_obj)
    result: Dict[str, object] = {
        "has_grid": bool(aff is not None and map_obj.grid_width and map_obj.grid_height),
        "has_bounds": has_bounds(map_obj),
        "transform": get_transform(map_obj),
        "grid_width": map_obj.grid_width,
        "grid_height": map_obj.grid_height,
        "warnings": [],
    }
    if not result["has_grid"]:
        result["warnings"].append("缺少栅格尺寸或变换信息，无法做尺度自检")
        return result

    # 图像宽/高在点云里的实际长度 = 列向量/行向量的模
    w = float(map_obj.grid_width)
    h = float(map_obj.grid_height)
    img_w_m = w * math.hypot(aff["a"], aff["d"])
    img_h_m = h * math.hypot(aff["b"], aff["e"])
    result["image_size_m"] = {"width": round(img_w_m, 3), "height": round(img_h_m, 3)}

    if not result["has_bounds"]:
        result["warnings"].append("地图未填 bounds，经纬度相关换算不可用")
        return result

    mean_lat = (map_obj.lat_min + map_obj.lat_max) / 2.0
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(mean_lat))
    bw = (map_obj.lon_max - map_obj.lon_min) * m_per_deg_lon
    bh = (map_obj.lat_max - map_obj.lat_min) * M_PER_DEG_LAT
    result["bounds_size_m"] = {"width": round(bw, 3), "height": round(bh, 3)}

    ratio_w = (img_w_m / bw) if bw else None
    ratio_h = (img_h_m / bh) if bh else None
    result["scale_ratio"] = {
        "width": None if ratio_w is None else round(ratio_w, 4),
        "height": None if ratio_h is None else round(ratio_h, 4),
    }
    for name, ratio in (("宽度", ratio_w), ("高度", ratio_h)):
        if ratio is not None and abs(ratio - 1.0) > warn_ratio:
            result["warnings"].append(
                "%s方向尺度偏差 %.1f%%：图像物理尺寸与 bounds 换算尺寸不一致，请检查 bounds 或 transform"
                % (name, (ratio - 1.0) * 100.0)
            )
    return result


def convert(map_obj, *, px: Optional[float] = None, py: Optional[float] = None,
            x: Optional[float] = None, y: Optional[float] = None,
            lon: Optional[float] = None, lat: Optional[float] = None) -> Dict[str, Optional[float]]:
    """给定任意一套坐标（像素 / 点云 / 经纬度），返回能算出来的全部坐标；算不出的为 None"""
    grid_ok = has_grid(map_obj)
    bounds_ok = has_bounds(map_obj)

    if px is not None and py is not None:
        if grid_ok:
            x, y = px_to_pc(map_obj, px, py)
        if bounds_ok:
            lon, lat = px_to_lonlat(map_obj, px, py)
    elif x is not None and y is not None:
        if grid_ok:
            px, py = pc_to_px(map_obj, x, y)
            if bounds_ok:
                lon, lat = px_to_lonlat(map_obj, px, py)
    elif lon is not None and lat is not None:
        if bounds_ok:
            px, py = lonlat_to_px(map_obj, lon, lat)
            if grid_ok:
                x, y = px_to_pc(map_obj, px, py)

    return {
        "px": None if px is None else round(float(px), 3),
        "py": None if py is None else round(float(py), 3),
        "x": None if x is None else round(float(x), 3),
        "y": None if y is None else round(float(y), 3),
        "lon": None if lon is None else round(float(lon), 7),
        "lat": None if lat is None else round(float(lat), 7),
    }


def resolve_pc_lonlat(map_obj, lon=None, lat=None, pc_x=None, pc_y=None):
    """把 (lon,lat) 与 (pc_x,pc_y) 统一成两套都有的值

    返回 (lon, lat, pc_x, pc_y, error)：
    - 只传 pc -> 反算 lon/lat；只传 lon/lat -> 正算 pc；
    - 两套都给 -> 校验偏差（超过 1 米报错）；
    - 都没有 / 不成对 -> 报错。
    """
    if lon is None and lat is None and pc_x is None and pc_y is None:
        return None, None, None, None, "请传 lon/lat 或 pc_x/pc_y"
    if (lon is None) != (lat is None) or (pc_x is None) != (pc_y is None):
        return None, None, None, None, "lon/lat 或 pc_x/pc_y 必须成对出现"

    can = bool(has_grid(map_obj) and has_bounds(map_obj))
    if pc_x is not None:
        if not can:
            return None, None, None, None, "该地图缺少栅格↔经纬度映射（需先做点云处理并填 bounds），无法用点云坐标反算经纬度"
        lon2, lat2 = pc_to_lonlat(map_obj, pc_x, pc_y)
        if lon is not None:
            x2, y2 = lonlat_to_pc(map_obj, lon, lat)
            if abs(x2 - pc_x) > 1.0 or abs(y2 - pc_y) > 1.0:
                return None, None, None, None, "传入的 lon/lat 与 pc_x/pc_y 不一致（偏差超过 1 米）"
        return lon2, lat2, float(pc_x), float(pc_y), None

    if not can:
        return float(lon), float(lat), None, None, None
    x, y = lonlat_to_pc(map_obj, lon, lat)
    return float(lon), float(lat), x, y, None


def get_ros_frame(map_obj):
    """ROS map_server 导出用的「规范帧」：忽略镜像、只允许等比 + 旋转

    返回 (dict, error)：
        dict = {"resolution": 米/像素, "yaw": 弧度, "origin_x": 左下角点云X, "origin_y": 左下角点云Y}

    为什么忽略镜像：yaml 的 origin 只有 (x, y, yaw)，表达不了镜像；
    所以导出时总是按「图像上方 = +y」的规范方向重新生成 PGM，位置由 origin + yaw 描述。
    """
    aff = get_affine(map_obj)
    if aff is None:
        return None, "缺少「像素->点云」变换，无法导出 ROS 地图"

    # 先撤掉镜像，得到规范方向的线性部分
    a, b, d, e = aff["a"], aff["b"], aff["d"], aff["e"]
    if bool(getattr(map_obj, "grid_flip_x", False)):
        a, d = -a, -d
    if bool(getattr(map_obj, "grid_flip_y", False)):
        b, e = -b, -e

    tol = 1e-6 * (abs(a) + abs(d) + 1e-9)
    if abs(b - d) > tol or abs(e + a) > tol:
        return None, (
            "当前变换含 pitch/roll 或剪切，ROS map_server 只支持「等比 + 旋转」，"
            "请先把 pitch_deg / roll_deg 置 0（自定义 affine 需为相似矩阵）"
        )

    resolution = math.hypot(a, d)
    grid_res = float(map_obj.grid_resolution or 0.0)
    if grid_res and abs(resolution - grid_res) > 1e-6 * max(grid_res, 1e-9):
        return None, (
            "变换的缩放(%.6f m/px)与栅格分辨率(%.6f m/px)不一致，"
            "请先 reset transform 再导出 ROS 地图" % (resolution, grid_res)
        )

    if map_obj.pc_min_x is None or map_obj.pc_min_y is None:
        return None, "缺少点云包围盒（pc_min_x / pc_min_y），请先做点云处理"

    return {
        "resolution": float(resolution),
        "yaw": math.atan2(d, a),
        "origin_x": float(map_obj.pc_min_x),
        "origin_y": float(map_obj.pc_min_y),
    }, None
