from sqlmodel import Session, select
from db.session import engine
from models.car.car import Cars, CarStatus

# ========== 全局仿真总开关 ==========
SIMULATION_RUN: bool = False

# 虚拟小车XY移动步长，模拟低速行驶
STEP_X = 0.08
STEP_Y = 0.06
# XY边界（对应南科大校园范围）
X_MIN, X_MAX = -250, 250
Y_MIN, Y_MAX = -180, 180

def update_sim_car_pos():
    """定时更新所有虚拟小车XY坐标"""
    # 开关关闭，直接退出，不执行任何更新，无数据库IO消耗
    global SIMULATION_RUN
    if not SIMULATION_RUN:
        return

    global STEP_X, STEP_Y
    with Session(engine) as db:
        # 仅筛选虚拟小车 isSimulation=True
        sim_cars = db.exec(select(Cars).where(Cars.isSimulation == True)).all()
        for car in sim_cars:
            # 静止/充电/故障状态不移动
            if car.status not in [CarStatus.FREE, CarStatus.WORKING]:
                continue

            # 坐标移动，碰到边界反向折返
            car.x += STEP_X
            car.y += STEP_Y
            if car.x >= X_MAX or car.x <= X_MIN:
                STEP_X = -STEP_X
            if car.y >= Y_MAX or car.y <= Y_MIN:
                STEP_Y = -STEP_Y

            car.speed = 1.0
            car.yaw += 0.3
        db.commit()

# 对外提供给接口调用的方法
def start_sim_task():
    global SIMULATION_RUN
    SIMULATION_RUN = True

def stop_sim_task():
    global SIMULATION_RUN
    SIMULATION_RUN = False

def get_sim_status() -> bool:
    global SIMULATION_RUN
    return SIMULATION_RUN