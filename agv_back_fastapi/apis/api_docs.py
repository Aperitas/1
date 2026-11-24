"""
OpenAPI 文档正文（给 /docs 用）。

设计：**不重复维护**——直接从仓库里的 `docs/map-guide.md` 按章节抽取 markdown，
再挂到各接口的 `description` 上。Swagger UI 会把 markdown 渲染成表格/代码块，
所以前端在 /docs 里点开某个接口，就能看到 map-guide 里对应的那一章。

改文档只需改 `docs/map-guide.md`，重启服务即生效（读取带 mtime 缓存）。
"""
from pathlib import Path
from typing import Dict, List, Tuple

DOC_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "map-guide.md"

_cache: Dict[str, object] = {"mtime": 0.0, "text": "", "blocks": []}


def _load() -> List[Tuple[str, str]]:
    """读取并切成 [(标题, 正文)]，按文件 mtime 缓存"""
    try:
        mtime = DOC_PATH.stat().st_mtime
    except OSError:
        return []
    if _cache["mtime"] == mtime and _cache["blocks"]:
        return _cache["blocks"]  # type: ignore[return-value]

    try:
        text = DOC_PATH.read_text(encoding="utf-8")
    except OSError:
        return []

    blocks: List[Tuple[str, str]] = []
    head, body = None, []
    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if head is not None:
                blocks.append((head, "\n".join(body).strip()))
            head, body = line, []
        elif head is not None:
            body.append(line)
    if head is not None:
        blocks.append((head, "\n".join(body).strip()))

    _cache.update({"mtime": mtime, "text": text, "blocks": blocks})
    return blocks


def section(*prefixes: str) -> str:
    """按标题前缀取章节（如 "## 15."、"### 17.3"），多个章节用分隔线拼接

    注意：命中 `## N.` 时会把其下所有 `### N.x` 子章节**一起带上**，否则只会拿到标题下的一小段。
    找不到时返回空串（接口描述会退回默认 docstring）。
    """
    blocks = _load()
    picked: List[str] = []
    for prefix in prefixes:
        start = None
        for i, (head, _body) in enumerate(blocks):
            if head.startswith(prefix):
                start = i
                break
        if start is None:
            continue

        head0, body0 = blocks[start]
        parts: List[str] = [head0, body0]
        if head0.startswith("## "):
            # 继续收集其下的 ### 子章节，直到下一个 ## 标题
            for j in range(start + 1, len(blocks)):
                nxt_head, nxt_body = blocks[j]
                if nxt_head.startswith("## "):
                    break
                parts.append(nxt_head + "\n\n" + nxt_body)
        picked.append("\n\n".join(x for x in parts if x).strip())
    return "\n\n---\n\n".join(picked)


# ===== 章节常量（供各路由的 description= 使用） =====
MAP_CONCEPT = section("## 1.")
MAP_FIELDS = section("## 2.")
MAP_ENDPOINTS = section("## 3.")
MAP_UPLOAD = section("## 4.")
GRID_CONTRACT = section("## 5.")
POINTCLOUD_NOTE = section("## 6.")
PERMISSIONS = section("## 7.")
FAQ = section("## 8.")
MAP_PROCESS = section("## 10.")
MAP_COORDS = section("## 11.")
CAR_POINTS = section("## 12.")
PATH_MAP_INFO = section("## 13.")
RESP_SHAPE = section("## 14.")
MAP_TRANSFORM = section("## 15.")
POINT_NODES = section("## 16.")
FIELD_CHEATSHEET = section("## 17.")
SITE_FIELDS = section("### 17.5", "### 17.6")
PATH_FIELDS = section("### 17.3", "### 17.4", "### 17.7", "### 17.8", "### 17.9")
ONLINE_DOC = section("## 18.")
NODE_TYPES = section("### 16.2")
PATH_TABLE = section("### 17.7")

# 路线创建/修改：节点类型说明 + 字段表
PATH_CREATE_DESC = "\n\n---\n\n".join(x for x in (POINT_NODES, NODE_TYPES, PATH_TABLE) if x)
PATH_UPDATE_DESC = PATH_CREATE_DESC
MAP_ONE_SHOT = section("## 19.")
CAR_POSE = section("## 20.")
MAP_ROS = section("## 21.")
GRID_FLIP = section("### 5.4")
SELF_TEST = section("## 22.")

# 栅格重画/翻转：§5.4 说明 + §22 自测方法
GRID_REGENERATE_DESC = "\n\n---\n\n".join(x for x in (GRID_FLIP, SELF_TEST) if x)


# 接口列表共用（地图列表 / 详情）
MAP_READ = "\n\n---\n\n".join(x for x in (MAP_FIELDS, GRID_CONTRACT) if x)
MAP_WRITE = "\n\n---\n\n".join(x for x in (MAP_FIELDS, FIELD_CHEATSHEET) if x)


# ===== Swagger 分组说明（app = FastAPI(openapi_tags=OPENAPI_TAGS)） =====
OPENAPI_TAGS = [
    {"name": "地图管理", "description": "地图 CRUD、点云/栅格文件、点云处理、坐标换算、地图变换、ROS 地图导出。细节见各接口描述。"},
    {"name": "路线管理", "description": "路线与节点的存取；`node_chain` 支持 site / waypoint / point 三种节点。"},
    {"name": "站点管理", "description": "停靠站点；坐标可传经纬度或**点云坐标**（pc_x/pc_y）。"},
    {"name": "路径点管理", "description": "路线的几何节点；坐标可传经纬度或**点云坐标**。"},
    {"name": "车端上报", "description": "车端定时上报经纬度/电量/速度/视频流，以及**局部点云位姿** pc_x/pc_y/pc_yaw。"},
    {"name": "用户管理", "description": "账户 CRUD、角色、地图可见范围。"},
    {"name": "小车管理", "description": "车辆 CRUD、视频流、指令下发、路线坐标下发。"},
    {"name": "认证登录", "description": "登录/登出/注册/邮箱验证码。"},
    {"name": "公共接口", "description": "健康检查等公共接口。"},
    {"name": "个人中心", "description": "登录者自己的资料、密码、头像。"},
    {"name": "实时通信", "description": "WebSocket：`/ws/map` 位置广播、`/ws/command` 车端指令通道。"},
]