"""
用户与地图的多对多关联表（一个账户可负责多张地图，一张地图也可有多个账户）。
说明：users.map_id 仍保留，作为"登录后默认打开的地图"。
"""
from typing import Optional

from sqlmodel import SQLModel, Field


class UserMapLink(SQLModel, table=True):
    __tablename__ = "usermap"

    user_id: Optional[int] = Field(default=None, foreign_key="users.id", primary_key=True)
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id", primary_key=True)