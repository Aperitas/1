# 南方科技大学主校区中心基准坐标
BASE_LON = 113.9686
BASE_LAT = 22.6042

def xy_to_gps(x: float, y: float):
    """
    小车内部平面XY(单位米) 转 真实地图经纬度
    x = 东向偏移米，y = 北向偏移米
    返回 (经度lon, 纬度lat)
    """
    # 1米对应的经纬度差值
    meter_per_lon = 1 / 102800
    meter_per_lat = 1 / 111320
    lon = BASE_LON + x * meter_per_lon
    lat = BASE_LAT + y * meter_per_lat
    return round(lon, 6), round(lat, 6)