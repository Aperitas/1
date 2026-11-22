"""
author:dlr123
date:2022年05月31日
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import EmailStr
from sqlmodel import SQLModel,Field,Relationship

from models.user.map_link import UserMapLink


class UserRole(str,Enum) :
    """ 用户角色 """
    ADMIN = "admin"            # 管理：最高权限（用户/地图/线路/小车管理 + 调度）
    DISPATCHER = "dispatcher"  # 调度：可查看全部信息 + 下发调度指令
    GUEST = "guest"            # 游客：仅可查看地图/线路等信息


class Users(SQLModel,table=True) :
    id: Optional[int] = Field(default=None,primary_key=True)
    name: str = Field(index=True,nullable=False,description="用户名")
    hashed_password: str
    # 用户状态
    isActive: bool = False
    create_time: datetime = datetime.now()
    last_active_time: Optional[datetime] = None
    # 用户信息
    isAdmin: bool = Field(default=False,description="历史字段：是否管理员，与 role 保持同步")
    role: str = Field(default=UserRole.GUEST.value,index=True,description="角色: admin/dispatcher/guest")
    avatar: Optional[str] = Field(default=None,description="头像URL")
    nickname: str
    # 说明：email / phone 暂不对外使用（接口层已移除），但保留数据库字段，
    #      以便以后启用邮箱验证/手机号功能；建号时后端会自动填充占位邮箱。
    email: EmailStr = Field(index=True)
    phone: Optional[int] = Field(default=None)
    address_id: Optional[int] = Field(default=None, description="保留字段,历史地址ID(已解除外键)")

    # ===== 新增：关联地图（默认地图，单值） =====
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id")
    # =========================

    # ===== 账户负责的地图（多对多） =====
    maps: List["Map"] = Relationship(back_populates="users", link_model=UserMapLink)
    # ===================================

    @property
    def effective_role(self) -> str :
        """ 实际角色：兼容历史数据（role 为空时按 isAdmin 推断） """
        if self.role :
            return self.role
        return UserRole.ADMIN.value if self.isAdmin else UserRole.GUEST.value

    @property
    def can_dispatch(self) -> bool :
        """ 是否具备调度权限（管理员或调度员） """
        return self.effective_role in (UserRole.ADMIN.value,UserRole.DISPATCHER.value)