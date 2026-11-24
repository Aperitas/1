# 地图系统说明（后端 / 前端对接用）

> 适用版本：`agv_back_fastapi`（FastAPI + SQLModel）
> 最后更新：2026-11-25

## 1. 概念

一张「地图」= 一条 `maps` 记录 + 最多两个文件槽位：

| 槽位 | 字段前缀 | 用途 | 支持的格式 |
|---|---|---|---|
| 点云 | `pointcloud_file_*` | 三维点云（建图产物） | `.pcd` `.ply` `.las` `.laz` `.xyz` `.zip` |
| 栅格 | `grid_file_*` | 二维俯视底图（前端贴图） | `.png` `.jpg` `.jpeg` `.webp` `.bmp` `.gif` `.tif` `.tiff` |

`map_type` 只有两种：

- `tianditu`：天地图，只用「左上/右下」两个经纬度角点圈定区域，不需要文件；
- `local`：本地地图，「点云 + 栅格」绑在一条记录里，可只传一个，之后补传。

> 栅格文件对后端只是一个**静态文件**：不解析像素、不含 EPSG/GeoTIFF 地理参考。
> 地理配准完全靠 `bounds`（左上/右下两个经纬度）——详见第 5 节。

## 2. 返回字段

`GET /admin/maps/{map_id}`：

```json
{
  "code": 200,
  "msg": "Success",
  "data": {
    "id": 1,
    "name": "轮椅场地",
    "description": "一楼大厅",
    "map_type": "local",
    "center_lon": 113.972,
    "center_lat": 22.602,
    "zoom": 18,
    "lon_min": 113.9680,
    "lat_min": 22.5980,
    "lon_max": 113.9760,
    "lat_max": 22.6060,
    "pointcloud_file_url": "/static/maps/map_1_pc_scans.pcd",
    "pointcloud_file_type": "pcd",
    "pointcloud_file_size": 45678901,
    "pointcloud_file_upload_time": "2026-11-24T20:10:00",
    "grid_file_url": "/static/maps/map_1_grid_floor.png",
    "grid_file_type": "png",
    "grid_file_size": 245311,
    "grid_file_upload_time": "2026-11-24T20:12:00",
    "file_url": "/static/maps/map_1_pc_scans.pcd",
    "fallback_map_id": null,
    "bounds": {
      "left_top":     { "lon": 113.9680, "lat": 22.6060 },
      "right_bottom": { "lon": 113.9760, "lat": 22.5980 }
    },
    "car_ids": [3, 4],
    "car_count": 2,
    "user_ids": [2],
    "user_count": 1,
    "path_count": 3,
    "created_at": "2026-11-24T20:00:00"
  }
}
```

| 字段 | 说明 |
|---|---|
| `map_type` | `tianditu` 天地图 / `local` 本地地图 |
| `lon_min/lat_min/lon_max/lat_max` | 区域矩形：西 / 南 / 东 / 北 |
| `bounds` | 上面四个值的封装；四个值齐全时才返回，否则为 `null` |
| `pointcloud_file_url` / `grid_file_url` | **相对路径**，需拼服务地址：`http://<host>:8001 + <url>` |
| `file_url` | **兼容字段**：有点云时返回点云地址，否则返回栅格。**取栅格请用 `grid_file_url`** |
| `fallback_map_id` | 兜底地图（必须 `local`），天地图定位漂移时切到它 |
| `car_ids` / `user_ids` / `path_count` | 关联车辆、账户、路线数量（列表与详情才有） |

## 3. 接口清单

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/admin/maps/` | 地图列表（可按 `map_type` 过滤，按可见范围裁剪） | 登录用户 |
| GET | `/admin/maps/{id}` | 地图详情 | 登录用户（不可见返回 400） |
| POST | `/admin/maps/` | 新建地图 | 管理员 |
| PUT | `/admin/maps/{id}` | 修改（只传要改的字段） | 管理员 |
| POST | `/admin/maps/upload` | 上传点云 / 栅格文件 | 管理员 |
| DELETE | `/admin/maps/{id}/files/{kind}` | 删除某一类文件（`pointcloud` / `grid`） | 管理员 |
| DELETE | `/admin/maps/{id}` | 删除地图（有站点/路径点/普通路线时拒绝） | 管理员 |
| GET | `/admin/maps/{id}/cars` | 地图上的车 | 登录用户 |
| GET | `/admin/maps/{id}/paths` | 地图上的路线 | 登录用户 |
| GET | `/admin/maps/{id}/users` | 地图关联账户 | 管理员 |
| GET | `/api/cars/{car_id}/maps` | 某台车绑定地图（含文件地址与 bounds） | 登录用户 |

静态文件：`GET /static/maps/{filename}`（`/static` 由 StaticFiles 挂载，CORS 走全局中间件）。

> 注意：地图相关接口**没有 `/api` 前缀**（是 `/admin/maps/...`）；只有 `/api/cars/...`、`/api/oauth/...`、`/api/user/...`、`/api/profile` 带 `/api`。

## 4. 上传契约

```http
POST /admin/maps/upload
Content-Type: multipart/form-data

map_id=1
kind=grid                       # grid | pointcloud
file=@floor.png                 # 见下方白名单
```

- `kind=grid` → 栅格槽位，允许 `.png .jpg .jpeg .webp .bmp .gif .tif .tiff`
- `kind=pointcloud` → 点云槽位，允许 `.pcd .ply .las .laz .xyz .zip`
- 保存为 `static/maps/map_{id}_{pc|grid}_{安全文件名}**，同类型重复上传会删掉旧文件
- 空文件（0 字节）直接拒绝；大小无硬限制（建议栅格 ≤ 5 MB、点云 ≤ 200 MB）
- 返回：

```json
{
  "code": 200,
  "msg": "栅格文件上传成功",
  "data": {
    "map_id": 1,
    "kind": "grid",
    "file_type": "png",
    "content_type": "image/png",
    "file_size": 245311,
    "file_url": "/static/maps/map_1_grid_floor.png"
  }
}
```

## 5. 栅格格式约定（重点）

### 5.1 地理配准

