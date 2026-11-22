"""
author:dlr123
date:2022年05月31日
"""
from datetime import datetime
from typing import Optional,List

from pydantic import Field
from sqlmodel import SQLModel

from models.user.users import UserRole


class UserIn(SQLModel) :
    """ 共享模型字段 """
    name: str


class UpdateUser(SQLModel) :
    hashed_password: Optional[str] = Field(default=None,description="用户hash密码")
    isActive: Optional[bool] = None
    last_active_time: Optional[datetime] = None
    nickname: Optional[str] = None
    role: Optional[str] = Field(default=None,description="角色: admin/dispatcher/guest")
    avatar: Optional[str] = Field(default=None,description="头像URL")
    # ===== 新增：用户默认地图ID（管理员更新用户时可修改） =====
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")
    # ===========================================================


class CreateUser(UpdateUser, UserIn):
    password: str = Field(...,min_length=6,max_length=72,description="明文密码（6~72位）")
    isActive: bool = False
    nickname: Optional[str] = Field(default=None,description="昵称，留空默认取账户名")
    create_time: datetime = datetime.now()
    isAdmin: bool = False  # 兼容字段：实际由 role 推导，服务端会忽略前端传值
    role: UserRole = Field(default=UserRole.GUEST,description="角色: admin/dispatcher/guest")
    code: Optional[str] = Field(default=None, max_length=6)  # 验证码也改为可选（因为已注释）
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")


class OutputUser(UserIn) :
    id: int
    roles: Optional[List[str]] = None
    role: Optional[str] = Field(default=None,description="角色: admin/dispatcher/guest")
    avatar: Optional[str] = Field(default=None,description="头像URL")
    nickname: str
    create_time: datetime
    last_active_time: Optional[datetime] = None
    isActive: bool = False
    # ===== 新增：用户默认地图ID =====
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")
    # ===============================

from pydantic import BaseModel
from typing import Optional

class UserUpdate(BaseModel):
    """管理员修改某个用户时使用的请求体"""
    name: Optional[str] = None
    nickname: Optional[str] = None
    isActive: Optional[bool] = None
    isAdmin: Optional[bool] = None
    role: Optional[UserRole] = Field(default=None,description="角色: admin/dispatcher/guest")
    avatar: Optional[str] = None
    # ===== 新增：用户默认地图ID（管理员更新用户时可修改） =====
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")
    # ===========================================================


class ProfileUpdateIn(BaseModel):
    """用户修改自己资料时使用的请求体（不含角色/密码）"""
    name: Optional[str] = Field(default=None,min_length=1,max_length=50,description="用户名")
    nickname: Optional[str] = Field(default=None,max_length=50,description="昵称")
    avatar: Optional[str] = Field(default=None,max_length=255,description="头像URL")


class PasswordChangeIn(BaseModel):
    """用户修改自己密码时使用的请求体"""
    old_password: str = Field(...,min_length=1,max_length=72,description="旧密码")
    new_password: str = Field(...,min_length=6,max_length=72,description="新密码（6~72位）")


class AdminResetPasswordIn(BaseModel):
    """管理员重置某个用户密码时使用的请求体"""
    new_password: str = Field(...,min_length=6,max_length=72,description="新密码（6~72位）")