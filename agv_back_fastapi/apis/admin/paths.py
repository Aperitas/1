from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from db.session import get_session
from models.path import Path
from schemas.path import PathCreate, PathUpdate, PathOut
from utils.resp_code import resp_200, resp_400, resp_500
from core.security import get_current_user
from models.user import Users
from typing import List, Dict, Any
import json
router = APIRouter(prefix="/admin/paths", tags=["路线管理"])

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
    try:
        # 将 node_chain 转为 JSON 字符串存储
        path = Path(
            name=data.name,
            path_type=data.path_type,
            car_id=data.car_id,
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

@router.get("/", summary="获取所有路线（可筛选类型或小车）")
async def list_paths(
        path_type: str = None,
        car_id: int = None,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """
    支持按路线类型或关联小车筛选。
    """
    query = select(Path)
    if path_type:
        query = query.where(Path.path_type == path_type)
    if car_id:
        query = query.where(Path.car_id == car_id)
    paths = session.exec(query).all()
    result = []
    for p in paths:
        d = p.dict()
        d["node_chain"] = json.loads(d["node_chain"])
        result.append(d)
    return resp_200(data=result)

@router.get("/{path_id}", summary="获取单条路线详情（含完整节点坐标）")
async def get_path(
        path_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")
    out = path.dict()
    out["node_chain"] = json.loads(out["node_chain"])
    return resp_200(data=out)

@router.put("/{path_id}", summary="修改路线（名称、类型、节点序列等）")
async def update_path(
        path_id: int,
        data: PathUpdate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")
    update_data = data.dict(exclude_unset=True)
    if "node_chain" in update_data:
        update_data["node_chain"] = json.dumps(update_data["node_chain"])
    for key, value in update_data.items():
        setattr(path, key, value)
    session.add(path)
    session.commit()
    session.refresh(path)
    out = path.dict()
    out["node_chain"] = json.loads(out["node_chain"])
    return resp_200(data=out, msg="路线更新成功")

@router.delete("/{path_id}", summary="删除路线")
async def delete_path(
        path_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    path = session.get(Path, path_id)
    if not path:
        return resp_400(msg="路线不存在")
    session.delete(path)
    session.commit()
    return resp_200(msg="路线已删除")