| 图片位置 | 对应经纬度 |
|---|---|
| 上边缘 | `lat_max`（`bounds.left_top.lat`） |
| 下边缘 | `lat_min`（`bounds.right_bottom.lat`） |
| 左边缘 | `lon_min`（`bounds.left_top.lon`） |
| 右边缘 | `lon_max`（`bounds.right_bottom.lon`） |

- **无旋转、无倾斜、无投影**：像素在经纬度矩形内均匀分布；
- 每像素：`Δlon = (lon_max - lon_min) / img.width`，`Δlat = (lat_max - lat_min) / img.height`；
- 经纬度 → 图上像素：`px = (lon - lon_min) / Δlon`，`py = (lat_max - lat) / Δlat`。

### 5.2 Leaflet 贴图

```js
const bounds = [[d.lat_min, d.lon_min], [d.lat_max, d.lon_max]]  // [西南, 东北]
L.imageOverlay(API_BASE + d.grid_file_url, bounds, {
  opacity: 0.85,
  interactive: false,
}).addTo(map)
map.fitBounds(bounds)

// 画车/站点/路线：经纬度 → 画布像素
const toPx = (lon, lat, img) => [
  (lon - d.lon_min) / (d.lon_max - d.lon_min) * img.naturalWidth,
  (d.lat_max - lat) / (d.lat_max - d.lat_min) * img.naturalHeight,
]
```

天地图 / 高德 WebGL、原生 canvas 同理：把图片铺满 `bounds` 矩形，再用上式换算。

### 5.3 格式与内容建议

| 项 | 建议 |
|---|---|
| 容器 | **PNG（24/32 位）** 优先；`.tif` 需 geotiff.js，浏览器不原生支持 |
| 尺寸 | 边长 ≤ 4096 px |
| 朝向 | 正北朝上（上 = 北） |
| 像素含义（可选约定） | 浅色 = 可通行 / 黑 = 障碍 / 透明 = 未知 |
| 比例尺 | 建议 0.05 m/px，100 m × 100 m ≈ 2000 × 2000 px |

> 后端目前不做栅格规划，颜色约定只为将来接入占用栅格留口子。

### 5.4 翻转（flip_x / flip_y）与坐标一致性

前端反馈「图和点云上下/左右反了」时，可以给栅格加镜像：

| 参数 | 含义 | 翻转后 |
|---|---|---|
| `flip_x` | 左右镜像 | 图像第 0 列 = `max_x`（东） |
| `flip_y` | 上下镜像 | 图像第 0 行 = `min_y`（南） |

镜像不是「只翻图片」：后端会同时把 `grid_origin_x / grid_origin_y` 换成**新图左上角**的点云坐标，
并把 `px` / `py` 的符号并入仿射矩阵，因此 `/coords`、`/paths/{id}/points` 的换算**自动保持一致**，前端不用改代码。

| 组合 | 图像第 0 行 / 第 0 列 | `grid_origin_x` | `grid_origin_y` |
|---|---|---|---|
| 不翻 | 北 / 西 | `min_x` | `max_y` |
| `flip_y` | 南 / 西 | `min_x` | `min_y` |
| `flip_x` | 北 / 东 | `max_x` | `max_y` |
| 两者 | 南 / 东 | `max_x` | `min_y` |

在哪翻：`POST /admin/maps/upload-pointcloud`、`POST /admin/maps/{id}/pointcloud/process` 的 `flip_x/flip_y`；
或者**只重画栅格**（不动点云，1~2 秒）：`POST /admin/maps/{id}/grid/regenerate?flip_y=true`。

> 若同时设置了自定义 `tf_affine`，以矩阵为准（矩阵里已含翻转）；`grid_flip_*` 只影响「三轴 / 回退」模式。
> ROS 导出（§21）会**忽略**翻转，始终按规范方向生成 PGM。


## 6. 点云

- 支持 `.pcd .ply .las .laz .xyz .zip`；后端只存储，不解析；
- FAST-LIO 的 `scans.pcd` 常有数百 MB → 建议先体素降采样（5 cm）再传；
- 前端展示用 three.js / potree；坐标是建图时的局部坐标系，与经纬度**无对应关系**，如需对齐需自行算变换；
- 路线/站点不依赖点云，只依赖 `bounds`。

## 7. 权限与可见性

- 读：任何登录用户，但只能看到「自己负责的地图」（`admin` 不受限）；没有任何可见地图时列表返回空数组；
- 写：仅 `admin` 角色；
- 车-地图、用户-地图都是多对多：`PUT /api/cars/{id}/maps`、`PUT /api/user/{id}`（`map_ids`）为覆盖式设置，传 `[]` 解除全部。

## 8. FAQ

**Q：`file_url` 拿到的是 pcd，怎么取图片？**
用 `grid_file_url`；`file_url` 是历史兼容字段（优先点云）。

**Q：图片贴上去位置偏了？**
检查两点：① 图片上边缘是否为正北；② `bounds` 是否取的图片**四个角**（而非场地边界）。当前模型不支持旋转，斜拍/斜切的图无法精确对齐。

**Q：能传 zip 当栅格吗？**
不能。栅格必须是浏览器可直接渲染的图片；zip 仅用于点云。

**Q：为什么 `/static/maps/x.tif` 打不开？**
浏览器不原生支持 TIFF，服务器会按 `image/tiff` 返回，需要前端用 geotiff.js 解码。**建议转 PNG。**

**Q：地图删了文件还在吗？**
`DELETE /admin/maps/{id}` 会同时删除磁盘上的点云/栅格文件；只删单个文件用 `/files/{kind}`。

**Q：上传同名文件会怎样？**
按「同槽位覆盖」处理：先删旧文件再写新文件，文件名带 `map_{id}_{pc|grid}_` 前缀，不会影响另一类文件。

## 9. curl 示例

