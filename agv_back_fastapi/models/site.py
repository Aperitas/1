from enum import Enum

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict, Any
from datetime import datetime


class StopMode(str, Enum):
    """站点停靠模式

    - TIMED(timed)：等一段时间自动走（类似地铁），时长由 dwell_time 控制
    - WAIT_COMMAND(wait_command)：车端发命令才走（类似观光车/有人值守）
    """
    TIMED = "timed"
    WAIT_COMMAND = "wait_command"


class Site(SQLModel, table=True):
    __tablename__ = "sites"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="站点名称，如 '图书馆站'")
    lon: float = Field(description="经度")
    lat: float = Field(description="纬度")
    dwell_time: Optional[int] = Field(default=0, description="停靠时间（秒），仅 timed 模式生效")
    stop_mode: str = Field(default=StopMode.TIMED.value,
                           description="停靠模式: timed=等一段时间自动走, wait_command=车端发命令才走")
    description: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id")
    # ===== 点云坐标（米）：与 lon/lat 互为换算结果，前端可直接传这两个 =====
    pc_x: Optional[float] = Field(default=None, description="点云坐标 X（米）")
    pc_y: Optional[float] = Field(default=None, description="点云坐标 Y（米）")
    map: Optional["Map"] = Relationship(back_populates="sites")