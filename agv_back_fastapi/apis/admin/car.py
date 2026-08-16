import datetime
import uuid
from pathlib import Path
from typing import Optional
import datetime
from core.logger import logger
from schemas.position import CarUploadMsg
from utils.resp_code import resp_200
import cv2
import numpy as np
from fastapi import APIRouter, Request, UploadFile, Depends
from starlette.responses import StreamingResponse
from utils import detect_surface
from core.config import settings
from core.logger import logger
from core.security import get_current_user
from crud.items import itemCrud
from db.session import get_session
from models.car.tasks import Tasks, TaskStatus
from models.item.items import Items
from models.item.links import ItemProcessLink
from models.item.items import UserOrder, OrderStatus
from models.user.users import Users
from schemas.items import QueryInItems, OutputItems, SearchItems
from utils.resp_code import resp_200, resp_500, resp_400
from models.car.car import Cars, CarStatus
from schemas.car_command import CarCommandIn
from models.path import Path
from enum import Enum
#from core import FastAPiNode


car_api = APIRouter(prefix='/cars')


async def gen_frames(frame):
    ret, buffer = cv2.imencode('.jpg', frame)
    frame = buffer.tobytes()
    yield (b'--frame\r\n'
           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')




# 全局内存缓存，存放实时小车位置
car_position_cache = {}

@car_api.get("/list", summary="获取所有小车完整信息，包含地图GPS经纬度")
async def get_car_list(user: Users = Depends(get_current_user)):
    """
    前端地图页面调用，返回每台小车真实GPS经纬度/航向/电量
    """
    with get_session() as session:
        all_cars = session.query(Cars).all()
        result = []
        for car in all_cars:
            # 直接拼装返回数据，不再依赖任何中间 Schema
            item = {
                "car_id": car.id,
                "name": car.name,
                "status": car.status,      # 已经是 int
                "x": car.x,               # 保留但前端已不用
                "y": car.y,
                "yaw": car.yaw,
                "speed": car.speed,
                "lon": car.lon,
                "lat": car.lat,
                "battery": car.battery,   # 新增：电量也返回给前端

            }
            result.append(item)
    return resp_200(data=result)
@car_api.post("/{car_id}/command", summary="下发指令给小车")
async def send_command(
        car_id: int,
        data: CarCommandIn,
        user: Users = Depends(get_current_user),
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
        # 加载路线
        from models.path import Path
        path = session.get(Path, data.path_id)
        if not path:
            return resp_400(msg="路线不存在")
        # 更新小车状态
        car.status = CarStatus.WORKING
        car.current_task_id = data.path_id
        session.add(car)
        session.commit()
        # TODO: 此处实际下发路线给车端（通过TCP/WebSocket/HTTP）
        logger.info(f"管理员 {user.name} 下发指令 {data.command} 给小车 {car_id}，路线ID: {data.path_id}")
        # 模拟下发成功
        return resp_200(msg=f"指令 {data.command} 已下发，小车开始行驶")

    elif data.command == "stop":
        car.status = CarStatus.FREE
        car.current_task_id = None
        session.add(car)
        session.commit()
        # TODO: 通知车端停止
        logger.info(f"管理员 {user.name} 下发指令 stop 给小车 {car_id}")
        return resp_200(msg="小车已停止")

    elif data.command == "pause":
        if car.status != CarStatus.WORKING:
            return resp_400(msg="小车当前未在工作，无法暂停")
        car.status = CarStatus.PAUSE
        session.add(car)
        session.commit()
        logger.info(f"管理员 {user.name} 下发指令 pause 给小车 {car_id}")
        return resp_200(msg="小车已暂停")

    elif data.command == "resume":
        if car.status != CarStatus.PAUSE:
            return resp_400(msg="小车当前未暂停，无需恢复")
        car.status = CarStatus.WORKING
        session.add(car)
        session.commit()
        logger.info(f"管理员 {user.name} 下发指令 resume 给小车 {car_id}")
        return resp_200(msg="小车已恢复运行")

    else:
        return resp_400(msg=f"不支持的指令: {data.command}")
