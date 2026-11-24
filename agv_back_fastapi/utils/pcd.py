"""
PCD 点云工具：解析 / 体素降采样 / 写回二进制 PCD / 俯视投影成栅格 PNG。

只依赖 numpy 与标准库（PNG 用 zlib 自写），不引入 open3d / Pillow / PCL。
支持 DATA=ascii / binary；binary_compressed 会明确报错（可用 pcl 转 binary）。
"""
import math
import struct
import zlib
from typing import Dict, Tuple

import numpy as np


class PcdFormatError(ValueError):
    """点云文件格式不支持时抛出"""


_XYZ_FIELDS = ("x", "y", "z")


def read_pcd_header(path: str) -> Dict[str, object]:
    """读取 PCD 头部；返回 {FIELDS, SIZE, TYPE, COUNT, WIDTH, HEIGHT, POINTS, DATA, DATA_OFFSET}"""
    header: Dict[str, object] = {}
    data_offset = 0
    with open(path, "rb") as f:
        while True:
            raw = f.readline()
            if not raw:
                raise PcdFormatError("PCD 头部不完整（没读到 DATA 行）")
            data_offset = f.tell()
            try:
                line = raw.decode("ascii").strip()
            except UnicodeDecodeError:
                raise PcdFormatError("PCD 头部不是 ASCII，可能不是点云文件")
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            key = parts[0].upper()
            if key == "FIELDS":
                header["FIELDS"] = [p.lower() for p in parts[1:]]
            elif key == "SIZE":
                header["SIZE"] = [int(x) for x in parts[1:]]
            elif key == "TYPE":
                header["TYPE"] = [p.upper() for p in parts[1:]]
            elif key == "COUNT":
                header["COUNT"] = [int(x) for x in parts[1:]]
            elif key == "WIDTH":
                header["WIDTH"] = int(parts[1])
            elif key == "HEIGHT":
                header["HEIGHT"] = int(parts[1])
            elif key == "POINTS":
                header["POINTS"] = int(parts[1])
            elif key == "DATA":
                header["DATA"] = parts[1].lower()
                break
            else:
                header[key] = parts[1:]
    header["DATA_OFFSET"] = data_offset
    return header


