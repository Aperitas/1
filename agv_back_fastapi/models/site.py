from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict, Any
from datetime import datetime

class Site(SQLModel, table=True):
    __tablename__ = "sites"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="站点名称，如 '图书馆站'")
    lon: float = Field(description="经度")
    lat: float = Field(description="纬度")
    dwell_time: Optional[int] = Field(default=0, description="停靠时间（秒），0表示不停靠")
    description: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    map_id: Optional[int] = Field(default=None, foreign_key="maps.id")
    map: Optional["Map"] = Relationship(back_populates="sites")