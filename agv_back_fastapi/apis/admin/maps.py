from fastapi import APIRouter, Depends, Query, File, UploadFile, Form
from sqlmodel import Session, select
from db.session import get_session
from models.map import Map, MapType
from models.site import Site
from models.waypoint import Waypoint
from models.path import Path
from models.car.car import Cars
from models.car.map_link import CarMapLink
from models.user.map_link import UserMapLink
from apis.access import visible_map_ids
from schemas.map import MapCreate, MapUpdate, MapOut
from utils.resp_code import resp_200, resp_400, resp_500
from core.security import get_current_user, get_current_admin
from models.user import Users
from typing import List, Optional
import os
import shutil
import json
from datetime import datetime
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/admin/maps", tags=["地图管理"])

VALID_MAP_TYPES = {t.value for t in MapType}


def _validate_map_object(map_obj: Map, session: Session) -> Optional[str]:
    """校验地图类型、天地图范围、兜底地图，返回错误信息或 None"""
    if map_obj.map_type not in VALID_MAP_TYPES:
        return f"map_type 只能是 {sorted(VALID_MAP_TYPES)}"
    if map_obj.map_type == MapType.TIANDITU.value:
        bounds = (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max)
        if any(value is None for value in bounds):
            return "天地图类型必须提供 lon_min/lat_min/lon_max/lat_max 四个角点"
        if map_obj.lon_min >= map_obj.lon_max or map_obj.lat_min >= map_obj.lat_max:
            return "天地图区域非法：需满足 lon_min<lon_max 且 lat_min<lat_max"
        if not (-180 <= map_obj.lon_min <= 180 and -180 <= map_obj.lon_max <= 180):
            return "经度必须在 -180~180 之间"
        if not (-90 <= map_obj.lat_min <= 90 and -90 <= map_obj.lat_max <= 90):
            return "纬度必须在 -90~90 之间"
    if map_obj.fallback_map_id is not None:
        if map_obj.id is not None and map_obj.fallback_map_id == map_obj.id:
            return "兜底地图不能指向自己"
        fallback = session.get(Map, map_obj.fallback_map_id)
        if fallback is None:
            return f"兜底地图不存在: {map_obj.fallback_map_id}"
        if fallback.map_type != MapType.POINTCLOUD.value:
            return "兜底地图必须是点云类型(pointcloud)"
    return None

# 地图文件存储目录
MAP_UPLOAD_DIR = "static/maps"
os.makedirs(MAP_UPLOAD_DIR, exist_ok=True)


