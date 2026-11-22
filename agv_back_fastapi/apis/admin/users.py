"""
author:dlr123
date:2022年06月28日
"""
import datetime

from fastapi import APIRouter,Depends
from fastapi import Path
from schemas.user import CreateUser, UserUpdate
from core.logger import logger
from core.security import get_current_admin, get_password_hash
from crud.user import create_user, get_user_conflict
from db.session import get_session
from models.user.users import Users, UserRole
from utils.resp_code import resp_200,resp_500,resp_400

user_api = APIRouter(prefix='/user')


@user_api.get('/getuserlist', summary="获取用户列表（不含超级管理员）")
async def get_user_list(user: Users = Depends(get_current_admin)):
    """仅管理员可调用，返回除 id=1（超级管理员）外所有用户的 id、用户名与角色。"""
    with get_session() as session:
        try:
            all_user:list[Users] = session.query(Users).filter(Users.id != 1).all()
            res_data = [{'id':u.id,'name':u.name,'role':u.effective_role} for u in all_user]
            return resp_200(data=res_data,msg='获取用户名列表成功')
        except Exception as e:
            logger.error(f'获取用户名列表失败错误,因为：{e}')
            return resp_500(msg="数据库操作错误")


@user_api.post('/create', summary="管理员创建新用户")
async def create_new_user(userInfo: CreateUser,login_user: Users = Depends(get_current_admin)):
    """仅管理员可创建用户；role 决定角色(admin/dispatcher/guest)，isAdmin 由 role 自动同步。"""
    conflict = get_user_conflict(name=userInfo.name,email=userInfo.email)
    if conflict != None:
        return resp_400(msg=conflict)
    try:
        userInfo.hashed_password = get_password_hash(userInfo.password)
        userInfo.create_time = datetime.datetime.now()
        if userInfo.map_id is None:
            userInfo.map_id = 1
        result = create_user(userInfo)
    except Exception as e:
        logger.error(f'创建用户失败！-- {e}')
        return resp_500(msg='创建用户失败！')
    logger.info(f"管理员 {login_user.name} 创建了用户 {result['name']}（角色: {result['role']}）")
    return resp_200(data=result,msg="创建用户成功！")

# ------------------新增：编辑用户信息接口 PUT ------------------
@user_api.put("/{user_id}", summary="管理员修改指定用户信息")
async def update_target_user(
        update_data: UserUpdate,
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

            # 只更新前端传入的字段（pydantic v1 用 dict，不能用 model_dump）
            update_dict = update_data.dict(exclude_unset=True)

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

            # 用户名/邮箱修改需要查重
            if "name" in update_dict or "email" in update_dict:
                conflict = get_user_conflict(name=update_dict.get("name"),
                                             email=update_dict.get("email"),
                                             exclude_id=target_user.id)
                if conflict != None:
                    return resp_400(msg=conflict)

            for k, v in update_dict.items():
                setattr(target_user, k, v)

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