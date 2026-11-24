"""
统一响应壳：给 FastAPI 的 response_model 使用，让 /docs 能展示 data 的真实字段。

用法：
    @router.get("/", response_model=ApiResponse[List[PathOut]])
"""
from typing import Generic, Optional, TypeVar

from pydantic import Field
from pydantic.generics import GenericModel

T = TypeVar("T")


class ApiResponse(GenericModel, Generic[T]):
    """统一返回结构：{code, msg, data}"""
    code: int = Field(200, description="业务状态码：200=成功，其他见 msg")
    msg: str = Field("Success", description="提示信息")
    data: Optional[T] = Field(None, description="业务数据")