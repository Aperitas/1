"""
author:dlr123
date:2022年06月07日
"""
from fastapi import APIRouter,Depends
from typing import Optional
from core.logger import logger
from core.security import get_current_user
from db import get_session
from models.user.users import Users
from schemas.user import OutputUser
from utils.resp_code import resp_200
from utils.custom_exc import UserNotExist,PermissionNotEnough

commons_api = APIRouter(prefix="/commons")


@commons_api.get('/userinfo', summary="获取用户信息（可查询指定用户）")
async def get_user_info(user: Users = Depends(get_current_user),user_id:Optional[int]=None) :
    """不传 user_id 返回登录者自身信息；传 user_id 时仅管理员可查询他人信息。"""
    target_user = None
    if user_id is not None:
        if user.isAdmin:
            with get_session() as session:
                try:
                    target_user = session.query(Users).get(user_id)
                    if target_user is None:
                        raise UserNotExist("请求的用户不存在")
                except Exception as e:
                    session.rollback()
                    logger.error(f'用户信息获取失败,因为：{e}')
                    raise e
        else:
            raise PermissionNotEnough("你没有访问其他用户信息的权限")
    else:
        # 不传user_id，查询登录者自己
        target_user = user

    data = OutputUser.from_orm(target_user)
    # 判断【被查询用户】的角色，不是登录者user
    data.role = target_user.effective_role
    data.roles = [target_user.effective_role]
    return resp_200(data=data)
