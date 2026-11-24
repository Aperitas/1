from fastapi import APIRouter, Depends, HTTPException, Body, Path
from sqlmodel import Session, select
from db.session import get_session
from models.site import Site, StopMode
from apis.access import visible_map_ids
from schemas.path import SiteCreate, SiteUpdate, SiteOut
from schemas.resp import ApiResponse
from utils.resp_code import resp_200, resp_400, resp_500
from utils.patch import clean_update
from core.security import get_current_user
from models.user import Users
from typing import List
from typing import Optional
from fastapi import Query

router = APIRouter(prefix="/admin/sites", tags=["站点管理"])

VALID_STOP_MODES = {StopMode.TIMED.value, StopMode.WAIT_COMMAND.value}


def _validate_site(data) -> Optional[str]:
    """校验停靠模式与停靠时间，返回错误信息或 None"""
    stop_mode = getattr(data, "stop_mode", None)
    if stop_mode is not None and stop_mode not in VALID_STOP_MODES:
        return f"stop_mode 只能是 {sorted(VALID_STOP_MODES)}"
    dwell_time = getattr(data, "dwell_time", None)
    if dwell_time is not None and dwell_time < 0:
        return "dwell_time 不能为负数"
    return None


@router.post("/", summary="新增站点")
async def create_site(
        data: SiteCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """
    前端在地图上点击后，保存一个站点（可设置停靠模式与停靠时间）。
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    error = _validate_site(data)
    if error:
        return resp_400(msg=error)
    try :
        site = Site(**data.dict())
        session.add(site)
        session.commit()
        session.refresh(site)
        return resp_200(data=site.dict(), msg="站点创建成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"创建失败：{str(e)}")

@router.get("/", summary="获取所有站点列表", response_model=ApiResponse[List[SiteOut]])
async def list_sites(
        map_id: Optional[int] = Query(None, description="按地图ID筛选"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """获取站点列表，可按 map_id 过滤。"""
    visible = visible_map_ids(session, user)
    if map_id is not None and visible is not None and map_id not in visible:
        return resp_400(msg="无权访问该地图")
    query = select(Site)
    if visible is not None:
        query = query.where(Site.map_id.in_(visible))
    if map_id is not None:
        query = query.where(Site.map_id == map_id)
    sites = session.exec(query).all()
    return resp_200(data=[s.dict() for s in sites])

@router.get("/{site_id}", summary="获取单个站点详情", response_model=ApiResponse[SiteOut])
async def get_site(
        site_id: int = Path(..., description="站点ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """按 id 获取单个站点详情。"""
    site = session.get(Site, site_id)
    if not site:
        return resp_400(msg="站点不存在")
    visible = visible_map_ids(session, user)
    if visible is not None and site.map_id not in visible:
        return resp_400(msg="无权访问该地图的站点")
    return resp_200(data=site.dict())

@router.put("/{site_id}", summary="修改站点信息")
async def update_site(
        site_id: int = Path(..., description="站点ID"),
        data: SiteUpdate = Body(..., description="要修改的字段（只传需要改的；不传 / 传 null / 传空串均表示保持原值），description 传 null 表示清空"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员修改站点信息，仅更新传入的字段。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    error = _validate_site(data)
    if error:
        return resp_400(msg=error)
    site = session.get(Site, site_id)
    if not site:
        return resp_400(msg="站点不存在")
    for key, value in clean_update(data, allow_null={"description"}).items():
        setattr(site, key, value)
    session.add(site)
    session.commit()
    session.refresh(site)
    return resp_200(data=site.dict(), msg="更新成功")

@router.delete("/{site_id}", summary="删除站点")
async def delete_site(
        site_id: int = Path(..., description="站点ID"),
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """管理员删除站点。"""
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    site = session.get(Site, site_id)
    if not site:
        return resp_400(msg="站点不存在")
    # TODO: 检查是否被路线引用，若引用则禁止删除
    session.delete(site)
    session.commit()
    return resp_200(msg="站点已删除")