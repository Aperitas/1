from fastapi import APIRouter, Depends
from sqlmodel import Session
from db.session import get_session
from models.car import Cars
from schemas.position import CarReportIn
from utils.resp_code import resp_200, resp_400
from datetime import datetime
import json
from apis.websocket.process import manager

router = APIRouter(prefix="/report", tags=["车端上报"])

@router.post("/car_status")
async def car_status_report(data: CarReportIn, session: Session = Depends(get_session)):
    """车端上报经纬度、电量、速度、视频地址"""
    car = session.get(Cars, data.car_id)
    if not car:
        return resp_400(msg="小车ID不存在")

    # 更新真实数据
    car.lon = data.lon
    car.lat = data.lat
    car.yaw = data.yaw
    car.speed = data.speed
    car.battery = data.battery
    car.video_streams = json.dumps(data.video_streams)  # 存为JSON字符串
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