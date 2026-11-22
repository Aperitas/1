#!/usr/bin/env python3
# _*_ coding: utf-8 _*_
# @Time : 2021/9/25 22:08
# @Author : zxiaosi
# @desc : 创建与删除所有表, 初始化数据
from sqlalchemy import inspect,text
from sqlmodel import SQLModel
from core.logger import logger
from db import engine


# 历史库自动补列：表名 -> {列名: 列定义}
# 注意：当前使用 SQLite；若切换到 PostgreSQL，布尔列请改成 "BOOLEAN DEFAULT FALSE"
_COLUMN_MIGRATIONS = {
    "users": {"role": "VARCHAR DEFAULT 'guest'", "avatar": "VARCHAR"},
    "sites": {"stop_mode": "VARCHAR DEFAULT 'timed'"},
    "paths": {"is_temp": "BOOLEAN DEFAULT 0"},
    "maps": {
        "map_type": "VARCHAR DEFAULT 'tianditu'",
        "lon_min": "FLOAT", "lat_min": "FLOAT", "lon_max": "FLOAT", "lat_max": "FLOAT",
        "fallback_map_id": "INTEGER",  # 老库不加真实自引用外键（SQLite ALTER 限制），由接口层校验
    },
}

# 补列后需要回填的默认值：表名 -> {列名: 默认值 SQL 字面量}
_COLUMN_BACKFILL = {
    "users": {"role": "'guest'"},
    "sites": {"stop_mode": "'timed'"},
    "paths": {"is_temp": "0"},
    "maps": {"map_type": "'tianditu'"},
}


def _ensure_columns(engine) :
    """ 为历史数据库补齐新增列；SQLModel.metadata.create_all 不会修改已存在的表 """
    try :
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        for table_name,columns in _COLUMN_MIGRATIONS.items() :
            if table_name not in table_names :
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            with engine.begin() as connection :
                for column_name,definition in columns.items() :
                    if column_name in existing :
                        continue
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
                    default_value = _COLUMN_BACKFILL.get(table_name,{}).get(column_name)
                    if default_value is not None :
                        connection.execute(text(
                            f"UPDATE {table_name} SET {column_name} = {default_value} WHERE {column_name} IS NULL"))
                    logger.info(f"{table_name} 表已补充 {column_name} 列")
                # 历史数据：把原来的 isAdmin 标记同步成管理员角色
                if table_name == "users" and "role" in existing | set(columns) :
                    connection.execute(text(
                        "UPDATE users SET role = 'admin' WHERE isAdmin = 1 AND (role IS NULL OR role != 'admin')"))
    except Exception as e :
        logger.error(f"表结构迁移失败（新库可忽略）: {e}")


def _ensure_path_constraints(engine) :
    """ 清理非法路线数据，并建立"每车每图仅一条临时路径"的唯一索引 """
    try :
        inspector = inspect(engine)
        if "paths" not in inspector.get_table_names() :
            return
        columns = {column["name"] for column in inspector.get_columns("paths")}
        if "is_temp" not in columns or "map_id" not in columns :
            return
        with engine.begin() as connection :
            # 1) 路线必须属于地图：删除没有 map_id 的历史数据
            connection.execute(text("DELETE FROM paths WHERE map_id IS NULL"))
            # 2) 临时路径必须属于车辆：删除没有 car_id 的历史数据
            connection.execute(text("DELETE FROM paths WHERE is_temp = 1 AND car_id IS NULL"))
            # 3) 同车同图存在多条临时路径时，只保留最新一条
            connection.execute(text(
                "DELETE FROM paths WHERE is_temp = 1 AND id NOT IN ("
                "SELECT MAX(id) FROM paths WHERE is_temp = 1 GROUP BY car_id, map_id)"))
            # 4) 部分唯一索引：保证每辆车在每张地图内只有一条临时路径
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_paths_temp_car_map "
                "ON paths(car_id, map_id) WHERE is_temp = 1"))
            logger.info("paths 表数据清理与临时路径唯一索引检查完成")
    except Exception as e :
        logger.error(f"paths 表约束处理失败（应用层仍会校验）: {e}")


def init_db(isdrop=False) :
    """ 创建 models/__init__ 下的所有表 """
    try :
        if isdrop :
            drop_db()  # 删除所有的表
        SQLModel.metadata.create_all(engine)  # 创建数据库
        _ensure_columns(engine)  # 兼容历史库：补齐新增列
        _ensure_path_constraints(engine)  # 路线归属清理 + 临时路径唯一索引
        logger.info("创建表成功!!!")
    except Exception as e :
        logger.error(f"创建表失败!!! -- 错误信息如下:\n{e}")
    finally :
        engine.dispose()
        return engine


def drop_db() :
    """ 删除 models/__init__ 下的所有表 """
    try :
        SQLModel.metadata.drop_all(engine)
        logger.info("删除表成功!!!")
    except Exception as e :
        logger.error(f"删除表失败!!! -- 错误信息如下:\n{e}")
    finally :
        engine.dispose()
