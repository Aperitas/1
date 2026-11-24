"""
author:dlr123
date:2022年07月06日
"""
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime

from models.car.map_link import CarMapLink

class CarStatus(int, Enum):
    """车辆状态（返回给前端的是整型值）

    - 0 INACTIVATE：关机 / ROS 未启动
    - 1 FREE：空闲（在线但未分配任务）
    - 2 WORKING：执行任务中
    - 3 PAUSE：已暂停
    - 4 CHARGING：充电中
    - 5 Fault：故障
    """
    INACTIVATE = 0
    FREE = 1
    WORKING = 2
    PAUSE = 3
    CHARGING = 4
    Fault = 5


class Cars(SQLModel, table=True):
    """小车（AGV）信息"""
    id: Optional[int] = Field(default=None, primary_key=True, description="车辆ID")
    name: str = Field(..., description="车辆名称")
    productor: Optional[str] = Field(default=None, description="厂商")
    fault_reason: Optional[str] = Field(default=None, description="故障原因（status=Fault 时有值）")
    description: Optional[str] = Field(default=None, description="备注")
    status: CarStatus = Field(default=CarStatus.INACTIVATE, description="状态：0关机/1空闲/2工作中/3暂停/4充电/5故障")
    current_task_id: Optional[int] = Field(default=None, description="当前任务ID（历史字段，目前用于记录正在执行的路线ID）")
    ip: str = Field(..., description="车端 IP")
    port: str = Field(..., description="车端端口")
    weight: float = Field(..., description="载重（kg）")

    # 真实GPS经纬度（车端上报）
    lon: Optional[float] = Field(default=113.9686, description="经度，南科大基准")
    lat: Optional[float] = Field(default=22.6042, description="纬度，南科大基准")
    yaw: Optional[float] = Field(default=0.0, description="航向角 0朝北")
    speed: Optional[float] = Field(default=0.0, description="小车速度 m/s")

    # ===== 局部点云图坐标（车端在点云/栅格里定位后上报；前端在点云图上画车用） =====
    pc_map_id: Optional[int] = Field(default=None, description="点云位姿所属的地图ID（点云坐标系）")
    pc_x: Optional[float] = Field(default=None, description="点云坐标 X（米）")
    pc_y: Optional[float] = Field(default=None, description="点云坐标 Y（米）")
    pc_z: Optional[float] = Field(default=None, description="点云坐标 Z（米，相对点云原点，不是海拔）")
    pc_roll: Optional[float] = Field(default=None, description="点云坐标系下的横滚角 roll（度，右手系）")
    pc_pitch: Optional[float] = Field(default=None, description="点云坐标系下的俯仰角 pitch（度，右手系）")
    pc_yaw: Optional[float] = Field(default=None, description="点云坐标系下的航向角 yaw（度，+x 轴为 0，逆时针为正）")

    battery: Optional[float] = Field(default=100.0, description="电量百分比 0-100")
    video_streams: Optional[str] = Field(default="{}", description="多角度视频流地址JSON字符串，如 {'front':'rtsp://...'}")
    last_heartbeat: Optional[datetime] = Field(default=None, description="最后一次上报心跳时间")

    control_mode: Optional[str] = Field(default="AUTO", description="控制模式: MANUAL / AUTO / TRACKING")
    tracking_path_id: Optional[int] = Field(default=None, description="寻迹模式下正在寻迹的路线ID")

    tasks: List["Tasks"] = Relationship(back_populates="car")
    # ===== 车辆所属地图（多对多） =====
    maps: List["Map"] = Relationship(back_populates="cars", link_model=CarMapLink)
    # ==================================