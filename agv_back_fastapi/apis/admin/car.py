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