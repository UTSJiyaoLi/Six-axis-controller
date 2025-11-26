"""
===============================================================================
Real-Time 6-Axis Motion Controller
===============================================================================
Author: 中交集团粤港澳大湾区创新研究院--------李继尧
Description:
    本程序用于生成多轴运动曲线（roll / pitch / yaw / x / y / z）并通过 UDP 
    实时发送 @A6T 指令控制外部设备，以实现六自由度平台或执行器的实时运动控制。

    程序支持任意段数的运动组合，包括：
        - 正弦波 (Sin)
        - 方波 (Square)
        - 三角波 (Triangle)
        - 梯形波 / 线性段 (Linear)
    用户可自由配置：
        - 周期（T）
        - 振幅（A）
        - 周期个数（N）

===============================================================================
主要功能：
1. **波形生成（离线计算）**
    - 解析用户输入的运动段 (WaveSegment)
    - 自动拼接多段曲线
    - 基于 dt_ms 计算真实时间轴（真实时间 = step_index * dt_ms）
    - 支持任意发送频率（10ms / 20ms / 40ms 等）

2. **多线程 UDP 实时发送**
    - 使用 QThread + QTimer(Qt.PreciseTimer) 构建独立发送线程
    - 主线程负责渲染图像，不影响 UDP 发送周期
    - 每个 dt_ms 周期发送一帧 @A6T 指令：
        @A6T:roll,pitch,yaw,x,y,z,dt_ms#

3. **实时图像显示（6 轴曲线）**
    - Matplotlib 嵌入 PyQt5 绘图
    - 动态显示曲线、当前值标记点、数值文本
    - 可调刷新频率，避免 UI 降低实时性

4. **可调 dt_ms（发送频率）**
    - 支持用户在 UI 中设置 dt_ms
    - 所有模块自动适应新的 dt_ms
    - 插补步数、真实运动时间、UDP 指令全部同步更新

5. **平滑停止（插补衰减）**
    - 用户点击“停止”后，SenderWorker 进入停止插补模式
    - 当前值线性衰减至 0
    - 插补过程中每一帧都发送给 UI（不抽帧）
    - 停止条件：
         - 6 个通道全部接近 0（图像端停止条件）
         - 或达到步数上限（保险）
    - 结束时自动发送一帧 @A6T:0,0,0,0,0,0,dt_ms#

6. **高稳定性的实时控制**
    - 发送线程独立运行，不受 UI 绘图影响
    - QTimer(Qt.PreciseTimer) 使 tick 误差保持在 ±1~3ms
    - 保证真实世界中的“运动时间”与用户输入一致

===============================================================================
适用场景：
    - 六自由度运动平台实时控制
    - 执行器/舵机/机构的同步轨迹控制
    - 水下机器人、具身智能机器人轨迹调度
    - 实验设备的实时激励与扰动模拟
    - 任意需要 “实时曲线 + 周期发送” 的硬件控制场景

===============================================================================
文件结构：
    - WaveSegment / AxisProgram：波形段定义与拼接
    - generate_a6t_data：生成离线曲线数据
    - generate_a6t_command_for_index：生成 UDP 指令
    - MplCanvas：界面绘图模块
    - SenderWorker（线程）：实时发送与停止插补
    - MainWindow：主界面/UI逻辑

===============================================================================
使用说明（简要）：
    1. 输入各轴的段参数（T、N、F）
    2. 设置 dt_ms（推荐 10~40 ms）
    3. 点击 “开始播放” 生成波形 + 实时发送 UDP
    4. 点击 “停止” → 自动衰减到 0 → 停止发送
    5. 图像端和设备端保持严格一致的时间轴与状态

===============================================================================
"""


import sys
import os
import math
import socket
from dataclasses import dataclass
from typing import List, Dict

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QLabel, QLineEdit,
    QCheckBox, QPushButton, QDoubleSpinBox
)
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QIcon

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib import font_manager
import matplotlib


# ---------- 资源路径 & 字体 ----------

