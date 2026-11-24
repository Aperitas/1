from fastapi import APIRouter, Depends, Query, Body, File, UploadFile, Form, Path as ApiPath
from sqlmodel import Session, select, update
from db.session import get_session
from models.map import Map, MapType
from models.site import Site
from models.waypoint import Waypoint
from models.path import Path
from models.car.car import Cars
from models.car.map_link import CarMapLink
from models.user.map_link import UserMapLink
from apis.access import visible_map_ids
from apis.views import car_payload
from core.logger import logger
from schemas.map import MapCreate, MapUpdate, MapOut, MapTransformIn
from schemas.resp import ApiResponse
from apis.api_docs import MAP_READ, MAP_WRITE, MAP_UPLOAD, MAP_ONE_SHOT, MAP_PROCESS, MAP_COORDS, MAP_TRANSFORM, MAP_ROS
from utils.resp_code import resp_200, resp_400, resp_500
from utils.patch import clean_update
from utils.pcd import (
    PcdFormatError, build_grid, build_grid_in_frame, read_pcd_xyz,
    voxel_downsample, write_pcd_binary, write_pgm, write_png,
)
from utils.coords import (
    convert as convert_coords, corners_lonlat, corners_pc, get_transform,
    get_affine, has_bounds as map_has_bounds, has_grid as map_has_grid, px_to_pc, transform_check,
)
from core.security import get_current_user, get_current_admin
from models.user import Users
from typing import List, Optional
import math
import mimetypes
import uuid
import os
import re
import shutil
import time
import json
from datetime import datetime
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/admin/maps", tags=["地图管理"])

VALID_MAP_TYPES = {t.value for t in MapType}

# 允许上传的文件类型（按槽位区分）
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
POINTCLOUD_SUFFIXES = {".pcd", ".ply", ".las", ".laz", ".xyz", ".zip"}

# Windows 下 mimetypes 可能缺少部分类型映射；显式注册后，上传返回值与 StaticFiles 的 Content-Type 都会正确
for _ext, _ct in (
    (".webp", "image/webp"),
    (".tif", "image/tiff"),
    (".tiff", "image/tiff"),
    (".bmp", "image/bmp"),
    (".pcd", "application/octet-stream"),
    (".ply", "application/octet-stream"),
    (".las", "application/octet-stream"),
    (".laz", "application/octet-stream"),
    (".xyz", "text/plain"),
):
    mimetypes.add_type(_ct, _ext)


def _safe_stem(filename) -> str:
    # 去掉目录与特殊字符，防止路径穿越；长度截断
    stem = os.path.splitext(os.path.basename(filename or ""))[0] or "file"
    return re.sub(r"[^\w.\-]", "_", stem)[:80]


def _apply_corner_fields(payload: dict) -> dict:
    """支持用 左上/右下 角点写法（left_top_*/right_bottom_*）代替 lon_min/lat_min/lon_max/lat_max"""
    left_top_lon = payload.pop("left_top_lon", None)
    left_top_lat = payload.pop("left_top_lat", None)
    right_bottom_lon = payload.pop("right_bottom_lon", None)
    right_bottom_lat = payload.pop("right_bottom_lat", None)
    if left_top_lon is not None:
        payload["lon_min"] = left_top_lon
    if left_top_lat is not None:
        payload["lat_max"] = left_top_lat
    if right_bottom_lon is not None:
        payload["lon_max"] = right_bottom_lon
    if right_bottom_lat is not None:
        payload["lat_min"] = right_bottom_lat
    return payload


def _cleanup_created_map(session: Session, map_obj, written):
    """一步建图失败时回滚：删掉半成品文件与已插入的地图记录"""
    for path in written or []:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            logger.warning("清理半成品文件失败 %s: %s" % (path, exc))
    if map_obj is None or getattr(map_obj, "id", None) is None:
        return
    try:
        exists = session.get(Map, map_obj.id)
        if exists is not None:
            session.delete(exists)
            session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("回滚地图记录失败 %s: %s" % (map_obj.id, exc))


def _file_url(path: Optional[str]) -> Optional[str]:
    """把磁盘路径转换成 /static 访问地址"""
    return f"/static/maps/{os.path.basename(path)}" if path else None


def _bounds_payload(map_obj: Map) -> Optional[dict]:
    """左上 / 右下角点（四个值齐全时返回）"""
    if None in (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max):
        return None
    return {
        "left_top": {"lon": map_obj.lon_min, "lat": map_obj.lat_max},
        "right_bottom": {"lon": map_obj.lon_max, "lat": map_obj.lat_min},
    }


def _map_payload(map_obj: Map) -> dict:
    """地图标准输出：含点云/栅格两个文件地址与 bounds 角点"""
    data = map_obj.dict()
    data["pointcloud_file_url"] = _file_url(map_obj.pointcloud_file_path)
    data["grid_file_url"] = _file_url(map_obj.grid_file_path)
    data["file_url"] = data["pointcloud_file_url"] or data["grid_file_url"]
    data["bounds"] = _bounds_payload(map_obj)
    return data


