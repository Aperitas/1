from sqlmodel import SQLModel
from typing import Optional

class CarCommandIn(SQLModel):
    command: str  # start / stop / pause / resume / goto
    path_id: Optional[int] = None
    params: Optional[dict] = None