def resource_path(relative_path: str) -> str:
    """兼容 PyInstaller 打包后的资源路径"""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def setup_chinese_font() -> None:
    """给 Matplotlib 设置一个可用的中文字体"""
    preferred_fonts = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    available = {f.name for f in font_manager.fontManager.ttflist}

    for name in preferred_fonts:
        if name in available:
            matplotlib.rcParams["font.sans-serif"] = [name]
            break

    matplotlib.rcParams["axes.unicode_minus"] = False

setup_chinese_font()

# ---------- 波形数据结构 & 算法 ----------

@dataclass
class WaveSegment:
    T: float  # 周期 (s)
    A: float  # 幅值
    N: int    # 周期个数


@dataclass
class AxisProgram:
    enabled: bool
    segments: List[WaveSegment]
    phase_deg: float = 0.0  # 相位角度


def startup_scale(global_cycle_idx: int) -> float:
    """
    启动缓冲：
    第 1 周期 20%，第 2 周期 40%，第 3 周期 80%，之后 100%
    """
    if global_cycle_idx == 0:
        return 0.2
    elif global_cycle_idx == 1:
        return 0.4
    elif global_cycle_idx == 2:
        return 0.8
    else:
        return 1.0


def axis_total_duration(axis: AxisProgram) -> float:
    """某个轴的总时长(秒)"""
    if not axis.enabled or not axis.segments:
        return 0.0
    return sum(seg.T * seg.N for seg in axis.segments)


def axis_value_at_time(axis: AxisProgram, t: float) -> float:
    """
    给定时间 t（秒），按分段正弦 + 启动缓冲 + 相位计算该轴值
    """
    if not axis.enabled or not axis.segments:
        return 0.0

    total_T = axis_total_duration(axis)
    if t >= total_T:
        return 0.0

    time_cursor = 0.0
    cycles_before = 0

    for seg in axis.segments:
        seg_duration = seg.T * seg.N
        if t < time_cursor + seg_duration:
            t_in_seg = t - time_cursor
            local_cycle_idx = int(t_in_seg / seg.T)
            tau = (t_in_seg % seg.T) / seg.T

            global_cycle_idx = cycles_before + local_cycle_idx
            s = startup_scale(global_cycle_idx)

            phase_rad = math.radians(axis.phase_deg)
            return s * seg.A * math.sin(2 * math.pi * tau + phase_rad)

        time_cursor += seg_duration
        cycles_before += seg.N

    return 0.0


def generate_a6t_data(
    programs: Dict[str, AxisProgram],
    base_z: float,
    k_roll: float,
    k_pitch: float,
    k_yaw: float,
    dt_ms: int,
) -> Dict[str, list]:
    """
    根据 6 轴配置生成离散时序数据
    这里 dt_ms / 1000 就是“真实世界时间”的采样间隔
    """
    dt = dt_ms / 1000.0  # 单步时长(秒)
    total_duration = max(axis_total_duration(ax) for ax in programs.values())
    if total_duration <= 0:
        return {k: [] for k in ["t", "roll", "pitch", "yaw", "x", "y", "z"]}

    n_steps = int(total_duration / dt)

    t_list, roll_list, pitch_list = [], [], []
    yaw_list, x_list, y_list, z_list = [], [], [], []

    for step in range(n_steps + 1):
        t = step * dt  # 真实秒

        roll_wave = axis_value_at_time(programs["roll"], t)
        pitch_wave = axis_value_at_time(programs["pitch"], t)
        yaw_wave = axis_value_at_time(programs["yaw"], t)
        x_wave = axis_value_at_time(programs["x"], t)
        y_wave = axis_value_at_time(programs["y"], t)
        z_wave = axis_value_at_time(programs["z"], t)

        Roll = k_roll * roll_wave
        Pitch = k_pitch * pitch_wave
        Yaw = k_yaw * yaw_wave
        X = x_wave
        Y = y_wave
        Z = base_z + z_wave

        t_list.append(t)
        roll_list.append(Roll)
        pitch_list.append(Pitch)
        yaw_list.append(Yaw)
        x_list.append(X)
        y_list.append(Y)
        z_list.append(Z)

    return {
        "t": t_list,
        "roll": roll_list,
        "pitch": pitch_list,
        "yaw": yaw_list,
        "x": x_list,
        "y": y_list,
        "z": z_list,
    }


