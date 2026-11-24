import datetime
import json
import os
from typing import Optional, List, Dict
from schemas.car_command import CarCommandIn, ControlModeIn, CarMapSetIn
from fastapi import APIRouter, Depends, Query, Body, Path as ApiPath
from sqlmodel import Session, select, delete

from core.logger import logger
from core.security import get_current_user, get_current_dispatcher, get_current_admin
from db.session import get_session
from models.car.car import Cars, CarStatus
from models.car.map_link import CarMapLink
from models.car.tasks import Tasks
from models.map import Map
from models.path import Path
from models.user.users import Users
from apis.access import visible_map_ids
from apis.views import car_payload
from utils.coords import get_transform
from utils.video_streams import dump_streams, parse_streams
from utils.patch import blank_to_none, clean_update
from apis.api_docs import CAR_MANIFEST, CAR_POINTS
from utils.resp_code import resp_200, resp_500, resp_400
from apis.websocket.process import manager
from pydantic import BaseModel, Field, validator

car_api = APIRouter(prefix='/cars')

# 静态地图目录（manifest 里拼 ROS 地图路径用，与 maps.py 保持一致）
MAP_UPLOAD_DIR = os.path.join("static", "maps")


# ===== 车辆-地图关联辅助函数 =====
def _normalize_map_ids(map_ids) -> List[int]:
    """去重并保持传入顺序"""
    return list(dict.fromkeys(map_ids or []))


def _validate_map_ids(session: Session, map_ids):
    """校验地图是否存在，返回 (ids, error)"""
    unique_ids = _normalize_map_ids(map_ids)
    if not unique_ids:
        return [], None
    exists = set(session.exec(select(Map.id).where(Map.id.in_(unique_ids))).all())
    missing = [mid for mid in unique_ids if mid not in exists]
    if missing:
        return None, f"地图不存在: {missing}"
    return unique_ids, None


def _get_car_map_ids(session: Session, car_id: int) -> List[int]:
    """查询车辆当前关联的地图 id 列表"""
    return list(session.exec(select(CarMapLink.map_id).where(CarMapLink.car_id == car_id)).all())


def _replace_car_maps(session: Session, car_id: int, map_ids: List[int]) -> None:
    """覆盖式设置车辆所属地图（先清空再写入）"""
    session.execute(delete(CarMapLink).where(CarMapLink.car_id == car_id))
    for map_id in map_ids:
        session.add(CarMapLink(car_id=car_id, map_id=map_id))


def _map_file_url(path):
    # 磁盘路径 -> /static 访问地址
    return f"/static/maps/{os.path.basename(path)}" if path else None


def _map_bounds(map_obj: Map):
    # 左上/右下角点（四个值齐全时返回）
    if None in (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max):
        return None
    return {
        "left_top": {"lon": map_obj.lon_min, "lat": map_obj.lat_max},
        "right_bottom": {"lon": map_obj.lon_max, "lat": map_obj.lat_min},
    }


# ===== 视频流辅助函数 =====
def _check_stream_url_conflict(session: Session, streams: Dict[str, str],
                               exclude_car_id: Optional[int] = None) -> Optional[str]:
    """检查视频流地址是否已被其他车辆占用，返回错误信息或 None"""
    urls = {url for url in (streams or {}).values() if url}
    if not urls:
        return None
    for other in session.exec(select(Cars)).all():
        if exclude_car_id is not None and other.id == exclude_car_id:
            continue
        duplicated = urls & set(parse_streams(other.video_streams).values())
        if duplicated:
            return f"该视频流地址已被车辆 {other.id} 使用: {sorted(duplicated)[0]}"
    return None


class VideoStreamsIn(BaseModel):
    """更新车辆视频流地址的请求体（仅管理员）"""
    streams: Dict[str, str] = Field(
        default={},
        description="视频流字典：键=视角名（如 front/back），值=播放地址（如 http://39.108.77.178:6010/front）",
    )


