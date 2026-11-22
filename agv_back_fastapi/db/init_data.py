"""
author:dlr123
date:2022年06月12日
"""
import datetime

from core.logger import logger
from core.security import get_password_hash
from crud.user import userCrud
from models.user import Users
from models.user.users import UserRole
from .session import get_session


def init_user():
    with get_session() as session:
        try:
            user = userCrud.get_by_name('admin')
            if user is None:
                adminInfo = Users(id=1,
                                  name='admin',
                                  hashed_password=get_password_hash('123456'),
                                  create_time=datetime.datetime.now() - datetime.timedelta(2000),
                                  isAdmin=True,
                                  role=UserRole.ADMIN.value,
                                  nickname='admin',
                                  email='admin@example.com')
                session.add(adminInfo)
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f'管理者信息初始化失败,因为：{e}')
        else:
            logger.info('管理者信息初始化成功')


async def init_data():
    """ 初始化表数据 """
    init_user()