def generate_a6t_command_for_index(data: Dict[str, list], idx: int, dt_ms: int) -> str:
    """生成某一时刻对应的 @A6T 指令"""
    return "@A6T:{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},{}#".format(
        data["roll"][idx],
        data["pitch"][idx],
        data["yaw"][idx],
        data["x"][idx],
        data["y"][idx],
        data["z"][idx],
        dt_ms,
    )

# ---------- Matplotlib 画布 ----------

class MplCanvas(FigureCanvas):
    def __init__(self, parent=None):
        fig = Figure(figsize=(8, 6), dpi=100)
        self.axes = fig.subplots(3, 2, sharex=True)

        # 水印
        fig.text(
            0.5, 0.5,
            "中交粤港澳创新研究院",
            fontsize=30,
            color="gray",
            alpha=0.15,
            ha="center",
            va="center",
            rotation=30,
        )

        super().__init__(fig)
        self.setParent(parent)

class SenderWorker(QtCore.QObject):
    """
    发送线程：
    - 使用 QTimer(Qt.PreciseTimer) 每 dt_ms 发送一条 UDP 指令
    - 支持正常播放 + 停止插补（线性衰减到 0）
    - 通过 tick 信号把当前 t 和数值发给主线程用于画图
    """
    tick = QtCore.pyqtSignal(float, object, bool, int)
    # 参数含义：t_now, cur_vals(dict), stopping(bool), idx(正常播放索引/停止阶段用-1)
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)

    def __init__(self, data: Dict[str, list], dt_ms: int, stop_duration_ms: int,
                 ip: str, port: int, parent=None):
        super().__init__(parent)
        self.data = data
        self.dt_ms = dt_ms
        self.stop_duration_ms = stop_duration_ms
        self.ip = ip
        self.port = port

        # 播放状态
        self.idx = 0
        self.n = len(self.data["t"])
        self.stopping_mode = False
        self.stop_step_index = 0
        self.stop_total_steps = 0
        self.stop_start_time = 0.0
        self.stop_start_values = {
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "x": 0.0, "y": 0.0, "z": 0.0,
        }

        self.timer: QtCore.QTimer | None = None
        self.sock: socket.socket | None = None

        # UI 刷新降频：比如每 5 帧通知主线程画一次图
        self.ui_every = 5
        self._tick_counter = 0
        self.zero_epsilon = 1e-3   # |值| < 1e-3 就当作 0, 用于画图停止判断

    @QtCore.pyqtSlot()
    def start(self):
        """在线程启动后调用：创建 socket 和定时器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except Exception as e:
            self.error.emit(f"创建 UDP Socket 失败：{e}")
            self.finished.emit()
            return

        if self.n == 0:
            self.finished.emit()
            return

        self.timer = QtCore.QTimer()
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.setInterval(self.dt_ms)
        self.timer.timeout.connect(self.on_timeout)
        self.timer.start()

    @QtCore.pyqtSlot()
    def request_stop(self):
        """主线程请求停止：从当前值开始做线性插补"""
        if self.stopping_mode or self.n == 0:
            return

        # 当前已经发送到的点：idx 指向“下一帧”
        if self.idx <= 0:
            cur_idx = 0
        elif self.idx >= self.n:
            cur_idx = self.n - 1
        else:
            cur_idx = self.idx - 1

        self.stop_start_values = {
            "roll":  self.data["roll"][cur_idx],
            "pitch": self.data["pitch"][cur_idx],
            "yaw":   self.data["yaw"][cur_idx],
            "x":     self.data["x"][cur_idx],
            "y":     self.data["y"][cur_idx],
            "z":     self.data["z"][cur_idx],
        }
        self.stop_start_time = self.data["t"][cur_idx]

        # 插补步数，例如 2000ms / 10ms = 200 步
        self.stop_total_steps = max(1, self.stop_duration_ms // self.dt_ms)
        self.stop_step_index = 0
        self.stopping_mode = True

    @QtCore.pyqtSlot()
    def on_timeout(self):
        if self.stopping_mode:
            self._stop_step()
        else:
            self._normal_step()

    def _normal_step(self):
        # 播放结束：进入收尾
        if self.idx >= self.n:
            self._finish()
            return

        t_now = self.data["t"][self.idx]
        cur_vals = {
            "roll":  self.data["roll"][self.idx],
            "pitch": self.data["pitch"][self.idx],
            "yaw":   self.data["yaw"][self.idx],
            "x":     self.data["x"][self.idx],
            "y":     self.data["y"][self.idx],
            "z":     self.data["z"][self.idx],
        }

        # 发送正常播放命令
        if self.sock is not None:
            try:
                cmd = generate_a6t_command_for_index(self.data, self.idx, self.dt_ms) + "\n"
                self.sock.sendto(cmd.encode("utf-8"), (self.ip, self.port))
            except Exception as e:
                self.error.emit(f"发送失败：{e}")
                self._finish()
                return

        is_last = (self.idx == self.n - 1)

        self._tick_counter += 1
        if is_last or (self._tick_counter % self.ui_every == 0):
            self.tick.emit(t_now, cur_vals, False, self.idx)

        self.idx += 1


    def _stop_step(self):
        """
        停止阶段：从 stop_start_values 线性衰减到 0。
        停止条件：所有通道都接近 0（|value| < zero_epsilon），
        或者步数达到 stop_total_steps 上限。
        """
        # 保险：如果理论步数已经走完，强制结束（避免逻辑错误导致死循环）
        if self.stop_step_index >= self.stop_total_steps:
            # 再发一条严格 0 的指令，保证设备端归零
            if self.sock is not None:
                try:
                    cmd = "@A6T:0.000,0.000,0.000,0.000,0.000,0.000,{}#\n".format(
                        self.dt_ms
                    )
                    self.sock.sendto(cmd.encode("utf-8"), (self.ip, self.port))
                except Exception:
                    pass
            self._finish()
            return

        # 计算当前步的插值系数 k：从 1.0 匀减到 0.0
        if self.stop_total_steps <= 1:
            k = 0.0
        else:
            # 用 0...(N-1) 这样的索引，最后一步 self.stop_step_index == N-1 时 k 精确为 0
            ratio = self.stop_step_index / (self.stop_total_steps - 1)
            k = 1.0 - ratio

        # 当前 6 个通道的值
        cur_vals = {
            name: self.stop_start_values[name] * k
            for name in ["roll", "pitch", "yaw", "x", "y", "z"]
        }

        dt_s = self.dt_ms / 1000.0
        t_now = self.stop_start_time + self.stop_step_index * dt_s

        # 判断“是否已经全为 0”（图像端/逻辑上的停止条件）
        all_zero = all(abs(cur_vals[name]) <= self.zero_epsilon
                    for name in ["roll", "pitch", "yaw", "x", "y", "z"])

        # 先通知 UI 画当前这一点（停止阶段不抽帧，每一步都画）
        self.tick.emit(t_now, cur_vals, True, -1)

        # 然后给设备发指令
        if self.sock is not None:
            try:
                cmd = "@A6T:{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},{}#\n".format(
                    cur_vals["roll"],
                    cur_vals["pitch"],
                    cur_vals["yaw"],
                    cur_vals["x"],
                    cur_vals["y"],
                    cur_vals["z"],
                    self.dt_ms,
                )
                self.sock.sendto(cmd.encode("utf-8"), (self.ip, self.port))
            except Exception as e:
                self.error.emit(f"停止插补发送失败：{e}")
                self._finish()
                return

        # 如果已经“全为 0”，或者步数达上限，就结束
        if all_zero or self.stop_step_index >= self.stop_total_steps - 1:
            # 再发一条严谨的 0 指令（防止最后一步不是严格 0）
            if self.sock is not None:
                try:
                    cmd = "@A6T:0.000,0.000,0.000,0.000,0.000,0.000,{}#\n".format(
                        self.dt_ms
                    )
                    self.sock.sendto(cmd.encode("utf-8"), (self.ip, self.port))
                except Exception:
                    pass
            self._finish()
            return

        # 否则继续下一步
        self.stop_step_index += 1


    def _finish(self):
        """统一的收尾函数：停掉定时器、关 socket、发 finished 信号"""
        if self.timer is not None:
            self.timer.stop()
            self.timer = None

        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        self.finished.emit()


# ---------- 主窗口 ----------

class MainWindow(QMainWindow):
    stop_requested = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setWindowTitle("六自由度平台控制器")

        # 全局参数（真实世界时间体系）
        self.base_z = 0
        self.dt_ms = 20               # 每步发送间隔(ms)，也是仿真采样间隔
        self.k_roll = 1.0
        self.k_pitch = 1.0
        self.k_yaw = 1.0
        self.stop_duration_ms = 2000

        central = QWidget()
        self.setCentralWidget(central)
        layout = QGridLayout(central)

        row = 0

        # --- 网络设置 ---
        layout.addWidget(QLabel("目标 IP:"), row, 0)
        self.ip_edit = QLineEdit("172.30.5.48")
        layout.addWidget(self.ip_edit, row, 1)

        layout.addWidget(QLabel("端口:"), row, 2)
        self.port_edit = QLineEdit("8900")
        layout.addWidget(self.port_edit, row, 3)
        row += 1

        # dt_ms 设置
        self.dt_label = QtWidgets.QLabel("dt_ms (ms):")
        self.dt_edit = QtWidgets.QLineEdit("10")
        self.dt_edit.setFixedWidth(60)

        # --- 轴配置表 ---
        self.axis_names = ["roll", "pitch", "yaw", "x", "y", "z"]
        self.axis_labels = {
            "roll": "Roll (°)",
            "pitch": "Pitch (°)",
            "yaw": "Yaw (°)",
            "x": "X (mm)",
            "y": "Y (mm)",
            "z": "Z (mm 相对 base_z)",
        }

        self.axis_enable: Dict[str, QCheckBox] = {}
        self.axis_phase: Dict[str, QDoubleSpinBox] = {}
        self.axis_segments: Dict[str, QLineEdit] = {}

        layout.addWidget(QLabel("轴"), row, 0)
        layout.addWidget(QLabel("启用"), row, 1)
        layout.addWidget(QLabel("相位 (deg)"), row, 2)
        layout.addWidget(QLabel("分段配置 T,A,N;T,A,N;..."), row, 3)
        row += 1

        for name in self.axis_names:
            layout.addWidget(QLabel(self.axis_labels[name]), row, 0)

            cb = QCheckBox()
            cb.setChecked(name in ["roll", "x", "z"])
            layout.addWidget(cb, row, 1)
            self.axis_enable[name] = cb

            phase = QDoubleSpinBox()
            phase.setRange(-360.0, 360.0)
            phase.setValue(0.0)
            layout.addWidget(phase, row, 2)
            self.axis_phase[name] = phase

            seg_edit = QLineEdit()
            seg_edit.setPlaceholderText("例如: 2,3,5; 1,5,10")
            if name == "roll":
                seg_edit.setText("2,3,5;1,5,10")
            elif name == "x":
                seg_edit.setText("3,10,4;1.5,20,8")
            elif name == "z":
                seg_edit.setText("4,15,3;2,25,6")
            layout.addWidget(seg_edit, row, 3)
            self.axis_segments[name] = seg_edit

            row += 1

        # --- 按钮 ---
        self.btn_start = QPushButton("开始")
        self.btn_stop = QPushButton("停止")
        layout.addWidget(self.btn_start, row, 0, 1, 1)
        layout.addWidget(self.btn_stop,  row, 1, 1, 1)
        layout.addWidget(self.dt_label, row, 4)
        layout.addWidget(self.dt_edit,  row, 5)
        row += 1

        # 信息栏
        self.info_label = QLabel("t = 0.00 s | 总时长 = 0.00 s")
        layout.addWidget(self.info_label, row, 0, 1, 4)
        row += 1

        # 画布
        self.canvas = MplCanvas(self)
        layout.addWidget(self.canvas, row, 0, 1, 4)

        # 播放状态
        self.data_cache: Dict[str, list] | None = None
        self.total_time = 0.0
        self.play_index = 0
        self.play_lines: Dict[str, any] = {}
        self.marker_lines: Dict[str, any] = {}
        self.value_texts: Dict[str, any] = {}

        # 绘图频率控制：每多少帧画一次图
        self.draw_every = 10      # 可以先用 10，后面你可以调 5、8 等看看效果
        self.frame_count = 0      # 帧计数器

        # 线程控制
        self.send_thread: QtCore.QThread | None = None
        self.sender: SenderWorker | None = None

        # 信号连接
        self.btn_start.clicked.connect(self.on_start_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)

    # ---------- 解析 T,A,N;T,A,N;... ----------

    def parse_segments(self, text: str) -> List[WaveSegment]:
        segs: List[WaveSegment] = []
        text = text.strip()
        if not text:
            return segs

        for part in text.split(";"):
            part = part.strip()
            if not part:
                continue
            nums = part.split(",")
            if len(nums) != 3:
                continue
            try:
                T = float(nums[0])
                A = float(nums[1])
                N = int(float(nums[2]))
                if T > 0 and N > 0:
                    segs.append(WaveSegment(T=T, A=A, N=N))
            except ValueError:
                continue
        return segs

    # ---------- 开始按钮 ----------

    def on_start_clicked(self):
        """生成数据 + 准备绘图 + 建立 UDP + 启动定时器"""
        try:
            # 清除停止状态
            self.stopping_mode = False
            self.stop_step_index = 0
            self.stop_total_steps = 0

            # 读取轴配置
            programs: Dict[str, AxisProgram] = {}
            for name in self.axis_names:
                enabled = self.axis_enable[name].isChecked()
                phase = self.axis_phase[name].value()
                segs = self.parse_segments(self.axis_segments[name].text())
                programs[name] = AxisProgram(
                    enabled=enabled,
                    segments=segs,
                    phase_deg=phase
                )

            # 生成 6 轴数据（真实世界时间）
            data = generate_a6t_data(
                programs,
                base_z=self.base_z,
                k_roll=self.k_roll,
                k_pitch=self.k_pitch,
                k_yaw=self.k_yaw,
                dt_ms=self.dt_ms,
            )
            # 读取 dt_ms
            try:
                self.dt_ms = int(self.dt_edit.text().strip())
                if self.dt_ms <= 0:
                    raise ValueError
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "错误", "dt_ms 必须是正整数！")
                return

            self.data_cache = data

            if not data["t"]:
                QtWidgets.QMessageBox.warning(self, "提示", "没有有效数据，请检查段配置。")
                return

            self.total_time = data["t"][-1]

            # 准备绘图
            self.play_index = 0
            self.setup_realtime_plot()

            # 帧计数器清零
            self.frame_count = 0

            total_display = self.total_time
            self.info_label.setText(f"t = 0.00 s | 总时长 = {total_display:.2f} s")

            # 读取 IP 和端口
            ip = self.ip_edit.text().strip()
            port_text = self.port_edit.text().strip()
            try:
                port = int(port_text)
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "网络错误", "端口必须是数字。")
                return
            if not ip:
                QtWidgets.QMessageBox.warning(self, "网络错误", "IP 地址不能为空。")
                return

            # 如果之前有旧线程，先清理
            if self.send_thread is not None:
                try:
                    self.send_thread.quit()
                    self.send_thread.wait(1000)
                except Exception:
                    pass
                self.send_thread = None
                self.sender = None

            # 创建发送线程和 Worker
            self.send_thread = QtCore.QThread(self)
            self.sender = SenderWorker(
                data=self.data_cache,
                dt_ms=self.dt_ms,
                stop_duration_ms=self.stop_duration_ms,
                ip=ip,
                port=port,
            )
            self.sender.moveToThread(self.send_thread)

            # 线程启动后，调用 worker.start()
            self.send_thread.started.connect(self.sender.start)
            # worker 每次 tick 通知主线程更新图像
            self.sender.tick.connect(self.on_sender_tick)
            # worker 出错
            self.sender.error.connect(self.on_sender_error)
            # worker 完成
            self.sender.finished.connect(self.on_sender_finished)
            self.sender.finished.connect(self.send_thread.quit)
            self.sender.finished.connect(self.sender.deleteLater)
            self.send_thread.finished.connect(self.send_thread.deleteLater)

            # stop 按钮通过信号请求 worker 做停止插补
            self.stop_requested.connect(self.sender.request_stop)

            # 启动线程（开始发 UDP）
            self.send_thread.start()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", str(e))

    # ---------- 停止按钮 ----------

    def on_stop_clicked(self):
        """请求停止：让发送线程从当前值线性插补到 0"""
        if self.sender is None:
            return
        # 发一个信号到 worker 所在的线程，由那边去算当前 idx 和起点
        self.stop_requested.emit()

    
    # ---------- 绘图初始化 ----------

    def setup_realtime_plot(self) -> None:
        """清空子图并初始化 6 条曲线和标记点"""
        data = self.data_cache
        if data is None:
            return

        axs = self.canvas.axes

        # X 轴右侧多预留一段衰减时间（秒）
        extra_time = self.stop_duration_ms / 1000.0
        x_max = self.total_time + extra_time

        for r in range(3):
            for c in range(2):
                axs[r, c].clear()
                axs[r, c].set_xlim(0, x_max)

        self.play_lines.clear()
        self.marker_lines.clear()
        self.value_texts.clear()

        # Roll / X
        line_roll, = axs[0, 0].plot([], [])
        axs[0, 0].set_ylabel("Roll (deg)")
        axs[0, 0].set_title("Roll")
        self.play_lines["roll"] = line_roll

        line_x, = axs[0, 1].plot([], [])
        axs[0, 1].set_ylabel("X (mm)")
        axs[0, 1].set_title("X")
        self.play_lines["x"] = line_x

        # Yaw / Y
        line_yaw, = axs[1, 0].plot([], [])
        axs[1, 0].set_ylabel("Yaw (deg)")
        axs[1, 0].set_title("Yaw")
        self.play_lines["yaw"] = line_yaw

        line_y, = axs[1, 1].plot([], [])
        axs[1, 1].set_ylabel("Y (mm)")
        axs[1, 1].set_title("Y")
        self.play_lines["y"] = line_y

        # Pitch / Z
        line_pitch, = axs[2, 0].plot([], [])
        axs[2, 0].set_ylabel("Pitch (deg)")
        axs[2, 0].set_title("Pitch")
        axs[2, 0].set_xlabel("Time (s)")
        self.play_lines["pitch"] = line_pitch

        line_z, = axs[2, 1].plot([], [])
        axs[2, 1].set_ylabel("Z (mm)")
        axs[2, 1].set_title("Z")
        axs[2, 1].set_xlabel("Time (s)")
        self.play_lines["z"] = line_z

        # 标记点
        m_roll,  = axs[0, 0].plot([], [], marker="o", linestyle="")
        m_x,     = axs[0, 1].plot([], [], marker="o", linestyle="")
        m_yaw,   = axs[1, 0].plot([], [], marker="o", linestyle="")
        m_y,     = axs[1, 1].plot([], [], marker="o", linestyle="")
        m_pitch, = axs[2, 0].plot([], [], marker="o", linestyle="")
        m_z,     = axs[2, 1].plot([], [], marker="o", linestyle="")

        self.marker_lines.update({
            "roll": m_roll, "x": m_x, "yaw": m_yaw,
            "y": m_y, "pitch": m_pitch, "z": m_z,
        })

        # 数值文字
        txt_roll  = axs[0, 0].text(0, 0, "", fontsize=8, ha="left", va="bottom")
        txt_x     = axs[0, 1].text(0, 0, "", fontsize=8, ha="left", va="bottom")
        txt_yaw   = axs[1, 0].text(0, 0, "", fontsize=8, ha="left", va="bottom")
        txt_y     = axs[1, 1].text(0, 0, "", fontsize=8, ha="left", va="bottom")
        txt_pitch = axs[2, 0].text(0, 0, "", fontsize=8, ha="left", va="bottom")
        txt_z     = axs[2, 1].text(0, 0, "", fontsize=8, ha="left", va="bottom")

        self.value_texts.update({
            "roll": txt_roll, "x": txt_x, "yaw": txt_yaw,
            "y": txt_y, "pitch": txt_pitch, "z": txt_z,
        })

        self.canvas.figure.subplots_adjust(hspace=0.6)
        self.canvas.draw()


    @QtCore.pyqtSlot(float, object, bool, int)
    def on_sender_tick(self, t_now: float, cur_vals: dict, stopping: bool, idx: int):
        """
        发送线程每隔 ui_every*dt_ms 通知一次：
        - t_now: 当前真实时间
        - cur_vals: 当前 roll/pitch/yaw/x/y/z 数值
        - stopping: 是否处于停止插补阶段
        - idx: 正常播放的索引（停止阶段为 -1）
        """
        if self.data_cache is None:
            return

        if not stopping:
            # 正常播放：用 idx 更新完整曲线
            if idx < 0 or idx >= len(self.data_cache["t"]):
                return
            t_slice = self.data_cache["t"][: idx + 1]

            self.play_lines["roll"].set_data(t_slice, self.data_cache["roll"][: idx + 1])
            self.play_lines["pitch"].set_data(t_slice, self.data_cache["pitch"][: idx + 1])
            self.play_lines["yaw"].set_data(t_slice, self.data_cache["yaw"][: idx + 1])
            self.play_lines["x"].set_data(t_slice, self.data_cache["x"][: idx + 1])
            self.play_lines["y"].set_data(t_slice, self.data_cache["y"][: idx + 1])
            self.play_lines["z"].set_data(t_slice, self.data_cache["z"][: idx + 1])
        else:
            # 停止插补阶段：在末尾追加一点
            for name, line in self.play_lines.items():
                xdata, ydata = line.get_data()
                xdata = list(xdata)
                ydata = list(ydata)
                xdata.append(t_now)
                ydata.append(cur_vals[name])
                line.set_data(xdata, ydata)

        # 标记点 + 文本（两种模式相同）
        self.marker_lines["roll"].set_data([t_now], [cur_vals["roll"]])
        self.marker_lines["pitch"].set_data([t_now], [cur_vals["pitch"]])
        self.marker_lines["yaw"].set_data([t_now], [cur_vals["yaw"]])
        self.marker_lines["x"].set_data([t_now], [cur_vals["x"]])
        self.marker_lines["y"].set_data([t_now], [cur_vals["y"]])
        self.marker_lines["z"].set_data([t_now], [cur_vals["z"]])

        for name in ["roll", "pitch", "yaw", "x", "y", "z"]:
            self.value_texts[name].set_position((t_now, cur_vals[name]))
            self.value_texts[name].set_text(f"{cur_vals[name]:.2f}")

        # 适当重算坐标轴并画图（这里仍可用 frame_count + draw_every 控制频率）
        self.frame_count += 1
        if self.frame_count % self.draw_every == 0:
            for r in range(3):
                for c in range(2):
                    ax = self.canvas.axes[r, c]
                    ax.relim()
                    ax.autoscale_view()
            self.canvas.draw()

        # 更新信息栏
        t_display = t_now
        total_display = self.total_time
        if stopping:
            self.info_label.setText(
                f"t = {t_display:.2f} s | 总时长 = {total_display:.2f} s (停止中…)"
            )
        else:
            self.info_label.setText(
                f"t = {t_display:.2f} s | 总时长 = {total_display:.2f} s"
            )

    @QtCore.pyqtSlot()
    def on_sender_finished(self):
        """发送线程结束：清理引用"""

        # ---- 新增：强制绘制最终0值 ----
        for r in range(3):
            for c in range(2):
                ax = self.canvas.axes[r, c]
                ax.relim()
                ax.autoscale_view()
        self.canvas.draw()
        self.sender = None
        self.send_thread = None


    @QtCore.pyqtSlot(str)
    def on_sender_error(self, msg: str):
        QtWidgets.QMessageBox.warning(self, "发送线程错误", msg)


if __name__ == "__main__":

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    window = MainWindow()
    window.resize(1100, 800)
    window.show()
    sys.exit(app.exec_())