```bash
# 1) 登录拿 token
TOKEN=$(curl -s -X POST http://127.0.0.1:8001/api/oauth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"123456"}' | jq -r .data.token)

# 2) 新建 local 地图（左上/右下角点）
curl -s -X POST http://127.0.0.1:8001/admin/maps/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"轮椅场地","map_type":"local",
       "center_lon":113.972,"center_lat":22.602,"zoom":18,
       "left_top_lon":113.968,"left_top_lat":22.606,
       "right_bottom_lon":113.976,"right_bottom_lat":22.598}'

# 3) 上传栅格 / 点云
curl -s -X POST http://127.0.0.1:8001/admin/maps/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F map_id=1 -F kind=grid -F file=@floor.png

curl -s -X POST http://127.0.0.1:8001/admin/maps/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F map_id=1 -F kind=pointcloud -F file=@scans_down.pcd

# 4) 绑到轮椅（car_id=4）
curl -s -X PUT http://127.0.0.1:8001/api/cars/4/maps \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"map_ids":[1]}'

# 5) 前端取图
curl -s http://127.0.0.1:8001/admin/maps/1 \
  -H "Authorization: Bearer $TOKEN"
# → data.grid_file_url = /static/maps/map_1_grid_floor.png
# → 完整地址 = http://127.0.0.1:8001/static/maps/map_1_grid_floor.png
```
## 10. 点云处理（体素降采样 + 生成栅格）

```http
POST /admin/maps/{map_id}/pointcloud/process
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `leaf_size` | 0.05 | 体素降采样边长（米）；传 0 不降采样 |
| `grid_resolution` | 0.05 | 栅格分辨率（米/像素） |
| `grid_mode` | occupancy | `occupancy`=占用（黑白）/ `height`=高度灰度 |
| `z_low` / `z_high` | 0.15 / 1.8 | 障碍判定：相对地面（z 的 5% 分位）的高度区间（米） |
| `replace` | false | true=覆盖原点云；false=另存 `*_down.pcd` |
| `generate_grid` | true | 是否同时生成/覆盖栅格图 |

**实测**（114.8 MB / 9,569,412 点）：耗时 **2.1 s** → 354,019 点 / **4.05 MB**，栅格 **580×503 @0.05 m**（29 m × 25 m）。

说明：

- 只支持 `.pcd`（`DATA ascii` / `binary`）；`binary_compressed` 需先用 pcl / CloudCompare 转换；
- 处理后 `pointcloud_file_*` 指向降采样文件，**原文件保留在磁盘不删除**；
- 自动回填 `pointcloud_point_count`、`pc_min_x/max_x/min_y/max_y/min_z/max_z`、
  `grid_origin_x`、`grid_origin_y`、`grid_resolution`、`grid_width`、`grid_height`；
- 栅格图命名 `map_{id}_grid_auto_{res}m.png`，同槽位旧图会被删除。

返回：

```json
{ "code": 200, "msg": "点云处理完成",
  "data": {
    "before_points": 9569412, "after_points": 354019,
    "before_size": 114833120, "after_size": 4245893,
    "pointcloud_file_url": "/static/maps/map_1_pc_scans_20261125_0053_aligned_down.pcd",
    "bounds_of_cloud": {"min_x": -17.995, "max_x": 10.995, "min_y": -9.119, "max_y": 15.997, "min_z": -0.499, "max_z": 4.0},
    "grid": { "grid_file_url": "/static/maps/map_1_grid_auto_0_05m.png",
              "grid_width": 580, "grid_height": 503, "grid_resolution": 0.05,
              "grid_origin_x": -17.995, "grid_origin_y": 15.997, "z_floor": -0.01 },
    "elapsed_ms": 2103 } }
```

## 11. 坐标换算（栅格 ↔ 点云 ↔ 经纬度）

```http
GET /admin/maps/{map_id}/coords?px=290&py=251      # 栅格像素
GET /admin/maps/{map_id}/coords?x=0&y=0            # 点云米
GET /admin/maps/{map_id}/coords?lon=113.96874&lat=22.60414   # 经纬度
```

一次只传一组完整坐标，返回能算出来的全部值：

```json
{ "code": 200, "data": {
    "map_id": 1, "has_grid": true, "has_bounds": true, "input": "像素",
    "grid_resolution": 0.05, "grid_origin_x": -17.995, "grid_origin_y": 15.997,
    "grid_width": 580, "grid_height": 503,
    "px": 290.0, "py": 251.0, "x": -3.495, "y": 3.447,
    "lon": 113.96874, "lat": 22.60414 } }
```

换算公式：

```
x  = grid_origin_x + px * grid_resolution
y  = grid_origin_y - py * grid_resolution
px = (x - grid_origin_x) / grid_resolution
py = (grid_origin_y - y) / grid_resolution

lon = lon_min + (px / grid_width)  * (lon_max - lon_min)
lat = lat_max - (py / grid_height) * (lat_max - lat_min)
```

前提：

- 「像素 ↔ 点云」需要地图做过**点云处理**；
- 「经纬度 ↔ 像素」需要地图填了 **bounds**；
- 图像第 0 行 = **北**，第 0 列 = **西**（即栅格图必须正北朝上）。

## 12. 路线节点坐标（前端绘图 / 车端导航）

```http
GET /admin/paths/{path_id}/points?frame=lonlat   # 经纬度
GET /admin/paths/{path_id}/points?frame=grid     # 栅格像素 px/py
GET /admin/paths/{path_id}/points?frame=pc       # 点云米 x/y（车端用）

GET /api/cars/{car_id}/paths/{path_id}/points?frame=pc   # 车端专用（附带归属校验）
```

```json
{ "code": 200, "data": {
    "path_id": 1, "name": "P1", "frame": "pc",
    "map_id": 1, "map_type": "local",
    "has_grid": true, "has_bounds": true, "missing": 0,
    "points": [
      { "index": 0, "type": "site", "id": 1, "name": "S1", "stop_mode": "timed", "dwell_time": 20,
        "lon": 113.96865, "lat": 22.6042, "px": 100.0, "py": 37.5, "x": -12.816, "y": 10.281 },
      { "index": 1, "type": "waypoint", "id": 1, "name": "W1", "stop_mode": null, "dwell_time": null,
        "lon": 113.96885, "lat": 22.60408, "px": 510.0, "py": 270.0, "x": 7.505, "y": -1.681 }
    ],
    "car_id": 1, "car_map_ids": [1], "path_in_car_maps": true } }
