from sqlmodel import SQLModel, Field
from pydantic import validator

from utils.patch import blank_to_none
from typing import Optional, Dict, Any, List
from datetime import datetime


class MapCreate(SQLModel):
    """新增地图（管理员调用）

    - map_type=tianditu：天地图，用左上/右下两个经纬度角点限定区域
    - map_type=local：本地地图（同一地点的「点云 + 栅格」绑定在一条记录里）
    - 区域坐标可传 lon_min/lat_min/lon_max/lat_max，也可直接传 left_top_* / right_bottom_*；
      不传则不做区域校验（后续可补传）
    """
    name: str = Field(..., description="地图名称，如 '南科大校园'")
    description: Optional[str] = Field(default=None, description="地图描述")
    map_type: str = Field(
        default="tianditu",
        description="地图类型：tianditu=天地图 / local=本地地图（点云+栅格）",
    )
    center_lon: float = Field(default=113.9686, description="地图中心经度")
    center_lat: float = Field(default=22.6042, description="地图中心纬度")
    zoom: int = Field(default=17, description="默认缩放级别（天地图建议 15~18）")
    # ===== 区域坐标（两种写法二选一，推荐左上/右下） =====
    lon_min: Optional[float] = Field(default=None, description="区域左边界经度（西）")
    lat_min: Optional[float] = Field(default=None, description="区域下边界纬度（南）")
    lon_max: Optional[float] = Field(default=None, description="区域右边界经度（东）")
    lat_max: Optional[float] = Field(default=None, description="区域上边界纬度（北）")
    left_top_lon: Optional[float] = Field(default=None, description="左上角经度（等价 lon_min）")
    left_top_lat: Optional[float] = Field(default=None, description="左上角纬度（等价 lat_max）")
    right_bottom_lon: Optional[float] = Field(default=None, description="右下角经度（等价 lon_max）")
    right_bottom_lat: Optional[float] = Field(default=None, description="右下角纬度（等价 lat_min）")
    fallback_map_id: Optional[int] = Field(
        default=None,
        description="兜底地图ID：必须是 local 类型（天地图定位漂移/丢失时切换到的本地地图）",
    )


class MapUpdate(SQLModel):
    """修改地图（管理员调用）：只传需要修改的字段"""
    name: Optional[str] = Field(default=None, description="地图名称")
    description: Optional[str] = Field(default=None, description="地图描述")
    map_type: Optional[str] = Field(default=None, description="地图类型：tianditu / local")
    center_lon: Optional[float] = Field(default=None, description="地图中心经度")
    center_lat: Optional[float] = Field(default=None, description="地图中心纬度")
    zoom: Optional[int] = Field(default=None, description="默认缩放级别")
    lon_min: Optional[float] = Field(default=None, description="区域左边界经度（西）")
    lat_min: Optional[float] = Field(default=None, description="区域下边界纬度（南）")
    lon_max: Optional[float] = Field(default=None, description="区域右边界经度（东）")
    lat_max: Optional[float] = Field(default=None, description="区域上边界纬度（北）")
    left_top_lon: Optional[float] = Field(default=None, description="左上角经度（等价 lon_min）")
    left_top_lat: Optional[float] = Field(default=None, description="左上角纬度（等价 lat_max）")
    right_bottom_lon: Optional[float] = Field(default=None, description="右下角经度（等价 lon_max）")
    right_bottom_lat: Optional[float] = Field(default=None, description="右下角纬度（等价 lat_min）")
    fallback_map_id: Optional[int] = Field(default=None, description="兜底地图ID（必须是 local 类型）")


    @validator("center_lon", "center_lat", "zoom", "lon_min", "lat_min", "lon_max", "lat_max", "left_top_lon", "left_top_lat", "right_bottom_lon", "right_bottom_lat", "fallback_map_id", pre=True)
    def _blank_to_none(cls, value):
        return blank_to_none(value)

class MapTransformIn(SQLModel):
    """设置地图变换（像素 -> 点云）：可缩放/平移/旋转；与其他 update 接口一致，只传要改的字段"""
    scale: Optional[float] = Field(default=None, description="米/像素（必须 > 0）")
    rot_deg: Optional[float] = Field(default=None, description="旋转角 yaw（度，绕 Z 轴，逆时针为正）")
    pitch_deg: Optional[float] = Field(default=None, description="绕 X 轴倾角（度）：正交俯视下表现为纵向压缩+剪切")
    roll_deg: Optional[float] = Field(default=None, description="绕 Y 轴倾角（度）")
    affine: Optional[List[float]] = Field(
        default=None,
        description="仿射矩阵 [a,b,c,d,e,f]：x=a*px+b*py+c，y=d*px+e*py+f；优先级高于 yaw/pitch/roll",
    )
    tx: Optional[float] = Field(default=None, description="图像原点(px=0,py=0) 对应的点云 X（米）")
    ty: Optional[float] = Field(default=None, description="图像原点(px=0,py=0) 对应的点云 Y（米）")
    reset: Optional[bool] = Field(default=None, description="true=清空 tf_*，回退到点云处理生成的 grid_origin_*/grid_resolution")

    @validator("scale", "rot_deg", "pitch_deg", "roll_deg", "tx", "ty", pre=True)
    def _blank_to_none(cls, value):
        return blank_to_none(value)


