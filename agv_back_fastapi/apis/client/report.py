import math

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from db.session import get_session
from models.car import Cars
from models.car.map_link import CarMapLink
from models.map import Map
from utils.coords import (
    has_bounds as map_has_bounds, has_grid as map_has_grid, lonlat_to_pc,
)
from schemas.position import CarReportIn
from schemas.car_command import SiteDepartIn
from apis.api_docs import CAR_POSE
from utils.resp_code import resp_200, resp_400
from datetime import datetime
from core.logger import logger
from apis.websocket.process import manager
from utils.video_streams import merge_streams

router = APIRouter(prefix="/report", tags=["车端上报"])


def _single_car_map_id(session: Session, car_id: int):
    """车辆只绑定一张地图时返回该地图ID，否则返回 None"""
    ids = list(session.exec(select(CarMapLink.map_id).where(CarMapLink.car_id == car_id)).all())
    return ids[0] if len(ids) == 1 else None


def _bearing_to_pc_yaw(map_obj, lon: float, lat: float, yaw_deg: float) -> float:
    """经纬度航向（0=正北，顺时针为正）-> 点云坐标系航向（度，+x 轴为 0，逆时针为正）

    做法：在经纬度上沿航向走 1 米，把两点都换算到点云坐标，取两点向量的夹角。
    这样自动把地图本身的旋转（transform）算进去。
    """
    rad = math.radians(float(yaw_deg or 0.0))
    step = 1.0  # 米
    dlat = math.cos(rad) * step / 111320.0
    dlon = math.sin(rad) * step / (111320.0 * math.cos(math.radians(lat)))
    x1, y1 = lonlat_to_pc(map_obj, lon, lat)
    x2, y2 = lonlat_to_pc(map_obj, lon + dlon, lat + dlat)
    return math.degrees(math.atan2(y2 - y1, x2 - x1))


PC_POSE_KEYS = ("pc_x", "pc_y", "pc_z", "pc_roll", "pc_pitch", "pc_yaw")


def _normalize_angle(value):
    """角度归一到 (-180, 180]；None 原样返回"""
    if value is None:
        return None
    v = float(value) % 360.0
    return v - 360.0 if v > 180.0 else v


def _check_finite_values(values: dict) -> str:
    """校验位姿数值必须是有限数字，返回错误信息或空串"""
    for name, value in values.items():
        if value is None:
            continue
        if not math.isfinite(float(value)):
            return "%s 必须是有限数字" % name
    return ""


def _resolve_pc_pose(session: Session, car, data) -> dict:
    """解析车辆在局部点云图中的完整 6DoF 位姿

    返回 dict（值为 None 表示「这次没拿到」，调用方应保持原值）：
        {map_id, pc_x, pc_y, pc_z, pc_roll, pc_pitch, pc_yaw}

    优先级：
    1) 车端直接上报 pc_x/pc_y（可同时带 pc_z / pc_roll / pc_pitch / pc_yaw）—— 最可信；
    2) 用地图变换把经纬度换算成点云坐标：**只能得到 x / y / yaw**，
       z 与 roll/pitch 无法从 2D 经纬度换算，保持 None；
    3) 都做不到时全部 None。
    """
    if data.pc_x is not None and data.pc_y is not None:
        return {
            "map_id": data.pc_map_id or car.pc_map_id,
            "pc_x": data.pc_x,
            "pc_y": data.pc_y,
            "pc_z": data.pc_z,
            "pc_roll": _normalize_angle(data.pc_roll),
            "pc_pitch": _normalize_angle(data.pc_pitch),
            "pc_yaw": _normalize_angle(data.pc_yaw),
        }

    empty = {"map_id": None, "pc_x": None, "pc_y": None, "pc_z": None,
             "pc_roll": None, "pc_pitch": None, "pc_yaw": None}
    map_id = data.pc_map_id or car.pc_map_id or _single_car_map_id(session, car.id)
    if map_id is None:
        return empty
    map_obj = session.get(Map, map_id)
    if map_obj is None or not (map_has_grid(map_obj) and map_has_bounds(map_obj)):
        return empty
    try:
        x, y = lonlat_to_pc(map_obj, data.lon, data.lat)
        yaw = data.pc_yaw if data.pc_yaw is not None else _bearing_to_pc_yaw(map_obj, data.lon, data.lat, data.yaw)
    except Exception as e:
        logger.warning("经纬度换算点云坐标失败（map_id=%s）: %s" % (map_id, e))
        return empty
    return {"map_id": map_id, "pc_x": x, "pc_y": y, "pc_z": None,
            "pc_roll": None, "pc_pitch": None, "pc_yaw": _normalize_angle(yaw)}


