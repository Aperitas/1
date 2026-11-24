from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict, Any
from datetime import datetime

class Waypoint(SQLModel, table=True):
    __tablename__ = "waypoints"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="路径点名称，如 'A点'")
    lon: float = Field(description="经度")
    lat: float = Field(description="纬度")
    description: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id")
    # ===== 点云坐标（米）：与 lon/lat 互为换算结果，前端可直接传这两个 =====
    pc_x: Optional[float] = Field(default=None, description="点云坐标 X（米）")
    pc_y: Optional[float] = Field(default=None, description="点云坐标 Y（米）")
    map: Optional["Map"] = Relationship(back_populates="waypoints")