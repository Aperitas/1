from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from enum import Enum

from models.user import Users
from models.user.map_link import UserMapLink
from models.car.map_link import CarMapLink


class MapType(str, Enum):
    """地图类型"""
    TIANDITU = "tianditu"      # 天地图（矢量/影像瓦片）
    GRID = "grid"              # 栅格地图
    POINTCLOUD = "pointcloud"  # 点云地图


class Map(SQLModel, table=True):
    __tablename__ = "maps"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="地图名称，如'南科大校园'")
    description: Optional[str] = Field(default=None, description="描述")
    center_lon: float = Field(default=113.9686, description="地图中心经度")
    center_lat: float = Field(default=22.6042, description="地图中心纬度")
    zoom: int = Field(default=17, description="默认缩放级别")
    # ===== 地图类型与天地图区域（两个角点） =====
    map_type: str = Field(default=MapType.TIANDITU.value, index=True,
                          description="地图类型: tianditu=天地图, grid=栅格, pointcloud=点云")
    lon_min: Optional[float] = Field(default=None, description="区域西南角经度")
    lat_min: Optional[float] = Field(default=None, description="区域西南角纬度")
    lon_max: Optional[float] = Field(default=None, description="区域东北角经度")
    lat_max: Optional[float] = Field(default=None, description="区域东北角纬度")
    # ===== 定位漂移/丢失时的兜底点云图 =====
    fallback_map_id: Optional[int] = Field(default=None, foreign_key="maps.id",
                                           description="漂移/丢定位时切换的点云地图ID")
    created_at: datetime = Field(default_factory=datetime.now)
    # ===== 新增：文件相关字段 =====
    file_path: Optional[str] = Field(default=None, description="文件存储路径")
    file_type: Optional[str] = Field(default=None, description="文件类型，如 pcd/zip")
    file_size: Optional[int] = Field(default=None, description="文件大小（字节）")
    upload_time: Optional[datetime] = Field(default=None, description="上传时间")
    # ===============================


    # 关系
    sites: List["Site"] = Relationship(back_populates="map")
    waypoints: List["Waypoint"] = Relationship(back_populates="map")
    paths: List["Path"] = Relationship(back_populates="map")
    # ===== 账户（多对多：一张地图可由多个账户负责） =====
    users: List["Users"] = Relationship(back_populates="maps", link_model=UserMapLink)
    # ================================================
    # ===== 地图拥有的车辆（多对多） =====
    cars: List["Cars"] = Relationship(back_populates="maps", link_model=CarMapLink)
    # ===================================