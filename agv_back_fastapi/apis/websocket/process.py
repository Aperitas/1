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

websocket_api = APIRouter(prefix='/ws')
manager = ConnectionManager()
dir_path = os.path.join(os.getcwd(),'apis/websocket/data')


@websocket_api.websocket("/")
async def websocket_endpoint(websocket: WebSocket) :
    route = 'test'
    username = 'test'
    id = 0
    await manager.connect(id,route,websocket)
    try :
        while True :
            data = await websocket.receive_text()
            data = f"hello {username}"
            await manager.send_personal_text(f"You wrote: {data}",id,route)
            await manager.broadcast_text(route,f"Client {username} says: {data}")
            time.sleep(1)
    except WebSocketDisconnect :
        manager.disconnect(id,route)
        await manager.broadcast_text(route,f"Client {username} left the chat")


@websocket_api.websocket("/get_process_data")
async def get_process_data(websocket: WebSocket,token: str) :
    tokeninfo: TokenInfo = await check_jwt_token(token)
    if not tokeninfo.isAdmin :
        raise PermissionNotEnough
    route = 'get_process_data'
    id = tokeninfo.id
    await manager.connect(id,route,websocket)
    session = get_session()

    async def get_data(session) :
        res_data = {'name' : '商品销售统计',
                    'children' : [],
                    'count' : 0}
        sql = select(Items)
        result = session.exec(sql).all()
        for item in result :
            kind = 'admin' if item.Provider == 'admin' else 'client'
            item_info = OutputItems.from_orm(item)
            item_info.kind = kind
            count = len(item.UserOrders)
            item_dict = {'name' : item.name,'value' : count,
                         'info' : item_info.dict()}
            res_data['children'].append(item_dict)
            res_data['count'] += count
        return res_data

    try :
        while True :
            res_data = await get_data(session)
            await manager.send_personal_json(res_data,id,route)
            time.sleep(1)
    except WebSocketDisconnect :
        manager.disconnect(id,route)
    except Exception as e :
        session.rollback()
        logger.error(f'websocket连接出错,因为：{e}')
    finally :
        session.close()


@websocket_api.websocket("/order")
async def websocket_endpoint(websocket: WebSocket) :
    await websocket.accept()
    try :
        while True :
            data = await websocket.receive_json()
            action = data.get('action')
            if action == 'getData' :
                file_name = data.get('chartName')
                if file_name is not None :
                    file_path = os.path.join(dir_path,f'{file_name}.json')
                    with open(file_path,'rt',encoding='utf-8') as f :
                        ret = json.load(f)
                    data['data'] = ret
            else :
                pass
            data = jsonable_encoder(data)
            await websocket.send_json(data)
    except WebSocketDisconnect :
        pass

@websocket_api.websocket("/map")
async def websocket_map(websocket: WebSocket, token: str = None):
    """
    前端地图页面通过此 WebSocket 接收小车实时位置推送。
    连接示例：ws://39.108.77.178:8001/ws/map?token=你的JWT
    """
    # 可选：验证 token（如果需要鉴权，取消注释下面的代码）
    # if token:
    #     tokeninfo = await check_jwt_token(token)
    #     user_id = tokeninfo.id
    # else:
    #     user_id = 0  # 未认证用户

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