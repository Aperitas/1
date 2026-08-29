"""
author:dlr123
date:2022年05月31日
"""
from datetime import datetime
from typing import Optional,List
from pydantic import EmailStr
from sqlmodel import SQLModel,Field,Relationship


class Users(SQLModel,table=True) :
    id: Optional[int] = Field(default=None,primary_key=True)
    name: str = Field(index=True,nullable=False,description="用户名")
    hashed_password: str
    # 用户状态
    isActive: bool = False
    create_time: datetime = datetime.now()
    last_active_time: Optional[datetime] = None
    # 用户信息
    isAdmin: bool = Field(default=False)
    nickname: str
    email: EmailStr = Field(index=True)
    phone: Optional[int] = Field(default=None)
    address_id: Optional[int] = Field(default=None,foreign_key="city.union_id")

    # ===== 新增：关联地图 =====
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id")
    # =========================

    address: Optional["City"] = Relationship(back_populates="userList")
    selfItems: List["Items"] = Relationship(back_populates="user")
    UserOrders: List["UserOrder"] = Relationship(back_populates="user")
    # ===== 新增：地图反向关系 =====
    map: Optional["Map"] = Relationship(back_populates="users")
    # =============================