```

- `missing` = 无法解析坐标的节点数量（&gt;0 说明节点没经纬度，或地图缺 bounds/grid）；
- `frame=pc` 时若地图缺 bounds，仍然返回 `x/y`，但 `lon/lat` 为 null。

## 13. 路线返回中的地图信息（map / loc / pc）

`GET /admin/paths/` 与 `GET /admin/paths/{id}` 现在额外返回：

```json
{
  "node_chain": [
    {"type": "site", "id": 1,
     "loc": {"lon": 113.96865, "lat": 22.6042},
     "pc": {"x": -12.816, "y": 10.281, "px": 100.0, "py": 37.5}}
  ],
  "map": {
    "id": 1, "name": "E2E-MAP", "map_type": "local",
    "center_lon": 113.96874, "center_lat": 22.60414, "zoom": 19,
    "bounds": {"left_top": {"lon": 113.9686, "lat": 22.60425},
               "right_bottom": {"lon": 113.96888, "lat": 22.60403}},
    "grid_file_url": "/static/maps/map_1_grid_auto_0_05m.png",
    "pointcloud_file_url": "/static/maps/map_1_pc_..._down.pcd",
    "grid_resolution": 0.05, "grid_origin_x": -17.995, "grid_origin_y": 15.997,
    "grid_width": 580, "grid_height": 503
  }
}
```

- `node_chain` 里**原本只有** `{type, id}`，`loc` / `pc` 是本次新增的回填字段；
- `loc` = 该节点（站点/路径点）的经纬度；`pc` = 换算到点云坐标系后的米制坐标（地图未处理点云时为 `null`）。

## 14. 统一响应结构 & 返回字段文档

所有接口返回：`{ "code": 200, "msg": "...", "data": ... }`。

以前 `/docs` 里看不到 `data` 的字段，是因为项目没有设置 `response_model`（FastAPI 无法推断 `data` 结构）。
现新增泛型响应壳 `schemas/resp.py::ApiResponse[T]`，以下接口已标注，Swagger 会完整展开返回字段：

| 接口 | response_model |
|---|---|
| `GET /admin/maps/` | `ApiResponse[List[MapOut]]` |
| `GET /admin/maps/{id}` | `ApiResponse[MapOut]` |
| `GET /admin/paths/` | `ApiResponse[List[PathOut]]` |
| `GET /admin/paths/{id}` | `ApiResponse[PathOut]` |
| `GET /admin/sites/` `GET /admin/sites/{id}` | `ApiResponse[List[SiteOut]]` / `ApiResponse[SiteOut]` |
| `GET /admin/waypoints/` `GET /admin/waypoints/{id}` | `ApiResponse[List[WaypointOut]]` / `ApiResponse[WaypointOut]` |

> 依赖：点云处理需要 **numpy**（已写入 `requirements.txt`），不需要 open3d / Pillow / PCL。
## 15. 地图变换（缩放 / 平移 / 旋转三轴）

栅格图与点云**不一定**正北朝上、也不一定与坐标轴对齐，所以用一组变换描述「像素 → 点云米」。

### 15.1 统一表示：2×3 仿射

```
x = a*px + b*py + c
y = d*px + e*py + f
```

参数来源按**优先级**取：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | `tf_affine` | JSON `[a,b,c,d,e,f]`，前端自己算好直接传（如三点对齐） |
| 2 | 三轴 `tf_scale`/`tf_rot_deg`/`tf_pitch_deg`/`tf_roll_deg`/`tf_tx`/`tf_ty` | 后端按欧拉角合成仿射 |
| 3 | `grid_resolution` / `grid_origin_x` / `grid_origin_y` | 点云处理生成的值（等价三轴全 0） |

> **为什么不是三个独立旋转？** 栅格是一张 2D 平面图。绕 X/Y 倾斜这张平面，在**正交俯视**下看到的是「压缩 + 剪切」，
> 数学上就是仿射矩阵；所以后端用仿射表达三轴效果，前端拖三个轴时后端负责换算。

### 15.2 三轴 → 仿射（后端实现，前端可照抄）

```
设 y=yaw(°), p=pitch(°), r=roll(°)，s=scale，T=(tx,ty)，c=cos、s_=sin：

a =  s*c(y)*c(p)
b = -s*(c(y)*s_(r)*s_(p) - s_(y)*c(r))
c =  tx
d =  s*s_(y)*c(p)
e = -s*(s_(y)*s_(r)*s_(p) + c(y)*c(r))
f =  ty
```

推导：图像点取 `(u, v, 0)`（`u = scale*px`，`v = -scale*py`，处理图像 y 向下），
按 `R = Rz(yaw) · Ry(pitch) · Rx(roll)` 旋转，正交俯视只取 X/Y 分量，再加平移。

- `pitch = roll = 0` 时退化为相似变换：`a = s·cos(y)`、`b = s·sin(y)`、`d = s·sin(y)`、`e = -s·cos(y)`；
- **只有 `scale` 是等比缩放**（和前端的感觉一致）；`pitch`/`roll` 用来把歪掉的图转正。

### 15.3 反变换（点云 → 像素）

```
det = a*e - b*d
px = ( e*(X-c) - b*(Y-f)) / det
py = (-d*(X-c) + a*(Y-f)) / det
```

### 15.4 接口

```http
GET /admin/maps/{map_id}/transform
PUT /admin/maps/{map_id}/transform
```

```json
// ① 简单（只有 yaw）
{ "scale": 0.05, "rot_deg": 3.5, "tx": -17.995, "ty": 15.997 }

// ② 三轴（前端拖三个轴）
{ "scale": 0.05, "rot_deg": 3.5, "pitch_deg": 10, "roll_deg": -4, "tx": -17.995, "ty": 15.997 }

// ③ 高级：前端自己算的仿射（优先级最高）
{ "affine": [0.0499, 0.0031, -17.995, 0.0031, -0.0499, 15.997] }

