from fastapi import APIRouter, Depends, Body, Path
from sqlmodel import Session, select
from db.session import get_session
from models.waypoint import Waypoint
from apis.access import visible_map_ids
from schemas.path import WaypointCreate, WaypointUpdate, WaypointOut
from schemas.resp import ApiResponse
from utils.resp_code import resp_200, resp_400, resp_500
from utils.patch import clean_update
from core.security import get_current_user
from models.user import Users
from typing import Optional, List
from fastapi import Query

router = APIRouter(prefix="/admin/waypoints", tags=["路径点管理"])

@router.post("/", summary="新增路径点")
async def create_waypoint(
        data: WaypointCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员新增路径点（地图上标定的坐标点）。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    try:
        wp = Waypoint(**data.dict())
        session.add(wp)
        session.commit()
        session.refresh(wp)
        return resp_200(data=wp.dict(), msg="路径点创建成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"创建失败：{str(e)}")

@router.get("/", summary="获取所有路径点", response_model=ApiResponse[List[WaypointOut]])
async def list_waypoints(
        map_id: Optional[int] = Query(None, description="按地图ID筛选"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """获取路径点列表，可按 map_id 过滤。"""
    visible = visible_map_ids(session, user)
    if map_id is not None and visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    query = select(Waypoint)
    if visible is not None:
        query = query.where(Waypoint.map_id.in_(visible))
    if map_id is not None:
        query = query.where(Waypoint.map_id == map_id)
    wps = session.exec(query).all()
    return resp_200(data=[w.dict() for w in wps])

@router.get("/{wp_id}", summary="获取单个路径点详情", response_model=ApiResponse[WaypointOut])
async def get_waypoint(
        wp_id: int = Path(..., description="路径点ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """按 id 获取单个路径点详情。"""
    wp = session.get(Waypoint, wp_id)
    if not wp:
        return resp_400(msg="路径点不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and wp.map_id not in visible:
        return resp_400(msg="无权访问该地图的路径点")
    return resp_200(data=wp.dict())

@router.put("/{wp_id}", summary="修改路径点信息")
async def update_waypoint(
        wp_id: int = Path(..., description="路径点ID"),
        data: WaypointUpdate = Body(..., description="要修改的字段（只传需要改的；不传 / 传 null / 传空串均表示保持原值），description 传 null 表示清空"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员修改路径点信息，仅更新传入的字段。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    wp = session.get(Waypoint, wp_id)
    if not wp:
        return resp_400(msg="路径点不存在")
    for key, value in clean_update(data, allow_null={"description"}).items():
        setattr(wp, key, value)
    session.add(wp)
    session.commit()
    session.refresh(wp)
    return resp_200(data=wp.dict(), msg="更新成功")

@router.delete("/{wp_id}", summary="删除路径点")
async def delete_waypoint(
        wp_id: int = Path(..., description="路径点ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员删除路径点。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    wp = session.get(Waypoint, wp_id)
    if not wp:
        return resp_400(msg="路径点不存在")
    # TODO: 检查是否被路线引用
    session.delete(wp)
    session.commit()
    return resp_200(msg="路径点已删除")