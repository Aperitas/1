"""
author:dlr123
date:2022年05月31日
"""
from fastapi import APIRouter

admin_api = APIRouter()
from .users import user_api
from .car import car_api

admin_api.include_router(user_api,tags=['Users'])
admin_api.include_router(car_api,tags=['Cars'])