// ④ 重置：清空所有 tf_*，回退到点云处理生成的值
{ "reset": true }
```

- 传 ①/② 会**清掉旧的 `affine`**（三轴优先）；传 ③ 只写 `tf_affine`，不动三轴字段；
- 只改 `tf_*`，**不会改动 bounds**（bounds 决定图贴到天地图的位置）。

### 15.5 返回

```json
{ "code": 200, "data": {
    "map_id": 1,
    "has_grid": true, "has_bounds": true,
    "transform": {
      "mode": "euler",
      "affine": [0.04922, 0.00973, -17.995, 0.00973, -0.04922, 15.997],
      "scale": 0.05, "rot_deg": 3.5, "pitch_deg": 10, "roll_deg": -4,
      "tx": -17.995, "ty": 15.997, "source": "tf"
    },
    "grid_width": 580, "grid_height": 503,
    "image_size_m": { "width": 29.0, "height": 25.15 },
    "bounds_size_m": { "width": 28.8, "height": 24.4 },
    "scale_ratio": { "width": 1.0069, "height": 1.0307 },
    "corners_pc": {
      "lt": { "x": -17.995, "y": 15.997 }, "rt": { "x": 10.995, "y": 15.997 },
      "rb": { "x": 10.995, "y": -9.119 }, "lb": { "x": -17.995, "y": -9.119 } },
    "corners_lonlat": {
      "lt": { "lon": 113.9686, "lat": 22.60425 }, "rb": { "lon": 113.96888, "lat": 22.60403 } },
    "warnings": [] } }
