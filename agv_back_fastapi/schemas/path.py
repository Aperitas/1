from sqlmodel import SQLModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# ---------- 站点 ----------
class SiteCreate(SQLModel):
    """新增站点（管理员）：站点是路线上的停靠点，可配置停靠模式"""
    name: str = Field(..., description="站点名称，如 '图书馆站'")
    lon: float = Field(..., description="站点经度")
    lat: float = Field(..., description="站点纬度")
    dwell_time: Optional[int] = Field(default=0, description="停靠时长（秒），仅 stop_mode=timed 时生效")
    stop_mode: str = Field(
        default="timed",
        description="停靠模式：timed=等一段时间自动走（类似地铁） / wait_command=车端发命令才走（类似观光车）",
    )
    description: Optional[str] = Field(default=None, description="站点备注")
    map_id: int = Field(..., description="所属地图ID")

class SiteUpdate(SQLModel):
    """修改站点（管理员）：只传需要修改的字段"""
    name: Optional[str] = Field(default=None, description="站点名称")
    lon: Optional[float] = Field(default=None, description="站点经度")
    lat: Optional[float] = Field(default=None, description="站点纬度")
    dwell_time: Optional[int] = Field(default=None, description="停靠时长（秒），仅 stop_mode=timed 时生效")
    stop_mode: Optional[str] = Field(default=None, description="停靠模式：timed / wait_command")
    description: Optional[str] = Field(default=None, description="站点备注")
    map_id: Optional[int] = Field(default=None, description="所属地图ID")

class SiteOut(SQLModel):
    """站点信息（返回结构）"""
    id: int = Field(..., description="站点ID")
    name: str = Field(..., description="站点名称")
    lon: float = Field(..., description="站点经度")
    lat: float = Field(..., description="站点纬度")
    dwell_time: int = Field(..., description="停靠时长（秒）")
    stop_mode: str = Field(..., description="停靠模式：timed / wait_command")
    description: Optional[str] = Field(default=None, description="站点备注")
    map_id: int = Field(..., description="所属地图ID")
    created_at: datetime = Field(..., description="创建时间")

# ---------- 路径点 ----------
class WaypointCreate(SQLModel):
    """新增路径点（管理员）：路径点是地图上标定的坐标点，可用于组成路线"""
    name: str = Field(..., description="路径点名称，如 'A点'")
    lon: float = Field(..., description="经度")
    lat: float = Field(..., description="纬度")
    description: Optional[str] = Field(default=None, description="备注")
    map_id: int = Field(..., description="所属地图ID")

class WaypointUpdate(SQLModel):
    """修改路径点（管理员）：只传需要修改的字段"""
    name: Optional[str] = Field(default=None, description="路径点名称")
    lon: Optional[float] = Field(default=None, description="经度")
    lat: Optional[float] = Field(default=None, description="纬度")
    description: Optional[str] = Field(default=None, description="备注")
    map_id: Optional[int] = Field(default=None, description="所属地图ID")

class WaypointOut(SQLModel):
    """路径点信息（返回结构）"""
    id: int = Field(..., description="路径点ID")
    name: str = Field(..., description="路径点名称")
    lon: float = Field(..., description="经度")
    lat: float = Field(..., description="纬度")
    description: Optional[str] = Field(default=None, description="备注")
    map_id: int = Field(..., description="所属地图ID")
    created_at: datetime = Field(..., description="创建时间")

# ---------- 路线 ----------
class PathCreate(SQLModel):
    """新增路线（管理员）：路线必须归属一张地图"""
    name: str = Field(..., description="路线名称，如 '图书馆-实验室'")
    path_type: str = Field(..., description="路线类型：'吸附道路' / '贝塞尔曲线' / '折线'")
    node_chain: List[Dict[str, Any]] = Field(
        ...,
        description="有序节点序列，元素形如 {\"type\":\"site\",\"id\":1} 或 {\"type\":\"waypoint\",\"id\":3}",
    )
    car_id: Optional[int] = Field(default=None, description="指定该路线专属的车辆ID（不传则通用）")
    map_id: int = Field(..., description="所属地图ID（必填）")
    is_temp: bool = Field(
        default=False,
        description=(
            "是否临时路径：true=临时路径（必须传 car_id，且同一车辆在同一地图内只能有一条，"
            "重复创建会自动覆盖） / false=普通路径"
        ),
    )

class PathUpdate(SQLModel):
    """修改路线（管理员）：只传需要修改的字段"""
    name: Optional[str] = Field(default=None, description="路线名称")
    path_type: Optional[str] = Field(default=None, description="路线类型：'吸附道路' / '贝塞尔曲线' / '折线'")
    node_chain: Optional[List[Dict[str, Any]]] = Field(default=None, description="有序节点序列")
    car_id: Optional[int] = Field(default=None, description="专属车辆ID")
    map_id: Optional[int] = Field(default=None, description="所属地图ID")
    is_temp: Optional[bool] = Field(default=None, description="是否临时路径")

class PathOut(SQLModel):
    """路线信息（返回结构）"""
    id: int = Field(..., description="路线ID")
    name: str = Field(..., description="路线名称")
    path_type: str = Field(..., description="路线类型")
    node_chain: List[Dict[str, Any]] = Field(..., description="有序节点序列（已从 JSON 字符串转为对象）")
    car_id: Optional[int] = Field(default=None, description="专属车辆ID")
    map_id: int = Field(..., description="所属地图ID")
    map_type: str = Field(..., description="所属地图类型：tianditu=天地图 / local=本地地图")
    is_temp: bool = Field(..., description="是否临时路径")
    created_at: datetime = Field(..., description="创建时间")