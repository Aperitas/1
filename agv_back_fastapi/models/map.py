from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime

class Map(SQLModel, table=True):
    __tablename__ = "maps"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="地图名称，如'南科大校园'")
    description: Optional[str] = Field(default=None, description="描述")
    center_lon: float = Field(default=113.9686, description="地图中心经度")
    center_lat: float = Field(default=22.6042, description="地图中心纬度")
    zoom: int = Field(default=17, description="默认缩放级别")
    created_at: datetime = Field(default_factory=datetime.now)

    # 关系
    sites: List["Site"] = Relationship(back_populates="map")
    waypoints: List["Waypoint"] = Relationship(back_populates="map")
    paths: List["Path"] = Relationship(back_populates="map")