from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from db.session import get_session
from models.site import Site
from schemas.path import SiteCreate, SiteUpdate, SiteOut
from utils.resp_code import resp_200, resp_400, resp_500
from core.auth import get_current_user
from models.user import Users
from typing import List

router = APIRouter(prefix="/admin/sites", tags=["站点管理（新增）"])

@router.post("/", summary="新增站点")
async def create_site(
        data: SiteCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """
    前端在地图上点击后，保存一个站点（可设置停靠时间）。
    """
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    try:
        site = Site(**data.dict())
        session.add(site)
        session.commit()
        session.refresh(site)
        return resp_200(data=site.dict(), msg="站点创建成功")
    except Exception as e:
        session.rollback()
        return resp_500(msg=f"创建失败：{str(e)}")

@router.get("/", summary="获取所有站点列表")
async def list_sites(
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    """
    返回所有站点，支持后续分页。
    """
    sites = session.exec(select(Site)).all()
    return resp_200(data=[s.dict() for s in sites])

@router.get("/{site_id}", summary="获取单个站点详情")
async def get_site(
        site_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    site = session.get(Site, site_id)
    if not site:
        return resp_400(msg="站点不存在")
    return resp_200(data=site.dict())

@router.put("/{site_id}", summary="修改站点信息")
async def update_site(
        site_id: int,
        data: SiteUpdate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    site = session.get(Site, site_id)
    if not site:
        return resp_400(msg="站点不存在")
    for key, value in data.dict(exclude_unset=True).items():
        setattr(site, key, value)
    session.add(site)
    session.commit()
    session.refresh(site)
    return resp_200(data=site.dict(), msg="更新成功")

@router.delete("/{site_id}", summary="删除站点")
async def delete_site(
        site_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    site = session.get(Site, site_id)
    if not site:
        return resp_400(msg="站点不存在")
    # TODO: 检查是否被路线引用，若引用则禁止删除
    session.delete(site)
    session.commit()
    return resp_200(msg="站点已删除")