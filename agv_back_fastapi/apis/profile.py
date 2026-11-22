"""
author:dlr123
个人中心接口：登录用户查看/修改自己的资料、密码、头像。
"""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile

from core.logger import logger
from core.security import get_current_user, get_password_hash, verify_password
from crud.user import get_user_conflict
from db.session import get_session
from models.user.users import Users
from schemas.user import OutputUser, PasswordChangeIn, ProfileUpdateIn
from utils.resp_code import resp_200, resp_400, resp_500

profile_api = APIRouter(prefix='/profile')

# 头像保存目录（static 已通过 register/mount.py 挂载，可直接访问）
AVATAR_DIR = os.path.join("static", "avatars")
ALLOWED_AVATAR_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB


def _build_profile(user: Users) -> OutputUser :
    """ 把用户对象转成对外输出模型（补齐角色，对外不暴露密码） """
    data = OutputUser.from_orm(user)
    data.role = user.effective_role
    data.roles = [user.effective_role]
    return data


@profile_api.get("", summary="获取当前登录用户信息")
async def get_my_profile(user: Users = Depends(get_current_user)) :
    """ 返回登录者自己的资料（含角色、头像，不含密码） """
    return resp_200(data=_build_profile(user))


@profile_api.put("", summary="修改自己的资料")
async def update_my_profile(data: ProfileUpdateIn,user: Users = Depends(get_current_user)) :
    """ 修改自己的用户名/昵称/邮箱/手机/头像；角色与密码不能在这里修改 """
    update_data = data.dict(exclude_unset=True)
    if not update_data :
        return resp_400(msg="没有需要修改的字段")

    # 用户名唯一性校验（排除自己）
    conflict = get_user_conflict(name=update_data.get("name"),
                                 exclude_id=user.id)
    if conflict :
        return resp_400(msg=conflict)

    with get_session() as session :
        me = session.query(Users).filter(Users.id == user.id).first()
        if me is None :
            return resp_400(msg="用户不存在")
        try :
            for key,value in update_data.items() :
                setattr(me,key,value)
            session.add(me)
            session.commit()
            session.refresh(me)
        except Exception as e :
            session.rollback()
            logger.error(f"修改个人资料失败: {e}")
            return resp_500(msg="修改个人资料失败")
        result = _build_profile(me)

    logger.info(f"用户 {user.name} 修改了个人资料: {list(update_data.keys())}")
    return resp_200(data=result,msg="资料修改成功")


@profile_api.put("/password", summary="修改自己的密码")
async def change_my_password(data: PasswordChangeIn,user: Users = Depends(get_current_user)) :
    """ 先校验旧密码再写入新密码（bcrypt，兼容历史密码哈希） """
    if data.old_password == data.new_password :
        return resp_400(msg="新密码不能与旧密码相同")
    with get_session() as session :
        me = session.query(Users).filter(Users.id == user.id).first()
        if me is None :
            return resp_400(msg="用户不存在")
        if not verify_password(data.old_password,me.hashed_password) :
            return resp_400(msg="旧密码不正确")
        try :
            me.hashed_password = get_password_hash(data.new_password)
            session.add(me)
            session.commit()
        except Exception as e :
            session.rollback()
            logger.error(f"修改密码失败: {e}")
            return resp_500(msg="修改密码失败")
    logger.info(f"用户 {user.name} 修改了自己的密码")
    return resp_200(msg="密码修改成功")


@profile_api.post("/avatar", summary="上传头像")
async def upload_avatar(file: UploadFile = File(...),user: Users = Depends(get_current_user)) :
    """ 上传头像（png/jpg/jpeg/gif/webp，≤2MB），保存到 static/avatars 并写回用户资料 """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_AVATAR_SUFFIX :
        return resp_400(msg="仅支持 png/jpg/jpeg/gif/webp 格式的头像")

    content = await file.read()
    if not content :
        return resp_400(msg="上传的文件为空")
    if len(content) > MAX_AVATAR_SIZE :
        return resp_400(msg="头像大小不能超过 2MB")

    os.makedirs(AVATAR_DIR,exist_ok=True)
    filename = f"user_{user.id}_{uuid.uuid4().hex}{suffix}"
    file_path = os.path.join(AVATAR_DIR,filename)
    try :
        with open(file_path,"wb") as f :
            f.write(content)
    except Exception as e :
        logger.error(f"保存头像失败: {e}")
        return resp_500(msg="头像保存失败")

    avatar_url = f"/{AVATAR_DIR.replace(os.sep,'/')}/{filename}"
    with get_session() as session :
        me = session.query(Users).filter(Users.id == user.id).first()
        if me is None :
            return resp_400(msg="用户不存在")
        try :
            me.avatar = avatar_url
            session.add(me)
            session.commit()
        except Exception as e :
            session.rollback()
            logger.error(f"更新头像失败: {e}")
            return resp_500(msg="头像更新失败")

    logger.info(f"用户 {user.name} 更新了头像: {avatar_url}")
    return resp_200(data={"avatar" : avatar_url},msg="头像上传成功")
