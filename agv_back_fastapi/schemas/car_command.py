from sqlmodel import SQLModel, Field
from typing import Optional, List
from enum import Enum


class CarCommandIn(SQLModel):
    """给小车下发指令的请求体"""
    command: str = Field(
        ...,
        description=(
            "指令类型：start=开始执行指定路线（需 path_id） / goto=前往指定路线（需 path_id） "
            "/ stop=停止并清空任务 / pause=暂停 / resume=恢复 "
            "/ depart=在 wait_command 停靠点发车（可在 params.site_id 指定站点）"
        ),
    )
    path_id: Optional[int] = Field(default=None, description="路线ID：start / goto 指令必填")
    params: Optional[dict] = Field(default=None, description="附加参数，例如 {\"site_id\": 2}")


class CarMapSetIn(SQLModel):
    """设置车辆所属地图（覆盖式）"""
    map_ids: List[int] = Field(default=[], description="地图ID列表：传空数组表示解除全部关联")


class SiteDepartIn(SQLModel):
    """车端在 wait_command 站点请求发车"""
    car_id: int = Field(..., description="车辆ID")
    site_id: Optional[int] = Field(default=None, description="当前停靠的站点ID（可选，用于日志与前端提示）")


class ControlModeEnum(str, Enum):
    """小车控制模式

    - AUTO：自动模式，由调度系统下发指令
    - MANUAL：手动模式，交由人工遥控
    - TRACKING：寻迹模式，沿指定路线循环行驶
    """
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    TRACKING = "TRACKING"


class ControlModeIn(SQLModel):
    """切换控制模式的请求体"""
    mode: ControlModeEnum = Field(..., description="目标控制模式：AUTO / MANUAL / TRACKING")
    path_id: Optional[int] = Field(default=None, description="寻迹路线ID：仅 mode=TRACKING 时必填")
