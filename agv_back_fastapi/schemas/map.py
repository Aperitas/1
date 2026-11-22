from sqlmodel import SQLModel
from typing import Optional
from datetime import datetime

class MapCreate(SQLModel):
    name: str
    description: Optional[str] = None
    map_type: str = "tianditu"  # tianditu / grid / pointcloud
    center_lon: float = 113.9686
    center_lat: float = 22.6042
    zoom: int = 17
    lon_min: Optional[float] = None
    lat_min: Optional[float] = None
    lon_max: Optional[float] = None
    lat_max: Optional[float] = None
    fallback_map_id: Optional[int] = None

class MapUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    map_type: Optional[str] = None
    center_lon: Optional[float] = None
    center_lat: Optional[float] = None
    zoom: Optional[int] = None
    lon_min: Optional[float] = None
    lat_min: Optional[float] = None
    lon_max: Optional[float] = None
    lat_max: Optional[float] = None
    fallback_map_id: Optional[int] = None

class MapOut(SQLModel):
    id: int
    name: str
    description: Optional[str]
    map_type: str
    center_lon: float
    center_lat: float
    zoom: int
    lon_min: Optional[float] = None
    lat_min: Optional[float] = None
    lon_max: Optional[float] = None
    lat_max: Optional[float] = None
    fallback_map_id: Optional[int] = None
    created_at: datetime