class MapOut(SQLModel):
    """地图信息（返回结构）"""
    id: int = Field(..., description="地图ID")
    name: str = Field(..., description="地图名称")
    description: Optional[str] = Field(default=None, description="地图描述")
    map_type: str = Field(..., description="地图类型：tianditu=天地图 / local=本地地图")
    center_lon: float = Field(..., description="地图中心经度")
    center_lat: float = Field(..., description="地图中心纬度")
    zoom: int = Field(..., description="默认缩放级别")
    lon_min: Optional[float] = Field(default=None, description="区域左边界经度（西 = 左上角经度）")
    lat_min: Optional[float] = Field(default=None, description="区域下边界纬度（南 = 右下角纬度）")
    lon_max: Optional[float] = Field(default=None, description="区域右边界经度（东 = 右下角经度）")
    lat_max: Optional[float] = Field(default=None, description="区域上边界纬度（北 = 左上角纬度）")
    bounds: Optional[Dict[str, Any]] = Field(default=None, description="区域角点：{left_top:{lon,lat}, right_bottom:{lon,lat}}")
    fallback_map_id: Optional[int] = Field(default=None, description="兜底地图ID（必须是 local 类型）")

    # ===== 点云文件 =====
    pointcloud_file_path: Optional[str] = Field(default=None, description="点云文件磁盘路径")
    pointcloud_file_type: Optional[str] = Field(default=None, description="点云文件类型，如 pcd")
    pointcloud_file_size: Optional[int] = Field(default=None, description="点云文件大小（字节）")
    pointcloud_file_upload_time: Optional[datetime] = Field(default=None, description="点云上传时间")
    pointcloud_file_url: Optional[str] = Field(default=None, description="点云文件访问地址（相对路径，需拼服务地址）")

    # ===== 栅格文件 =====
    grid_file_path: Optional[str] = Field(default=None, description="栅格文件磁盘路径")
    grid_file_type: Optional[str] = Field(default=None, description="栅格文件类型，如 png")
    grid_file_size: Optional[int] = Field(default=None, description="栅格文件大小（字节）")
    grid_file_upload_time: Optional[datetime] = Field(default=None, description="栅格上传时间")
    grid_file_url: Optional[str] = Field(default=None, description="栅格文件访问地址（相对路径）")
    file_url: Optional[str] = Field(default=None, description="兼容字段：有点云取点云地址，否则取栅格地址")

    # ===== 点云/栅格空间信息（点云处理接口自动填充） =====
    pointcloud_point_count: Optional[int] = Field(default=None, description="点云点数（降采样后）")
    pc_min_x: Optional[float] = Field(default=None, description="点云包围盒最小 X（米）")
    pc_max_x: Optional[float] = Field(default=None, description="点云包围盒最大 X（米）")
    pc_min_y: Optional[float] = Field(default=None, description="点云包围盒最小 Y（米）")
    pc_max_y: Optional[float] = Field(default=None, description="点云包围盒最大 Y（米）")
    pc_min_z: Optional[float] = Field(default=None, description="点云包围盒最小 Z（米）")
    pc_max_z: Optional[float] = Field(default=None, description="点云包围盒最大 Z（米）")
    grid_origin_x: Optional[float] = Field(default=None, description="栅格左上角对应的点云 X（米）")
    grid_origin_y: Optional[float] = Field(default=None, description="栅格左上角对应的点云 Y（米）")
    grid_resolution: Optional[float] = Field(default=None, description="栅格分辨率（米/像素）")
    grid_width: Optional[int] = Field(default=None, description="栅格宽度（像素）")
    grid_height: Optional[int] = Field(default=None, description="栅格高度（像素）")

    # ===== 关联统计（列表/详情接口附带） =====
    car_ids: Optional[List[int]] = Field(default=None, description="关联车辆ID列表")
    car_count: Optional[int] = Field(default=None, description="关联车辆数量")
    user_ids: Optional[List[int]] = Field(default=None, description="关联账户ID列表")
    user_count: Optional[int] = Field(default=None, description="关联账户数量")
    path_count: Optional[int] = Field(default=None, description="包含的路线数量")
    created_at: datetime = Field(..., description="创建时间")