def _validate_map_object(map_obj: Map, session: Session) -> Optional[str]:
    """校验地图类型、区域角点、兜底地图；区域坐标"传了才校验"，返回错误信息或 None"""
    if map_obj.map_type not in VALID_MAP_TYPES:
        return f"map_type 只能是 {sorted(VALID_MAP_TYPES)}"
    bounds = (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max)
    provided = [value for value in bounds if value is not None]
    if provided:
        if len(provided) != 4:
            return "区域坐标需同时提供四个值：lon_min/lat_min/lon_max/lat_max（或 left_top/right_bottom）"
        if map_obj.lon_min >= map_obj.lon_max or map_obj.lat_min >= map_obj.lat_max:
            return "区域坐标非法：需满足 左<右（lon_min<lon_max）且 下<上（lat_min<lat_max）"
        if not (-180 <= map_obj.lon_min <= 180 and -180 <= map_obj.lon_max <= 180):
            return "经度必须在 -180~180 之间"
        if not (-90 <= map_obj.lat_min <= 90 and -90 <= map_obj.lat_max <= 90):
            return "纬度必须在 -90~90 之间"
    if map_obj.fallback_map_id is not None:
        if map_obj.id is not None and map_obj.fallback_map_id == map_obj.id:
            return "兜底地图不能指向自己"
        fallback = session.get(Map, map_obj.fallback_map_id)
        if fallback is None:
            return f"兜底地图不存在: {map_obj.fallback_map_id}"
        if fallback.map_type != MapType.LOCAL.value:
            return "兜底地图必须是本地地图(local)"
    return None

# 地图文件存储目录
MAP_UPLOAD_DIR = "static/maps"
os.makedirs(MAP_UPLOAD_DIR, exist_ok=True)


