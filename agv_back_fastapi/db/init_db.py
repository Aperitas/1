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
}

# 补列后需要回填的默认值：表名 -> {列名: 默认值 SQL 字面量}
_COLUMN_BACKFILL = {
    "users": {"role": "'guest'"},
    "sites": {"stop_mode": "'timed'"},
    "paths": {"is_temp": "0"},
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


def init_db(isdrop=False) :
    """ 创建 models/__init__ 下的所有表 """
    try :
        if isdrop :
            drop_db()  # 删除所有的表
        SQLModel.metadata.create_all(engine)  # 创建数据库
        _ensure_columns(engine)  # 兼容历史库：补齐新增列
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
