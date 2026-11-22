"""
车辆与地图的多对多关联表（一辆车可属于多张地图，一张地图也可拥有多辆车）。
"""
from typing import Optional

from sqlmodel import SQLModel, Field


class CarMapLink(SQLModel, table=True):
    __tablename__ = "carmap"

    car_id: Optional[int] = Field(default=None, foreign_key="cars.id", primary_key=True)
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id", primary_key=True)