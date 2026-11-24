#!/usr/bin/env python3
# _*_ coding: utf-8 _*_
# @Time : 2021/9/19 17:02
# @Author : zxiaosi
# @desc : 配置文件
import secrets
from typing import Union, List
from pydantic import BaseSettings, AnyHttpUrl
import os

project_desc = """
    🎉 AGV 调度系统后端接口 🎉
    ✨ 演示账号: admin / 123456 ✨

    【用户角色】
    - admin：管理员，最高权限（用户 / 地图 / 路线 / 小车管理 + 调度指令）
    - dispatcher：调度员，可查看数据并下发调度指令，不能修改资源
    - guest：游客，只读（只能看到自己负责的地图及其下属数据）

    【地图类型 map_type】
    - tianditu：天地图，用左上/右下两个经纬度角点（left_top_* / right_bottom_*）限定区域
    - local：本地地图，同一地点的「点云 + 栅格」绑定在一条记录里；点云/栅格各自上传（上传接口 kind=pointcloud|grid）

    【地图区域坐标】
    - 可用 left_top_lon/left_top_lat + right_bottom_lon/right_bottom_lat（左上/右下）传入；
    - 也可用 lon_min/lat_min/lon_max/lat_max；不传则不校验（后续可补录）；
    - 返回中额外提供 bounds.left_top / bounds.right_bottom。

    【路线 / 临时路径】
    - 每条路线记录所属地图类型 map_type（tianditu / local），可按此筛选
    - 普通路径 is_temp=false：同一车辆/地图可有多条
    - 临时路径 is_temp=true：必须指定 car_id，且每辆车在每张地图内只能有一条（重复创建会自动覆盖）

    【站点停靠模式 stop_mode】
    - timed：等一段时间自动走（时长由 dwell_time 秒控制）
    - wait_command：车端发命令才走（车端调用 POST /report/site_depart 或调度端下发 depart 指令）

【接口文档说明】
- 每个接口的 description 里内嵌了《地图系统说明》的对应章节（含义 / 传什么 / 存什么 / 示例）
- 例如：`PUT /admin/maps/{id}/transform` 的描述就是「地图变换（三轴 + 仿射）」整章
- 源码文档：docs/map-guide.md（与 /docs 描述同源）
"""


class Settings(BaseSettings):
    PROJECT_DESC: str = project_desc  # 描述
    PROJECT_VERSION: Union[int, str] = 1.0  # 版本
    PROJECT_ROOT_PATH: str = os.path.abspath('./')
    BASE_URL: AnyHttpUrl = "http://127.0.0.1:8000"  # 开发环境

    API_PREFIX: str = "/api"  # 接口前缀
    STATIC_DIR: str = 'static'  # 静态文件目录
    GLOBAL_ENCODING: str = 'utf-8'  # 全局编码
    CORS_ORIGINS: List[str] = ["*"]  # 跨域请求

    SECRET_KEY: str = secrets.token_urlsafe(32)  # 密钥(每次重启服务密钥都会改变, token解密失败导致过期, 可设置为常量)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 1  # token过期时间: 60 minutes * 24 hours * 1 days = 1 days

    # REDIS_URI: str = "redis://:123456@localhost:6379/1"  # redis
    DATABASE_URI: str = "sqlite:///./sql_app.db?check_same_thread=False"  # Sqlite(同步)
    # DATABASE_URI: str = "sqlite+aiosqlite:///./sql_app.db?check_same_thread=False"  # Sqlite(异步)
    # DATABASE_URI: str = "mysql+asyncmy://root:123456@localhost:3306/elective_system?charset=utf8"  # MySQL(异步)
    # DATABASE_URI: str = "postgresql+asyncpg://postgres:123456@localhost:5432/postgres"  # PostgreSQL(异步)
    DATABASE_ECHO: bool = False  # 是否打印数据库日志 (可看到创建表、表数据增删改查的信息)

    LOGGER_DIR: str = "logs"  # 日志文件夹名
    LOGGER_NAME: str = '{time:YYYY-MM-DD_HH-mm-ss}.log'  # 日志文件名 (时间格式)
    LOGGER_LEVEL: str = 'DEBUG'  # 日志等级: ['DEBUG' | 'INFO']
    LOGGER_ROTATION: str = "12:00"  # 日志分片: 按 时间段/文件大小 切分日志. 例如 ["500 MB" | "12:00" | "1 week"]
    LOGGER_RETENTION: str = "7 days"  # 日志保留的时间: 超出将删除最早的日志. 例如 ["1 days"]
        
    TIANDITU_KEY: str = "c6fbb80be2f3c2677985f6d44683437d"  # 天地图服务器端 Key


    class Config:
        case_sensitive = True  # 区分大小写


settings = Settings()
