from fastapi import APIRouter, Depends, Query, Body, File, UploadFile, Form, Path as ApiPath
from sqlmodel import Session, select, update
from db.session import get_session
from models.map import Map, MapType
from models.site import Site
from models.waypoint import Waypoint
from models.path import Path
from models.car.car import Cars
from models.car.map_link import CarMapLink
from models.user.map_link import UserMapLink
from apis.access import visible_map_ids
from apis.views import car_payload
from core.logger import logger
from schemas.map import MapCreate, MapUpdate, MapOut
from utils.resp_code import resp_200, resp_400, resp_500
from utils.patch import clean_update
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


def _apply_corner_fields(payload: dict) -> dict:
    """支持用 左上/右下 角点写法（left_top_*/right_bottom_*）代替 lon_min/lat_min/lon_max/lat_max"""
    left_top_lon = payload.pop("left_top_lon", None)
    left_top_lat = payload.pop("left_top_lat", None)
    right_bottom_lon = payload.pop("right_bottom_lon", None)
    right_bottom_lat = payload.pop("right_bottom_lat", None)
    if left_top_lon is not None:
        payload["lon_min"] = left_top_lon
    if left_top_lat is not None:
        payload["lat_max"] = left_top_lat
    if right_bottom_lon is not None:
        payload["lon_max"] = right_bottom_lon
    if right_bottom_lat is not None:
        payload["lat_min"] = right_bottom_lat
    return payload


def _file_url(path: Optional[str]) -> Optional[str]:
    """把磁盘路径转换成 /static 访问地址"""
    return f"/static/maps/{os.path.basename(path)}" if path else None


def _bounds_payload(map_obj: Map) -> Optional[dict]:
    """左上 / 右下角点（四个值齐全时返回）"""
    if None in (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max):
        return None
    return {
        "left_top": {"lon": map_obj.lon_min, "lat": map_obj.lat_max},
        "right_bottom": {"lon": map_obj.lon_max, "lat": map_obj.lat_min},
    }


def _map_payload(map_obj: Map) -> dict:
    """地图标准输出：含点云/栅格两个文件地址与 bounds 角点"""
    data = map_obj.dict()
    data["pointcloud_file_url"] = _file_url(map_obj.pointcloud_file_path)
    data["grid_file_url"] = _file_url(map_obj.grid_file_path)
    data["file_url"] = data["pointcloud_file_url"] or data["grid_file_url"]
    data["bounds"] = _bounds_payload(map_obj)
    return data


def _validate_map_object(map_obj: Map, session: Session) -> Optional[str]:
    """校验地图类型、区域角点、兜底地图；区域坐标"传了才校验"，返回错误信息或 None"""
    if map_obj.map_type not in VALID_MAP_TYPES:
        return f"map_type 只能是 {sorted(VALID_MAP_TYPES)}"
    bounds = (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max)
    provided = [value for value in bounds if value is not None]
    if provided:
        if len(provided) != 4:
            return "区域坐标需同时提供四个值：lon_min/lat_min/lon_max/lat_max（或 left_top/right_bottom）"
        if map_obj.lon_min >= map_obj.lon_max or map_obj.lat_min >= map_obj.lat_max:
            return "区域坐标非法：需满足 左<右（lon_min<lon_max）且 下<上（lat_min<lat_max）"
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
        if fallback.map_type != MapType.LOCAL.value:
            return "兜底地图必须是本地地图(local)"
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
    """管理员新增地图：tianditu=天地图 / local=本地地图（点云+栅格）。
    区域坐标可用 left_top/right_bottom 写法，也可以不传（后续补录）。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    payload = _apply_corner_fields(data.dict())
    try:
        new_map = Map(**payload)
    except Exception as e:
        return resp_400(msg=f"参数错误：{str(e)}")
    error = _validate_map_object(new_map, session)
    if error:
        return resp_400(msg=error)
    try:
        session.add(new_map)
        session.commit()
        session.refresh(new_map)
        return resp_200(data=_map_payload(new_map), msg="地图创建成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"创建失败：{str(e)}")


@router.post("/upload", summary="上传地图文件（点云/栅格）")
async def upload_map_file(
        map_id: int = Form(..., description="要绑定文件的地图ID"),
        kind: str = Form("pointcloud", description="文件类型：pointcloud=点云文件 / grid=栅格文件"),
        file: UploadFile = File(..., description="要上传的文件（.pcd/.ply/.png/.tif/.zip 等）"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """上传或替换地图文件：
    - kind=pointcloud 写入「点云」槽位，kind=grid 写入「栅格」槽位；
    - 同类型重复上传会删除旧磁盘文件后替换；
    - 两个文件都可以不传（字段为 null），后续可随时补传。
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    if kind not in ("pointcloud", "grid"):
        return resp_400(msg="kind 只能是 pointcloud 或 grid")

    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")

    # 保存文件（文件名带类型前缀，避免点云与栅格互相覆盖）
    prefix = "pc" if kind == "pointcloud" else "grid"
    filename = f"map_{map_id}_{prefix}_{file.filename}"
    file_path = os.path.join(MAP_UPLOAD_DIR, filename)

    # 定义异步保存函数，放入线程池执行，避免阻塞主服务
    def save_file():
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    try:
        await run_in_threadpool(save_file)
    except Exception as e:
        return resp_500(msg=f"文件保存失败：{str(e)}")

    # 删除同类型旧文件
    old_path = map_obj.pointcloud_file_path if kind == "pointcloud" else map_obj.grid_file_path
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except Exception as e:
            logger.warning(f"清理旧文件失败: {e}")

    # 更新数据库
    file_type = os.path.splitext(filename)[1].lstrip(".")
    file_size = os.path.getsize(file_path)
    now = datetime.now()
    if kind == "pointcloud":
        map_obj.pointcloud_file_path = file_path
        map_obj.pointcloud_file_type = file_type
        map_obj.pointcloud_file_size = file_size
        map_obj.pointcloud_file_upload_time = now
    else:
        map_obj.grid_file_path = file_path
        map_obj.grid_file_type = file_type
        map_obj.grid_file_size = file_size
        map_obj.grid_file_upload_time = now

    session.add(map_obj)
    session.commit()
    session.refresh(map_obj)

    return resp_200(
        msg=f"{'点云' if kind == 'pointcloud' else '栅格'}文件上传成功",
        data={
            "map_id": map_obj.id,
            "kind": kind,
            "file_type": file_type,
            "file_size": file_size,
            "file_url": _file_url(file_path),
        }
    )


