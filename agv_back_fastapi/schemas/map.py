from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class MapCreate(SQLModel):
    """新增地图（管理员调用）"""
    name: str = Field(..., description="地图名称，如 '南科大校园'")
    description: Optional[str] = Field(default=None, description="地图描述")
    map_type: str = Field(
        default="tianditu",
        description=(
            "地图类型：tianditu=天地图（矢量/影像瓦片，需传四角点范围） "
            "/ grid=栅格地图（文件内含经纬度） "
            "/ pointcloud=点云地图"
        ),
    )
    center_lon: float = Field(default=113.9686, description="地图中心经度")
    center_lat: float = Field(default=22.6042, description="地图中心纬度")
    zoom: int = Field(default=17, description="默认缩放级别（天地图建议 15~18）")
    lon_min: Optional[float] = Field(default=None, description="区域西南角经度（map_type=tianditu 时必填）")
    lat_min: Optional[float] = Field(default=None, description="区域西南角纬度（map_type=tianditu 时必填）")
    lon_max: Optional[float] = Field(default=None, description="区域东北角经度（tianditu 必填，且需 > lon_min）")
    lat_max: Optional[float] = Field(default=None, description="区域东北角纬度（tianditu 必填，且需 > lat_min）")
    fallback_map_id: Optional[int] = Field(
        default=None,
        description="定位漂移/丢失时的兜底地图ID（必须是一张 pointcloud 类型的点云地图）",
    )


class MapUpdate(SQLModel):
    """修改地图（管理员调用）：只传需要修改的字段"""
    name: Optional[str] = Field(default=None, description="地图名称")
    description: Optional[str] = Field(default=None, description="地图描述")
    map_type: Optional[str] = Field(default=None, description="地图类型：tianditu / grid / pointcloud")
    center_lon: Optional[float] = Field(default=None, description="地图中心经度")
    center_lat: Optional[float] = Field(default=None, description="地图中心纬度")
    zoom: Optional[int] = Field(default=None, description="默认缩放级别")
    lon_min: Optional[float] = Field(default=None, description="区域西南角经度（tianditu 必填）")
    lat_min: Optional[float] = Field(default=None, description="区域西南角纬度（tianditu 必填）")
    lon_max: Optional[float] = Field(default=None, description="区域东北角经度（tianditu 必填）")
    lat_max: Optional[float] = Field(default=None, description="区域东北角纬度（tianditu 必填）")
    fallback_map_id: Optional[int] = Field(default=None, description="兜底点云地图ID（必须是 pointcloud 类型）")


class MapOut(SQLModel):
    """地图信息（返回结构）"""
    id: int = Field(..., description="地图ID")
    name: str = Field(..., description="地图名称")
    description: Optional[str] = Field(default=None, description="地图描述")
    map_type: str = Field(..., description="地图类型：tianditu / grid / pointcloud")
    center_lon: float = Field(..., description="地图中心经度")
    center_lat: float = Field(..., description="地图中心纬度")
    zoom: int = Field(..., description="默认缩放级别")
    lon_min: Optional[float] = Field(default=None, description="区域西南角经度")
    lat_min: Optional[float] = Field(default=None, description="区域西南角纬度")
    lon_max: Optional[float] = Field(default=None, description="区域东北角经度")
    lat_max: Optional[float] = Field(default=None, description="区域东北角纬度")
    fallback_map_id: Optional[int] = Field(default=None, description="兜底点云地图ID")
    created_at: datetime = Field(..., description="创建时间")