def read_pcd_xyz(path: str) -> np.ndarray:
    """读取 PCD 的 x/y/z，返回 (N,3) float32；已剔除 NaN/Inf"""
    header = read_pcd_header(path)
    fields = header.get("FIELDS") or []
    for k in _XYZ_FIELDS:
        if k not in fields:
            raise PcdFormatError("PCD 缺少 %s 字段（FIELDS=%s）" % (k, fields))
    points = int(header.get("POINTS") or (int(header["WIDTH"]) * int(header.get("HEIGHT") or 1)))
    data_format = header.get("DATA")

    if data_format == "ascii":
        with open(path, "rb") as f:
            f.seek(int(header["DATA_OFFSET"]))
            text = f.read().decode("ascii", errors="replace")
        cols = len(fields)
        values = np.array(text.split(), dtype=np.float64)
        values = values[: (len(values) // cols) * cols].reshape(-1, cols)
        if len(values) == 0:
            raise PcdFormatError("PCD 数据为空")
        idx = [fields.index(k) for k in _XYZ_FIELDS]
        xyz = values[:, idx].astype(np.float32)
    elif data_format == "binary":
        sizes = header["SIZE"]
        types = header["TYPE"]
        counts = header.get("COUNT") or [1] * len(fields)
        dtype_fields = []
        point_step = 0
        for name, size, typ, cnt in zip(fields, sizes, types, counts):
            if typ == "F":
                dt = "f%d" % size
            elif typ == "I":
                dt = "i%d" % size
            elif typ == "U":
                dt = "u%d" % size
            else:
                raise PcdFormatError("未知的 TYPE: %s" % typ)
            dtype_fields.append((name, dt) if cnt == 1 else (name, dt, (cnt,)))
            point_step += size * cnt
        dtype = np.dtype(dtype_fields)
        with open(path, "rb") as f:
            f.seek(int(header["DATA_OFFSET"]))
            raw = f.read(points * point_step)
        if len(raw) < points * point_step:
            raise PcdFormatError("PCD 二进制数据不完整（期望 %d 字节，实际 %d）" % (points * point_step, len(raw)))
        arr = np.frombuffer(raw, dtype=dtype, count=points)
        xyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float32)
    elif data_format == "binary_compressed":
        raise PcdFormatError("暂不支持 binary_compressed，请先用 pcl_convert_pcd_ascii_binary 或 CloudCompare 转成 binary")
    else:
        raise PcdFormatError("未知的 DATA 类型: %s" % data_format)

    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    if len(xyz) == 0:
        raise PcdFormatError("PCD 没有有效点（全是 NaN/Inf？）")
    return xyz


def write_pcd_binary(path: str, xyz: np.ndarray) -> int:
    """把 (N,3) 写回 binary PCD，返回点数"""
    pts = np.ascontiguousarray(xyz, dtype=np.float32)
    n = int(len(pts))
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\n"
        "FIELDS x y z\n"
        "SIZE 4 4 4\n"
        "TYPE F F F\n"
        "COUNT 1 1 1\n"
        "WIDTH %d\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        "POINTS %d\n"
        "DATA binary\n" % (n, n)
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(pts.tobytes())
    return n


def voxel_downsample(xyz: np.ndarray, leaf_size: float = 0.05) -> np.ndarray:
    """体素降采样：每个体素取质心（numpy 向量化，千万点在秒级）"""
    if leaf_size is None or leaf_size <= 0:
        raise ValueError("leaf_size 必须大于 0")
    pts = np.ascontiguousarray(xyz, dtype=np.float64)
    if len(pts) == 0:
        return np.zeros((0, 3), dtype=np.float32)
    keys = np.floor(pts / float(leaf_size)).astype(np.int64)
    keys -= keys.min(axis=0)
    dims = keys.max(axis=0) + 1
    flat = (keys[:, 0] * dims[1] + keys[:, 1]) * dims[2] + keys[:, 2]
    uniq, inverse = np.unique(flat, return_inverse=True)
    counts = np.bincount(inverse, minlength=len(uniq)).astype(np.float64)
    sums = np.empty((len(uniq), 3), dtype=np.float64)
    for i in range(3):
        sums[:, i] = np.bincount(inverse, weights=pts[:, i], minlength=len(uniq))
    centers = sums / counts[:, None]
    return centers.astype(np.float32)

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: str, pixels: np.ndarray) -> None:
    """写 PNG：pixels 支持 (h,w) uint8 灰度 或 (h,w,4) uint8 RGBA"""
    if pixels.ndim == 2:
        color_type = 0
    elif pixels.ndim == 3 and pixels.shape[2] == 4:
        color_type = 6
    else:
        raise ValueError("只支持灰度 (h,w) 或 RGBA (h,w,4)")
    h, w = pixels.shape[:2]
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        raw.extend(row.tobytes())
    ihdr = struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_png_chunk(b"IHDR", ihdr))
        f.write(_png_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        f.write(_png_chunk(b"IEND", b""))


def build_grid(xyz: np.ndarray, resolution: float = 0.05, mode: str = "occupancy",
               z_low: float = 0.15, z_high: float = 1.8, max_side: int = 8000) -> Tuple[np.ndarray, Dict[str, float]]:
    """俯视投影成栅格图，返回 (pixels, meta)

    - mode=occupancy：RGBA，障碍=(25,25,25,255)，可见地面=(255,255,255,255)，无点=透明(0,0,0,0)
    - mode=height：灰度，按高度归一化（越高越亮）
    - 障碍判定：相对地面（z 的 5% 分位）高度落在 [z_low, z_high] 米内的点
    - 图像第 0 行 = 北（原图正北朝上），第 0 列 = 西
    """
    pts = xyz[np.isfinite(xyz).all(axis=1)]
    if len(pts) == 0:
        raise ValueError("点云为空")
    if resolution <= 0:
        raise ValueError("resolution 必须大于 0")

    min_x, max_x = float(pts[:, 0].min()), float(pts[:, 0].max())
    min_y, max_y = float(pts[:, 1].min()), float(pts[:, 1].max())
    min_z, max_z = float(pts[:, 2].min()), float(pts[:, 2].max())
    z_floor = float(np.percentile(pts[:, 2], 5))

    width = int(math.floor((max_x - min_x) / resolution)) + 1
    height = int(math.floor((max_y - min_y) / resolution)) + 1
    if max(width, height) > max_side:
        raise ValueError("栅格尺寸 %dx%d 超过上限 %d，请调大 resolution（当前 %.3f m/px）" % (width, height, max_side, resolution))

    origin_x = min_x
    origin_y = max_y
    cols = np.clip(((pts[:, 0] - origin_x) / resolution).astype(np.int64), 0, width - 1)
    rows = np.clip(((origin_y - pts[:, 1]) / resolution).astype(np.int64), 0, height - 1)
    flat = rows * width + cols
    cells = width * height

    meta = {
        "width": width, "height": height, "resolution": float(resolution),
        "origin_x": origin_x, "origin_y": origin_y, "z_floor": z_floor,
        "min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y,
        "min_z": min_z, "max_z": max_z, "mode": mode,
    }

    if mode == "height":
        maxz = np.full(cells, -np.inf, dtype=np.float64)
        np.maximum.at(maxz, flat, pts[:, 2])
        img = np.zeros(cells, dtype=np.float32)
        valid = np.isfinite(maxz)
        if valid.any():
            lo, hi = float(maxz[valid].min()), float(maxz[valid].max())
            span = hi - lo if hi > lo else 1.0
            img[valid] = (maxz[valid] - lo) / span * 255.0
        return img.reshape(height, width).astype(np.uint8), meta

    total = np.bincount(flat, minlength=cells)
    z = pts[:, 2] - z_floor
    band = (z >= float(z_low)) & (z <= float(z_high))
    occ = np.bincount(flat[band], minlength=cells) if bool(band.any()) else np.zeros(cells, dtype=np.int64)
    rgba = np.zeros((cells, 4), dtype=np.uint8)
    rgba[total > 0] = (255, 255, 255, 255)
    rgba[occ > 0] = (25, 25, 25, 255)
    return rgba.reshape(height, width, 4), meta