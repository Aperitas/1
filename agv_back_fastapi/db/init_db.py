#!/usr/bin/env python3
# _*_ coding: utf-8 _*_
# @Time : 2021/9/25 22:08
# @Author : zxiaosi
# @desc : 创建与删除所有表, 初始化数据
from sqlalchemy import inspect,text
from sqlmodel import SQLModel
from core.logger import logger
from db import engine


def _ensure_user_columns(engine) :
    """ 为历史数据库补齐新增列（role/avatar）；create_all 不会修改已存在的表 """
    try :
        inspector = inspect(engine)
        if "users" not in inspector.get_table_names() :
            return
        columns = {column["name"] for column in inspector.get_columns("users")}
        with engine.begin() as connection :
            if "role" not in columns :
                connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'guest'"))
                connection.execute(text("UPDATE users SET role = 'guest' WHERE role IS NULL"))
                logger.info("users 表已补充 role 列")
            if "avatar" not in columns :
                connection.execute(text("ALTER TABLE users ADD COLUMN avatar VARCHAR"))
                logger.info("users 表已补充 avatar 列")
            # 历史数据：把原来的 isAdmin 标记同步成管理员角色
            connection.execute(text("UPDATE users SET role = 'admin' WHERE isAdmin = 1 AND (role IS NULL OR role != 'admin')"))
    except Exception as e :
        logger.error(f"用户表结构迁移失败（新库可忽略）: {e}")


def init_db(isdrop=False) :
    """ 创建 models/__init__ 下的所有表 """
    try :
        if isdrop :
            drop_db()  # 删除所有的表
        SQLModel.metadata.create_all(engine)  # 创建数据库
        _ensure_user_columns(engine)  # 兼容历史库：补齐 users.role / users.avatar
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
