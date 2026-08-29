"""
author:dlr123
date:2022年05月31日
"""
from datetime import datetime
from typing import Optional,List

from pydantic import Field,EmailStr
from sqlmodel import SQLModel


class UserIn(SQLModel) :
    """ 共享模型字段 """
    name: str


class UpdateUser(SQLModel) :
    hashed_password: Optional[str] = Field(default=None,description="用户hash密码")
    email: Optional[EmailStr] = Field(default=None,description="用户邮箱")
    isActive: Optional[bool] = None
    last_active_time: Optional[datetime] = None
    phone: Optional[int] = Field(default=None)
    nickname: Optional[str] = None
    address_id: Optional[int] = None
    # ===== 新增：用户默认地图ID（管理员更新用户时可修改） =====
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")
    # ===========================================================


class CreateUser(UpdateUser, UserIn):
    password: str
    isActive: bool = False
    nickname: str
    address: Optional[List[int]] = Field(default=None)  # 改为可选
    email: EmailStr
    create_time: datetime = datetime.now()
    isAdmin: bool = False
    code: Optional[str] = Field(default=None, max_length=6)  # 验证码也改为可选（因为已注释）
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")


class OutputUser(UserIn) :
    id: int
    email: Optional[EmailStr] = Field(default=None,description="用户邮箱")
    roles: Optional[List[str]] = None
    phone: Optional[int] = Field(default=None)
    address_id: Optional[int] = None
    # address: Optional[str] = None
    nickname: str
    create_time: datetime
    last_active_time: Optional[datetime] = None
    isActive: bool = False
    # ===== 新增：用户默认地图ID =====
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")
    # ===============================

from pydantic import BaseModel, EmailStr
from typing import Optional

class UserUpdate(BaseModel):
    name: Optional[str] = None
    nickname: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    isActive: Optional[bool] = None
    isAdmin: Optional[bool] = None
    address_id: Optional[int] = None
    # ===== 新增：用户默认地图ID（管理员更新用户时可修改） =====
    map_id: Optional[int] = Field(default=None, description="用户默认地图ID")
    # ===========================================================