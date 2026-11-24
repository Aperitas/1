"""
在线文档页：把 docs/*.md 渲染成 HTML，方便前端直接在 8001 上实时查看。

- GET /help/map-guide   地图系统说明（Map Guide）
"""
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from core.logger import logger
from utils.md import PAGE_TEMPLATE, render_markdown

router = APIRouter(prefix="/help", tags=["在线文档"])

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"
_cache = {"path": "", "mtime": 0.0, "html": ""}


def _render(filename: str, title: str) -> HTMLResponse:
    """渲染 markdown（按 mtime 缓存，文件改了刷新即可看到最新内容）"""
    path = DOCS_DIR / filename
    if not path.exists():
        return HTMLResponse(
            "<h1>文档不存在</h1><p>缺失文件：%s</p>" % path,
            status_code=404,
        )
    mtime = path.stat().st_mtime
    if _cache["path"] != str(path) or _cache["mtime"] != mtime:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("读取文档失败: %s" % exc)
            return HTMLResponse("<h1>读取文档失败</h1><p>%s</p>" % exc, status_code=500)
        body = render_markdown(text)
        updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        _cache.update({
            "path": str(path),
            "mtime": mtime,
            "html": PAGE_TEMPLATE % {
                "title": title,
                "updated": "文档更新时间：%s" % updated,
                "body": body,
            },
        })
    return HTMLResponse(_cache["html"])


@router.get("/map-guide", response_class=HTMLResponse, summary="地图系统说明（传什么 / 存什么 / 坐标换算）")
async def map_guide():
    """在线展示 docs/map-guide.md：地图文件格式、上传契约、坐标换算、路径与站点字段说明。

    修改 docs/map-guide.md 后刷新本页即可，无需重启服务。
    """
    return _render("map-guide.md", "地图系统说明 · Map Guide")