from sqlmodel import SQLModel
from typing import Optional, List, Dict, Any
from datetime import datetime

# ---------- 站点 ----------
class SiteCreate(SQLModel):
    name: str
    lon: float
    lat: float
    dwell_time: Optional[int] = 0
    stop_mode: str = "timed"  # timed=等一段时间自动走, wait_command=车端发命令才走
    description: Optional[str] = None
    map_id: int

class SiteUpdate(SQLModel):
    name: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    dwell_time: Optional[int] = None
    stop_mode: Optional[str] = None
    description: Optional[str] = None
    map_id: Optional[int] = None

class SiteOut(SQLModel):
    id: int
    name: str
    lon: float
    lat: float
    dwell_time: int
    stop_mode: str
    description: Optional[str]
    map_id: int
    created_at: datetime

# ---------- 路径点 ----------
class WaypointCreate(SQLModel):
    name: str
    lon: float
    lat: float
    description: Optional[str] = None
    map_id: int

class WaypointUpdate(SQLModel):
    name: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    description: Optional[str] = None
    map_id: Optional[int] = None

class WaypointOut(SQLModel):
    id: int
    name: str
    lon: float
    lat: float
    description: Optional[str]
    map_id: int
    created_at: datetime

# ---------- 路线 ----------
class PathCreate(SQLModel):
    name: str
    path_type: str  # '吸附道路'/'贝塞尔曲线'/'折线'
    node_chain: List[Dict[str, Any]]  # [{"type":"site","id":1}, ...]
    car_id: Optional[int] = None
    map_id: int  # 必须指定所属地图
    is_temp: bool = False  # 是否临时路径

class PathUpdate(SQLModel):
    name: Optional[str] = None
    path_type: Optional[str] = None
    node_chain: Optional[List[Dict[str, Any]]] = None
    car_id: Optional[int] = None
    map_id: Optional[int] = None
    is_temp: Optional[bool] = None

class PathOut(SQLModel):
    id: int
    name: str
    path_type: str
    node_chain: List[Dict[str, Any]]  # 转为Python对象返回
    car_id: Optional[int]
    map_id: int
    is_temp: bool
    created_at: datetime