# ===== 定义接收前端传来的小车数据结构 =====
class CarCreateIn(BaseModel):
    """新增小车（管理员）"""
    name: str = Field(..., description="车辆名称，如 'AGV-01'")
    productor: Optional[str] = Field(default="未知厂商", description="厂商")
    weight: Optional[float] = Field(default=50.0, description="载重（kg）")
    ip: Optional[str] = Field(default="192.168.1.100", description="车端 IP")
    port: Optional[str] = Field(default="9090", description="车端端口")
    lon: Optional[float] = Field(default=113.9686, ge=-180, le=180, description="初始经度（WGS84），默认南科大基准")
    lat: Optional[float] = Field(default=22.6042, ge=-90, le=90, description="初始纬度（WGS84），默认南科大基准")
    yaw: Optional[float] = Field(default=0.0, description="初始航向角（度，0=正北，顺时针）")
    map_ids: Optional[List[int]] = Field(default=None, description="车辆所属地图ID列表（可多选）")
    video_streams: Optional[Dict[str, str]] = Field(
        default=None,
        description='视频流字典，如 {"front": "http://39.108.77.178:6010/front"}；不传则为空',
    )

@car_api.post("/create", summary="新增小车")
async def create_car(
    data: CarCreateIn,
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """
    在系统中新增一台小车。如果新增成功，返回自动生成的 car_id。
    可通过 map_ids 指定该车所属地图（多选，可不传）。
    可传 lon/lat/yaw 指定初始经纬度与航向，不传则用南科大基准坐标。
    """
    if not user.isAdmin:
        return resp_400(msg="权限不足，仅管理员可操作")

    map_ids, error = _validate_map_ids(session, data.map_ids)
    if error:
        return resp_400(msg=error)

    error = _check_stream_url_conflict(session, data.video_streams or {})
    if error:
        return resp_400(msg=error)

    try:
        # 创建新小车，所有轨迹数据默认给 0 或 100
        new_car = Cars(
            name=data.name,
            productor=data.productor,
            weight=data.weight,
            ip=data.ip,
            port=data.port,
            status=CarStatus.FREE,      # 默认状态为空闲
            lon=data.lon,
            lat=data.lat,
            yaw=data.yaw,
            speed=0.0,
            battery=100.0,
            video_streams=dump_streams(data.video_streams),
            control_mode="AUTO"         # 默认自动模式
        )
        session.add(new_car)
        session.commit()
        session.refresh(new_car)

        # 写入车辆-地图关联
        if map_ids:
            _replace_car_maps(session, new_car.id, map_ids)
            session.commit()

        logger.info(f"管理员 {user.name} 新增了一台小车: {data.name} (ID: {new_car.id}, 地图: {map_ids})")
        return resp_200(msg="小车创建成功", data={
            "car_id": new_car.id,
            "map_ids": map_ids,
            "video_streams": parse_streams(new_car.video_streams),
        })
    except Exception as e:
        session.rollback()
        logger.error(f"创建小车失败: {e}")
        return resp_500(msg=f"创建小车失败: {str(e)}")

# 放在 CarCreateIn 的下面
class CarUpdateIn(BaseModel):
    """修改小车（管理员）：只传需要修改的字段"""
    name: Optional[str] = Field(default=None, description="车辆名称")
    productor: Optional[str] = Field(default=None, description="厂商")
    weight: Optional[float] = Field(default=None, description="载重（kg）")
    ip: Optional[str] = Field(default=None, description="车端 IP")
    port: Optional[str] = Field(default=None, description="车端端口")
    lon: Optional[float] = Field(default=None, ge=-180, le=180, description="经度（WGS84），可手动校正，范围 -180~180")
    lat: Optional[float] = Field(default=None, ge=-90, le=90, description="纬度（WGS84），可手动校正，范围 -90~90")
    yaw: Optional[float] = Field(default=None, description="航向角（度，0=正北，顺时针）")
    status: Optional[int] = Field(default=None, description="状态：0关机/1空闲/2工作中/3暂停/4充电/5故障")
    description: Optional[str] = Field(default=None, description="备注")
    map_ids: Optional[List[int]] = Field(default=None, description="车辆所属地图ID列表（传了就整体覆盖，传 [] 表示解除全部）")
    video_streams: Optional[Dict[str, str]] = Field(
        default=None,
        description="视频流字典（传了就整体覆盖，传 {} 表示清空）",
    )

    @validator("weight", "lon", "lat", "yaw", "status", pre=True)
    def _blank_to_none(cls, value):
        return blank_to_none(value)

@car_api.put("/{car_id}/update", summary="修改小车信息")
async def update_car(
    car_id: int = ApiPath(..., description="车辆ID"),
    data: CarUpdateIn = Body(..., description="要修改的字段（只传需要改的；不传 / 传 null / 传空串均表示保持原值），description 传 null 表示清空"),
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """
    修改指定小车的信息。只需传需要修改的字段，未传的字段保持原样。
    支持手动校正经纬度/航向（lon/lat/yaw）：车端没上报 GPS 时，管理员可直接摆放车辆位置。
    """
    if not user.isAdmin:
        return resp_400(msg="权限不足，仅管理员可操作")
    
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
        
    try:
        # 遍历传入的字段并更新；map_ids 不是 Cars 的列，单独处理
        update_data = clean_update(data, allow_null={"description"})
        new_map_ids = update_data.pop("map_ids", None)
        new_streams = update_data.pop("video_streams", None)
        if new_streams:
            error = _check_stream_url_conflict(session, new_streams, exclude_car_id=car.id)
            if error:
                return resp_400(msg=error)
        if new_map_ids is not None:
            new_map_ids, error = _validate_map_ids(session, new_map_ids)
            if error:
                return resp_400(msg=error)
        for key, value in update_data.items():
            # 如果传了 status，需要转成枚举类型
            if key == "status":
                try:
                    car.status = CarStatus(value)
                except ValueError:
                    return resp_400(msg=f"无效的小车状态值: {value}")
            else:
                setattr(car, key, value)
                
        if new_streams is not None:
            car.video_streams = dump_streams(new_streams)
        session.add(car)
        session.commit()
        session.refresh(car)

        if new_map_ids is not None:
            _replace_car_maps(session, car.id, new_map_ids)
            session.commit()

        result = car.dict()
        result["map_ids"] = _get_car_map_ids(session, car.id)
        result["video_streams"] = parse_streams(car.video_streams)
        logger.info(f"管理员 {user.name} 修改了小车 {car_id} 的信息")
        return resp_200(msg="小车信息修改成功", data=result)
    except Exception as e:
        session.rollback()
        logger.error(f"修改小车信息失败: {e}")
        return resp_500(msg=f"修改失败: {str(e)}")

@car_api.get("/{car_id}/manifest", summary="车端同步清单（绑定地图的文件地址 + 可用路线）", description=CAR_MANIFEST)
async def get_car_manifest(
        car_id: int = ApiPath(..., description="车辆ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """车端客户端启动/定时调用：一次拿到「该车绑定地图的文件信息」和「可见路线列表」。

    - `car`：车辆基本信息 + 当前点云位姿（pc_*）；
    - `maps`：车绑定的地图，含 `grid`（PNG 地址/大小/mtime/宽高/分辨率/翻转）、
      `pointcloud`（PCD 地址/大小/时间）、`ros_map`（导出过才有）、`transform`；
    - `paths`：该车可见地图下的路线（带 `node_count`，便于判断缓存是否过期）。

    车端建议流程：对比本地缓存的 `size + mtime` 决定是否重新下载 `/static/maps/...`；
    执行任务时再调 `GET /api/cars/{car_id}/paths/{path_id}/points?frame=pc`。
    """
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")

    def _file_info(path):
        """磁盘文件 -> {url, size, mtime}；不存在返回 None"""
        if not path or not os.path.exists(path):
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        return {
            "url": _map_file_url(path),
            "size": st.st_size,
            "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S"),
        }

    visible = visible_map_ids(session, user)
    car_map_ids = _get_car_map_ids(session, car_id)
    if visible is not None:
        car_map_ids = [mid for mid in car_map_ids if mid in visible]

    maps_payload = []
    for map_id in car_map_ids:
        map_obj = session.get(Map, map_id)
        if map_obj is None:
            continue

        grid_info = _file_info(map_obj.grid_file_path) or {}
        grid_info.update({
            "width": map_obj.grid_width,
            "height": map_obj.grid_height,
            "resolution": map_obj.grid_resolution,
            "flip_x": bool(map_obj.grid_flip_x),
            "flip_y": bool(map_obj.grid_flip_y),
            "grid_origin_x": map_obj.grid_origin_x,
            "grid_origin_y": map_obj.grid_origin_y,
        })

        pc_info = _file_info(map_obj.pointcloud_file_path) or {}
        pc_info.update({"type": map_obj.pointcloud_file_type, "points": map_obj.pointcloud_point_count})

        ros_map = None
        ros_yaml = os.path.join(MAP_UPLOAD_DIR, "map_%d_ros.yaml" % map_id)
        ros_pgm = os.path.join(MAP_UPLOAD_DIR, "map_%d_ros.pgm" % map_id)
        if os.path.exists(ros_yaml) and os.path.exists(ros_pgm):
            ros_map = {"yaml_url": _map_file_url(ros_yaml), "pgm_url": _map_file_url(ros_pgm)}

        bounds = None
        if None not in (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max):
            bounds = {
                "left_top": {"lon": map_obj.lon_min, "lat": map_obj.lat_max},
                "right_bottom": {"lon": map_obj.lon_max, "lat": map_obj.lat_min},
            }

        maps_payload.append({
            "id": map_obj.id,
            "name": map_obj.name,
            "map_type": map_obj.map_type,
            "center_lon": map_obj.center_lon,
            "center_lat": map_obj.center_lat,
            "zoom": map_obj.zoom,
            "bounds": bounds,
            "grid": grid_info,
            "pointcloud": pc_info,
            "ros_map": ros_map,
            "transform": get_transform(map_obj),
        })

    paths_payload = []
    query = select(Path)
    query = query.where(Path.map_id.in_(car_map_ids)) if car_map_ids else query.where(Path.id == -1)
    for path in session.exec(query).all():
        try:
            nodes = json.loads(path.node_chain or "[]")
        except Exception:
            nodes = []
        paths_payload.append({
            "id": path.id,
            "name": path.name,
            "path_type": path.path_type,
            "map_id": path.map_id,
            "map_type": path.map_type,
            "car_id": path.car_id,
            "is_temp": bool(path.is_temp),
            "node_count": len(nodes) if isinstance(nodes, list) else 0,
        })

    return resp_200(data={
        "car": {
            "car_id": car.id,
            "name": car.name,
            "control_mode": car.control_mode,
            "status": car.status,
            "last_heartbeat": car.last_heartbeat,
            "pc_map_id": car.pc_map_id,
            "pc_x": car.pc_x,
            "pc_y": car.pc_y,
            "pc_z": car.pc_z,
            "pc_roll": car.pc_roll,
            "pc_pitch": car.pc_pitch,
            "pc_yaw": car.pc_yaw,
        },
        "maps": maps_payload,
        "paths": paths_payload,
    })


@car_api.get("/{car_id}/paths/{path_id}/points", summary="车端取路线坐标（默认点云米制）", description=CAR_POINTS)
async def get_car_path_points(
        car_id: int = ApiPath(..., description="车辆ID"),
        path_id: int = ApiPath(..., description="路线ID"),
        frame: str = Query("pc", description="坐标系：pc=点云米(x,y) / lonlat=经纬度 / grid=栅格像素"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """车端导航用：返回该路线在点云坐标系下的有序点（米），站点附带 stop_mode / dwell_time。

    """
    if frame not in ("lonlat", "grid", "pc"):
        return resp_400(msg="frame 只能是 lonlat / grid / pc")
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")

    from apis.admin.paths import resolve_path_points
    data = resolve_path_points(session, path, frame)
    if frame in ("grid", "pc") and not data["has_grid"]:
        return resp_400(msg="该地图还没有栅格↔点云映射，请先对地图做点云处理")
    data["car_id"] = car_id
    data["car_map_ids"] = _get_car_map_ids(session, car_id)
    data["path_in_car_maps"] = (path.map_id in data["car_map_ids"]) if path.map_id is not None else False
    return resp_200(data=data)


@car_api.get("/list", summary="获取小车列表（可按地图ID筛选）")
async def get_car_list(
    map_id: Optional[int] = Query(None, description="按地图ID筛选：只返回该地图上的小车"),
    user: Users = Depends(get_current_user)
):
    """
    前端地图页面调用，返回每台小车真实GPS经纬度/航向/电量，以及所属地图列表。
    传 map_id 时只返回该地图上的车；非管理员只能看到自己负责的地图。
    """
    with get_session() as session:
        visible = visible_map_ids(session, user)
        if map_id is not None:
            if session.get(Map, map_id) is None:
                return resp_400(msg="地图不存在")
            if visible is not None and map_id not in visible:
                return resp_400(msg="无权访问该地图")

        all_cars = session.query(Cars).all()
        map_names = {m.id: m.name for m in session.exec(select(Map)).all()}
        car_map_ids = {}
        for link in session.exec(select(CarMapLink)).all():
            car_map_ids.setdefault(link.car_id, []).append(link.map_id)

        result = []
        for car in all_cars:
            car_maps = car_map_ids.get(car.id, [])
            if visible is not None:
                # 非管理员：只能看到与"自己负责的地图"关联的车辆
                car_maps = [mid for mid in car_maps if mid in visible]
                if not car_maps:
                    continue
            if map_id is not None and map_id not in car_maps:
                continue
            result.append(car_payload(car, car_maps, map_names))
    return resp_200(data=result)


@car_api.get("/{car_id}/maps", summary="获取车辆所属地图")
async def get_car_maps(
    car_id: int = ApiPath(..., description="车辆ID"),
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """查看某辆小车关联的所有地图（含类型/中心点/范围，便于前端直接切图）。"""
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
    map_ids = _get_car_map_ids(session, car_id)
    visible = visible_map_ids(session, user)
    if visible is not None:
        map_ids = [mid for mid in map_ids if mid in visible]
    maps = session.exec(select(Map).where(Map.id.in_(map_ids))).all() if map_ids else []
    return resp_200(data={
        "car_id": car_id,
        "map_ids": map_ids,
        "maps": [{
            "id": m.id,
            "name": m.name,
            "map_type": m.map_type,
            "center_lon": m.center_lon,
            "center_lat": m.center_lat,
            "zoom": m.zoom,
            "lon_min": m.lon_min,
            "lat_min": m.lat_min,
            "lon_max": m.lon_max,
            "lat_max": m.lat_max,
            "pointcloud_file_url": _map_file_url(m.pointcloud_file_path),
            "grid_file_url": _map_file_url(m.grid_file_path),
            "bounds": _map_bounds(m),
        } for m in maps],
    })


@car_api.put("/{car_id}/maps", summary="设置车辆所属地图")
async def set_car_maps(
    car_id: int = ApiPath(..., description="车辆ID"),
    data: CarMapSetIn = Body(..., description="地图ID列表（覆盖式，传 [] 解除全部关联）"),
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_admin)
):
    """覆盖式设置某辆小车所属的地图（传空数组表示解除全部关联）。"""
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
    map_ids, error = _validate_map_ids(session, data.map_ids)
    if error:
        return resp_400(msg=error)
    try:
        _replace_car_maps(session, car_id, map_ids)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"设置车辆所属地图失败: {e}")
        return resp_500(msg="设置车辆所属地图失败")
    logger.info(f"管理员 {user.name} 设置小车 {car_id} 的所属地图为 {map_ids}")
    return resp_200(data={"car_id": car_id, "map_ids": map_ids}, msg="设置成功")


@car_api.get("/{car_id}/video_streams", summary="获取车辆视频流地址")
async def get_car_video_streams(
    car_id: int = ApiPath(..., description="车辆ID"),
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """读取数据库中的 video_streams（JSON 字符串）并解析成字典返回。

    返回示例：{"front": "http://39.108.77.178:6010/front"}
    字段为空或历史数据格式非法时返回 {}。
    """
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
    return resp_200(data=parse_streams(car.video_streams))


@car_api.put("/{car_id}/video_streams", summary="更新车辆视频流地址（仅管理员）")
async def update_car_video_streams(
    car_id: int = ApiPath(..., description="车辆ID"),
    data: VideoStreamsIn = Body(..., description="视频流字典，如 {streams: {front: http://39.108.77.178:6010/front}}"),
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_admin)
):
    """把前端传来的视频流字典序列化为 JSON 字符串后写入 video_streams 字段。

    - 仅管理员可调用（非管理员返回 403）；
    - 传 {} 表示清空；
    - 返回更新后的字典。
    """
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")

    error = _check_stream_url_conflict(session, data.streams, exclude_car_id=car_id)
    if error:
        return resp_400(msg=error)

    try:
        car.video_streams = dump_streams(data.streams)
        session.add(car)
        session.commit()
        session.refresh(car)
    except Exception as e:
        session.rollback()
        logger.error(f"更新车辆视频流失败: {e}")
        return resp_500(msg=f"更新车辆视频流失败: {str(e)}")

    logger.info(f"管理员 {user.name} 更新了小车 {car_id} 的视频流: {car.video_streams}")
    return resp_200(data=parse_streams(car.video_streams), msg="视频流更新成功")


@car_api.delete("/{car_id}", summary="删除小车")
async def delete_car(
    car_id: int = ApiPath(..., description="车辆ID"),
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """
    删除指定小车（仅管理员）：
    - 小车正在执行任务(WORKING)时不允许删除，需先停止；
    - 若仍有路线专属于该车，禁止删除，需先删除或解除这些路线；
    - 删除前把历史任务的 car_id 置空，避免外键悬挂；
    - 同步清理该车在 WebSocket 指令通道中的连接记录。
    """
    if not user.isAdmin:
        return resp_400(msg="权限不足，仅管理员可删除小车")

    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")

    # 1. 正在执行任务的小车禁止删除
    if car.status == CarStatus.WORKING:
        return resp_400(msg="小车正在执行任务，请先停止后再删除")

    # 2. 普通路线仍禁止删除；临时路径随车辆自动清理
    normal_paths = session.exec(select(Path).where(
        Path.car_id == car_id, Path.is_temp == False)).all()
    if normal_paths:
        return resp_400(msg=f"该小车仍被 {len(normal_paths)} 条普通路线引用，请先删除或解除这些路线")

    car_name = car.name
    try:
        # 3. 删除该车的临时路径、解除其与地图的关联
        for temp_path in session.exec(select(Path).where(
                Path.car_id == car_id, Path.is_temp == True)).all():
            session.delete(temp_path)
        for link in session.exec(select(CarMapLink).where(CarMapLink.car_id == car_id)).all():
            session.delete(link)

        # 4. 解除历史任务与小车的外键关联
        related_tasks = session.exec(select(Tasks).where(Tasks.car_id == car_id)).all()
        for task in related_tasks:
            task.car_id = None
            session.add(task)

        session.delete(car)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"删除小车失败: {e}")
        return resp_500(msg=f"删除小车失败: {str(e)}")

    # 4. 清理 WebSocket 指令通道中该车的连接记录
    manager.active_connections["command"].pop(car_id, None)

    logger.info(f"管理员 {user.name} 删除了小车: {car_name} (ID: {car_id})")
    return resp_200(msg="小车已删除", data={"car_id": car_id})


@car_api.post("/{car_id}/command", summary="下发指令给小车")
async def send_command(
        car_id: int = ApiPath(..., description="车辆ID"),
        data: CarCommandIn = Body(..., description="指令内容（command 必填）"),
        user: Users = Depends(get_current_dispatcher),
        session: Session = Depends(get_session)
):
    """
    前端向指定小车下发指令：
    - start: 开始执行指定路线（需传 path_id）
    - stop: 停止当前任务
    - pause: 暂停当前任务
    - resume: 恢复暂停的任务
    - goto: 前往指定路线（等同于 start，语义不同）
    """
    # 1. 校验小车是否存在
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")

    # 2. 根据指令类型处理
    if data.command in ["start", "goto"]:
        if not data.path_id:
            return resp_400(msg="start/goto 指令需要指定 path_id")
        path = session.get(Path, data.path_id)
        if not path:
            return resp_400(msg="路线不存在")
        car.status = CarStatus.WORKING
        car.current_task_id = data.path_id
        session.add(car)
        session.commit()
        logger.info(f"管理员 {user.name} 下发指令 {data.command} 给小车 {car_id}，路线ID: {data.path_id}")

        # ===== WebSocket 推送指令给车端 =====
        ws_msg = {
            "command": data.command,
            "path_id": data.path_id,
            "timestamp": datetime.datetime.now().isoformat()
        }
        try:
            await manager.send_personal_json(ws_msg, car_id, "command")
            logger.info(f"指令已通过 WebSocket 推送给车端 {car_id}")
        except Exception as e:
            logger.error(f"WebSocket 推送失败: {e}")
        # ===================================

        return resp_200(msg=f"指令 {data.command} 已下发，小车开始行驶")

    elif data.command == "stop":
        car.status = CarStatus.FREE
        car.current_task_id = None
        session.add(car)
        session.commit()
        logger.info(f"管理员 {user.name} 下发指令 stop 给小车 {car_id}")

        # ===== WebSocket 推送停止指令 =====
        ws_msg = {"command": "stop", "timestamp": datetime.datetime.now().isoformat()}
        try:
            await manager.send_personal_json(ws_msg, car_id, "command")
        except Exception:
            pass
        # ================================

        return resp_200(msg="小车已停止")

    elif data.command == "pause":
        if car.status != CarStatus.WORKING:
            return resp_400(msg="小车当前未在工作，无法暂停")
        car.status = CarStatus.PAUSE
        session.add(car)
        session.commit()
        logger.info(f"管理员 {user.name} 下发指令 pause 给小车 {car_id}")

        ws_msg = {"command": "pause", "timestamp": datetime.datetime.now().isoformat()}
        try:
            await manager.send_personal_json(ws_msg, car_id, "command")
        except Exception:
            pass

        return resp_200(msg="小车已暂停")

    elif data.command == "resume":
        if car.status != CarStatus.PAUSE:
            return resp_400(msg="小车当前未暂停，无需恢复")
        car.status = CarStatus.WORKING
        session.add(car)
        session.commit()
        logger.info(f"管理员 {user.name} 下发指令 resume 给小车 {car_id}")

        ws_msg = {"command": "resume", "timestamp": datetime.datetime.now().isoformat()}
        try:
            await manager.send_personal_json(ws_msg, car_id, "command")
        except Exception:
            pass

        return resp_200(msg="小车已恢复运行")

    elif data.command == "depart":
        # wait_command 站点：允许调度端代为发车
        ws_msg = {
            "command": "depart",
            "site_id": (data.params or {}).get("site_id"),
            "timestamp": datetime.datetime.now().isoformat()
        }
        try:
            await manager.send_personal_json(ws_msg, car_id, "command")
        except Exception:
            pass
        logger.info(f"管理员/调度员 {user.name} 向小车 {car_id} 下发发车指令")
        return resp_200(msg="发车指令已下发")

    else:
        return resp_400(msg=f"不支持的指令: {data.command}")

@car_api.post("/{car_id}/control_mode", summary="切换小车控制模式")
async def switch_control_mode(
        car_id: int = ApiPath(..., description="车辆ID"),
        data: ControlModeIn = Body(..., description="目标控制模式（mode 必填）"),
        user: Users = Depends(get_current_dispatcher),
        session: Session = Depends(get_session)
):
    """
    切换小车控制模式：
    - AUTO: 自动模式（由调度系统控制）
    - MANUAL: 手动模式（人工控制）
    - TRACKING: 寻迹模式

    限制：
    - 小车正在执行任务（WORKING）时不允许切换，需先暂停或停止。
    - 切换为 TRACKING 时必须指定 path_id（寻迹的路线）。
    """
    # 1. 校验小车是否存在（权限已由 get_current_dispatcher 依赖校验）
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")

    # 3. 前置条件：正在执行任务时不允许切换
    if car.status == CarStatus.WORKING:
        return resp_400(msg="小车正在执行任务，请先暂停或停止后再切换模式")

    # 4. 检查是否与当前模式相同
    new_mode = data.mode.value
    if car.control_mode == new_mode:
        return resp_400(msg=f"小车当前已处于 {new_mode} 模式，无需切换")

    # 5. 如果切到 TRACKING，必须指定寻迹路线
    if new_mode == "TRACKING":
        if not data.path_id:
            return resp_400(msg="寻迹模式需要指定 path_id")
        path = session.get(Path, data.path_id)
        if not path:
            return resp_400(msg="路线不存在")
        car.tracking_path_id = data.path_id
    else:
        # 切到其他模式时清空寻迹路线
        car.tracking_path_id = None

    # 6. 更新控制模式
    old_mode = car.control_mode
    car.control_mode = new_mode
    session.add(car)
    session.commit()
    logger.info(f"管理员 {user.name} 将小车 {car_id} 控制模式从 {old_mode} 切换为 {new_mode}")

    # 7. WebSocket 推送（只发 mode，不发 path_id；路线数据后续走独立 topic）
    ws_msg = {
        "type": "control_mode",
        "mode": new_mode,
        "timestamp": datetime.datetime.now().isoformat()
    }
    try:
        await manager.send_personal_json(ws_msg, car_id, "command")
        logger.info(f"控制模式变更已推送给车端 {car_id}")
    except Exception as e:
        logger.error(f"WebSocket 推送失败: {e}")

    # 8. 返回给前端
    return resp_200(
        msg=f"控制模式已切换为 {new_mode}",
        data={
            "control_mode": new_mode,
            "tracking_path_id": car.tracking_path_id
        }
    )