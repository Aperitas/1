from fastapi import APIRouter, Depends, Body, Path as ApiPath
from sqlmodel import Session, select
from db.session import get_session
import os

from models.path import Path
from models.site import Site
from models.waypoint import Waypoint
from utils.coords import convert as convert_coords, has_bounds as map_has_bounds, has_grid as map_has_grid
from models.map import Map
from models.car.map_link import CarMapLink
from apis.access import visible_map_ids
from schemas.path import PathCreate, PathUpdate, PathOut
from schemas.resp import ApiResponse
from utils.resp_code import resp_200, resp_400, resp_500
from utils.patch import clean_update
from core.security import get_current_user
from models.user import Users
from typing import Optional
from fastapi import Query
from typing import List, Dict, Any
import json
router = APIRouter(prefix="/admin/paths", tags=["路线管理"])

def _map_brief(session: Session, map_id):
    """路径返回里内嵌的地图信息（含 bounds / 文件地址 / 栅格映射）"""
    if map_id is None:
        return None
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return None

    def _url(path):
        return "/static/maps/%s" % os.path.basename(path) if path else None

    bounds = None
    if None not in (map_obj.lon_min, map_obj.lat_min, map_obj.lon_max, map_obj.lat_max):
        bounds = {
            "left_top": {"lon": map_obj.lon_min, "lat": map_obj.lat_max},
            "right_bottom": {"lon": map_obj.lon_max, "lat": map_obj.lat_min},
        }
    return {
        "id": map_obj.id, "name": map_obj.name, "map_type": map_obj.map_type,
        "center_lon": map_obj.center_lon, "center_lat": map_obj.center_lat, "zoom": map_obj.zoom,
        "bounds": bounds,
        "grid_file_url": _url(map_obj.grid_file_path),
        "pointcloud_file_url": _url(map_obj.pointcloud_file_path),
        "grid_resolution": map_obj.grid_resolution,
        "grid_origin_x": map_obj.grid_origin_x, "grid_origin_y": map_obj.grid_origin_y,
        "grid_width": map_obj.grid_width, "grid_height": map_obj.grid_height,
    }


def _node_lonlat(session: Session, node: dict, cache: dict):
    """解析节点的经纬度（site / waypoint）"""
    ntype = (node.get("type") or "").lower()
    nid = node.get("id")
    if nid is None:
        return None, None
    key = (ntype, nid)
    if key in cache:
        return cache[key]
    obj = None
    if ntype == "site":
        obj = session.get(Site, nid)
    elif ntype == "waypoint":
        obj = session.get(Waypoint, nid)
    result = (getattr(obj, "lon", None), getattr(obj, "lat", None))
    cache[key] = result
    return result


def _path_payload(session: Session, path: Path) -> dict:
    """路线标准输出：node_chain 回填 loc(经纬度)/pc(点云)，并内嵌 map 信息"""
    data = path.dict()
    try:
        nodes = json.loads(data.get("node_chain") or "[]")
    except Exception:
        nodes = []
    map_obj = session.get(Map, path.map_id) if path.map_id is not None else None
    can_grid = bool(map_obj is not None and map_has_grid(map_obj))
    cache = {}
    enriched = []
    for node in nodes:
        if not isinstance(node, dict):
            enriched.append(node)
            continue
        item = dict(node)
        if (node.get("type") or "").lower() == "point":
            px_, py_ = node.get("x"), node.get("y")
            conv = convert_coords(map_obj, x=px_, y=py_) if (can_grid and px_ is not None and py_ is not None) else {}
            item["loc"] = None if conv.get("lon") is None else {"lon": conv["lon"], "lat": conv["lat"]}
            item["pc"] = None if px_ is None or py_ is None else {
                "x": px_, "y": py_, "px": conv.get("px"), "py": conv.get("py")}
            enriched.append(item)
            continue
        lon, lat = _node_lonlat(session, node, cache)
        item["loc"] = None if lon is None or lat is None else {"lon": lon, "lat": lat}
        item["pc"] = None
        if can_grid and lon is not None and lat is not None:
            conv = convert_coords(map_obj, lon=lon, lat=lat)
            item["pc"] = {"x": conv["x"], "y": conv["y"], "px": conv["px"], "py": conv["py"]}
        enriched.append(item)
    data["node_chain"] = enriched
    data["map"] = _map_brief(session, path.map_id)
    return data


