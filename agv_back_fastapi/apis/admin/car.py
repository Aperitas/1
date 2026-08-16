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
from utils.geo_transform import xy_to_gps
#from core import FastAPiNode


class CtrOption(int, Enum):
    ACTIVATE = 0
    PAUSE = 1
    CONTINUE = 2
    CANCEL = 3
    INACTIVATE = 4


car_api = APIRouter(prefix='/cars')


@car_api.post('/setStatus')
async def setStatus(car_id: int, ctl_code: int, req: Request, user: Users = Depends(get_current_user)):
    res = resp_200(msg="success")
    with get_session() as session:
        try:
            car: Cars = session.query(Cars).get(car_id)
            if car is None:
                raise ValueError("the car is not exit")
            if ctl_code == CtrOption.PAUSE:
                if car.status == CarStatus.WORKING:
                    req.state.rosnode.cancelGoal()
                    # car.status = CarStatus.PAUSE
                    # session.add(car)
                else:
                    logger.warning("the car is not pausing,it can't")
                    res = resp_400(msg="the car has been pausing!")
            elif ctl_code == CtrOption.CONTINUE:
                if car.status == CarStatus.PAUSE:
                    car.status = CarStatus.FREE
                    session.add(car)
                elif car.status == CarStatus.FREE:
                    res = resp_400(msg="the car is free,not need to set to continue")
                else:
                    res = resp_400(msg="the car can not be set to continue")
            elif ctl_code == CtrOption.ACTIVATE:
                if car.status == CarStatus.INACTIVATE:
                    if car.current_task_id is not None:
                        task = session.query(Tasks).get(car.current_task_id)
                        if task is not None:
                            car.status = CarStatus.PAUSE
                        else:
                            car.current_task_id = None
                            car.status = CarStatus.FREE
                    else:
                        car.status = CarStatus.FREE
                    session.add(car)
                else:
                    res = resp_400(msg="the car can has been activated")
            elif ctl_code == CtrOption.INACTIVATE:
                if car.status == CarStatus.WORKING:
                    res = resp_400(msg="please pause the car firstly or wait for it complete")
                elif car.status == CarStatus.INACTIVATE:
                    res = resp_400(msg="the car is inactivate,it is not need to set")
                else:
                    car.status = CarStatus.INACTIVATE
                session.add(car)
            else:  # cancel the task
                if car.status == CarStatus.PAUSE and car.current_task_id is not None:
                    task: Tasks = session.query(Tasks).get(car.current_task_id)
                    if task is not None:
                        task.end_time = datetime.datetime.now()
                        task.status = TaskStatus.FAIL
                        try:
                            order: UserOrder = task.UserOrder[0]
                        except:
                            order: UserOrder = task.UserOrder
                        order.status = OrderStatus.Fail
                        task.fail_reason = "we can not complete the order"
                        order.reject_or_fail_reason = "we can not complete the order"
                    car.status = CarStatus.FREE
                    car.current_task_id = None
                    session.add(task)
                    session.add(car)
                    session.add(order)
                elif car.status == CarStatus.WORKING:
                    res = resp_400(msg="please pause the car firstly")
                else:
                    res = resp_400(msg='the car can not be cancel')
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning(f"ros status control error! because: {e}")
            res = resp_400(msg="set car status fail")
    return res


@car_api.post('/runDemo')
async def setStatus(taskId: int, req: Request, car_id: int = 1,
                    user: Users = Depends(get_current_user)):
    res = resp_200(msg="success")
    with get_session() as session:
        try:
            car: Cars = session.query(Cars).get(car_id)
            if car is None:
                raise ValueError("the car is not exit")
            if car.status != CarStatus.FREE:
                if car.status == CarStatus.WORKING:
                    if taskId == 0:
                        req.state.rosnode.cancelDemoGoal()
                    else:
                        res = resp_400(msg="the car can not excecute the demo now!")
                else:
                    res = resp_400(msg="the car can not excecute the demo now!")
            else:
                car.status = CarStatus.WORKING
                session.add(car)
                session.commit()
                started = req.state.rosnode.callDemo(taskId)
                if not started:
                    res = resp_400(msg="the server is not start!")
        except Exception as e:
            session.rollback()
            logger.warning(f"demo run error! because: {e}")
            res = resp_400(msg="demo run fail")
    return res


async def gen_frames(frame):
    ret, buffer = cv2.imencode('.jpg', frame)
    frame = buffer.tobytes()
    yield (b'--frame\r\n'
           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@car_api.post('/processImage')
async def process_image(req: Request, uploadImage: Optional[UploadFile] = None,
                        user: Users = Depends(get_current_user)):
    res = resp_200(msg="sucess!")
    img = None
    sucess = True
    if uploadImage is None:
        img = req.state.rosnode.callForImage()
        if img is None:
            res = resp_400(msg="can not get the camera frame")
            sucess = False
    else:
        try:
            content = uploadImage.file.read()
            img = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        except:
            res = resp_400(msg="the image upload has something error!")
            sucess = False
    if sucess:
        img = detect_surface(img)
        return StreamingResponse(gen_frames(img), media_type='multipart/x-mixed-replace; boundary=frame')
    else:
        return res


# 全局内存缓存，存放实时小车位置
car_position_cache = {}

@car_api.post("/position/upload")
async def upload_car_position(pos: CarUploadMsg):
    """
    车端ROS主动上报位置，免鉴权
    完整路径：POST /api/admin/cars/position/upload
    """
    car_position_cache[pos.car_id] = {
        "car_id": pos.car_id,
        "x": pos.x,
        "y": pos.y,
        "speed": pos.speed,
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logger.info(f"收到小车{pos.car_id}上报 x={pos.x},y={pos.y},speed={pos.speed}")
    return resp_200(data=car_position_cache[pos.car_id])


@car_api.get("/position/all")
async def get_all_car_position():
    """
    前端轮询获取所有小车实时位置
    完整路径：GET /api/admin/cars/position/all
    """
    out_list = []
    for car_id, pos_data in car_position_cache.items():
        x = pos_data["x"]
        y = pos_data["y"]
        # XY平面坐标转真实GPS经纬度
        lon, lat = xy_to_gps(x, y)
        new_data = {
            **pos_data,
            "lon": lon,
            "lat": lat
        }
        out_list.append(new_data)
    return resp_200(data=out_list)

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