"""
author:dlr123
date:2022年06月07日
"""
import datetime

from fastapi import Depends

from apis.oauth import oauth_api
from core.logger import logger
from core.security import get_current_admin, get_password_hash
from crud.user import create_user, get_user_conflict
from models.user.users import Users
from schemas.user import CreateUser
from utils.resp_code import resp_400,resp_500,resp_200


@oauth_api.post('/register', summary="创建用户（仅管理员）")
async def register_user(userInfo: CreateUser,admin: Users = Depends(get_current_admin)) :
    """仅管理员可创建用户：role 决定角色(admin/dispatcher/guest)，isAdmin 由 role 自动同步。"""
    conflict = get_user_conflict(name=userInfo.name)
    if conflict != None :
        return resp_400(msg=conflict)
    try :
        userInfo.hashed_password = get_password_hash(userInfo.password)
        userInfo.create_time = datetime.datetime.now()
        # 默认绑定地图 1
        if userInfo.map_id is None :
            userInfo.map_id = 1
        result = create_user(userInfo)
    except Exception as e :
        logger.error(f'创建用户失败！-- {e}')
        return resp_500(msg='创建用户失败！')
    logger.info(f"管理员 {admin.name} 创建了用户 {result['name']}（角色: {result['role']}）")
    return resp_200(data=result,msg="创建用户成功！")