@router.post("/car_status", summary="车端状态上报", description=CAR_POSE)
async def car_status_report(data: CarReportIn, session: Session = Depends(get_session)):
    """车端上报经纬度、电量、速度、视频地址，更新后通过 WebSocket 广播给前端地图页面。

    可选上报 **局部点云完整位姿**（`pc_map_id` / `pc_x` / `pc_y` / `pc_z` / `pc_roll` / `pc_pitch` / `pc_yaw`）：
    - 车端在点云/栅格图里定位好后直接传，前端就能在点云图上画出车；
    - 不传时后端会尝试用地图变换（bounds + transform）把经纬度换算成点云坐标与航向；
    - 两者都不可用时保持上一次的值，不会把已有位姿清空。
    """
    car = session.get(Cars, data.car_id)
    if not car:
        return resp_400(msg="小车ID不存在")

    # 更新真实数据
    car.lon = data.lon
    car.lat = data.lat
    car.yaw = data.yaw
    car.speed = data.speed
    car.battery = data.battery
    # 视频流：只有车端真的上报了才合并，避免空值覆盖管理员配置、或冲掉其他视角
    if data.video_streams:
        car.video_streams = merge_streams(car.video_streams, data.video_streams)

    # 6DoF 位姿：先校验，再逐字段合并（本次没拿到的字段保持上次值，不清零）
    error = _check_finite_values({
        "pc_x": data.pc_x, "pc_y": data.pc_y, "pc_z": data.pc_z,
        "pc_roll": data.pc_roll, "pc_pitch": data.pc_pitch, "pc_yaw": data.pc_yaw,
    })
    if error:
        return resp_400(msg=error)
    if data.pc_z is not None and abs(float(data.pc_z)) > 1000.0:
        return resp_400(msg="pc_z 超出范围（-1000 ~ 1000 米）")

    pose = _resolve_pc_pose(session, car, data)
    if pose["map_id"] is not None:
        car.pc_map_id = pose["map_id"]
    for key in PC_POSE_KEYS:
        if pose[key] is not None:
            setattr(car, key, pose[key])

    car.last_heartbeat = datetime.now()

    session.add(car)
    session.commit()
    # 广播给所有订阅地图的前端
    await manager.broadcast_json("map", {
        "car_id": car.id,
        "lon": car.lon,
        "lat": car.lat,
        "yaw": car.yaw,
        "speed": car.speed,
        "battery": car.battery,
        "pc_map_id": car.pc_map_id,
        "pc_x": car.pc_x,
        "pc_y": car.pc_y,
        "pc_z": car.pc_z,
        "pc_roll": car.pc_roll,
        "pc_pitch": car.pc_pitch,
        "pc_yaw": car.pc_yaw,
        "status": car.status  # 可选
    })
    return resp_200(msg="状态更新成功")


@router.post("/site_depart", summary="车端请求发车（wait_command 站点）")
async def site_depart(data: SiteDepartIn, session: Session = Depends(get_session)):
    """车端在 wait_command 模式的站点按键发车：服务端向该车 WS 通道推送 depart 指令。"""
    car = session.get(Cars, data.car_id)
    if not car:
        return resp_400(msg="小车ID不存在")

    ws_msg = {
        "command": "depart",
        "site_id": data.site_id,
        "timestamp": datetime.now().isoformat()
    }
    pushed = True
    try:
        await manager.send_personal_json(ws_msg, data.car_id, "command")
    except KeyError:
        pushed = False
        logger.warning(f"小车 {data.car_id} 未连接指令通道，发车指令未送达")
    except Exception as e:
        pushed = False
        logger.error(f"推送发车指令失败: {e}")

    logger.info(f"小车 {data.car_id} 在站点 {data.site_id} 请求发车（推送={pushed}）")
    return resp_200(
        data={"car_id": data.car_id, "site_id": data.site_id, "pushed": pushed},
        msg="发车指令已下发" if pushed else "车端未连接指令通道"
    )