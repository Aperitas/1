"""
车辆视频流（Cars.video_streams 字段）的解析与序列化工具。

数据库里存的是 JSON 字符串，例如：'{"front": "http://39.108.77.178:6010/front"}'。
"""
import json
from typing import Dict, Optional


def parse_streams(raw: Optional[str]) -> Dict[str, str]:
    """把 video_streams（JSON 字符串）解析成字典；为空或非法时返回 {}"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def dump_streams(streams: Optional[Dict[str, str]]) -> str:
    """把视频流字典序列化为 JSON 字符串（URL 原样保存）"""
    return json.dumps(streams or {}, ensure_ascii=False)


def merge_streams(raw: Optional[str], new_streams: Optional[Dict[str, str]]) -> str:
    """把新上报的视频流合并进已有配置（同键覆盖），返回 JSON 字符串

    用于车端上报：避免用空值覆盖管理员配置，也避免冲掉其他视角的地址。
    """
    merged = {**parse_streams(raw), **(new_streams or {})}
    return dump_streams(merged)