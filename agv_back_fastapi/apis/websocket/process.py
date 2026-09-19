"""
author:dlr123
date:2022年06月14日
"""
import json
import os
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import select
from fastapi.encoders import jsonable_encoder
from core.logger import logger
from core.security import check_jwt_token
from db.session import get_session
from models.item.items import Items
from schemas import TokenInfo
from schemas.items import OutputItems
from utils.custom_exc import PermissionNotEnough
from .common import ConnectionManager
import websockets

websocket_api = APIRouter(prefix='/ws')
manager = ConnectionManager()
dir_path = os.path.join(os.getcwd(), 'apis/websocket/data')


@websocket_api.websocket("/map")
async def websocket_map(websocket: WebSocket, token: str = None):
    """
    前端地图页面通过此 WebSocket 接收小车实时位置推送。
    连接示例：ws://39.108.77.178:8001/ws/map?token=你的JWT
    """
    route = "map"
    user_id = 0
    await manager.connect(user_id, route, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, route)


@websocket_api.websocket("/command")
async def websocket_command(websocket: WebSocket, token: str = None):
    """
    车端连接此 WebSocket 接收指令。
    连接示例：ws://39.108.77.178:8001/ws/command?token=你的JWT
    """
    logger.info(f"WebSocket /command 连接尝试，token: {token}")
    route = "command"
    car_id = None

    # ========== 只 accept 一次 ==========
    await websocket.accept()
    logger.info(f"WebSocket /command 连接已接受")

    # ========== 等待车端发送注册信息 ==========
    try:
        msg = await websocket.receive_text()
        data = json.loads(msg)
        if data.get("type") != "register":
            await websocket.close(code=1008, reason="Invalid registration")
            return
        car_id = data.get("car_id")
        if car_id is None:
            await websocket.close(code=1008, reason="Missing car_id")
            return
        # 手动注册到 manager（避免调用 manager.connect() 造成重复 accept）
        manager.active_connections[route][car_id] = websocket
        logger.info(f"车端 {car_id} 已连接指令通道")
    except WebSocketDisconnect:
        logger.info("车端在注册阶段断开连接")
        return
    except Exception as e:
        logger.error(f"车端注册失败: {e}")
        return

    # ========== 保持连接，接收车端确认消息 ==========
    try:
        while True:
            msg = await websocket.receive_text()
            logger.debug(f"车端 {car_id} 确认: {msg}")
    except WebSocketDisconnect:
        logger.info(f"车端 {car_id} 断开连接")
    finally:
        manager.active_connections[route].pop(car_id, None)