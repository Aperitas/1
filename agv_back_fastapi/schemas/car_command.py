from sqlmodel import SQLModel
from typing import Optional, List
from enum import Enum

class CarCommandIn(SQLModel):
    command: str  # start / stop / pause / resume / goto / depart
    path_id: Optional[int] = None
    params: Optional[dict] = None


class CarMapSetIn(SQLModel):
    """设置车辆所属地图（覆盖式）"""
    map_ids: List[int] = []


class SiteDepartIn(SQLModel):
    """车端在 wait_command 站点请求发车"""
    car_id: int
    site_id: Optional[int] = None

# ===== 新增：控制模式切换请求体 =====
class ControlModeEnum(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    TRACKING = "TRACKING"


class ControlModeIn(SQLModel):
    mode: ControlModeEnum  # AUTO / MANUAL
    path_id: Optional[int] = None  # 仅当 mode=TRACKING 时必填
