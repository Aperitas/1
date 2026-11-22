#!/usr/bin/env python3
# _*_ coding: utf-8 _*_
# @Time : 2021/12/24 14:48
# @Author : zxiaosi
# @desc : token
from typing import Optional
from schemas.user import UserIn
from pydantic import Field
from sqlmodel import SQLModel


class Token(SQLModel):
    """ 登录返回的 token """
    access_token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field(..., description="令牌类型，固定为 bearer")


class TokenInfo(UserIn):
    """ 写入 JWT 的用户信息 """
    id: Optional[int] = Field(default=None, description="用户ID")
    isAdmin: bool = Field(default=False, description="是否管理员（兼容字段，实际以数据库 role 为准）")