@router.delete("/{map_id}/files/{kind}", summary="删除地图的点云/栅格文件")
async def delete_map_file(
        map_id: int = ApiPath(..., description="地图ID"),
        kind: str = ApiPath(..., description="要删除的文件类型：pointcloud / grid"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_admin)
):
    """单独删除地图的点云或栅格文件，同时清理磁盘文件（另一类文件不受影响）。"""
    if kind not in ("pointcloud", "grid"):
        return resp_400(msg="kind 只能是 pointcloud 或 grid")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")

    old_path = map_obj.pointcloud_file_path if kind == "pointcloud" else map_obj.grid_file_path
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except Exception as e:
            logger.warning(f"清理文件失败: {e}")

    if kind == "pointcloud":
        map_obj.pointcloud_file_path = None
        map_obj.pointcloud_file_type = None
        map_obj.pointcloud_file_size = None
        map_obj.pointcloud_file_upload_time = None
    else:
        map_obj.grid_file_path = None
        map_obj.grid_file_type = None
        map_obj.grid_file_size = None
        map_obj.grid_file_upload_time = None

    session.add(map_obj)
    session.commit()
    return resp_200(msg="文件已删除", data={"map_id": map_id, "kind": kind})


@router.get("/", summary="获取所有地图列表")
async def list_maps(
        map_type: Optional[str] = Query(None, description="按类型筛选：tianditu=天地图 / local=本地地图"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """获取地图列表（按账户可见范围过滤），附带点云/栅格文件地址、bounds 与各类数量。"""
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
        d = _map_payload(m)
        d["car_ids"] = car_ids_by_map.get(m.id, [])
        d["car_count"] = len(d["car_ids"])
        d["user_ids"] = user_ids_by_map.get(m.id, [])
        d["user_count"] = len(d["user_ids"])
        d["path_count"] = path_counts.get(m.id, 0)
        result.append(d)
    return resp_200(data=result)


@router.get("/{map_id}", summary="获取单个地图详情")
async def get_map(
        map_id: int = ApiPath(..., description="地图ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """按 id 获取单个地图详情，附带点云/栅格文件地址、bounds 与关联车辆/账户/路线数量。"""
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    d = _map_payload(map_obj)
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
        map_id: int = ApiPath(..., description="地图ID"),
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

    # 车辆可能属于多张地图：一并带出（非管理员只列出可见地图）
    car_map_ids = {}
    if car_ids:
        for link in session.exec(select(CarMapLink).where(CarMapLink.car_id.in_(car_ids))).all():
            car_map_ids.setdefault(link.car_id, []).append(link.map_id)
    map_names = {m.id: m.name for m in session.exec(select(Map)).all()}
    payload = []
    for car in cars:
        mids = car_map_ids.get(car.id, [])
        if visible is not None:
            mids = [mid for mid in mids if mid in visible]
        payload.append(car_payload(car, mids, map_names))
    return resp_200(data={
        "map_id": map_id,
        "car_ids": car_ids,
        "cars": payload,
    })


@router.get("/{map_id}/paths", summary="获取地图包含的路线")
async def list_map_paths(
        map_id: int = ApiPath(..., description="地图ID"),
        is_temp: Optional[bool] = Query(None, description="是否临时路径：true=只看临时 / false=只看普通 / 不传=全部"),
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
        map_id: int = ApiPath(..., description="地图ID"),
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
        map_id: int = ApiPath(..., description="地图ID"),
        data: MapUpdate = Body(..., description="要修改的字段（只传需要改的；不传 / 传 null / 传空串均表示保持原值），description/fallback_map_id 传 null 表示清空", example={"name": "南科大-1F"}),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员修改地图信息，仅更新传入的字段（会重新校验类型/范围/兜底）。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    old_map_type = map_obj.map_type
    for key, value in _apply_corner_fields(clean_update(data, allow_null={"description", "fallback_map_id"})).items():
        setattr(map_obj, key, value)
    error = _validate_map_object(map_obj, session)
    if error:
        session.rollback()
        return resp_400(msg=error)
    session.add(map_obj)
    session.commit()
    # 地图类型变更时，同步该地图下所有路线的 map_type
    if map_obj.map_type != old_map_type:
        session.execute(update(Path).where(Path.map_id == map_id).values(map_type=map_obj.map_type))
        session.commit()
        logger.info(f"地图 {map_id} 类型变更为 {map_obj.map_type}，已同步其下路线")
    session.refresh(map_obj)
    return resp_200(data=_map_payload(map_obj), msg="地图更新成功")


@router.delete("/{map_id}", summary="删除地图")
async def delete_map(
        map_id: int = ApiPath(..., description="地图ID"),
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
    # 删除数据库前，清理点云与栅格两个磁盘文件
    for path in (map_obj.pointcloud_file_path, map_obj.grid_file_path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logger.warning(f"清理文件失败: {e}")
    
    session.delete(map_obj)
    session.commit()
    return resp_200(msg="地图已删除")