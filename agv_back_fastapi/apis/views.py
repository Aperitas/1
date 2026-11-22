"""
接口输出格式辅助函数（避免多处返回结构不一致）。
"""
from typing import Dict, List

from models.car.car import Cars


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
        "battery" : car.battery,
        "map_ids" : map_ids,
        "maps" : [{"id" : mid,"name" : map_names.get(mid)} for mid in map_ids],
    }