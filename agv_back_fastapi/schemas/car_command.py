from sqlmodel import SQLModel
from typing import Optional
from enum import Enum

class CarCommandIn(SQLModel):
    command: str  # start / stop / pause / resume / goto
    path_id: Optional[int] = None
    params: Optional[dict] = None

# ===== 新增：控制模式切换请求体 =====
class ControlModeEnum(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    TRACKING = "TRACKING"


class ControlModeIn(SQLModel):
    mode: ControlModeEnum  # AUTO / MANUAL
    path_id: Optional[int] = None  # 仅当 mode=TRACKING 时必填
