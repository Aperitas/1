import datetime
from typing import Optional, List
from schemas.car_command import CarCommandIn, ControlModeIn, CarMapSetIn
from fastapi import APIRouter, Depends
from sqlmodel import Session, select, delete

from core.logger import logger
from core.security import get_current_user, get_current_dispatcher, get_current_admin
from db.session import get_session
from models.car.car import Cars, CarStatus
from models.car.map_link import CarMapLink
from models.car.tasks import Tasks
from models.map import Map
from models.path import Path
from models.user.users import Users
from utils.resp_code import resp_200, resp_500, resp_400
from apis.websocket.process import manager
from pydantic import BaseModel

car_api = APIRouter(prefix='/cars')


# ===== 车辆-地图关联辅助函数 =====
def _normalize_map_ids(map_ids) -> List[int]:
    """去重并保持传入顺序"""
    return list(dict.fromkeys(map_ids or []))


def _validate_map_ids(session: Session, map_ids):
    """校验地图是否存在，返回 (ids, error)"""
    unique_ids = _normalize_map_ids(map_ids)
    if not unique_ids:
        return [], None
    exists = set(session.exec(select(Map.id).where(Map.id.in_(unique_ids))).all())
    missing = [mid for mid in unique_ids if mid not in exists]
    if missing:
        return None, f"地图不存在: {missing}"
    return unique_ids, None


def _get_car_map_ids(session: Session, car_id: int) -> List[int]:
    """查询车辆当前关联的地图 id 列表"""
    return list(session.exec(select(CarMapLink.map_id).where(CarMapLink.car_id == car_id)).all())


def _replace_car_maps(session: Session, car_id: int, map_ids: List[int]) -> None:
    """覆盖式设置车辆所属地图（先清空再写入）"""
    session.execute(delete(CarMapLink).where(CarMapLink.car_id == car_id))
    for map_id in map_ids:
        session.add(CarMapLink(car_id=car_id, map_id=map_id))


# ===== 定义接收前端传来的小车数据结构 =====
class CarCreateIn(BaseModel):
    name: str
    productor: Optional[str] = "未知厂商"
    weight: Optional[float] = 50.0
    ip: Optional[str] = "192.168.1.100"
    port: Optional[str] = "9090"
    map_ids: Optional[List[int]] = None  # 所属地图（可多选）

@car_api.post("/create", summary="新增小车")
async def create_car(
    data: CarCreateIn,
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """
    在系统中新增一台小车。如果新增成功，返回自动生成的 car_id。
    可通过 map_ids 指定该车所属地图（多选，可不传）。
    """
    if not user.isAdmin:
        return resp_400(msg="权限不足，仅管理员可操作")

    map_ids, error = _validate_map_ids(session, data.map_ids)
    if error:
        return resp_400(msg=error)

    try:
        # 创建新小车，所有轨迹数据默认给 0 或 100
        new_car = Cars(
            name=data.name,
            productor=data.productor,
            weight=data.weight,
            ip=data.ip,
            port=data.port,
            status=CarStatus.FREE,      # 默认状态为空闲
            lon=113.9686,               # 默认南科大经纬度
            lat=22.6042,
            yaw=0.0,
            speed=0.0,
            battery=100.0,
            video_streams="{}",
            control_mode="AUTO"         # 默认自动模式
        )
        session.add(new_car)
        session.commit()
        session.refresh(new_car)

        # 写入车辆-地图关联
        if map_ids:
            _replace_car_maps(session, new_car.id, map_ids)
            session.commit()

        logger.info(f"管理员 {user.name} 新增了一台小车: {data.name} (ID: {new_car.id}, 地图: {map_ids})")
        return resp_200(msg="小车创建成功", data={"car_id": new_car.id, "map_ids": map_ids})
    except Exception as e:
        session.rollback()
        logger.error(f"创建小车失败: {e}")
        return resp_500(msg=f"创建小车失败: {str(e)}")

# 放在 CarCreateIn 的下面
class CarUpdateIn(BaseModel):
    name: Optional[str] = None
    productor: Optional[str] = None
    weight: Optional[float] = None
    ip: Optional[str] = None
    port: Optional[str] = None
    status: Optional[int] = None  # 允许管理员手动改状态
    description: Optional[str] = None
    map_ids: Optional[List[int]] = None  # 所属地图（传了就整体覆盖）

@car_api.put("/{car_id}/update", summary="修改小车信息")
async def update_car(
    car_id: int,
    data: CarUpdateIn,
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """
    修改指定小车的信息。只需传需要修改的字段，未传的字段保持原样。
    """
    if not user.isAdmin:
        return resp_400(msg="权限不足，仅管理员可操作")
    
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
        
    try:
        # 遍历传入的字段并更新；map_ids 不是 Cars 的列，单独处理
        update_data = data.dict(exclude_unset=True)
        new_map_ids = update_data.pop("map_ids", None)
        if new_map_ids is not None:
            new_map_ids, error = _validate_map_ids(session, new_map_ids)
            if error:
                return resp_400(msg=error)
        for key, value in update_data.items():
            # 如果传了 status，需要转成枚举类型
            if key == "status":
                try:
                    car.status = CarStatus(value)
                except ValueError:
                    return resp_400(msg=f"无效的小车状态值: {value}")
            else:
                setattr(car, key, value)
                
        session.add(car)
        session.commit()
        session.refresh(car)

        if new_map_ids is not None:
            _replace_car_maps(session, car.id, new_map_ids)
            session.commit()

        result = car.dict()
        result["map_ids"] = _get_car_map_ids(session, car.id)
        logger.info(f"管理员 {user.name} 修改了小车 {car_id} 的信息")
        return resp_200(msg="小车信息修改成功", data=result)
    except Exception as e:
        session.rollback()
        logger.error(f"修改小车信息失败: {e}")
        return resp_500(msg=f"修改失败: {str(e)}")

@car_api.get("/list", summary="获取所有小车完整信息，包含地图GPS经纬度")
async def get_car_list(user: Users = Depends(get_current_user)):
    """
    前端地图页面调用，返回每台小车真实GPS经纬度/航向/电量，以及所属地图列表
    """
    with get_session() as session:
        all_cars = session.query(Cars).all()
        links = session.exec(select(CarMapLink)).all()
        map_names = {m.id: m.name for m in session.exec(select(Map)).all()}
        car_map_ids = {}
        for link in links:
            car_map_ids.setdefault(link.car_id, []).append(link.map_id)

        result = []
        for car in all_cars:
            map_ids = car_map_ids.get(car.id, [])
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
                "map_ids": map_ids,
                "maps": [{"id": mid, "name": map_names.get(mid)} for mid in map_ids],
            }
            result.append(item)
    return resp_200(data=result)


@car_api.get("/{car_id}/maps", summary="获取车辆所属地图")
async def get_car_maps(
    car_id: int,
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """查看某辆小车关联的所有地图。"""
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
    map_ids = _get_car_map_ids(session, car_id)
    maps = session.exec(select(Map).where(Map.id.in_(map_ids))).all() if map_ids else []
    return resp_200(data={
        "car_id": car_id,
        "map_ids": map_ids,
        "maps": [{"id": m.id, "name": m.name} for m in maps],
    })


@car_api.put("/{car_id}/maps", summary="设置车辆所属地图")
async def set_car_maps(
    car_id: int,
    data: CarMapSetIn,
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_admin)
):
    """覆盖式设置某辆小车所属的地图（传空数组表示解除全部关联）。"""
    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")
    map_ids, error = _validate_map_ids(session, data.map_ids)
    if error:
        return resp_400(msg=error)
    try:
        _replace_car_maps(session, car_id, map_ids)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"设置车辆所属地图失败: {e}")
        return resp_500(msg="设置车辆所属地图失败")
    logger.info(f"管理员 {user.name} 设置小车 {car_id} 的所属地图为 {map_ids}")
    return resp_200(data={"car_id": car_id, "map_ids": map_ids}, msg="设置成功")


