import datetime
import uuid
from pathlib import Path
from typing import Optional
from enum import Enum
from schemas.car_command import CarCommandIn, ControlModeIn
import cv2
import numpy as np
from fastapi import APIRouter, Request, UploadFile, Depends
from starlette.responses import StreamingResponse
from sqlmodel import Session, select

from core.config import settings
from core.logger import logger
from core.security import get_current_user
from crud.items import itemCrud
from db.session import get_session
from models.car.car import Cars, CarStatus
from models.car.tasks import Tasks, TaskStatus
from models.item.items import Items, UserOrder, OrderStatus
from models.item.links import ItemProcessLink
from models.path import Path
from models.user.users import Users
from schemas.items import QueryInItems, OutputItems, SearchItems
from schemas.position import CarUploadMsg
from schemas.car_command import CarCommandIn
from utils.resp_code import resp_200, resp_500, resp_400
from utils import detect_surface
from apis.websocket.process import manager

car_api = APIRouter(prefix='/cars')


async def gen_frames(frame):
    ret, buffer = cv2.imencode('.jpg', frame)
    frame = buffer.tobytes()
    yield (b'--frame\r\n'
           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


# 全局内存缓存，存放实时小车位置（仅供临时测试用）
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
            item = {
                "car_id": car.id,
                "name": car.name,
                "status": car.status,
                "control_mode": car.control_mode,
                "tracking_path_id": car.tracking_path_id,
                "yaw": car.yaw,
                "speed": car.speed,
                "lon": car.lon,
                "lat": car.lat,
                "battery": car.battery,


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

    else:
        return resp_400(msg=f"不支持的指令: {data.command}")

@car_api.post("/{car_id}/control_mode", summary="切换小车控制模式")
async def switch_control_mode(
        car_id: int,
        data: ControlModeIn,
        user: Users = Depends(get_current_user),
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
    # 1. 仅管理员可操作
    if not user.isAdmin:
        return resp_400(msg="权限不足，仅管理员可切换控制模式")

    # 2. 校验小车是否存在
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