@router.post("/", summary="新增地图")
async def create_map(
        data: MapCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员新增地图（名称、中心经纬度、默认缩放级别等）。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    try:
        new_map = Map(**data.dict())
    except Exception as e:
        return resp_400(msg=f"参数错误：{str(e)}")
    error = _validate_map_object(new_map, session)
    if error:
        return resp_400(msg=error)
    try:
        session.add(new_map)
        session.commit()
        session.refresh(new_map)
        return resp_200(data=new_map.dict(), msg="地图创建成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"创建失败：{str(e)}")


@router.post("/upload", summary="上传地图文件")
async def upload_map_file(
        map_id: int = Form(...),
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """上传地图文件（点云/压缩包），绑定到指定地图"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")

    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")

    # 保存文件
    filename = f"map_{map_id}_{file.filename}"
    file_path = os.path.join(MAP_UPLOAD_DIR, filename)

    #定义异步保存函数，放入线程池执行，避免阻塞主服务
    def save_file():
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    try:
        await run_in_threadpool(save_file)
    except Exception as e:
        return resp_500(msg=f"文件保存失败：{str(e)}")
    
    # 更新数据库
    map_obj.file_path = file_path
    map_obj.file_type = os.path.splitext(filename)[1].lstrip(".")
    map_obj.file_size = os.path.getsize(file_path)
    map_obj.upload_time = datetime.now()
    session.add(map_obj)
    session.commit()
    session.refresh(map_obj)

    return resp_200(
        msg="地图文件上传成功",
        data={
            "map_id": map_obj.id,
            "file_type": map_obj.file_type,
            "file_size": map_obj.file_size,
            "file_url": f"/static/maps/{filename}"
        }
    )


@router.get("/", summary="获取所有地图列表")
async def list_maps(
        map_type: Optional[str] = Query(None, description="按类型筛选: tianditu/grid/pointcloud"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """获取地图列表（按账户可见范围过滤），附带文件 URL、车辆/账户/路线数量。"""
    visible = visible_map_ids(session, user)
    query = select(Map)
    if visible is not None:
        query = query.where(Map.id.in_(visible))
    if map_type is not None:
        query = query.where(Map.map_type == map_type)
    maps = session.exec(query).all()

    car_ids_by_map = {}
    for link in session.exec(select(CarMapLink)).all():
        car_ids_by_map.setdefault(link.map_id, []).append(link.car_id)
    user_ids_by_map = {}
    for link in session.exec(select(UserMapLink)).all():
        user_ids_by_map.setdefault(link.map_id, []).append(link.user_id)
    path_counts = {}
    for p in session.exec(select(Path)).all():
        path_counts[p.map_id] = path_counts.get(p.map_id, 0) + 1

    result = []
    for m in maps:
        d = m.dict()
        d["file_url"] = f"/static/maps/{os.path.basename(m.file_path)}" if m.file_path else None
        d["car_ids"] = car_ids_by_map.get(m.id, [])
        d["car_count"] = len(d["car_ids"])
        d["user_ids"] = user_ids_by_map.get(m.id, [])
        d["user_count"] = len(d["user_ids"])
        d["path_count"] = path_counts.get(m.id, 0)
        result.append(d)
    return resp_200(data=result)


@router.get("/{map_id}", summary="获取单个地图详情")
async def get_map(
        map_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """按 id 获取单个地图详情，附带文件 URL、关联车辆/账户/路线数量。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    d = map_obj.dict()
    d["file_url"] = f"/static/maps/{os.path.basename(map_obj.file_path)}" if map_obj.file_path else None
    d["car_ids"] = [link.car_id for link in session.exec(
        select(CarMapLink).where(CarMapLink.map_id == map_id)).all()]
    d["car_count"] = len(d["car_ids"])
    d["user_ids"] = [link.user_id for link in session.exec(
        select(UserMapLink).where(UserMapLink.map_id == map_id)).all()]
    d["user_count"] = len(d["user_ids"])
    d["path_count"] = len(session.exec(select(Path).where(Path.map_id == map_id)).all())
    return resp_200(data=d)


@router.get("/{map_id}/cars", summary="获取地图包含的车辆")
async def list_map_cars(
        map_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """查看某张地图下关联的所有小车（多对多）。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    car_ids = [link.car_id for link in session.exec(
        select(CarMapLink).where(CarMapLink.map_id == map_id)).all()]
    cars = session.exec(select(Cars).where(Cars.id.in_(car_ids))).all() if car_ids else []
    return resp_200(data={
        "map_id": map_id,
        "car_ids": car_ids,
        "cars": [{"id": c.id, "name": c.name, "status": c.status} for c in cars],
    })


@router.get("/{map_id}/paths", summary="获取地图包含的路线")
async def list_map_paths(
        map_id: int,
        is_temp: Optional[bool] = Query(None, description="是否临时路径"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """查看某张地图下的路线（可按是否临时路径筛选），node_chain 已转成对象返回。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    query = select(Path).where(Path.map_id == map_id)
    if is_temp is not None:
        query = query.where(Path.is_temp == is_temp)
    result = []
    for p in session.exec(query).all():
        d = p.dict()
        d["node_chain"] = json.loads(d["node_chain"])
        result.append(d)
    return resp_200(data=result)


@router.get("/{map_id}/users", summary="获取地图关联的账户")
async def list_map_users(
        map_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_admin)
):
    """管理员查看某张地图关联的所有账户（多对多）。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    user_ids = [link.user_id for link in session.exec(
        select(UserMapLink).where(UserMapLink.map_id == map_id)).all()]
    users = session.exec(select(Users).where(Users.id.in_(user_ids))).all() if user_ids else []
    return resp_200(data={
        "map_id": map_id,
        "user_ids": user_ids,
        "users": [{"id": u.id, "name": u.name, "nickname": u.nickname, "role": u.effective_role} for u in users],
    })


@router.put("/{map_id}", summary="修改地图信息")
async def update_map(
        map_id: int,
        data: MapUpdate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员修改地图信息，仅更新传入的字段（会重新校验类型/范围/兜底）。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    for key, value in data.dict(exclude_unset=True).items():
        setattr(map_obj, key, value)
    error = _validate_map_object(map_obj, session)
    if error:
        session.rollback()
        return resp_400(msg=error)
    session.add(map_obj)
    session.commit()
    session.refresh(map_obj)
    return resp_200(data=map_obj.dict(), msg="地图更新成功")


@router.delete("/{map_id}", summary="删除地图")
async def delete_map(
        map_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员删除地图：有站点/路径点/普通路线时禁止删除；临时路径自动清理，
    车辆与账户关联自动解绑，其他地图指向它的兜底关系会被置空，磁盘文件一并删除。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    sites = session.exec(select(Site).where(Site.map_id == map_id)).first()
    waypoints = session.exec(select(Waypoint).where(Waypoint.map_id == map_id)).first()
    normal_paths = session.exec(
        select(Path).where(Path.map_id == map_id, Path.is_temp == False)).first()
    if sites or waypoints or normal_paths:
        return resp_400(msg="该地图下存在站点、路径点或普通路线，无法删除（临时路径会自动清理）")

    # 临时路径随地图一起删除（一次性数据）
    for temp_path in session.exec(
            select(Path).where(Path.map_id == map_id, Path.is_temp == True)).all():
        session.delete(temp_path)
    # 解除车辆与该地图的关联
    for link in session.exec(select(CarMapLink).where(CarMapLink.map_id == map_id)).all():
        session.delete(link)
    # 解除账户与该地图的关联
    for link in session.exec(select(UserMapLink).where(UserMapLink.map_id == map_id)).all():
        session.delete(link)
    # 其他地图若把本图当作兜底点云图，置空
    for other in session.exec(select(Map).where(Map.fallback_map_id == map_id)).all():
        other.fallback_map_id = None
        session.add(other)
    # 删除数据库前，清理磁盘文件
    if map_obj.file_path and os.path.exists(map_obj.file_path):
        try:
            os.remove(map_obj.file_path)
        except Exception as e:
            print(f"清理文件失败: {e}")
    
    session.delete(map_obj)
    session.commit()
    return resp_200(msg="地图已删除")