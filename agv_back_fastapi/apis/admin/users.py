"""
author:dlr123
date:2022年06月28日
"""
import datetime

from fastapi import APIRouter,Body,Depends
from fastapi import Path
from sqlmodel import select, delete
from apis.access import normalize_ids
from schemas.user import AdminResetPasswordIn, CreateUser, UserMapSetIn, UserUpdate
from core.logger import logger
from core.security import get_current_admin, get_password_hash
from crud.user import create_user, get_user_conflict
from db.session import get_session
from models.map import Map
from models.user.map_link import UserMapLink
from models.user.users import Users, UserRole
from utils.resp_code import resp_200,resp_500,resp_400
from utils.patch import clean_update

user_api = APIRouter(prefix='/user')


@user_api.get('/getuserlist', summary="获取用户列表（不含超级管理员）")
async def get_user_list(user: Users = Depends(get_current_admin)):
    """仅管理员可调用，返回除 id=1（超级管理员）外所有用户的 id、用户名与角色。"""
    with get_session() as session:
        try:
            all_user:list[Users] = session.query(Users).filter(Users.id != 1).all()
            links = session.exec(select(UserMapLink)).all()
            user_maps = {}
            for link in links:
                user_maps.setdefault(link.user_id, []).append(link.map_id)
            res_data = [{'id':u.id,'name':u.name,'nickname':u.nickname,'avatar':u.avatar,
                         'role':u.effective_role,'map_ids':user_maps.get(u.id,[])} for u in all_user]
            return resp_200(data=res_data,msg='获取用户名列表成功')
        except Exception as e:
            logger.error(f'获取用户名列表失败错误,因为：{e}')
            return resp_500(msg="数据库操作错误")


@user_api.post('/create', summary="管理员创建新用户")
async def create_new_user(userInfo: CreateUser,login_user: Users = Depends(get_current_admin)):
    """仅管理员可创建用户；role 决定角色(admin/dispatcher/guest)，isAdmin 由 role 自动同步。"""
    conflict = get_user_conflict(name=userInfo.name)
    if conflict != None:
        return resp_400(msg=conflict)
    try:
        userInfo.hashed_password = get_password_hash(userInfo.password)
        userInfo.create_time = datetime.datetime.now()
        result = create_user(userInfo)
    except ValueError as e:
        return resp_400(msg=str(e))
    except Exception as e:
        logger.error(f'创建用户失败！-- {e}')
        return resp_500(msg='创建用户失败！')
    logger.info(f"管理员 {login_user.name} 创建了用户 {result['name']}（角色: {result['role']}）")
    return resp_200(data=result,msg="创建用户成功！")

# ------------------新增：编辑用户信息接口 PUT ------------------
@user_api.put("/{user_id}", summary="管理员修改指定用户信息")
async def update_target_user(
        update_data: UserUpdate = Body(..., description="要修改的字段（只传需要改的；不传 / 传 null / 传空串均表示保持原值），nickname/avatar/map_id 传 null 表示清空", example={"nickname": "小李", "role": "dispatcher"}),
        user_id: int = Path(..., description="待修改用户ID"),
        login_user: Users = Depends(get_current_admin)
):
    """管理员修改指定用户信息，仅更新前端传入的字段（可修改角色）。"""
    with get_session() as session:
        try:
            # 查询目标用户
            target_user = session.query(Users).filter(Users.id == user_id).first()
            if not target_user:
                return resp_400(msg="目标用户不存在")

            # 只更新前端真正传入的字段（pydantic v1 用 dict）：null / 空串视为不修改
            update_dict = clean_update(update_data, allow_null={"nickname", "avatar", "map_id"})
            # users.nickname 在库里是 NOT NULL：传 null 表示清空昵称，落库用空串
            if "nickname" in update_dict and update_dict["nickname"] is None:
                update_dict["nickname"] = ""
            new_map_ids = update_dict.pop("map_ids", None)

            # 角色与 isAdmin 同步：优先 role；只传 isAdmin 时折算成角色
            new_role = update_dict.pop("role", None)
            new_is_admin = update_dict.pop("isAdmin", None)
            if new_role is not None:
                new_role = new_role.value if isinstance(new_role, UserRole) else new_role
            elif new_is_admin is not None:
                new_role = UserRole.ADMIN.value if new_is_admin else UserRole.GUEST.value
            if new_role is not None:
                if target_user.id == login_user.id and new_role != UserRole.ADMIN.value:
                    return resp_400(msg="不能取消自己的管理员权限")
                target_user.role = new_role
                target_user.isAdmin = (new_role == UserRole.ADMIN.value)

            # 用户名修改需要查重
            if "name" in update_dict:
                conflict = get_user_conflict(name=update_dict.get("name"),
                                             exclude_id=target_user.id)
                if conflict != None:
                    return resp_400(msg=conflict)

            for k, v in update_dict.items():
                setattr(target_user, k, v)

            # 账户负责的地图（多对多，覆盖式）
            if new_map_ids is not None:
                new_map_ids = normalize_ids(new_map_ids)
                existing = set(session.exec(select(Map.id).where(Map.id.in_(new_map_ids))).all()) if new_map_ids else set()
                missing = [m for m in new_map_ids if m not in existing]
                if missing:
                    return resp_400(msg=f"地图不存在: {missing}")
                session.execute(delete(UserMapLink).where(UserMapLink.user_id == target_user.id))
                for map_id in new_map_ids:
                    session.add(UserMapLink(user_id=target_user.id, map_id=map_id))
                if new_map_ids and target_user.map_id not in new_map_ids:
                    target_user.map_id = new_map_ids[0]
                if not new_map_ids:
                    target_user.map_id = None

            session.commit()
            session.refresh(target_user)
            return resp_200(data=target_user, msg="用户信息修改成功")
        except Exception as e:
            logger.error(f"修改用户失败，错误：{e}")
            return resp_500(msg="数据库操作异常，修改失败")

