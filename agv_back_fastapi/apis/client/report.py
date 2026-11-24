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


def _resolve_pc_pose(session: Session, car, data):
    """解析车辆在局部点云图中的位姿，返回 (pc_map_id, pc_x, pc_y, pc_yaw)

    优先级：
    1) 车端直接上报 pc_x/pc_y（并可带 pc_yaw）—— 最可信；
    2) 用地图变换把经纬度换算成点云坐标（航向也一起换算）；
    3) 都做不到时返回 (None, None, None, None)，调用方保持原值不动。
    """
    if data.pc_x is not None and data.pc_y is not None:
        return (data.pc_map_id or car.pc_map_id), data.pc_x, data.pc_y, data.pc_yaw

    map_id = data.pc_map_id or car.pc_map_id or _single_car_map_id(session, car.id)
    if map_id is None:
        return None, None, None, None
    map_obj = session.get(Map, map_id)
    if map_obj is None or not (map_has_grid(map_obj) and map_has_bounds(map_obj)):
        return None, None, None, None
    try:
        x, y = lonlat_to_pc(map_obj, data.lon, data.lat)
        yaw = data.pc_yaw if data.pc_yaw is not None else _bearing_to_pc_yaw(map_obj, data.lon, data.lat, data.yaw)
    except Exception as e:
        logger.warning("经纬度换算点云坐标失败（map_id=%s）: %s" % (map_id, e))
        return None, None, None, None
    return map_id, x, y, yaw


@router.post("/car_status", summary="车端状态上报", description=CAR_POSE)
async def car_status_report(data: CarReportIn, session: Session = Depends(get_session)):
    """车端上报经纬度、电量、速度、视频地址，更新后通过 WebSocket 广播给前端地图页面。

    可选上报 **局部点云位姿**（`pc_map_id` / `pc_x` / `pc_y` / `pc_yaw`）：
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
    # 局部点云位姿：能算出来才更新，算不出来保持原值
    pc_map_id, pc_x, pc_y, pc_yaw = _resolve_pc_pose(session, car, data)
    if pc_map_id is not None:
        car.pc_map_id = pc_map_id
        car.pc_x = pc_x
        car.pc_y = pc_y
        car.pc_yaw = pc_yaw

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