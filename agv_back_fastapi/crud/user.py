"""
author:dlr123
date:2022年05月31日
"""
import uuid
from typing import Optional

from sqlmodel import select,Session

from core.security import verify_password
from crud.base import CRUDBase
from db.session import get_session
from models import Users
from models.user.users import UserRole
from schemas import UpdateUser,CreateUser
from utils.custom_exc import ErrorUser


class UserCrud(CRUDBase[Users,UpdateUser,CreateUser]) :
    def __init__(self) :
        super(UserCrud,self).__init__(Users)

    def get_by_name(self,name: str,db: Session = get_session()) -> Optional[Users] :
        """ 通过名字得到用户 """
        sql = select(self.model).where(self.model.name == name)
        result = db.scalar(sql)
        db.close()  # 释放会话
        return result

    def authenticate(self,username: str,password: str) -> Optional[Users] :
        """ 验证用户 """
        user = self.get_by_name(username)
        if not user :
            raise ErrorUser("用户不存在")
        if not verify_password(password,user.hashed_password) :
            raise ErrorUser("密码错误")
        return user

    def get_by_email(self,email: str,db: Session = get_session()) -> Optional[Users] :
        sql = select(self.model).where(self.model.email == email)
        result = db.scalar(sql)
        db.close()
        return result

    def get_id_by_name(self,name: str,db: Session = get_session()) -> Optional[int] :
        result = self.get_by_name(name,db)
        return result.id


userCrud = UserCrud()


def get_user_conflict(name: Optional[str] = None,email: Optional[str] = None,
                      exclude_id: Optional[int] = None) -> Optional[str] :
    """ 检查用户名/邮箱是否被占用：返回提示信息，无冲突返回 None """
    with get_session() as session :
        if name :
            query = session.query(Users).filter(Users.name == name)
            if exclude_id is not None :
                query = query.filter(Users.id != exclude_id)
            if query.first() is not None :
                return "用户名已经存在，请更换用户名"
        if email :
            query = session.query(Users).filter(Users.email == email)
            if exclude_id is not None :
                query = query.filter(Users.id != exclude_id)
            if query.first() is not None :
                return "该邮箱已经被注册，请更换邮箱"
    return None


def create_user(payload: CreateUser) -> dict :
    """ 创建用户：role 与 isAdmin 自动同步、默认绑定地图 1，返回 {id, name, role}
        说明：邮箱/手机号暂不对外使用，users.email 列非空 → 自动填充占位邮箱 """
    role = payload.role.value if isinstance(payload.role,UserRole) else (payload.role or UserRole.GUEST.value)
    nickname = payload.nickname or payload.name
    with get_session() as session :
        user = Users(
            name=payload.name,
            hashed_password=payload.hashed_password or "",
            nickname=nickname,
            email=f"user.{uuid.uuid4().hex[:12]}@example.com",
            isActive=payload.isActive,
            create_time=payload.create_time,
            map_id=payload.map_id or 1,
            role=role,
            isAdmin=(role == UserRole.ADMIN.value),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        result = {"id" : user.id,"name" : user.name,"role" : user.role}
    return result


if __name__ == "__main__" :
    print(userCrud.get_by_name("admin").dict())
