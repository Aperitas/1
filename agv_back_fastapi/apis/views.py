"""
接口输出格式辅助函数（避免多处返回结构不一致）。
"""
from typing import Dict, List

from models.car.car import Cars
from utils.video_streams import parse_streams


def car_payload(car: Cars, map_ids: List[int], map_names: Dict[int, str]) -> dict :
    """ 车辆信息的标准输出结构（车列表 / 地图详情共用） """
    return {
        "car_id" : car.id,
        "name" : car.name,
        "status" : car.status,
        "control_mode" : car.control_mode,
        "tracking_path_id" : car.tracking_path_id,
        "yaw" : car.yaw,
        "speed" : car.speed,
        "lon" : car.lon,
        "lat" : car.lat,
        # 局部点云坐标（车端在点云/栅格图中定位后上报；前端在点云图上画车用）
        "pc_map_id" : car.pc_map_id,
        "pc_x" : car.pc_x,
        "pc_y" : car.pc_y,
        "pc_z" : car.pc_z,
        "pc_roll" : car.pc_roll,
        "pc_pitch" : car.pc_pitch,
        "pc_yaw" : car.pc_yaw,
        "battery" : car.battery,
        "video_streams" : parse_streams(car.video_streams),
        "map_ids" : map_ids,
        "maps" : [{"id" : mid,"name" : map_names.get(mid)} for mid in map_ids],
    }