from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

class Path(SQLModel, table=True):
    __tablename__ = "paths"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="路线名称，如 '图书馆-实验室'")
    path_type: str = Field(description="路线类型: '吸附道路'/'贝塞尔曲线'/'折线'")

    # 存储有序的节点ID列表（JSON数组）
    node_chain: str = Field(default="[]", description="节点序列，如 [{'type':'site','id':1}, {'type':'waypoint','id':3}]")

    # 可选：关联小车
    car_id: Optional[int] = Field(default=None, foreign_key="cars.id", description="若指定，则此路线专属于某辆车")

    # 是否临时路径（属性/功能与普通路径完全一致，仅用于前端分组与筛选）
    is_temp: bool = Field(default=False, index=True, description="是否临时路径")

    # 所属地图类型（由所属地图自动带入：tianditu=天地图 / local=本地地图）
    map_type: str = Field(default="tianditu", index=True, description="所属地图类型: tianditu / local")

    created_at: Optional[datetime] = Field(default_factory=datetime.now, description="创建时间")
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id", description="所属地图ID（路线必须归属地图）")
    map: Optional["Map"] = Relationship(back_populates="paths")
    def set_nodes(self, nodes: List[Dict[str, any]]):
        self.node_chain = json.dumps(nodes)

    def get_nodes(self) -> List[Dict[str, any]]:
        return json.loads(self.node_chain)