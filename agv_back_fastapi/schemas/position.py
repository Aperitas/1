"""
author:dlr123
date:2022年06月02日
"""
from sqlmodel import SQLModel
from typing import Optional

class Position(SQLModel) :
    x: float
    y: float


class Orientation(SQLModel) :
    yaw:float


class DevicePositon(Position,Orientation) :
    floor: int

class CarUploadMsg(Position):
    car_id: int
    speed: float

# ========== 新增：给前端地图用的带GPS经纬度小车模型 ==========
class CarMapOut(SQLModel):
    car_id: int
    name: str
    status: int
    # 原有平面坐标
    x: float
    y: float
    yaw: float
    speed: float
    # 新增真实GPS坐标（南科大基准）
    lon: Optional[float]
    lat: Optional[float]
    # 区分虚拟/真实小车
    isSimulation: bool