```

- `mode`：`affine`（直接存矩阵）/ `euler`（三轴）/ `similarity`（只有 yaw）/ `grid`（回退到点云处理值）；
- `affine` 是**解析后的最终矩阵**，前端画图直接用这 6 个数即可；
- `scale_ratio` 偏离 1 超过 5% 时 `warnings` 会提示：图被拖动/旋转过，或 bounds 没跟着改。

### 15.6 前端三点对齐（可选）

已知三个像素点 `(px_i, py_i)` 与其在点云中的坐标 `(x_i, y_i)`，解 6 元一次方程组即可得到 `affine`：

```
[px1 py1 1] [a]   [x1]
[px2 py2 1] [b] = [x2]
[px3 py3 1] [c]   [x3]     同理解 d/e/f 用 y1..y3
```

解出后 `PUT /admin/maps/{id}/transform` 传 `{"affine": [...]}`。

## 16. 点云坐标点（站点 / 路径点 / node_chain）

前端在点云图上取点，**直接传点云米制坐标**即可，后端会自动换算经纬度并存两套。

### 16.1 站点 / 路径点

```http
POST /admin/sites/     { "name": "A站", "map_id": 1, "pc_x": -12.8, "pc_y": 10.3, "dwell_time": 20 }
POST /admin/waypoints/ { "name": "W1",  "map_id": 1, "pc_x": -5.2,  "pc_y": -3.1 }
```

| 你传的 | 后端做什么 |
|---|---|
| 只传 `pc_x` / `pc_y` | 用地图变换反算 `lon/lat`，**两套都存** |
| 只传 `lon` / `lat` | 正算 `pc_x` / `pc_y`，两套都存 |
| 两套都传 | 校验偏差，> 1 米返回 400 |
| 都不传 | 400（`lon/lat` 在库里是必填） |

> 只传 `pc_x/pc_y` 时要求地图已完成点云处理且填了 `bounds`，否则无法反算经纬度。

### 16.2 路线 node_chain

```json
[
  {"type": "site",     "id": 3},                  // 站点：有停靠语义（stop_mode / dwell_time）
  {"type": "point",    "x": 3.2, "y": -7.5},      // 纯几何点：点云米制坐标，不停靠
  {"type": "waypoint", "id": 1}
]
```

- `site` / `waypoint` 必须带 `id`；
- `point` 必须带 `x`、`y`（米），用于贝塞尔控制点等；
- 其它 `type` 一律 400。
## 17. 字段速查：每个接口「传什么」→「存什么 / 返回什么」

### 17.1 地图 `POST /admin/maps/`、`PUT /admin/maps/{id}`

| 请求字段 | 类型 | 必填 | 存到哪 / 作用 |
|---|---|---|---|
| `name` | str | 创建必填 | `maps.name` |
| `description` | str | 否 | `maps.description`（update 传 null 可清空） |
| `map_type` | str | 否（默认 tianditu） | `maps.map_type`：`tianditu` / `local` |
| `center_lon` / `center_lat` | float | 否 | `maps.center_lon/lat` 地图中心 |
| `zoom` | int | 否 | `maps.zoom` 默认缩放级别 |
| `left_top_lon` / `left_top_lat` | float | 否 | → `maps.lon_min` / `maps.lat_max` |
| `right_bottom_lon` / `right_bottom_lat` | float | 否 | → `maps.lon_max` / `maps.lat_min` |
| `lon_min` / `lat_min` / `lon_max` / `lat_max` | float | 否 | 直接写 `maps.*`（与上面角点二选一） |
| `fallback_map_id` | int | 否 | `maps.fallback_map_id`（兜底地图，必须 local） |

### 17.2 地图文件 `POST /admin/maps/upload`（multipart）

| 表单字段 | 说明 | 存到哪 |
|---|---|---|
| `map_id` | 地图ID | — |
| `kind` | `pointcloud` / `grid` | — |
| `file` | 点云 `.pcd`；栅格 `.png/.jpg/.jpeg/.webp/.bmp/.gif/.tif/.tiff` | 磁盘 `static/maps/map_{id}_{pc|grid}_<安全名>` + `pointcloud_file_*` / `grid_file_*` |

### 17.3 点云处理 `POST /admin/maps/{id}/pointcloud/process`（query）

| 参数 | 默认 | 作用 | 写回字段 |
|---|---|---|---|
| `leaf_size` | 0.05 | 体素边长（米），0=不降采样 | `pointcloud_file_path/size/type/upload_time`、`pointcloud_point_count` |
| `grid_resolution` | 0.05 | 米/像素 | `grid_resolution`、`grid_width`、`grid_height` |
| `grid_mode` | occupancy | occupancy / height | 生成 `grid_file_*` |
| `z_low` / `z_high` | 0.15 / 1.8 | 障碍判定高度区间 | 影响栅格内容 |
| `replace` | false | 覆盖原点云？ | true=写回原路径 |
| `flip_x` / `flip_y` | false | 栅格左右 / 上下镜像 | `grid_flip_x/y`、`grid_origin_x/y` |
| `generate_grid` | true | 是否生成栅格 | `grid_file_path` 等 |
| `keep_original` | false | **默认删除原始大点云**（只留降采样结果）；true=保留 | 磁盘 |
| — | — | 自动统计点云包围盒 | `pc_min_x/max_x/min_y/max_y/min_z/max_z`、`grid_origin_x/grid_origin_y` |

### 17.4 地图变换 `PUT /admin/maps/{id}/transform`

| 请求字段 | 存到哪 | 说明 |
|---|---|---|
| `scale` | `maps.tf_scale` | 米/像素，必须 > 0 |
| `rot_deg` | `maps.tf_rot_deg` | 旋转角（度，逆时针为正） |
| `tx` | `maps.tf_tx` | 图像原点对应的点云 X |
| `ty` | `maps.tf_ty` | 图像原点对应的点云 Y |
| `pitch_deg` | `maps.tf_pitch_deg` | 绕 X 轴倾角（度） |
| `roll_deg` | `maps.tf_roll_deg` | 绕 Y 轴倾角（度） |
| `affine` | `maps.tf_affine` | JSON `[a,b,c,d,e,f]`，优先级高于三轴 |
| `reset=true` | 清空上面 4 个 | 回退到点云处理生成的值 |

### 17.5 站点 `POST /admin/sites/`、`PUT /admin/sites/{id}`

| 请求字段 | 必填 | 存到哪 |
|---|---|---|
| `name` | 创建必填 | `sites.name` |
| `map_id` | 创建必填 | `sites.map_id` |
| `lon` / `lat` | 与 pc 二选一 | `sites.lon/lat`（另一套自动换算补全） |
| `pc_x` / `pc_y` | 与 lon/lat 二选一 | `sites.pc_x/pc_y`（点云米制坐标） |
| `dwell_time` | 否（默认 0） | `sites.dwell_time` 停靠秒数 |
| `stop_mode` | 否（默认 timed） | `sites.stop_mode`：`timed` / `wait_command` |
| `description` | 否 | `sites.description`（update 传 null 可清空） |

### 17.6 路径点 `POST /admin/waypoints/`、`PUT /admin/waypoints/{id}`

字段同站点，去掉 `dwell_time` / `stop_mode`：`name`、`map_id`、`lon/lat` 或 `pc_x/pc_y`、`description`。

### 17.7 路线 `POST /admin/paths/`、`PUT /admin/paths/{id}`

| 请求字段 | 必填 | 存到哪 |
|---|---|---|
| `name` | 创建必填 | `paths.name` |
| `path_type` | 创建必填 | `paths.path_type`（如 `折线` / `贝塞尔曲线` / `吸附道路`） |
| `node_chain` | 创建必填 | `paths.node_chain`（JSON 字符串） |
| `map_id` | 创建必填 | `paths.map_id`；同时**自动带入** `paths.map_type` |
| `car_id` | 否 | `paths.car_id` 专属车辆；update 传 null 解除 |
| `is_temp` | 否（默认 false） | `paths.is_temp` 临时路径（同车同图唯一，重复创建自动覆盖） |

`node_chain` 元素：

| 元素 | 含义 | 是否停靠 |
|---|---|---|
| `{"type":"site","id":3}` | 引用站点 | 是（`stop_mode` / `dwell_time`） |
| `{"type":"waypoint","id":1}` | 引用路径点 | 否 |
| `{"type":"point","x":3.2,"y":-7.5}` | 点云米制坐标裸点 | 否 |

### 17.8 路线坐标 `GET /admin/paths/{id}/points`、`GET /api/cars/{car_id}/paths/{path_id}/points`

| 查询参数 | 说明 |
|---|---|
| `frame=lonlat` | 返回 `lon/lat` |
| `frame=grid` | 返回 `px/py`（栅格像素） |
| `frame=pc` | 返回 `x/y`（点云米，**车端导航用**） |

每个点返回：`index`、`type`、`id`、`name`、`stop_mode`、`dwell_time`、`lon`、`lat`、`px`、`py`、`x`、`y`；`missing` 表示该坐标系下解析失败的节点数。

### 17.9 坐标换算 `GET /admin/maps/{id}/coords`

| 入参（三选一，必须成对） | 返回 |
|---|---|
| `px` + `py` | 全部：`px/py`、`x/y`、`lon/lat` |
| `x` + `y` | 全部 |
| `lon` + `lat` | 全部 |

算不出来的字段返回 `null`（例如地图没填 bounds 时没有 `lon/lat`）。

## 18. 这些说明在 /docs 里怎么看

本文档的章节**已经内嵌到 `/docs` 对应接口的 Description 里**（同一个 md 源，改这里重启即生效，不需要单独页面）：

| 想看什么 | 打开 `/docs` 里的哪个接口 | 对应章节 |
|---|---|---|
| 地图字段含义 | `GET /admin/maps/{id}` | §2 返回字段 + §5 栅格格式 |
| 上传点云/栅格 | `POST /admin/maps/upload` | §4 上传契约 |
| 一步建图 | `POST /admin/maps/upload-pointcloud` | §19 一步建图 |
| 点云滤波/生成栅格 | `POST /admin/maps/{id}/pointcloud/process` | §10 点云处理 |
| **地图变换（三轴 + 仿射）** | `GET` / `PUT /admin/maps/{id}/transform` | **§15** |
| 坐标换算 | `GET /admin/maps/{id}/coords` | §11 |
| 翻转 / 重画栅格 | `POST /admin/maps/{id}/grid/regenerate` | §5.4 + §22 |
| 导出 ROS 地图 | `GET /admin/maps/{id}/ros-map` | §21 |
| 路线节点类型 | `POST /admin/paths/` | §16 + §17.7 |
| 路线坐标（车端） | `GET /admin/paths/{id}/points` | §12 |
| 站点/路径点传点云坐标 | `POST /admin/sites/`、`/admin/waypoints/` | §16.1 + §17.5/17.6 |
| 车在点云图里的位置 | `POST /report/car_status` | §20 |

> 三轴在 Swagger 里看：`PUT /admin/maps/{id}/transform` → Schema 里的 `rot_deg`（三轴-1 / yaw）、
> `pitch_deg`（三轴-2）、`roll_deg`（三轴-3）；分别带示例值 3.5 / 10 / -4。

## 19. 一步建图（推荐）：上传点云直接生成地图

以前要「建空地图 → 上传 → 调 process」，还会把原始大 PCD 留在磁盘。现在有一步到位的接口：

```http
POST /admin/maps/upload-pointcloud      # multipart/form-data
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `file` | 必填 | 点云文件（`.pcd`，`DATA=ascii / binary`） |
| `name` | 必填 | 地图名称 |
| `map_id` | 空=自增 | **前端指定地图ID**；已存在返回 400 |
| `description` | 空 | 备注 |
| `map_type` | `local` | 地图类型 |
| `center_lon` / `center_lat` / `zoom` | 空 | 默认南科大基准 / 17 |
| `left_top_lon/lat`、`right_bottom_lon/lat` | 空 | 区域角点（可后补） |
| `leaf_size` | 0.05 | 体素降采样边长（米），0=不降采样 |
| `grid_resolution` | 0.05 | 栅格分辨率（米/像素） |
| `grid_mode` | `occupancy` | `occupancy` / `height` |
| `z_low` / `z_high` | 0.15 / 1.8 | 障碍判定高度区间（米） |
| `flip_x` / `flip_y` | false / false | 栅格左右 / 上下镜像（见 §5.4）；翻转后 origin 自动换到新左上角 |
| `keep_original` | **false** | 是否保留原始大点云；默认只留降采样结果 |

