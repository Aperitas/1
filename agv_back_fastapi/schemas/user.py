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
    name: str = Field(..., description="账户名（登录用户名，全局唯一）")


class UpdateUser(SQLModel) :
    hashed_password: Optional[str] = Field(default=None,description="用户hash密码（服务端生成，前端无需传）")
    isActive: Optional[bool] = Field(default=None,description="是否在线/启用：登录置 true，登出置 false")
    last_active_time: Optional[datetime] = Field(default=None,description="最后活跃时间")
    nickname: Optional[str] = Field(default=None,description="昵称（展示用，可与账户名不同）")
    role: Optional[str] = Field(default=None,description="角色：admin=管理员 / dispatcher=调度员 / guest=游客")
    avatar: Optional[str] = Field(default=None,description="头像URL")
    # ===== 新增：用户默认地图ID（管理员更新用户时可修改） =====
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")
    # ===========================================================


class CreateUser(UpdateUser, UserIn):
    password: str = Field(...,min_length=6,max_length=72,description="明文密码（6~72位，服务端 bcrypt 加密后入库）")
    isActive: bool = Field(default=False,description="是否在线/启用")
    nickname: Optional[str] = Field(default=None,description="昵称，留空默认取账户名")
    create_time: datetime = Field(default=datetime.now(),description="创建时间（服务端会覆盖为当前时间）")
    isAdmin: bool = Field(default=False,description="兼容字段：实际由 role 推导，服务端忽略前端传值")
    role: UserRole = Field(default=UserRole.GUEST,description="角色：admin=管理员 / dispatcher=调度员 / guest=游客")
    code: Optional[str] = Field(default=None, max_length=6, description="邮箱验证码（暂未启用）")
    map_id: Optional[int] = Field(default=None, description="默认地图ID（登录后默认打开的地图；不传则取 map_ids 第一个）")
    map_ids: Optional[List[int]] = Field(default=None, description="账户负责的地图ID列表（决定该账户能看到哪些地图）")


class OutputUser(UserIn) :
    """用户信息（返回结构，不含密码/邮箱/手机号）"""
    id: int = Field(..., description="用户ID")
    roles: Optional[List[str]] = Field(default=None, description="角色列表（兼容前端旧的 roles 字段）")
    role: Optional[str] = Field(default=None,description="角色：admin=管理员 / dispatcher=调度员 / guest=游客")
    avatar: Optional[str] = Field(default=None,description="头像URL")
    nickname: str = Field(..., description="昵称")
    create_time: datetime = Field(..., description="创建时间")
    last_active_time: Optional[datetime] = Field(default=None, description="最后活跃时间")
    isActive: bool = Field(default=False, description="是否在线/启用")
    # ===== 新增：用户默认地图ID =====
    map_id: Optional[int] = Field(default=None, description="默认地图ID（登录后默认打开的地图）")
    # ===============================

from pydantic import BaseModel, validator
from typing import Optional

from utils.patch import blank_to_none

class UserUpdate(BaseModel):
    """管理员修改某个用户时使用的请求体（只传需要修改的字段）"""
    name: Optional[str] = Field(default=None, description="账户名（唯一）")
    nickname: Optional[str] = Field(default=None, description="昵称")
    isActive: Optional[bool] = Field(default=None, description="是否在线/启用")
    isAdmin: Optional[bool] = Field(default=None, description="兼容字段：true→role=admin，false→role=guest")
    role: Optional[UserRole] = Field(default=None,description="角色：admin=管理员 / dispatcher=调度员 / guest=游客")
    avatar: Optional[str] = Field(default=None, description="头像URL")
    # ===== 新增：用户默认地图ID（管理员更新用户时可修改） =====
    map_id: Optional[int] = Field(default=None, description="默认地图ID（登录后默认打开的地图）")
    map_ids: Optional[List[int]] = Field(default=None, description="账户负责的地图ID列表（传了就整体覆盖）")
    # ===========================================================


    @validator("isActive", "isAdmin", "map_id", pre=True)
    def _blank_to_none(cls, value):
        return blank_to_none(value)

class UserMapSetIn(BaseModel):
    """设置账户负责的地图（覆盖式）"""
    map_ids: List[int] = Field(default=[], description="地图ID列表：传空数组表示解除全部关联")


class ProfileUpdateIn(BaseModel):
    """用户修改自己资料时使用的请求体（不含角色/密码）"""
    name: Optional[str] = Field(default=None,max_length=50,description="用户名（传空串/null 视为不修改）")
    nickname: Optional[str] = Field(default=None,max_length=50,description="昵称")
    avatar: Optional[str] = Field(default=None,max_length=255,description="头像URL")


class PasswordChangeIn(BaseModel):
    """用户修改自己密码时使用的请求体"""
    old_password: str = Field(...,min_length=1,max_length=72,description="旧密码")
    new_password: str = Field(...,min_length=6,max_length=72,description="新密码（6~72位）")


class AdminResetPasswordIn(BaseModel):
    """管理员重置某个用户密码时使用的请求体"""
    new_password: str = Field(...,min_length=6,max_length=72,description="新密码（6~72位）")