#!/usr/bin/env python3
# _*_ coding: utf-8 _*_
# @Time : 2022/2/25 11:23
# @Author : zxiaosi
# @desc : 登录模型
from pydantic import BaseModel, Field

class Login(BaseModel):
    """ 登录模型（JSON 方式登录） """
    username: str = Field(..., description="账户名（即用户表中的 name，全局唯一）")
    password: str = Field(..., description="明文密码")

