"""
author:dlr123
date:2022年06月02日
"""
from sqlmodel import SQLModel
from typing import Optional
from typing import Optional, Dict, Any
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



class CarReportIn(SQLModel):
    car_id: int
    lon: float
    lat: float
    yaw: float
    speed: float
    battery: float
    video_streams: Optional[Dict[str, str]] = {}  # 前端传JSON对象