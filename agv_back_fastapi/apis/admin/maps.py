from fastapi import APIRouter, Depends, Query, File, UploadFile, Form
from sqlmodel import Session, select
from db.session import get_session
from models.map import Map
from models.site import Site
from models.waypoint import Waypoint
from models.path import Path
from schemas.map import MapCreate, MapUpdate, MapOut
from utils.resp_code import resp_200, resp_400, resp_500
from core.security import get_current_user
from models.user import Users
from typing import List, Optional
import os
import shutil
from datetime import datetime

router = APIRouter(prefix="/admin/maps", tags=["地图管理"])

# 地图文件存储目录
MAP_UPLOAD_DIR = "static/maps"
os.makedirs(MAP_UPLOAD_DIR, exist_ok=True)


@router.post("/", summary="新增地图")
async def create_map(
        data: MapCreate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    try:
        new_map = Map(**data.dict())
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
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
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
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    maps = session.exec(select(Map)).all()
    result = []
    for m in maps:
        d = m.dict()
        d["file_url"] = f"/static/maps/{os.path.basename(m.file_path)}" if m.file_path else None
        result.append(d)
    return resp_200(data=result)


@router.get("/{map_id}", summary="获取单个地图详情")
async def get_map(
        map_id: int,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    d = map_obj.dict()
    d["file_url"] = f"/static/maps/{os.path.basename(map_obj.file_path)}" if map_obj.file_path else None
    return resp_200(data=d)


@router.put("/{map_id}", summary="修改地图信息")
async def update_map(
        map_id: int,
        data: MapUpdate,
        session: Session = Depends(get_session),
        user: Users = Depends(get_current_user)
):
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    for key, value in data.dict(exclude_unset=True).items():
        setattr(map_obj, key, value)
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
    if not user.isAdmin:
        return resp_400(msg="仅管理员可操作")
    map_obj = session.get(Map, map_id)
    if not map_obj:
        return resp_400(msg="地图不存在")
    sites = session.exec(select(Site).where(Site.map_id == map_id)).first()
    waypoints = session.exec(select(Waypoint).where(Waypoint.map_id == map_id)).first()
    paths = session.exec(select(Path).where(Path.map_id == map_id)).first()
    if sites or waypoints or paths:
        return resp_400(msg="该地图下存在站点、路径点或路线，无法删除")
    session.delete(map_obj)
    session.commit()
    return resp_200(msg="地图已删除")