内部流程（一次请求内完成，任一步失败自动回滚并删除半成品）：

```
上传流 -> 临时文件 -> 体素降采样 -> map_{id}_pc_<名>_down.pcd
       -> 俯视投影 -> map_{id}_grid_auto_<res>m.png
       -> 回填 pc_min/max、pointcloud_point_count、grid_origin/res/width/height
       -> 删除临时文件（keep_original=false 时原图完全不落盘）
```

返回（地图完整信息 + 处理统计）：

```json
{ "code": 200, "msg": "地图创建成功",
  "data": {
    "id": 7, "name": "轮椅场地", "map_type": "local",
    "pointcloud_file_url": "/static/maps/map_7_pc_scans_aligned_down.pcd",
    "grid_file_url": "/static/maps/map_7_grid_auto_0_05m.png",
    "pointcloud_point_count": 354019,
    "pc_min_x": -17.995, "pc_max_x": 10.995, "pc_min_y": -9.119, "pc_max_y": 15.997,
    "grid_origin_x": -17.995, "grid_origin_y": 15.997,
    "grid_resolution": 0.05, "grid_width": 580, "grid_height": 503,
    "bounds": null,
    "stats": { "before_points": 9569412, "after_points": 354019,
               "before_size": 114833120, "after_size": 4245893,
               "elapsed_ms": 2841, "original_kept": false } } }
```

与旧流程对比：

| | 旧流程（建壳 → upload → process） | 一步建图 |
|---|---|---|
| 请求次数 | 3 次 | **1 次** |
| map_id | 只能自增 | 可指定 |
| 原始大 PCD | 默认保留 | **默认删除** |
| 失败清理 | 需手动删 | 自动回滚删行删文件 |

> `POST /admin/maps/{id}/pointcloud/process` 仍然保留，用于「对已有地图的点云再次滤波 / 重新生成栅格」，
> 它也新增了 `keep_original` 参数，默认 false。


## 20. 车辆在局部点云图中的位置

前端要在点云/栅格图上画车，需要车在**点云坐标系**下的位姿（不是经纬度）。

### 20.1 数据流

```
车端定位（ROS 里的 map 坐标系位姿）
      ↓ POST /report/car_status   （pc_map_id / pc_x / pc_y / pc_yaw）
      ↓ 入库 cars.pc_map_id / pc_x / pc_y / pc_yaw
      ├─→ WebSocket `map` 频道广播（实时推给前端地图页）
      └─→ GET /api/cars/list 返回
```

### 20.2 上报方式（三种，按可信度）

| 车端传的 | 后端行为 |
|---|---|
| `pc_x` + `pc_y`（可带 `pc_yaw`、`pc_map_id`） | **直接采用**，最可信 |
| 只传 `lon`/`lat`/`yaw` | 用地图的 `bounds` + `transform` **自动换算** `pc_x/pc_y/pc_yaw`（需要地图做过点云处理且填了 bounds） |
| 都不传 / 换算失败 | **保持上一次的值**，不会把已有位姿清空 |

`pc_map_id` 不传时：若车辆只绑定了一张地图，自动用那张；绑定多张时必须明确传。

### 20.3 字段与坐标约定

| 字段 | 含义 |
|---|---|
| `pc_map_id` | 位姿所属地图（点云坐标系） |
| `pc_x` / `pc_y` | 点云坐标（米） |
| `pc_yaw` | 点云坐标系航向角（**度**，`+x` 轴为 0，逆时针为正） |
| `lon` / `lat` / `yaw` | 仍照常上报（`yaw` 是 0=正北、顺时针） |

> 航向换算：后端会在地图上沿航向前进 1 米取第二点，两点都换算到点云后取 `atan2`，因此自动包含地图旋转。

### 20.4 前端画车

```js
// 方式一：用 /coords 把点云坐标换成像素
const { px, py } = (await api.get(`/admin/maps/${car.pc_map_id}/coords?x=${car.pc_x}&y=${car.pc_y}`)).data

// 方式二：自己用 transform 的仿射矩阵算（省一次请求）
// px = ( e*(x-c) - b*(y-f)) / det ，py = (-d*(x-c) + a*(y-f)) / det
// 朝向：画箭头时用 pc_yaw（相对 +x 轴逆时针）
```

`GET /api/cars/list` 与 WS 广播里的车辆对象都会带：

```json
{ "car_id": 4, "lon": 113.96878, "lat": 22.60420, "yaw": 90,
  "pc_map_id": 1, "pc_x": 0.05, "pc_y": -0.05, "pc_yaw": 0.0,
  "speed": 0.5, "battery": 80 }
```
## 21. 导出 ROS 地图（map_server / AMCL 用）

```http
GET /admin/maps/{map_id}/ros-map
```

