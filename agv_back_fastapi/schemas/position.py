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
    # ===== 可选：局部点云坐标（车端在点云/栅格图中定位后上报，前端在点云图上画车用） =====
    pc_map_id: Optional[int] = Field(
        default=None,
        description="点云坐标所属地图ID；不传时若车辆只绑定一张地图则自动用那张",
    )
    pc_x: Optional[float] = Field(default=None, description="点云坐标 X（米）")
    pc_y: Optional[float] = Field(default=None, description="点云坐标 Y（米）")
    pc_yaw: Optional[float] = Field(
        default=None,
        description="点云坐标系下的航向角（度，+x 轴为 0，逆时针为正）；不传时用经纬度航向换算",
    )
