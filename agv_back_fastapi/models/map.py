from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
from enum import Enum

from models.user import Users
from models.user.map_link import UserMapLink
from models.car.map_link import CarMapLink


class MapType(str, Enum):
    """地图类型

    - TIANDITU(tianditu)：天地图（矢量/影像瓦片），用左上/右下两个经纬度角点限定区域
    - LOCAL(local)：本地地图，同一地点的「点云 + 栅格」两两绑定在一条记录里，
      并保存左上/右下经纬度，用于把该图叠加到天地图上
    """
    TIANDITU = "tianditu"
    LOCAL = "local"


class Map(SQLModel, table=True):
    __tablename__ = "maps"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="地图名称，如'南科大校园'")
    description: Optional[str] = Field(default=None, description="描述")
    center_lon: float = Field(default=113.9686, description="地图中心经度")
    center_lat: float = Field(default=22.6042, description="地图中心纬度")
    zoom: int = Field(default=17, description="默认缩放级别")
    # ===== 地图类型与区域（左上 / 右下 两个角点） =====
    map_type: str = Field(default=MapType.TIANDITU.value, index=True,
                          description="地图类型: tianditu=天地图, local=本地地图（点云+栅格）")
    lon_min: Optional[float] = Field(default=None, description="区域左边界经度（左上经度 = 西边界）")
    lat_min: Optional[float] = Field(default=None, description="区域下边界纬度（右下纬度 = 南边界）")
    lon_max: Optional[float] = Field(default=None, description="区域右边界经度（右下经度 = 东边界）")
    lat_max: Optional[float] = Field(default=None, description="区域上边界纬度（左上纬度 = 北边界）")
    # ===== 定位漂移/丢失时的兜底地图（一般为天地图指向一张本地地图） =====
    fallback_map_id: Optional[int] = Field(default=None, foreign_key="maps.id",
                                           description="兜底地图ID：必须是 local 类型（天地图漂移时切换到的本地地图）")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    # ===== 本地地图（local）：点云 + 栅格两套文件 =====
    pointcloud_file_path: Optional[str] = Field(default=None, description="点云文件存储路径")
    pointcloud_file_type: Optional[str] = Field(default=None, description="点云文件类型，如 pcd/ply/zip")
    pointcloud_file_size: Optional[int] = Field(default=None, description="点云文件大小（字节）")
    pointcloud_file_upload_time: Optional[datetime] = Field(default=None, description="点云文件上传时间")
    grid_file_path: Optional[str] = Field(default=None, description="栅格文件存储路径")
    grid_file_type: Optional[str] = Field(default=None, description="栅格文件类型，如 png/tif/zip")
    grid_file_size: Optional[int] = Field(default=None, description="栅格文件大小（字节）")
    grid_file_upload_time: Optional[datetime] = Field(default=None, description="栅格文件上传时间")
    # ===== 点云/栅格的空间信息（由「点云处理」接口自动填充，用于坐标换算） =====
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

    # ===== 地图变换（栅格像素 <-> 点云米）：为空时回退到 grid_origin_* / grid_resolution =====
    tf_scale: Optional[float] = Field(default=None, description="变换：米/像素（为空则用 grid_resolution）")
    tf_rot_deg: Optional[float] = Field(default=None, description="变换：旋转角（度，逆时针为正；为空则 0）")
    tf_tx: Optional[float] = Field(default=None, description="变换：图像原点(px=0,py=0) 对应的点云 X（为空则用 grid_origin_x）")
    tf_ty: Optional[float] = Field(default=None, description="变换：图像原点(px=0,py=0) 对应的点云 Y（为空则用 grid_origin_y）")
    tf_pitch_deg: Optional[float] = Field(default=None, description="变换：绕 X 轴倾角（度，正交俯视下等价于纵向剪切+压缩）")
    tf_roll_deg: Optional[float] = Field(default=None, description="变换：绕 Y 轴倾角（度）")
    tf_affine: Optional[str] = Field(default=None, description="变换：仿射矩阵 JSON [a,b,c,d,e,f]，等效 x=a*px+b*py+c, y=d*px+e*py+f；设置后优先级高于 yaw/pitch/roll")
    # ===== 栅格镜像（生成时就翻转，并体现在「像素->点云」变换里，坐标换算自动跟着变） =====
    grid_flip_x: bool = Field(default=False, description="栅格是否左右镜像（翻转后图像第 0 列 = max_x）")
    grid_flip_y: bool = Field(default=False, description="栅格是否上下镜像（翻转后图像第 0 行 = min_y）")
    # ===== 以下为历史字段（早期单文件版本），保留但不再读写 =====
    file_path: Optional[str] = Field(default=None, description="历史字段：早期地图文件路径")
    file_type: Optional[str] = Field(default=None, description="历史字段：早期地图文件类型")
    file_size: Optional[int] = Field(default=None, description="历史字段：早期文件大小（字节）")
    upload_time: Optional[datetime] = Field(default=None, description="历史字段：早期上传时间")
    # ================================================================


    # 关系
    sites: List["Site"] = Relationship(back_populates="map")
    waypoints: List["Waypoint"] = Relationship(back_populates="map")
    paths: List["Path"] = Relationship(back_populates="map")
    # ===== 账户（多对多：一张地图可由多个账户负责） =====
    users: List["Users"] = Relationship(back_populates="maps", link_model=UserMapLink)
    # ================================================
    # ===== 地图拥有的车辆（多对多） =====
    cars: List["Cars"] = Relationship(back_populates="maps", link_model=CarMapLink)
    # ===================================