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
from schemas.map import MapCreate, MapUpdate, MapOut
from schemas.resp import ApiResponse
from utils.resp_code import resp_200, resp_400, resp_500
from utils.patch import clean_update
from utils.pcd import PcdFormatError, build_grid, read_pcd_xyz, voxel_downsample, write_pcd_binary, write_png
from utils.coords import convert as convert_coords, has_bounds as map_has_bounds, has_grid as map_has_grid
from core.security import get_current_user, get_current_admin
from models.user import Users
from typing import List, Optional
import mimetypes
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


@router.post("/", summary="新增地图")
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


@router.post("/upload", summary="上传地图文件（点云/栅格）")
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


@router.post("/{map_id}/pointcloud/process", summary="点云滤波（体素降采样）并可生成栅格图")
async def process_pointcloud(
        map_id: int = ApiPath(..., description="地图ID"),
        leaf_size: float = Query(0.05, description="体素降采样边长（米）；传 0 表示不降采样"),
        grid_resolution: float = Query(0.05, description="栅格分辨率（米/像素）"),
        grid_mode: str = Query("occupancy", description="栅格模式：occupancy=占用（黑白） / height=高度灰度"),
        z_low: float = Query(0.15, description="障碍判定下限：相对地面的高度（米）"),
        z_high: float = Query(1.8, description="障碍判定上限：相对地面的高度（米）"),
        replace: bool = Query(False, description="是否用降采样结果覆盖原点云文件"),
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


@router.get("/{map_id}/coords", summary="坐标换算：栅格像素 / 点云 / 经纬度")
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
    return resp_200(data={
        "map_id": map_id,
        "has_grid": True,
        "has_bounds": bounds_ok,
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


@router.get("/", summary="获取所有地图列表", response_model=ApiResponse[List[MapOut]])
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


@router.get("/{map_id}", summary="获取单个地图详情", response_model=ApiResponse[MapOut])
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


@router.put("/{map_id}", summary="修改地图信息")
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