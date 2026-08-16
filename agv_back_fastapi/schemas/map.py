from sqlmodel import SQLModel
from typing import Optional
from datetime import datetime

class MapCreate(SQLModel):
    name: str
    description: Optional[str] = None
    center_lon: float = 113.9686
    center_lat: float = 22.6042
    zoom: int = 17

class MapUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    center_lon: Optional[float] = None
    center_lat: Optional[float] = None
    zoom: Optional[int] = None

class MapOut(SQLModel):
    id: int
    name: str
    description: Optional[str]
    center_lon: float
    center_lat: float
    zoom: int
    created_at: datetime