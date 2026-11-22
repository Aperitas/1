"""
author:dlr123
date:2022年06月02日
"""
from sqlmodel import SQLModel, Field
from typing import Optional, Dict


class Position(SQLModel) :
    """平面坐标（局部坐标系，单位米）"""
    x: float = Field(..., description="局部坐标 X（米）")
    y: float = Field(..., description="局部坐标 Y（米）")


class Orientation(SQLModel) :
    """朝向"""
    yaw: float = Field(..., description="航向角（弧度/度，与车端约定）")


class DevicePositon(Position,Orientation) :
    """设备位置（含楼层）"""
    floor: int = Field(..., description="所在楼层")


class CarUploadMsg(Position):
    """车端上报的简易位置消息"""
    car_id: int = Field(..., description="车辆ID")
    speed: float = Field(..., description="速度（m/s）")


class CarReportIn(SQLModel):
    """车端状态上报（POST /report/car_status）"""
    car_id: int = Field(..., description="车辆ID")
    lon: float = Field(..., description="GPS 经度（WGS84）")
    lat: float = Field(..., description="GPS 纬度（WGS84）")
    yaw: float = Field(..., description="航向角（0 朝北）")
    speed: float = Field(..., description="当前速度（m/s）")
    battery: float = Field(..., description="电量百分比（0~100）")
    video_streams: Optional[Dict[str, str]] = Field(
        default={},
        description="多路视频流地址，例如 {\"front\":\"rtsp://...\",\"back\":\"rtsp://...\"}",
    )