"""
author:dlr123
date:2022年06月28日
"""
from fastapi import APIRouter,Depends
from fastapi.encoders import jsonable_encoder
from fastapi import Path
from schemas.user import UserUpdate
from crud.user import userCrud
from core.logger import logger
from core.security import get_current_user
from crud.orders import orderCrud
from db.session import get_session
from models.item.items import UserOrder
from models.user.users import Users
from schemas.orders import CreateOrder,UpdateOrder,QueryOrder,OutputOrder
from utils.resp_code import resp_200,resp_500,resp_400

user_api = APIRouter(prefix='/user')

@user_api.get('/getuserlist')
async def get_user_list(user: Users = Depends(get_current_user)):
    if user.isAdmin:
        with get_session() as session:
            try:
                all_user:list[Users] = session.query(Users).filter(Users.id != 1).all()
                res_data = [{'id':user.id,'name':user.name} for user in all_user]
                return resp_200(data=res_data,msg='获取用户名列表成功')
            except Exception as e:
                logger.error(f'获取用户名列表失败错误,因为：{e}')
                return resp_500(msg="数据库操作错误")

        pass
    else:
        raise PermissionError("没有权限获得所有用户")
    pass

# ------------------新增：编辑用户信息接口 PUT ------------------
@user_api.put("/{user_id}", summary="管理员修改指定用户信息")
async def update_target_user(
        update_data: UserUpdate,
        user_id: int = Path(..., description="待修改用户ID"),
        login_user: Users = Depends(get_current_user)
):
    # 和上方列表接口保持一致权限判断
    if not login_user.isAdmin:
        raise PermissionError("无权限修改用户信息")

    with get_session() as session:
        try:
            # 查询目标用户
            target_user = session.query(Users).filter(Users.id == user_id).first()
            if not target_user:
                return resp_400(msg="目标用户不存在")

            # 只更新前端传入的字段
            update_dict = update_data.model_dump(exclude_unset=True)
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
        login_user: Users = Depends(get_current_user)
):
    # 管理员权限校验
    if not login_user.isAdmin:
        raise PermissionError("无权限删除用户账号")

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