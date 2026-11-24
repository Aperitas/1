from fastapi import APIRouter, Depends, Body, Path as ApiPath
from sqlmodel import Session, select
from db.session import get_session
from models.path import Path
from models.map import Map
from models.car.map_link import CarMapLink
from apis.access import visible_map_ids
from schemas.path import PathCreate, PathUpdate, PathOut
from utils.resp_code import resp_200, resp_400, resp_500
from utils.patch import clean_update
from core.security import get_current_user
from models.user import Users
from typing import Optional
from fastapi import Query
from typing import List, Dict, Any
import json
router = APIRouter(prefix="/admin/paths", tags=["路线管理"])


def _find_temp_path(session: Session, car_id: int, map_id: int, exclude_path_id: Optional[int] = None):
    """查找同车同图的临时路径（可排除自身）"""
    query = select(Path).where(Path.is_temp == True, Path.car_id == car_id, Path.map_id == map_id)
    if exclude_path_id is not None:
        query = query.where(Path.id != exclude_path_id)
    return session.exec(query).first()


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
    node_chain 示例：[{"type":"site","id":1}, {"type":"waypoint","id":3}]
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    # 路线必须归属一张已存在的地图（并自动继承地图类型）
    map_obj = session.get(Map, data.map_id)
    if map_obj is None:
        return resp_400(msg="地图不存在")

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
                out_data = existing.dict()
                out_data["node_chain"] = json.loads(out_data["node_chain"])
                return resp_200(data=out_data, msg="该车辆在此地图已有临时路径，已自动覆盖")
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
        # 返回时把 node_chain 转回 Python 对象
        out_data = path.dict()
        out_data["node_chain"] = json.loads(out_data["node_chain"])
        return resp_200(data=out_data, msg="路线保存成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"保存失败：{str(e)}")

@router.get("/", summary="获取所有路线（可筛选类型、小车或地图）")
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
        d = p.dict()
        d["node_chain"] = json.loads(d["node_chain"])
        result.append(d)
    return resp_200(data=result)

@router.get("/{path_id}", summary="获取单条路线详情（含完整节点坐标）")
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
    out = path.dict()
    out["node_chain"] = json.loads(out["node_chain"])
    return resp_200(data=out)

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
    out = path.dict()
    out["node_chain"] = json.loads(out["node_chain"])
    return resp_200(data=out, msg="路线更新成功")

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