# ------------------新增：删除用户接口 DELETE ------------------
@user_api.delete("/{user_id}", summary="管理员删除指定用户账号")
async def delete_target_user(
        user_id: int = Path(..., description="待删除用户ID"),
        login_user: Users = Depends(get_current_admin)
):
    """管理员删除指定用户账号，禁止删除当前登录的管理员自己。"""
    with get_session() as session:
        try:
            target_user = session.query(Users).filter(Users.id == user_id).first()
            if not target_user:
                return resp_400(msg="目标用户不存在")
            # 限制：不能删除当前登录的管理员自己
            if target_user.id == login_user.id:
                return resp_400(msg="禁止删除当前登录管理员账号")

            session.delete(target_user)
            session.commit()
            return resp_200(msg="用户账号删除完成")
        except Exception as e:
            logger.error(f"删除用户失败，错误：{e}")
            return resp_500(msg="数据库操作异常，删除失败")


# ------------------新增：管理员重置用户密码 PUT ------------------
@user_api.put("/{user_id}/password", summary="管理员重置指定用户密码")
async def reset_target_user_password(
        data: AdminResetPasswordIn,
        user_id: int = Path(..., description="目标用户ID"),
        login_user: Users = Depends(get_current_admin)
):
    """管理员直接重置某个用户的密码（无需旧密码），用于用户忘记密码的场景。"""
    with get_session() as session:
        try:
            target_user = session.query(Users).filter(Users.id == user_id).first()
            if not target_user:
                return resp_400(msg="目标用户不存在")

            target_user.hashed_password = get_password_hash(data.new_password)
            session.add(target_user)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"重置用户密码失败，错误：{e}")
            return resp_500(msg="数据库操作异常，重置失败")

    logger.info(f"管理员 {login_user.name} 重置了用户 {user_id} 的密码")
    return resp_200(msg="密码重置成功")


# ------------------账户-地图（多对多） ------------------
@user_api.get("/{user_id}/maps", summary="获取指定账户负责的地图")
async def get_user_maps(
        user_id: int = Path(..., description="目标用户ID"),
        login_user: Users = Depends(get_current_admin)
):
    """管理员查看某个账户负责（关联）的地图列表。"""
    with get_session() as session:
        target = session.query(Users).filter(Users.id == user_id).first()
        if not target:
            return resp_400(msg="目标用户不存在")
        map_ids = [link.map_id for link in session.exec(
            select(UserMapLink).where(UserMapLink.user_id == user_id)).all()]
        maps = session.exec(select(Map).where(Map.id.in_(map_ids))).all() if map_ids else []
        return resp_200(data={
            "user_id": user_id,
            "map_ids": map_ids,
            "maps": [{"id": m.id, "name": m.name, "map_type": m.map_type} for m in maps],
        })


@user_api.put("/{user_id}/maps", summary="设置指定账户负责的地图")
async def set_user_maps(
        data: UserMapSetIn,
        user_id: int = Path(..., description="目标用户ID"),
        login_user: Users = Depends(get_current_admin)
):
    """覆盖式设置某个账户负责的地图（传空数组表示解除全部关联）。"""
    map_ids = normalize_ids(data.map_ids)
    with get_session() as session:
        target = session.query(Users).filter(Users.id == user_id).first()
        if not target:
            return resp_400(msg="目标用户不存在")
        if map_ids:
            existing = set(session.exec(select(Map.id).where(Map.id.in_(map_ids))).all())
            missing = [m for m in map_ids if m not in existing]
            if missing:
                return resp_400(msg=f"地图不存在: {missing}")
        try:
            session.execute(delete(UserMapLink).where(UserMapLink.user_id == user_id))
            for map_id in map_ids:
                session.add(UserMapLink(user_id=user_id, map_id=map_id))
            if map_ids and target.map_id not in map_ids:
                target.map_id = map_ids[0]
            if not map_ids:
                target.map_id = None
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"设置账户地图失败: {e}")
            return resp_500(msg="设置账户地图失败")
    logger.info(f"管理员 {login_user.name} 设置账户 {user_id} 的地图为 {map_ids}")
    return resp_200(data={"user_id": user_id, "map_ids": map_ids}, msg="设置成功")