@router.post("/", summary="新增地图", description=MAP_WRITE)
async def create_map(
        data: MapCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员新增地图：tianditu=天地图 / local=本地地图（点云+栅格）。
    区域坐标可用 left_top/right_bottom 写法，也可以不传（后续补录）。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    payload = _apply_corner_fields(data.dict())
    try:
        new_map = Map(**payload)
    except Exception as e:
        return resp_400(msg=f"参数错误：{str(e)}")
    error = _validate_map_object(new_map, session)
    if error:
        return resp_400(msg=error)
    try:
        session.add(new_map)
        session.commit()
        session.refresh(new_map)
        return resp_200(data=_map_payload(new_map), msg="地图创建成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"创建失败：{str(e)}")


@router.post("/upload", summary="上传地图文件（点云/栅格）", description=MAP_UPLOAD)
async def upload_map_file(
        map_id: int = Form(..., description="要绑定文件的地图ID"),
        kind: str = Form("pointcloud", description="文件类型：pointcloud=点云文件 / grid=栅格文件"),
        file: UploadFile = File(..., description="要上传的文件（.pcd/.ply/.png/.tif/.zip 等）"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """上传或替换地图文件：
    - kind=pointcloud 写入「点云」槽位，kind=grid 写入「栅格」槽位；
    - 同类型重复上传会删除旧磁盘文件后替换；
    - 两个文件都可以不传（字段为 null），后续可随时补传。
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    if kind not in ("pointcloud", "grid"):
        return resp_400(msg="kind 只能是 pointcloud 或 grid")

    suffix = os.path.splitext(file.filename or "")[1].lower()
    allowed = IMAGE_SUFFIXES if kind == "grid" else POINTCLOUD_SUFFIXES
    if suffix not in allowed:
        readable = " / ".join(sorted(s.lstrip(".") for s in allowed))
        return resp_400(msg=f"{'栅格图片' if kind == 'grid' else '点云文件'}仅支持：{readable}")

    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")

    # 保存文件（文件名带类型前缀，避免点云与栅格互相覆盖）
    prefix = "pc" if kind == "pointcloud" else "grid"
    filename = f"map_{map_id}_{prefix}_{_safe_stem(file.filename)}{suffix}"
    file_path = os.path.join(MAP_UPLOAD_DIR, filename)

    # 定义异步保存函数，放入线程池执行，避免阻塞主服务
    def save_file():
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    try:
        await run_in_threadpool(save_file)
    except Exception as e:
        return resp_500(msg=f"文件保存失败：{str(e)}")

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return resp_400(msg="上传的文件为空")

    # 删除同类型旧文件
    old_path = map_obj.pointcloud_file_path if kind == "pointcloud" else map_obj.grid_file_path
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except Exception as e:
            logger.warning(f"清理旧文件失败: {e}")

    # 更新数据库
    file_type = os.path.splitext(filename)[1].lstrip(".")
    file_size = os.path.getsize(file_path)
    now = datetime.now()
    if kind == "pointcloud":
        map_obj.pointcloud_file_path = file_path
        map_obj.pointcloud_file_type = file_type
        map_obj.pointcloud_file_size = file_size
        map_obj.pointcloud_file_upload_time = now
    else:
        map_obj.grid_file_path = file_path
        map_obj.grid_file_type = file_type
        map_obj.grid_file_size = file_size
        map_obj.grid_file_upload_time = now

    session.add(map_obj)
    session.commit()
    session.refresh(map_obj)

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return resp_200(
        msg=f"{'点云' if kind == 'pointcloud' else '栅格'}文件上传成功",
        data={
            "map_id": map_obj.id,
            "kind": kind,
            "file_type": file_type,
            "content_type": content_type,
            "file_size": file_size,
            "file_url": _file_url(file_path),
        }
    )


@router.post("/{map_id}/pointcloud/process", summary="点云滤波（体素降采样）并可生成栅格图", description=MAP_PROCESS)
async def process_pointcloud(
        map_id: int = ApiPath(..., description="地图ID"),
        leaf_size: float = Query(0.05, description="体素降采样边长（米）；传 0 表示不降采样"),
        grid_resolution: float = Query(0.05, description="栅格分辨率（米/像素）"),
        grid_mode: str = Query("occupancy", description="栅格模式：occupancy=占用（黑白） / height=高度灰度"),
        z_low: float = Query(0.15, description="障碍判定下限：相对地面的高度（米）"),
        z_high: float = Query(1.8, description="障碍判定上限：相对地面的高度（米）"),
        replace: bool = Query(False, description="是否用降采样结果覆盖原点云文件"),
        keep_original: bool = Query(False, description="是否保留原始大点云；默认 false=只留降采样结果（省磁盘）"),
        generate_grid: bool = Query(True, description="是否同时生成/覆盖栅格图"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """对已上传的 .pcd 做体素降采样，可选同时生成俯视占用栅格图。

    - 处理后地图的 pointcloud_file_* 指向降采样文件（原文件保留在磁盘，不删除）；
    - 同时回填 pc_min/max、grid_origin/resolution/width/height，供 /coords 换算；
    - leaf_size / grid_resolution 单位都是米，默认 0.05（5cm）。
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    if grid_mode not in ("occupancy", "height"):
        return resp_400(msg="grid_mode 只能是 occupancy 或 height")

    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    src = map_obj.pointcloud_file_path
    if not src or not os.path.exists(src):
        return resp_400(msg="该地图还没有点云文件，请先上传")
    if (map_obj.pointcloud_file_type or "").lower() != "pcd":
        return resp_400(msg="目前只支持 .pcd 点云滤波（请先转成 pcd）")

    before_size = os.path.getsize(src)
    started = time.time()
    try:
        xyz = read_pcd_xyz(src)
        before_points = int(len(xyz))
        pts = voxel_downsample(xyz, leaf_size) if leaf_size and leaf_size > 0 else xyz
        after_points = int(len(pts))

        stem = os.path.splitext(os.path.basename(src))[0]
        out_path = src if replace else os.path.join(MAP_UPLOAD_DIR, "%s_down.pcd" % stem)
        write_pcd_binary(out_path, pts)

        now = datetime.now()
        map_obj.pointcloud_file_path = out_path
        map_obj.pointcloud_file_type = "pcd"
        map_obj.pointcloud_file_size = os.path.getsize(out_path)
        map_obj.pointcloud_file_upload_time = now
        map_obj.pointcloud_point_count = after_points
        map_obj.pc_min_x = float(pts[:, 0].min())
        map_obj.pc_max_x = float(pts[:, 0].max())
        map_obj.pc_min_y = float(pts[:, 1].min())
        map_obj.pc_max_y = float(pts[:, 1].max())
        map_obj.pc_min_z = float(pts[:, 2].min())
        map_obj.pc_max_z = float(pts[:, 2].max())

        grid_data = None
        if generate_grid:
            pixels, meta = build_grid(pts, resolution=grid_resolution, mode=grid_mode, z_low=z_low, z_high=z_high)
            grid_name = "map_%d_grid_auto_%sm.png" % (map_id, str(grid_resolution).replace(".", "_"))
            grid_path = os.path.join(MAP_UPLOAD_DIR, grid_name)
            write_png(grid_path, pixels)
            old_grid = map_obj.grid_file_path
            if old_grid and os.path.exists(old_grid) and os.path.abspath(old_grid) != os.path.abspath(grid_path):
                try:
                    os.remove(old_grid)
                except Exception as exc:
                    logger.warning("清理旧栅格失败: %s" % exc)
            map_obj.grid_file_path = grid_path
            map_obj.grid_file_type = "png"
            map_obj.grid_file_size = os.path.getsize(grid_path)
            map_obj.grid_file_upload_time = now
            map_obj.grid_origin_x = meta["origin_x"]
            map_obj.grid_origin_y = meta["origin_y"]
            map_obj.grid_resolution = meta["resolution"]
            map_obj.grid_width = meta["width"]
            map_obj.grid_height = meta["height"]
            grid_data = {
                "grid_file_url": _file_url(grid_path),
                "grid_width": meta["width"],
                "grid_height": meta["height"],
                "grid_resolution": meta["resolution"],
                "grid_origin_x": meta["origin_x"],
                "grid_origin_y": meta["origin_y"],
                "z_floor": meta["z_floor"],
            }

        # 原始大文件处理：replace 时已覆盖，否则按 keep_original 决定是否删除
        original_deleted = False
        if (not replace) and (not keep_original) and os.path.abspath(src) != os.path.abspath(out_path):
            try:
                os.remove(src)
                original_deleted = True
            except Exception as exc:
                logger.warning("删除原始点云失败 %s: %s" % (src, exc))

        session.add(map_obj)
        session.commit()
        session.refresh(map_obj)

        return resp_200(msg="点云处理完成", data={
            "map_id": map_id,
            "before_points": before_points,
            "after_points": after_points,
            "before_size": before_size,
            "after_size": map_obj.pointcloud_file_size,
            "pointcloud_file_url": _file_url(map_obj.pointcloud_file_path),
            "original_deleted": original_deleted,
            "bounds_of_cloud": {
                "min_x": map_obj.pc_min_x, "max_x": map_obj.pc_max_x,
                "min_y": map_obj.pc_min_y, "max_y": map_obj.pc_max_y,
                "min_z": map_obj.pc_min_z, "max_z": map_obj.pc_max_z,
            },
            "grid": grid_data,
            "elapsed_ms": int((time.time() - started) * 1000),
        })
    except PcdFormatError as e:
        session.rollback()
        return resp_400(msg=str(e))
    except ValueError as e:
        session.rollback()
        return resp_400(msg=str(e))
    except Exception as e:
        session.rollback()
        logger.error("点云处理失败: %s" % e)
        return resp_500(msg="点云处理失败: %s" % str(e))


@router.get("/{map_id}/coords", summary="坐标换算：栅格像素 / 点云 / 经纬度", description=MAP_COORDS)
async def map_coords(
        map_id: int = ApiPath(..., description="地图ID"),
        px: Optional[float] = Query(None, description="栅格像素列（0=左/西，向右增大）"),
        py: Optional[float] = Query(None, description="栅格像素行（0=上/北，向下增大）"),
        x: Optional[float] = Query(None, description="点云坐标 X（米）"),
        y: Optional[float] = Query(None, description="点云坐标 Y（米）"),
        lon: Optional[float] = Query(None, description="经度（WGS84）"),
        lat: Optional[float] = Query(None, description="纬度（WGS84）"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """三套坐标互转：传任意一组完整的 (px,py) / (x,y) / (lon,lat)，返回能算出来的全部坐标。

    - 需要地图已做过「点云处理」（提供 grid_origin/resolution/width/height）；
    - 经纬度换算还需要地图的 bounds（lon_min/lat_min/lon_max/lat_max）；
    - 像素 <-> 点云：x = grid_origin_x + px*res，y = grid_origin_y - py*res；
    - 像素 <-> 经纬度：按 bounds 线性铺满整幅图（第 0 行=北，第 0 列=西）。
    """
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")

    pairs = [(px, py, "像素"), (x, y, "点云"), (lon, lat, "经纬度")]
    given = [item for item in pairs if item[0] is not None and item[1] is not None]
    if not given:
        return resp_400(msg="请传一组完整坐标：px+py / x+y / lon+lat")
    if len(given) > 1:
        return resp_400(msg="一次只传一组坐标，避免歧义")
    if not map_has_grid(map_obj):
        return resp_400(msg="该地图还没有栅格↔点云映射信息，请先调用 POST /admin/maps/{id}/pointcloud/process")

    result = convert_coords(map_obj, px=px, py=py, x=x, y=y, lon=lon, lat=lat)
    bounds_ok = map_has_bounds(map_obj)
    if not bounds_ok:
        result["lon"] = None
        result["lat"] = None
    check = transform_check(map_obj)
    return resp_200(data={
        "map_id": map_id,
        "has_grid": True,
        "has_bounds": bounds_ok,
        "transform": get_transform(map_obj),
        "warnings": check.get("warnings", []),
        "grid_resolution": map_obj.grid_resolution,
        "grid_origin_x": map_obj.grid_origin_x,
        "grid_origin_y": map_obj.grid_origin_y,
        "grid_width": map_obj.grid_width,
        "grid_height": map_obj.grid_height,
        "input": given[0][2],
        "px": result["px"], "py": result["py"],
        "x": result["x"], "y": result["y"],
        "lon": result["lon"], "lat": result["lat"],
    })


@router.get("/{map_id}/transform", summary="查看地图变换（缩放/平移/旋转）与尺度自检", description=MAP_TRANSFORM)
async def get_map_transform(
        map_id: int = ApiPath(..., description="地图ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """返回当前生效的「像素 -> 点云」变换、图像四角坐标与尺度自检。

    - source=tf：使用 tf_* 字段；source=grid：回退到点云处理生成的值；
    - corners_pc：图像四角在点云中的坐标（车端坐标系）；
    - corners_lonlat：图像四角按 bounds 铺满后的经纬度（展示用）；
    - scale_ratio 偏离 1 超过 5% 时 warnings 会提示（图被拖动过 / bounds 没跟着改）。
    """
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")

    data = transform_check(map_obj)
    data["map_id"] = map_id
    data["corners_pc"] = corners_pc(map_obj)
    data["corners_lonlat"] = corners_lonlat(map_obj)
    return resp_200(data=data)


@router.put("/{map_id}/transform", summary="设置地图变换（缩放/平移/旋转）", description=MAP_TRANSFORM)
async def set_map_transform(
        map_id: int = ApiPath(..., description="地图ID"),
        data: MapTransformIn = Body(..., description="要修改的变换字段；reset=true 则清空回到自动值"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """设置「像素 -> 点云」变换（只改 tf_* 字段，**不会改动 bounds**）。

    三种写法（优先级从高到低）：
    1) 高级：传 `affine=[a,b,c,d,e,f]`，直接指定 x=a*px+b*py+c、y=d*px+e*py+f；
    2) 三轴：传 `scale` + `rot_deg`(yaw) + `pitch_deg` + `roll_deg` + `tx`/`ty`，
       后端按 Rz(yaw)*Ry(pitch)*Rx(roll) 正交投影合成仿射（pitch/roll 用于把歪掉的图转正）；
    3) 简单：只传 `scale` + `rot_deg` + `tx`/`ty`（等价 pitch=roll=0）。

    传了简单/三轴字段会清掉旧的 `affine`；`reset=true` 清空全部 tf_*，回退到点云处理生成的值。
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")

    payload = data.dict(exclude_unset=True)
    if payload.get("reset"):
        # 全部清空：回退到「点云处理」生成的值
        map_obj.tf_scale = None
        map_obj.tf_rot_deg = None
        map_obj.tf_tx = None
        map_obj.tf_ty = None
        map_obj.tf_pitch_deg = None
        map_obj.tf_roll_deg = None
        map_obj.tf_affine = None
    else:
        # 高级模式：前端自己算好的 2x3 仿射矩阵
        if payload.get("affine") is not None:
            vals = payload["affine"]
            if not isinstance(vals, (list, tuple)) or len(vals) != 6:
                return resp_400(msg="affine 必须是长度 6 的数组 [a,b,c,d,e,f]")
            try:
                vals = [float(v) for v in vals]
            except (TypeError, ValueError):
                return resp_400(msg="affine 的元素必须是数字")
            map_obj.tf_affine = json.dumps(vals)

        # 简单 / 三轴模式：传了任一角度或 scale/平移，就以三轴为准（清掉旧矩阵）
        euler_keys = ("scale", "rot_deg", "pitch_deg", "roll_deg", "tx", "ty")
        if any(k in payload and payload[k] is not None for k in euler_keys):
            if payload.get("scale") is not None and payload["scale"] <= 0:
                return resp_400(msg="scale 必须大于 0")
            for key in euler_keys:
                if key in payload and payload[key] is not None:
                    setattr(map_obj, "tf_" + key, float(payload[key]))
            map_obj.tf_affine = None

    session.add(map_obj)
    session.commit()
    session.refresh(map_obj)

    result = transform_check(map_obj)
    result["map_id"] = map_id
    result["corners_pc"] = corners_pc(map_obj)
    result["corners_lonlat"] = corners_lonlat(map_obj)
    return resp_200(data=result, msg="地图变换已更新")


@router.post("/upload-pointcloud", summary="一步建图：上传点云 → 滤波 → 生成栅格 → 创建地图", description=MAP_ONE_SHOT)
async def create_map_from_pointcloud(
        file: UploadFile = File(..., description="点云文件（.pcd，DATA=ascii / binary）"),
        name: str = Form(..., description="地图名称"),
        map_id: Optional[int] = Form(None, description="指定地图ID；不传则自增；已存在返回 400"),
        description: Optional[str] = Form(None, description="地图描述"),
        map_type: str = Form("local", description="地图类型，默认 local"),
        center_lon: Optional[float] = Form(None, description="地图中心经度（默认南科大基准）"),
        center_lat: Optional[float] = Form(None, description="地图中心纬度（默认南科大基准）"),
        zoom: Optional[int] = Form(None, description="默认缩放级别（默认 17）"),
        left_top_lon: Optional[float] = Form(None, description="区域左上角经度（西边界）"),
        left_top_lat: Optional[float] = Form(None, description="区域左上角纬度（北边界）"),
        right_bottom_lon: Optional[float] = Form(None, description="区域右下角经度（东边界）"),
        right_bottom_lat: Optional[float] = Form(None, description="区域右下角纬度（南边界）"),
        leaf_size: float = Form(0.05, description="体素降采样边长（米），0=不降采样"),
        grid_resolution: float = Form(0.05, description="栅格分辨率（米/像素）"),
        grid_mode: str = Form("occupancy", description="栅格模式：occupancy=占用(黑白) / height=高度灰度"),
        z_low: float = Form(0.15, description="障碍判定下限：相对地面的高度（米）"),
        z_high: float = Form(1.8, description="障碍判定上限：相对地面的高度（米）"),
        keep_original: bool = Form(False, description="是否保留原始大点云；默认 false=只留降采样结果"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """一次性完成「上传点云 → 降采样滤波 → 生成栅格 → 建立地图」。

    与「先建空地图 → /upload → /pointcloud/process」相比：

    - 只要一次请求；
    - 原始大文件默认**不落盘**（keep_original=false），磁盘只留降采样后的 PCD 与栅格 PNG；
    - `map_id` 可由前端指定（便于和前端编号对齐），不传则自增，已存在返回 400；
    - 任一步失败都会回滚：删除已插入的地图记录与半成品文件（PCD / PNG）。

    地图的空间信息（pointcloud_point_count、pc_min/max、grid_origin/resolution/width/height）
    会由本次处理自动回填，随后可直接用 /admin/maps/{id}/coords 做坐标换算。
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    if grid_mode not in ("occupancy", "height"):
        return resp_400(msg="grid_mode 只能是 occupancy 或 height")
    if map_type not in VALID_MAP_TYPES:
        return resp_400(msg="map_type 只能是 %s" % sorted(VALID_MAP_TYPES))
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix != ".pcd":
        return resp_400(msg="目前只支持 .pcd 点云（DATA=ascii / binary）")
    if map_id is not None and session.get(Map, map_id) is not None:
        return resp_400(msg="地图ID %d 已存在，请换一个或留空让系统自增" % map_id)

    started = time.time()
    stem = _safe_stem(file.filename)
    temp_path = os.path.join(MAP_UPLOAD_DIR, "_tmp_%s.pcd" % uuid.uuid4().hex)
    map_obj = None
    written = []

    def _save_upload():
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    try:
        # ---------- 1) 上传流先落到临时文件（避免大文件占内存） ----------
        await run_in_threadpool(_save_upload)
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            return resp_400(msg="上传的文件为空")
        before_size = os.path.getsize(temp_path)

        # ---------- 2) 先插地图记录拿到 id（指定 map_id 时直接用它） ----------
        map_fields = {
            "name": name,
            "description": description,
            "map_type": map_type,
            "center_lon": center_lon if center_lon is not None else 113.9686,
            "center_lat": center_lat if center_lat is not None else 22.6042,
            "zoom": zoom if zoom is not None else 17,
            "lon_min": left_top_lon,
            "lat_max": left_top_lat,
            "lon_max": right_bottom_lon,
            "lat_min": right_bottom_lat,
        }
        if map_id is not None:
            map_fields["id"] = map_id
        map_obj = Map(**map_fields)
        error = _validate_map_object(map_obj, session)
        if error:
            return resp_400(msg=error)
        session.add(map_obj)
        session.commit()
        session.refresh(map_obj)

        # ---------- 3) 读点云 → 体素降采样 ----------
        xyz = read_pcd_xyz(temp_path)
        before_points = int(len(xyz))
        pts = voxel_downsample(xyz, leaf_size) if leaf_size and leaf_size > 0 else xyz
        after_points = int(len(pts))

        # ---------- 4) 写降采样 PCD；原始大文件按 keep_original 处理 ----------
        pc_path = os.path.join(MAP_UPLOAD_DIR, "map_%d_pc_%s_down.pcd" % (map_obj.id, stem))
        write_pcd_binary(pc_path, pts)
        written.append(pc_path)
        if keep_original:
            raw_path = os.path.join(MAP_UPLOAD_DIR, "map_%d_pc_%s%s" % (map_obj.id, stem, suffix))
            shutil.copyfile(temp_path, raw_path)
            written.append(raw_path)

        # ---------- 5) 俯视投影生成栅格 PNG ----------
        pixels, meta = build_grid(pts, resolution=grid_resolution, mode=grid_mode, z_low=z_low, z_high=z_high)
        grid_path = os.path.join(
            MAP_UPLOAD_DIR, "map_%d_grid_auto_%sm.png" % (map_obj.id, str(grid_resolution).replace(".", "_")))
        write_png(grid_path, pixels)
        written.append(grid_path)

        # ---------- 6) 回填地图字段 ----------
        now = datetime.now()
        map_obj.pointcloud_file_path = pc_path
        map_obj.pointcloud_file_type = "pcd"
        map_obj.pointcloud_file_size = os.path.getsize(pc_path)
        map_obj.pointcloud_file_upload_time = now
        map_obj.pointcloud_point_count = after_points
        map_obj.pc_min_x = float(pts[:, 0].min())
        map_obj.pc_max_x = float(pts[:, 0].max())
        map_obj.pc_min_y = float(pts[:, 1].min())
        map_obj.pc_max_y = float(pts[:, 1].max())
        map_obj.pc_min_z = float(pts[:, 2].min())
        map_obj.pc_max_z = float(pts[:, 2].max())
        map_obj.grid_file_path = grid_path
        map_obj.grid_file_type = "png"
        map_obj.grid_file_size = os.path.getsize(grid_path)
        map_obj.grid_file_upload_time = now
        map_obj.grid_origin_x = meta["origin_x"]
        map_obj.grid_origin_y = meta["origin_y"]
        map_obj.grid_resolution = meta["resolution"]
        map_obj.grid_width = meta["width"]
        map_obj.grid_height = meta["height"]
        session.add(map_obj)
        session.commit()
        session.refresh(map_obj)

        payload = _map_payload(map_obj)
        payload["stats"] = {
            "before_points": before_points,
            "after_points": after_points,
            "before_size": before_size,
            "after_size": map_obj.pointcloud_file_size,
            "grid_width": meta["width"],
            "grid_height": meta["height"],
            "grid_resolution": meta["resolution"],
            "grid_origin_x": meta["origin_x"],
            "grid_origin_y": meta["origin_y"],
            "z_floor": meta["z_floor"],
            "elapsed_ms": int((time.time() - started) * 1000),
            "original_kept": bool(keep_original),
        }
        logger.info("一步建图成功: map_id=%s %s -> %s 点 / %s 字节" % (
            map_obj.id, before_points, after_points, map_obj.pointcloud_file_size))
        return resp_200(msg="地图创建成功", data=payload)

    except PcdFormatError as e:
        session.rollback()
        _cleanup_created_map(session, map_obj, written)
        return resp_400(msg=str(e))
    except ValueError as e:
        session.rollback()
        _cleanup_created_map(session, map_obj, written)
        return resp_400(msg=str(e))
    except Exception as e:
        session.rollback()
        _cleanup_created_map(session, map_obj, written)
        logger.error("一步建图失败: %s" % e)
        return resp_500(msg="建图失败: %s" % str(e))
    finally:
        # 临时上传文件始终删除（keep_original 时内容已另存为正式文件）
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as exc:
            logger.warning("清理临时点云失败 %s: %s" % (temp_path, exc))


@router.get("/{map_id}/ros-map", summary="导出 ROS map_server 用的地图（.pgm + .yaml）", description=MAP_ROS)
async def export_ros_map(
        map_id: int = ApiPath(..., description="地图ID"),
        occupied_thresh: float = Query(0.65, description="占用概率阈值（写进 yaml）"),
        free_thresh: float = Query(0.196, description="空闲概率阈值（写进 yaml）"),
        negate: int = Query(0, description="0=黑=占用（默认）/ 1=反色"),
        z_low: float = Query(0.15, description="障碍判定下限：相对地面的高度（米）"),
        z_high: float = Query(1.8, description="障碍判定上限：相对地面的高度（米）"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """把地图导出成 ROS `map_server` 能直接加载的 `.pgm + .yaml`（给 AMCL / move_base 用）。

    - 栅格内容由**降采样后的点云**按地图当前栅格帧重新投影：0=占用、254=空闲、205=未知；
    - `yaml.origin` 取图像**左下角**像素在点云坐标系中的位置，`yaw` 取变换的旋转角；
      `resolution` 取变换的米/像素；
    - 只支持「等比 + 旋转」的相似变换：若地图变换含 **pitch/roll（剪切/非等比）**，
      返回 400 并提示先把 pitch/roll 置 0（map_server 的 origin 只支持 yaw）；
    - 生成的文件放在 `static/maps/`，可直接下载到车端使用。
    """
    if negate not in (0, 1):
        return resp_400(msg="negate 只能是 0 或 1")

    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")

    src = map_obj.pointcloud_file_path
    if not src or not os.path.exists(src):
        return resp_400(msg="该地图没有点云文件，无法导出栅格")
    if not (map_obj.grid_width and map_obj.grid_height and map_obj.grid_resolution
            and map_obj.grid_origin_x is not None and map_obj.grid_origin_y is not None):
        return resp_400(msg="该地图还没有栅格帧信息，请先做点云处理")

    aff = get_affine(map_obj)
    if aff is None:
        return resp_400(msg="该地图缺少「像素->点云」变换，无法计算 ROS 地图 origin")

    # 相似变换校验：a==-e 且 b==d（含 y 翻转+旋转+等比缩放）
    tol = 1e-6 * (abs(aff["a"]) + abs(aff["d"]) + 1e-9)
    if abs(aff["b"] - aff["d"]) > tol or abs(aff["e"] + aff["a"]) > tol:
        return resp_400(msg=(
            "当前地图变换不是「等比 + 旋转」的相似变换（含 pitch/roll 或自定义 affine 的剪切），"
            "ROS map_server 的 origin 只支持 yaw，请先把 pitch_deg / roll_deg 置 0"
        ))

    resolution = float(map_obj.grid_resolution)
    width = int(map_obj.grid_width)
    height = int(map_obj.grid_height)

    try:
        xyz = read_pcd_xyz(src)
        img = build_grid_in_frame(
            xyz,
            origin_x=float(map_obj.grid_origin_x),
            origin_y=float(map_obj.grid_origin_y),
            width=width,
            height=height,
            resolution=resolution,
            z_low=z_low,
            z_high=z_high,
        )
    except Exception as e:
        logger.error("导出 ROS 地图失败: %s" % e)
        return resp_500(msg="导出失败: %s" % str(e))

    # 左下角像素在点云里的位置 + 旋转角（rad）
    lb_x, lb_y = px_to_pc(map_obj, 0, height)
    yaw_rad = math.atan2(aff["d"], aff["a"])

    pgm_name = "map_%d_ros.pgm" % map_id
    yaml_name = "map_%d_ros.yaml" % map_id
    pgm_path = os.path.join(MAP_UPLOAD_DIR, pgm_name)
    yaml_path = os.path.join(MAP_UPLOAD_DIR, yaml_name)
    write_pgm(pgm_path, img)

    yaml_text = (
        "image: %s\n" % pgm_name
        + "resolution: %s\n" % resolution
        + "origin: [%.6f, %.6f, %.6f]\n" % (lb_x, lb_y, yaw_rad)
        + "negate: %d\n" % negate
        + "occupied_thresh: %s\n" % occupied_thresh
        + "free_thresh: %s\n" % free_thresh
    )
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_text)

    occ_cnt = int((img == 0).sum())
    free_cnt = int((img == 254).sum())
    unknown_cnt = int((img == 205).sum())
    logger.info("导出 ROS 地图: map_id=%s %dx%d res=%.3f 占用=%d" % (map_id, width, height, resolution, occ_cnt))

    return resp_200(msg="ROS 地图导出成功", data={
        "map_id": map_id,
        "pgm_url": _file_url(pgm_path),
        "yaml_url": _file_url(yaml_path),
        "yaml": yaml_text,
        "resolution": resolution,
        "width": width,
        "height": height,
        "origin": [round(lb_x, 6), round(lb_y, 6), round(yaw_rad, 6)],
        "origin_yaw_deg": round(math.degrees(yaw_rad), 4),
        "cells": {"occupied": occ_cnt, "free": free_cnt, "unknown": unknown_cnt},
        "usage": (
            "下载 pgm+yaml 到车端同一目录，然后：\n"
            "  rosrun map_server map_server <目录>/%s\n"
            "  AMCL 初始位姿可用 /initialpose 设置（x/y 用点云坐标）" % yaml_name
        ),
    })


@router.delete("/{map_id}/files/{kind}", summary="删除地图的点云/栅格文件")
async def delete_map_file(
        map_id: int = ApiPath(..., description="地图ID"),
        kind: str = ApiPath(..., description="要删除的文件类型：pointcloud / grid"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_admin)
):
    """单独删除地图的点云或栅格文件，同时清理磁盘文件（另一类文件不受影响）。"""
    if kind not in ("pointcloud", "grid"):
        return resp_400(msg="kind 只能是 pointcloud 或 grid")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")

    old_path = map_obj.pointcloud_file_path if kind == "pointcloud" else map_obj.grid_file_path
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except Exception as e:
            logger.warning(f"清理文件失败: {e}")

    if kind == "pointcloud":
        map_obj.pointcloud_file_path = None
        map_obj.pointcloud_file_type = None
        map_obj.pointcloud_file_size = None
        map_obj.pointcloud_file_upload_time = None
    else:
        map_obj.grid_file_path = None
        map_obj.grid_file_type = None
        map_obj.grid_file_size = None
        map_obj.grid_file_upload_time = None

    session.add(map_obj)
    session.commit()
    return resp_200(msg="文件已删除", data={"map_id": map_id, "kind": kind})


@router.get("/", summary="获取所有地图列表", response_model=ApiResponse[List[MapOut]], description=MAP_READ)
async def list_maps(
        map_type: Optional[str] = Query(None, description="按类型筛选：tianditu=天地图 / local=本地地图"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """获取地图列表（按账户可见范围过滤），附带点云/栅格文件地址、bounds 与各类数量。"""
    visible = visible_map_ids(session, user)
    query = select(Map)
    if visible is not None:
        query = query.where(Map.id.in_(visible))
    if map_type is not None:
        query = query.where(Map.map_type == map_type)
    maps = session.exec(query).all()

    car_ids_by_map = {}
    for link in session.exec(select(CarMapLink)).all():
        car_ids_by_map.setdefault(link.map_id, []).append(link.car_id)
    user_ids_by_map = {}
    for link in session.exec(select(UserMapLink)).all():
        user_ids_by_map.setdefault(link.map_id, []).append(link.user_id)
    path_counts = {}
    for p in session.exec(select(Path)).all():
        path_counts[p.map_id] = path_counts.get(p.map_id, 0) + 1

    result = []
    for m in maps:
        d = _map_payload(m)
        d["car_ids"] = car_ids_by_map.get(m.id, [])
        d["car_count"] = len(d["car_ids"])
        d["user_ids"] = user_ids_by_map.get(m.id, [])
        d["user_count"] = len(d["user_ids"])
        d["path_count"] = path_counts.get(m.id, 0)
        result.append(d)
    return resp_200(data=result)


@router.get("/{map_id}", summary="获取单个地图详情", response_model=ApiResponse[MapOut], description=MAP_READ)
async def get_map(
        map_id: int = ApiPath(..., description="地图ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """按 id 获取单个地图详情，附带点云/栅格文件地址、bounds 与关联车辆/账户/路线数量。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    d = _map_payload(map_obj)
    d["car_ids"] = [link.car_id for link in session.exec(
        select(CarMapLink).where(CarMapLink.map_id == map_id)).all()]
    d["car_count"] = len(d["car_ids"])
    d["user_ids"] = [link.user_id for link in session.exec(
        select(UserMapLink).where(UserMapLink.map_id == map_id)).all()]
    d["user_count"] = len(d["user_ids"])
    d["path_count"] = len(session.exec(select(Path).where(Path.map_id == map_id)).all())
    return resp_200(data=d)


@router.get("/{map_id}/cars", summary="获取地图包含的车辆")
async def list_map_cars(
        map_id: int = ApiPath(..., description="地图ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """查看某张地图下关联的所有小车（多对多）。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    car_ids = [link.car_id for link in session.exec(
        select(CarMapLink).where(CarMapLink.map_id == map_id)).all()]
    cars = session.exec(select(Cars).where(Cars.id.in_(car_ids))).all() if car_ids else []

    # 车辆可能属于多张地图：一并带出（非管理员只列出可见地图）
    car_map_ids = {}
    if car_ids:
        for link in session.exec(select(CarMapLink).where(CarMapLink.car_id.in_(car_ids))).all():
            car_map_ids.setdefault(link.car_id, []).append(link.map_id)
    map_names = {m.id: m.name for m in session.exec(select(Map)).all()}
    payload = []
    for car in cars:
        mids = car_map_ids.get(car.id, [])
        if visible is not None:
            mids = [mid for mid in mids if mid in visible]
        payload.append(car_payload(car, mids, map_names))
    return resp_200(data={
        "map_id": map_id,
        "car_ids": car_ids,
        "cars": payload,
    })


@router.get("/{map_id}/paths", summary="获取地图包含的路线")
async def list_map_paths(
        map_id: int = ApiPath(..., description="地图ID"),
        is_temp: Optional[bool] = Query(None, description="是否临时路径：true=只看临时 / false=只看普通 / 不传=全部"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """查看某张地图下的路线（可按是否临时路径筛选），node_chain 已转成对象返回。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    query = select(Path).where(Path.map_id == map_id)
    if is_temp is not None:
        query = query.where(Path.is_temp == is_temp)
    result = []
    for p in session.exec(query).all():
        d = p.dict()
        d["node_chain"] = json.loads(d["node_chain"])
        result.append(d)
    return resp_200(data=result)


@router.get("/{map_id}/users", summary="获取地图关联的账户")
async def list_map_users(
        map_id: int = ApiPath(..., description="地图ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_admin)
):
    """管理员查看某张地图关联的所有账户（多对多）。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    user_ids = [link.user_id for link in session.exec(
        select(UserMapLink).where(UserMapLink.map_id == map_id)).all()]
    users = session.exec(select(Users).where(Users.id.in_(user_ids))).all() if user_ids else []
    return resp_200(data={
        "map_id": map_id,
        "user_ids": user_ids,
        "users": [{"id": u.id, "name": u.name, "nickname": u.nickname, "role": u.effective_role} for u in users],
    })


@router.put("/{map_id}", summary="修改地图信息", description=MAP_WRITE)
async def update_map(
        map_id: int = ApiPath(..., description="地图ID"),
        data: MapUpdate = Body(..., description="要修改的字段（只传需要改的；不传 / 传 null / 传空串均表示保持原值），description/fallback_map_id 传 null 表示清空"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员修改地图信息，仅更新传入的字段（会重新校验类型/范围/兜底）。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    old_map_type = map_obj.map_type
    for key, value in _apply_corner_fields(clean_update(data, allow_null={"description", "fallback_map_id"})).items():
        setattr(map_obj, key, value)
    error = _validate_map_object(map_obj, session)
    if error:
        session.rollback()
        return resp_400(msg=error)
    session.add(map_obj)
    session.commit()
    # 地图类型变更时，同步该地图下所有路线的 map_type
    if map_obj.map_type != old_map_type:
        session.execute(update(Path).where(Path.map_id == map_id).values(map_type=map_obj.map_type))
        session.commit()
        logger.info(f"地图 {map_id} 类型变更为 {map_obj.map_type}，已同步其下路线")
    session.refresh(map_obj)
    return resp_200(data=_map_payload(map_obj), msg="地图更新成功")


@router.delete("/{map_id}", summary="删除地图")
async def delete_map(
        map_id: int = ApiPath(..., description="地图ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员删除地图：有站点/路径点/普通路线时禁止删除；临时路径自动清理，
    车辆与账户关联自动解绑，其他地图指向它的兜底关系会被置空，磁盘文件一并删除。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    sites = session.exec(select(Site).where(Site.map_id == map_id)).first()
    waypoints = session.exec(select(Waypoint).where(Waypoint.map_id == map_id)).first()
    normal_paths = session.exec(
        select(Path).where(Path.map_id == map_id, Path.is_temp == False)).first()
    if sites or waypoints or normal_paths:
        return resp_400(msg="该地图下存在站点、路径点或普通路线，无法删除（临时路径会自动清理）")

    # 临时路径随地图一起删除（一次性数据）
    for temp_path in session.exec(
            select(Path).where(Path.map_id == map_id, Path.is_temp == True)).all():
        session.delete(temp_path)
    # 解除车辆与该地图的关联
    for link in session.exec(select(CarMapLink).where(CarMapLink.map_id == map_id)).all():
        session.delete(link)
    # 解除账户与该地图的关联
    for link in session.exec(select(UserMapLink).where(UserMapLink.map_id == map_id)).all():
        session.delete(link)
    # 其他地图若把本图当作兜底点云图，置空
    for other in session.exec(select(Map).where(Map.fallback_map_id == map_id)).all():
        other.fallback_map_id = None
        session.add(other)
    # 删除数据库前，清理点云与栅格两个磁盘文件
    for path in (map_obj.pointcloud_file_path, map_obj.grid_file_path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logger.warning(f"清理文件失败: {e}")
    
    session.delete(map_obj)
    session.commit()
    return resp_200(msg="地图已删除")