@car_api.delete("/{car_id}", summary="删除小车")
async def delete_car(
    car_id: int,
    session: Session = Depends(get_session),
    user: Users = Depends(get_current_user)
):
    """
    删除指定小车（仅管理员）：
    - 小车正在执行任务(WORKING)时不允许删除，需先停止；
    - 若仍有路线专属于该车，禁止删除，需先删除或解除这些路线；
    - 删除前把历史任务的 car_id 置空，避免外键悬挂；
    - 同步清理该车在 WebSocket 指令通道中的连接记录。
    """
    if not user.isAdmin:
        return resp_400(msg="权限不足，仅管理员可删除小车")

    car = session.get(Cars, car_id)
    if not car:
        return resp_400(msg="小车不存在")

    # 1. 正在执行任务的小车禁止删除
    if car.status == CarStatus.WORKING:
        return resp_400(msg="小车正在执行任务，请先停止后再删除")

    # 2. 仍被路线引用时禁止删除（paths.car_id 为外键）
    related_paths = session.exec(select(Path).where(Path.car_id == car_id)).all()
    if related_paths:
        return resp_400(msg=f"该小车仍被 {len(related_paths)} 条路线引用，请先删除或解除这些路线")

    car_name = car.name
    try:
        # 3. 解除历史任务与小车的外键关联
        related_tasks = session.exec(select(Tasks).where(Tasks.car_id == car_id)).all()
        for task in related_tasks:
            task.car_id = None
            session.add(task)

        session.delete(car)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"删除小车失败: {e}")
        return resp_500(msg=f"删除小车失败: {str(e)}")

    # 4. 清理 WebSocket 指令通道中该车的连接记录
    manager.active_connections["command"].pop(car_id, None)

    logger.info(f"管理员 {user.name} 删除了小车: {car_name} (ID: {car_id})")
    return resp_200(msg="小车已删除", data={"car_id": car_id})


@car_api.post("/{car_id}/command", summary="下发指令给小车")
async def send_command(
        car_id: int,
        data: CarCommandIn,
        user: Users = Depends(get_current_dispatcher),
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

    elif data.command == "depart":
        # wait_command 站点：允许调度端代为发车
        ws_msg = {
            "command": "depart",
            "site_id": (data.params or {}).get("site_id"),
            "timestamp": datetime.datetime.now().isoformat()
        }
        try:
            await manager.send_personal_json(ws_msg, car_id, "command")
        except Exception:
            pass
        logger.info(f"管理员/调度员 {user.name} 向小车 {car_id} 下发发车指令")
        return resp_200(msg="发车指令已下发")

    else:
        return resp_400(msg=f"不支持的指令: {data.command}")

@car_api.post("/{car_id}/control_mode", summary="切换小车控制模式")
async def switch_control_mode(
        car_id: int,
        data: ControlModeIn,
        user: Users = Depends(get_current_dispatcher),
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
    # 1. 校验小车是否存在（权限已由 get_current_dispatcher 依赖校验）
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