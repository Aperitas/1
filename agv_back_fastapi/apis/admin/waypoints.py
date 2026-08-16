from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from db.session import get_session
from models.waypoint import Waypoint
from schemas.path import WaypointCreate, WaypointUpdate
from utils.resp_code import resp_200, resp_400, resp_500
from core.security import get_current_user
from models.user import Users

router = APIRouter(prefix="/admin/waypoints", tags=["路径点管理"])

@router.post("/", summary="新增路径点")
async def create_waypoint(
        data: WaypointCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
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

@router.get("/", summary="获取所有路径点")
async def list_waypoints(
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    wps = session.exec(select(Waypoint)).all()
    return resp_200(data=[w.dict() for w in wps])

@router.get("/{wp_id}", summary="获取单个路径点详情")
async def get_waypoint(
        wp_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    wp = session.get(Waypoint, wp_id)
    if not wp:
        return resp_400(msg="路径点不存在")
    return resp_200(data=wp.dict())

@router.put("/{wp_id}", summary="修改路径点信息")
async def update_waypoint(
        wp_id: int,
        data: WaypointUpdate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    wp = session.get(Waypoint, wp_id)
    if not wp:
        return resp_400(msg="路径点不存在")
    for key, value in data.dict(exclude_unset=True).items():
        setattr(wp, key, value)
    session.add(wp)
    session.commit()
    session.refresh(wp)
    return resp_200(data=wp.dict(), msg="更新成功")

@router.delete("/{wp_id}", summary="删除路径点")
async def delete_waypoint(
        wp_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    wp = session.get(Waypoint, wp_id)
    if not wp:
        return resp_400(msg="路径点不存在")
    # TODO: 检查是否被路线引用
    session.delete(wp)
    session.commit()
    return resp_200(msg="路径点已删除")