"""
author:dlr123
date:2022年06月14日
"""
import json
import os
import time

from fastapi import APIRouter,WebSocket,WebSocketDisconnect
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
dir_path = os.path.join(os.getcwd(),'apis/websocket/data')


@websocket_api.websocket("/map")
async def websocket_map(websocket: WebSocket, token: str = None):
    """
    前端地图页面通过此 WebSocket 接收小车实时位置推送。
    连接示例：ws://39.108.77.178:8001/ws/map?token=你的JWT
    """

    route = "map"  # 独立的广播通道
    user_id = 0    # 或从 token 解析
    await manager.connect(user_id, route, websocket)
    try:
        # 保持连接，等待消息（前端可能发心跳或关闭指令）
        while True:
            # 这里可以接收前端发来的消息（如心跳），也可忽略
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, route)

@websocket_api.websocket("/command")
async def websocket_command(websocket: WebSocket, token: str = None):
    logger.info(f"WebSocket /command 连接尝试，token: {token}")
    await websocket.accept()
    logger.info(f"WebSocket /command 连接已接受")
    """车端连接此 WebSocket 接收指令"""
    route = "command"
    car_id = None

    try:
        await websocket.accept()
    except Exception as e:
        logger.error(f"WebSocket 连接拒绝: {e}")
        return

    # 等待车端发送注册信息
    try:
        msg = await websocket.receive_text()
        data = json.loads(msg)
        if data.get("type") == "register":
            car_id = data.get("car_id")
            if car_id is None:
                await websocket.close(code=1008, reason="Missing car_id")
                return
            # 保存连接，以便后续推送指令
            await manager.connect(car_id, route, websocket)
            logger.info(f"车端 {car_id} 已连接指令通道")
        else:
            await websocket.close(code=1008, reason="Invalid registration")
            return
    except Exception as e:
        logger.error(f"车端连接失败: {e}")
        return

    try:
        while True:
            # 保持连接，接收车端的确认消息（或心跳）
            msg = await websocket.receive_text()
            # 可以处理车端的执行结果确认
            logger.debug(f"车端 {car_id} 确认: {msg}")
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"车端 {car_id} 断开连接")
    finally:
        manager.disconnect(car_id, route)