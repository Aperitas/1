from fastapi import APIRouter, Depends
from sqlmodel import Session
from db.session import get_session
from models.car import Cars
from schemas.position import CarReportIn
from schemas.car_command import SiteDepartIn
from utils.resp_code import resp_200, resp_400
from datetime import datetime
from core.logger import logger
from apis.websocket.process import manager
from utils.video_streams import merge_streams

router = APIRouter(prefix="/report", tags=["车端上报"])

@router.post("/car_status", summary="车端状态上报")
async def car_status_report(data: CarReportIn, session: Session = Depends(get_session)):
    """车端上报经纬度、电量、速度、视频地址，更新后通过 WebSocket 广播给前端地图页面。"""
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