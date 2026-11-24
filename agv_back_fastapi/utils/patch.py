"""
部分更新（PATCH 语义）辅助工具。

所有「修改」类接口统一约定：
- 只处理前端显式传入的字段（Pydantic v1：data.dict(exclude_unset=True)）；
- 传 null（None）  -> 视为「不修改」，直接忽略；
- 传空字符串 ""    -> 视为「不修改」，直接忽略；
- 例外：字段名在 allow_null 白名单里时，传 null / 空串表示「清空该字段」
  （例如 description、avatar 这类可空文本字段）；
- 容器类型（list / dict）不受影响：[] / {} 仍然表示显式清空。
"""
from typing import Any, Dict, Iterable


def clean_update(data, *, allow_null: Iterable[str] = ()) -> Dict[str, Any]:
    """把「部分更新」请求体清洗成真正需要写入数据库的字段字典。

    :param data: Pydantic 模型实例（update 请求体）
    :param allow_null: 允许显式置空（null 或 ""）的字段名集合
    :return: 需要更新的字段字典；调用方直接 setattr 即可
    """
    allow = set(allow_null)
    cleaned: Dict[str, Any] = {}
    for key, value in data.dict(exclude_unset=True).items():
        if key in allow:
            cleaned[key] = value
            continue
        if value is None:
            continue  # 没填 / 传 null -> 保持原值
        if isinstance(value, str) and value == "":
            continue  # 空串 -> 保持原值
        cleaned[key] = value
    return cleaned