from sqlmodel import SQLModel
from typing import Optional, List, Dict, Any
from datetime import datetime

# ---------- 站点 ----------
class SiteCreate(SQLModel):
    name: str
    lon: float
    lat: float
    dwell_time: Optional[int] = 0
    description: Optional[str] = None

class SiteUpdate(SQLModel):
    name: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    dwell_time: Optional[int] = None
    description: Optional[str] = None

class SiteOut(SQLModel):
    id: int
    name: str
    lon: float
    lat: float
    dwell_time: int
    description: Optional[str]
    created_at: datetime

# ---------- 路径点 ----------
class WaypointCreate(SQLModel):
    name: str
    lon: float
    lat: float
    description: Optional[str] = None

class WaypointUpdate(SQLModel):
    name: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    description: Optional[str] = None

class WaypointOut(SQLModel):
    id: int
    name: str
    lon: float
    lat: float
    description: Optional[str]
    created_at: datetime

# ---------- 路线 ----------
class PathCreate(SQLModel):
    name: str
    path_type: str  # '吸附道路'/'贝塞尔曲线'/'折线'
    node_chain: List[Dict[str, Any]]  # [{"type":"site","id":1}, ...]
    car_id: Optional[int] = None

class PathUpdate(SQLModel):
    name: Optional[str] = None
    path_type: Optional[str] = None
    node_chain: Optional[List[Dict[str, Any]]] = None
    car_id: Optional[int] = None

class PathOut(SQLModel):
    id: int
    name: str
    path_type: str
    node_chain: List[Dict[str, Any]]  # 转为Python对象返回
    car_id: Optional[int]
    created_at: datetime