def resolve_path_points(session: Session, path: Path, frame: str) -> dict:
    """按 frame 解析路线节点坐标，供 /points 接口与车端使用"""
    map_obj = session.get(Map, path.map_id) if path.map_id is not None else None
    can_grid = bool(map_obj is not None and map_has_grid(map_obj))
    can_geo = bool(can_grid and map_has_bounds(map_obj))
    cache = {}
    try:
        nodes = json.loads(path.node_chain or "[]")
    except Exception:
        nodes = []
    points = []
    missing = 0
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        if (node.get("type") or "").lower() == "point":
            px_, py_ = node.get("x"), node.get("y")
            conv_p = convert_coords(map_obj, x=px_, y=py_) if (can_grid and px_ is not None and py_ is not None) else {}
            item_p = {
                "index": idx, "type": "point", "id": None, "name": None,
                "stop_mode": None, "dwell_time": None,
                "lon": conv_p.get("lon"), "lat": conv_p.get("lat"),
                "px": conv_p.get("px"), "py": conv_p.get("py"),
                "x": px_, "y": py_,
            }
            if frame == "pc" and (px_ is None or py_ is None):
                missing += 1
            if frame == "grid" and (item_p["px"] is None or item_p["py"] is None):
                missing += 1
            if frame == "lonlat" and (item_p["lon"] is None or item_p["lat"] is None):
                missing += 1
            points.append(item_p)
            continue
        lon, lat = _node_lonlat(session, node, cache)
        conv = convert_coords(map_obj, lon=lon, lat=lat) if (can_geo and lon is not None and lat is not None) else {}
        item = {
            "index": idx,
            "type": node.get("type"),
            "id": node.get("id"),
            "name": None,
            "stop_mode": None,
            "dwell_time": None,
            "lon": lon, "lat": lat,
            "px": conv.get("px"), "py": conv.get("py"),
            "x": conv.get("x"), "y": conv.get("y"),
        }
        if (node.get("type") or "").lower() == "site":
            site = session.get(Site, node.get("id"))
            if site is not None:
                item["name"] = site.name
                item["stop_mode"] = site.stop_mode
                item["dwell_time"] = site.dwell_time
        elif (node.get("type") or "").lower() == "waypoint":
            wp = session.get(Waypoint, node.get("id"))
            if wp is not None:
                item["name"] = wp.name
        if frame == "pc" and (item["x"] is None or item["y"] is None):
            missing += 1
        if frame == "grid" and (item["px"] is None or item["py"] is None):
            missing += 1
        if frame == "lonlat" and (item["lon"] is None or item["lat"] is None):
            missing += 1
        points.append(item)
    return {
        "path_id": path.id, "name": path.name, "frame": frame,
        "map_id": path.map_id, "map_type": path.map_type,
        "has_grid": can_grid, "has_bounds": can_geo,
        "missing": missing, "points": points,
    }




def _find_temp_path(session: Session, car_id: int, map_id: int, exclude_path_id: Optional[int] = None):
    """查找同车同图的临时路径（可排除自身）"""
    query = select(Path).where(Path.is_temp == True, Path.car_id == car_id, Path.map_id == map_id)
    if exclude_path_id is not None:
        query = query.where(Path.id != exclude_path_id)
    return session.exec(query).first()


