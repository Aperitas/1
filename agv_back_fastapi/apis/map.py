import os
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from core.config import settings

router = APIRouter(prefix="/api/map", tags=["地图瓦片代理"])

LAYERS = {"vec": "vec_w", "cva": "cva_w"}
SUBDOMAINS = [f"t{i}" for i in range(8)]

# 全局客户端，复用连接池
client = httpx.AsyncClient(timeout=10.0)

@router.get("/tiles/{layer}/{z}/{x}/{y}.png", summary="天地图瓦片代理")
async def map_tile(layer: str, z: int, x: int, y: int) -> Response:
    upstream_layer = LAYERS.get(layer)
    # 限制只允许 vec 和 cva 图层，且 z 范围 1-18
    if upstream_layer is None or not 1 <= z <= 18:
        raise HTTPException(status_code=404, detail="tile not found")

    # 轮询子域名，提高加载速度
    host = SUBDOMAINS[(x + y) % len(SUBDOMAINS)]
    
    # 拼接请求，注意这里使用的是 settings.TIANDITU_KEY
    url = (
        f"https://{host}.tianditu.gov.cn/{upstream_layer}/wmts"
        "?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles"
        f"&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={settings.TIANDITU_KEY}"
    )

    try:
        upstream = await client.get(url)
    except httpx.HTTPError as exc:
        # 不要把错误详情抛给前端，防止泄露 Key
        raise HTTPException(status_code=502, detail="tile upstream error") from exc

    content_type = upstream.headers.get("content-type", "")
    # 校验上游返回的是否真的是图片
    if upstream.status_code != 200 or not content_type.startswith("image/"):
        raise HTTPException(status_code=502, detail="tile upstream error")

    # 返回图片字节，并加上缓存头，减轻服务器压力
    return Response(
        content=upstream.content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},  # 缓存 7 天
    )