"""
访问控制辅助：按"账户负责的地图"（UserMapLink）过滤可见数据。
管理员（admin）可见全部；调度/游客只能看到自己关联的地图及其下属数据。
"""
from typing import Optional, Set

from sqlmodel import Session, select

from models.user.users import Users, UserRole
from models.user.map_link import UserMapLink


def visible_map_ids(session: Session, user: Users) -> Optional[Set[int]] :
    """ 返回账户可见的地图 id 集合；管理员返回 None（表示全部可见） """
    if user.effective_role == UserRole.ADMIN.value :
        return None
    return set(session.exec(select(UserMapLink.map_id).where(UserMapLink.user_id == user.id)).all())


def can_access_map(session: Session, user: Users, map_id: Optional[int]) -> bool :
    """ 判断账户是否可访问指定地图 """
    visible = visible_map_ids(session, user)
    if visible is None :
        return True
    return map_id is not None and map_id in visible


def normalize_ids(ids) -> list :
    """ 去重并保持顺序 """
    return list(dict.fromkeys(ids or []))