def _validate_node_chain(nodes) -> Optional[str]:
    """校验 node_chain：支持 site / waypoint / point 三种节点"""
    if not isinstance(nodes, list):
        return "node_chain 必须是数组"
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            return "node_chain[%d] 必须是对象" % i
        ntype = (node.get("type") or "").lower()
        if ntype in ("site", "waypoint"):
            if node.get("id") is None:
                return "node_chain[%d] 缺少 id" % i
        elif ntype == "point":
            if node.get("x") is None or node.get("y") is None:
                return "node_chain[%d] 是 point 节点时必须提供点云坐标 x / y（米）" % i
        else:
            return "node_chain[%d] 的 type 只能是 site / waypoint / point" % i
    return None


def _validate_temp_path(session: Session, car_id: Optional[int], map_id: int,
                        exclude_path_id: Optional[int] = None) -> Optional[str]:
    """临时路径规则：必须指定车辆、车辆需关联该地图、每车每图仅一条"""
    if car_id is None:
        return "临时路径必须指定车辆"
    link = session.exec(select(CarMapLink).where(
        CarMapLink.car_id == car_id, CarMapLink.map_id == map_id)).first()
    if link is None:
        return "该车辆未关联此地图"
    if _find_temp_path(session, car_id, map_id, exclude_path_id) is not None:
        return "该车辆在此地图已存在临时路径"
    return None