| 查询参数 | 默认 | 说明 |
|---|---|---|
| `occupied_thresh` | 0.65 | 写进 yaml 的占用概率阈值 |
| `free_thresh` | 0.196 | 写进 yaml 的空闲概率阈值 |
| `negate` | 0 | 0=黑=占用（默认）/ 1=反色 |
| `z_low` / `z_high` | 0.15 / 1.8 | 障碍判定高度区间（米，相对地面） |

做了什么：

1. 用地图里**降采样后的点云**，按地图当前栅格帧（`grid_origin_x/y` + `grid_resolution` + `grid_width/height`）重新投影；
2. 输出 ROS 语义的灰度值：**0=占用、254=空闲、205=未知**，写成 `P5` 二进制 PGM；
3. `yaml.origin` 取图像**左下角**像素在点云坐标系中的位置，`yaw` 取变换的旋转角，`resolution` 取米/像素；
4. 两个文件写到 `static/maps/map_{id}_ros.pgm` 与 `.yaml`，可直接下载到车端。

返回示例：

```json
{ "code": 200, "msg": "ROS 地图导出成功",
  "data": {
    "map_id": 1,
    "pgm_url": "/static/maps/map_1_ros.pgm",
    "yaml_url": "/static/maps/map_1_ros.yaml",
    "yaml": "image: map_1_ros.pgm\nresolution: 0.1\norigin: [-10.000000, -8.100000, 0.000000]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n",
    "resolution": 0.1,
    "width": 201, "height": 161,
    "origin": [-10.0, -8.1, 0.0],
    "origin_yaw_deg": 0.0,
    "cells": { "occupied": 718, "free": 31641, "unknown": 2 },
    "usage": "下载 pgm+yaml 到车端同一目录，然后 rosrun map_server map_server <目录>/map_1_ros.yaml"
  } }
```

### 21.1 车端怎么用

```bash
# 1) 把两个文件放到同一目录（yaml 里的 image 是相对路径）
scp map_1_ros.pgm map_1_ros.yaml xxz@<车端>:/home/xxz/maps/

# 2) 起 map_server（ROS1 noetic）
rosrun map_server map_server /home/xxz/maps/map_1_ros.yaml
#    或写进 launch：
#    <node pkg="map_server" type="map_server" name="map_server"
#          args="/home/xxz/maps/map_1_ros.yaml" />

# 3) AMCL + move_base 里把 global_costmap 的 static_map 指向这个 map
#    AMCL 初始位姿用 /initialpose 设置（x/y 直接用点云坐标）
rosrun amcl amcl scan:=/scan
rostopic pub /initialpose geometry_msgs/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: 0.0, y: 0.0}, orientation: {w: 1.0}}}}'
```

### 21.2 已知限制

- **只支持「等比 + 旋转」的相似变换**：`map_server` 的 `origin` 只有 (x, y, yaw)，吃不下剪切/非等比。
  地图变换里如果设了 `pitch_deg` / `roll_deg`（或自己传了带剪切的 `affine`），本接口会返回 400，
  提示先把它们置 0（置 0 后等价的旋转仍可用 `rot_deg` 表达）。
- `origin` 用的是**像素位置**（不是格中心），与点云坐标差半个像素（0.05 m 分辨率下 2.5 cm），可忽略。
- 占用/空闲判定是**俯视高度带**启发式（默认地面以上 0.15~1.8 m 有点即占用），不是概率栅格；
  玻璃、悬空物、坡道等会有误差，可按需调 `z_low/z_high` 重新导出。
- 地图是 2D 的：车辆必须有 `scan`（或可降维的点云）与 `odom`，才能用 AMCL 定位。
- 导出**忽略 `flip_x / flip_y`**：PGM 始终按「图像上方 = +y」的规范方向生成，
  `yaml.origin` 取左下角（`pc_min_x, pc_min_y`）；响应里 `ros_export_ignores_flip=true` 表示该地图开过镜像。


## 22. 栅格图「方向不对」自测方法（给前端）

后端已用合成点云验证：**生成的栅格是「图像上方 = 点云 +y」**，并且 `coords` 与图片自洽。
若看起来反了，按下面顺序定位，别急着改图。

### 步骤 1：先分清是「镜像」还是「旋转」

- 只是上下颠倒、左右正常 → **镜像**（`flip_y`）或渲染 y 轴方向问题；
- 上下左右**都**颠倒（等于转了 180°）→ 是**旋转**，用 `PUT /transform {"rot_deg": 180}`，**不要用 flip**（flip 会把场地左右弄反）。

### 步骤 2：三个对照实验

| 实验 | 做法 | 说明 |
|---|---|---|
| ① 直接看 PNG | 浏览器打开 `grid_file_url` | 这就是后端视角；后端不会再翻一次 |
| ② 与点云对照 | 找场地里**只在一边**的物体（门、柱子、充电桩），看它在 PNG 的上面还是下面 | 与点云里该物体在 +y / -y 是否一致 |
| ③ 与天地图对照 | 用 `bounds` 叠图后，看同一物体在实景的哪一侧 | 分别验证「南北」与「东西」 |

### 步骤 3：按结论处理

| 现象 | 处理 |
|---|---|
| ②错（点云里在 +y，图里却在下方） | 前端渲染坐标系问题（three.js 默认 y-up、canvas y 向下）→ `flip_y=true`，或修渲染 |
| ②对、③错且整体转了 180° | 点云 +y 指向南 → `PUT /transform {"rot_deg": 180}` |
| ②对、③错且左右颠倒 | 检查 `bounds`：`left_top` 必须是「西 + 北」，`right_bottom` 是「东 + 南」 |
| ②③都对但和记忆中的场地不符 | 建图时朝向问题，重新建图或整体旋转 |

### 步骤 4：翻转后自检

```http
POST /admin/maps/{id}/grid/regenerate?flip_y=true     # 只重画栅格，不动点云
GET  /admin/maps/{id}/transform                       # flip_y 应为 true，corners_pc 随之变化
GET  /admin/maps/{id}/coords?px=0&py=0                # flip_y 后应变成 (min_x, min_y)
```

- `scale_ratio` 偏离 1 超过 5% 时 `warnings` 会提示：说明 `bounds` 与实际尺寸对不上（图被拖过或没填对）；
- 翻转不会影响车端：车端用的是 `points?frame=pc`（点云米制），与图像方向无关。

