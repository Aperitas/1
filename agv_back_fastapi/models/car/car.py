"""
author:dlr123
date:2022年07月06日
"""
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime

class CarStatus(int, Enum):
    INACTIVATE = 0  # 关机或者ros系统没有开启时表示为关机状态
    FREE = 1        # ros系统开启时，但没有分配任务，表示为空闲状态
    WORKING = 2     # 当小车在执行任务时，表示为工作状态
    PAUSE = 3
    CHARGING = 4    # 当小车处于充电状态时
    Fault = 5       # 当小车异常时，表示为故障状态

class Cars(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    productor: Optional[str] = None
    fault_reason: Optional[str] = None
    description: Optional[str] = None
    status: CarStatus = CarStatus.INACTIVATE
    current_task_id: Optional[int] = None
    ip: str
    port: str
    weight: float

    # 旧平面坐标（保留，但不再更新）
    x: float = Field(default=0.0)
    y: float = Field(default=0.0)

    # 真实GPS经纬度（车端上报）
    lon: Optional[float] = Field(default=113.9686, description="经度，南科大基准")
    lat: Optional[float] = Field(default=22.6042, description="纬度，南科大基准")
    yaw: Optional[float] = Field(default=0.0, description="航向角 0朝北")
    speed: Optional[float] = Field(default=0.0, description="小车速度 m/s")

    # ========== 新增：真实车物理属性 ==========
    battery: Optional[float] = Field(default=100.0, description="电量百分比 0-100")
    video_streams: Optional[str] = Field(default="{}", description="多角度视频流地址JSON字符串，如 {'front':'rtsp://...'}")
    last_heartbeat: Optional[datetime] = Field(default=None, description="最后一次上报心跳时间")
    # ========================================

    tasks: List["Tasks"] = Relationship(back_populates="car")
    devices: List["DeviceTypeLink"] = Relationship(back_populates="car_link")