@router.post("/", summary="保存路线（含节点序列和类型）")
async def create_path(
        data: PathCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """
    前端将规划好的路线（含有序节点列表）保存到数据库。
    node_chain 支持三种节点：
    - {"type":"site","id":1}              站点（有停靠语义：stop_mode / dwell_time）
    - {"type":"waypoint","id":3}          路径点
    - {"type":"point","x":3.2,"y":-7.5}   纯几何点：**点云米制坐标**，不停靠（贝塞尔控制点等）
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    # 路线必须归属一张已存在的地图（并自动继承地图类型）
    map_obj = session.get(Map, data.map_id)
    if map_obj is None:
        return resp_400(msg="地图不存在")
    error = _validate_node_chain(data.node_chain)
    if error:
        return resp_400(msg=error)

    # 临时路径：每车每图仅一条，重复则自动覆盖
    if data.is_temp:
        error = _validate_temp_path(session, data.car_id, data.map_id)
        if error is not None:
            if error == "该车辆在此地图已存在临时路径":
                existing = _find_temp_path(session, data.car_id, data.map_id)
                try:
                    existing.name = data.name
                    existing.path_type = data.path_type
                    existing.node_chain = json.dumps(data.node_chain)
                    existing.map_type = map_obj.map_type
                    session.add(existing)
                    session.commit()
                    session.refresh(existing)
                except Exception as e:
                    session.rollback()
                    return resp_500(msg=f"保存失败：{str(e)}")
                return resp_200(data=_path_payload(session, existing), msg="该车辆在此地图已有临时路径，已自动覆盖")
            return resp_400(msg=error)

    try:
        # 将 node_chain 转为 JSON 字符串存储
        path = Path(
            name=data.name,
            path_type=data.path_type,
            car_id=data.car_id,
            map_id=data.map_id,
            map_type=map_obj.map_type,
            is_temp=data.is_temp,
            node_chain=json.dumps(data.node_chain)   # 记得 import json
        )
        session.add(path)
        session.commit()
        session.refresh(path)
        return resp_200(data=_path_payload(session, path), msg="路线保存成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"保存失败：{str(e)}")

@router.get("/", summary="获取所有路线（可筛选类型、小车或地图）", response_model=ApiResponse[List[PathOut]])
async def list_paths(
        path_type: Optional[str] = Query(None, description="路线类型: 吸附道路/贝塞尔曲线/折线"),
        car_id: Optional[int] = Query(None, description="关联小车ID"),
        map_id: Optional[int] = Query(None, description="按地图ID筛选"),
        map_type: Optional[str] = Query(None, description="按地图类型筛选：tianditu=天地图 / local=本地地图"),
        is_temp: Optional[bool] = Query(None, description="是否临时路径"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """获取路线列表，可按路线类型、所属小车、所属地图、地图类型、是否临时路径筛选。"""
    visible = visible_map_ids(session, user)
    if map_id is not None and visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    query = select(Path)
    if visible is not None:
        query = query.where(Path.map_id.in_(visible))
    if path_type:
        query = query.where(Path.path_type == path_type)
    if car_id:
        query = query.where(Path.car_id == car_id)
    if map_id is not None:
        query = query.where(Path.map_id == map_id)
    if map_type is not None:
        query = query.where(Path.map_type == map_type)
    if is_temp is not None:
        query = query.where(Path.is_temp == is_temp)
    paths = session.exec(query).all()
    result = []
    for p in paths:
        result.append(_path_payload(session, p))
    return resp_200(data=result)

@router.get("/{path_id}", summary="获取单条路线详情（含完整节点坐标）", response_model=ApiResponse[PathOut])
async def get_path(
        path_id: int = ApiPath(..., description="路线ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """按 id 获取单条路线详情，node_chain 已转成对象返回。"""
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and path.map_id not in visible:
        return resp_400(msg="无权访问该地图的路线")
    return resp_200(data=_path_payload(session, path))

@router.get("/{path_id}/points", summary="把路线节点解析成坐标（经纬度 / 栅格像素 / 点云米）")
async def get_path_points(
        path_id: int = ApiPath(..., description="路线ID"),
        frame: str = Query("lonlat", description="坐标系：lonlat=经纬度 / grid=栅格像素(px,py) / pc=点云米(x,y，车端导航用)"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """按 node_chain 顺序返回每个节点的坐标。

    - frame=lonlat：lon / lat（节点自带经纬度即可）
    - frame=grid：px / py（需要地图已完成点云处理，且有栅格映射）
    - frame=pc：x / y（点云米制坐标；地图做过点云处理 + 填了 bounds 时，同时返回 lon/lat）
    """
    if frame not in ("lonlat", "grid", "pc"):
        return resp_400(msg="frame 只能是 lonlat / grid / pc")
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and path.map_id not in visible:
        return resp_400(msg="无权访问该地图的路线")
    data = resolve_path_points(session, path, frame)
    if frame in ("grid", "pc") and not data["has_grid"]:
        return resp_400(msg="该地图还没有栅格↔点云映射，请先调用 POST /admin/maps/{map_id}/pointcloud/process")
    return resp_200(data=data)


@router.put("/{path_id}", summary="修改路线（名称、类型、节点序列等）")
async def update_path(
        path_id: int = ApiPath(..., description="路线ID"),
        data: PathUpdate = Body(..., description="要修改的字段（只传需要改的；不传 / 传 null / 传空串均表示保持原值），car_id 传 null 表示解除专属"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员修改路线（名称、类型、节点序列等），node_chain 以 JSON 字符串入库。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")
    update_data = clean_update(data, allow_null={"car_id"})
    if "node_chain" in update_data:
        error = _validate_node_chain(update_data["node_chain"])
        if error:
            return resp_400(msg=error)
        update_data["node_chain"] = json.dumps(update_data["node_chain"])
    for key, value in update_data.items():
        setattr(path, key, value)

    # 校验归属地图，并同步地图类型
    map_obj = session.get(Map, path.map_id) if path.map_id is not None else None
    if map_obj is None:
        session.rollback()
        return resp_400(msg="地图不存在")
    path.map_type = map_obj.map_type
    # 校验临时路径规则（排除自身）
    if path.is_temp:
        error = _validate_temp_path(session, path.car_id, path.map_id, exclude_path_id=path.id)
        if error is not None:
            session.rollback()
            return resp_400(msg=error)

    session.add(path)
    session.commit()
    session.refresh(path)
    return resp_200(data=_path_payload(session, path), msg="路线更新成功")

@router.delete("/{path_id}", summary="删除路线")
async def delete_path(
        path_id: int = ApiPath(..., description="路线ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员删除路线。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")
    session.delete(path)
    session.commit()
    return resp_200(msg="路线已删除")