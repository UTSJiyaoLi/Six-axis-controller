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


# ---------- 基本数据结构 & 波形算法 ----------

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
    启动缓冲系数：
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
    """某个轴的总时长"""
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
    """根据 6 轴配置生成离散时序数据"""
    dt = dt_ms / 1000.0
    total_duration = max(axis_total_duration(ax) for ax in programs.values())
    if total_duration <= 0:
        return {k: [] for k in ["t", "roll", "pitch", "yaw", "x", "y", "z"]}

    n_steps = int(total_duration / dt)

    t_list, roll_list, pitch_list = [], [], []
    yaw_list, x_list, y_list, z_list = [], [], [], []

    for step in range(n_steps + 1):
        t = step * dt

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


# ---------- 主窗口 ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setWindowTitle("六自由度平台控制器")

        # 全局参数（固定值）
        self.base_z = 40.0
        self.dt_ms = 10        # 单步指令持续时间(ms)
        self.k_roll = 1.0
        self.k_pitch = 1.0
        self.k_yaw = 1.0

        # UDP 状态
        self.sock: socket.socket | None = None
        self.udp_target: tuple[str, int] | None = None

        # 停止插补设置：stop_duration_ms 内线性减到 0
        self.stop_duration_ms = 2000   # 可改：停止过渡总时长(ms)
        self.stopping_mode = False
        self.stop_step_index = 0
        self.stop_start_time = 0.0
        self.stop_total_steps = 0
        self.stop_start_values = {
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "x": 0.0, "y": 0.0, "z": 0.0,
        }

        central = QWidget()
        self.setCentralWidget(central)
        layout = QGridLayout(central)

        row = 0

        # --- 网络设置 ---
        layout.addWidget(QLabel("目标 IP:"), row, 0)
        self.ip_edit = QLineEdit("172.30.5.48")
        layout.addWidget(self.ip_edit, row, 1)

        layout.addWidget(QLabel("端口:"), row, 2)
        self.port_edit = QLineEdit("8090")
        layout.addWidget(self.port_edit, row, 3)
        row += 1

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
        row += 1

        # 信息栏
        self.info_label = QLabel("t = 0.0 s | 总时长 = 0.0 s")
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

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.on_timer_tick)

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
                programs[name] = AxisProgram(enabled=enabled,
                                             segments=segs,
                                             phase_deg=phase)

            # 生成 6 轴数据
            data = generate_a6t_data(
                programs,
                base_z=self.base_z,
                k_roll=self.k_roll,
                k_pitch=self.k_pitch,
                k_yaw=self.k_yaw,
                dt_ms=self.dt_ms,
            )
            self.data_cache = data

            if not data["t"]:
                QtWidgets.QMessageBox.warning(self, "提示", "没有有效数据，请检查段配置。")
                return

            self.total_time = data["t"][-1]

            # 准备绘图
            self.play_index = 0
            self.setup_realtime_plot()

            total_display = self.total_time * 10
            self.info_label.setText(f"t = 0.0 s | 总时长 = {total_display:.1f} s")

            # UDP socket
            if not self.setup_socket():
                return

            # 启动定时器
            self.timer.start(self.dt_ms)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", str(e))

    # ---------- 停止按钮 ----------

    def on_stop_clicked(self):
        """
        停止：从当前值开始，在 stop_duration_ms 内线性插补到 0 并继续发指令
        """
        if self.data_cache is None or not self.data_cache.get("t"):
            return
        if self.stopping_mode:
            return

        data = self.data_cache
        n = len(data["t"])
        if n == 0:
            return

        # 当前时间索引：play_index 指向下一帧，所以当前帧为 play_index-1
        if self.play_index <= 0:
            idx = 0
        elif self.play_index >= n:
            idx = n - 1
        else:
            idx = self.play_index - 1

        # 记录停止起点状态
        self.stop_start_values = {
            "roll":  data["roll"][idx],
            "pitch": data["pitch"][idx],
            "yaw":   data["yaw"][idx],
            "x":     data["x"][idx],
            "y":     data["y"][idx],
            "z":     data["z"][idx],
        }
        self.stop_start_time = data["t"][idx]

        # 插补步数
        self.stop_total_steps = max(1, self.stop_duration_ms // self.dt_ms)
        self.stop_step_index = 0
        self.stopping_mode = True

        # 确保 UDP 可用
        if self.sock is None or self.udp_target is None:
            if not self.setup_socket():
                self.stopping_mode = False
                return

        # 确保定时器在跑
        if not self.timer.isActive():
            self.timer.start(self.dt_ms)

    # ---------- UDP ----------

    def setup_socket(self) -> bool:
        """按当前 IP/端口创建 UDP socket"""
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        self.udp_target = None

        ip = self.ip_edit.text().strip()
        port_text = self.port_edit.text().strip()
        try:
            port = int(port_text)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "网络错误", "端口必须是数字。")
            return False

        if not ip:
            QtWidgets.QMessageBox.warning(self, "网络错误", "IP 地址不能为空。")
            return False

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_target = (ip, port)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "网络错误", f"创建 UDP Socket 失败：\n{e}")
            self.sock = None
            self.udp_target = None
            return False

        return True

    # ---------- 绘图初始化 ----------

    def setup_realtime_plot(self) -> None:
        """清空子图并初始化 6 条曲线和标记点"""
        data = self.data_cache
        if data is None:
            return

        axs = self.canvas.axes

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

    # ---------- 定时器：正常播放 ----------

    def on_timer_tick(self):
        if self.stopping_mode:
            self.stop_tick()
            return

        if self.data_cache is None:
            self.timer.stop()
            return

        data = self.data_cache
        n = len(data["t"])
        if n == 0:
            self.timer.stop()
            return

        if self.play_index >= n:
            # 播完原始轨迹后直接停，socket 也关掉
            self.timer.stop()
            if self.sock is not None:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                self.udp_target = None
            return

        idx = self.play_index
        t_now = data["t"][idx]
        t_slice = data["t"][: idx + 1]

        # 更新曲线
        self.play_lines["roll"].set_data(t_slice, data["roll"][: idx + 1])
        self.play_lines["pitch"].set_data(t_slice, data["pitch"][: idx + 1])
        self.play_lines["yaw"].set_data(t_slice, data["yaw"][: idx + 1])
        self.play_lines["x"].set_data(t_slice, data["x"][: idx + 1])
        self.play_lines["y"].set_data(t_slice, data["y"][: idx + 1])
        self.play_lines["z"].set_data(t_slice, data["z"][: idx + 1])

        # 当前值
        y_roll  = data["roll"][idx]
        y_pitch = data["pitch"][idx]
        y_yaw   = data["yaw"][idx]
        y_x     = data["x"][idx]
        y_y     = data["y"][idx]
        y_z     = data["z"][idx]

        # 标记点 + 文本
        self.marker_lines["roll"].set_data([t_now], [y_roll])
        self.marker_lines["pitch"].set_data([t_now], [y_pitch])
        self.marker_lines["yaw"].set_data([t_now], [y_yaw])
        self.marker_lines["x"].set_data([t_now], [y_x])
        self.marker_lines["y"].set_data([t_now], [y_y])
        self.marker_lines["z"].set_data([t_now], [y_z])

        self.value_texts["roll"].set_position((t_now, y_roll))
        self.value_texts["roll"].set_text(f"{y_roll:.2f}")

        self.value_texts["pitch"].set_position((t_now, y_pitch))
        self.value_texts["pitch"].set_text(f"{y_pitch:.2f}")

        self.value_texts["yaw"].set_position((t_now, y_yaw))
        self.value_texts["yaw"].set_text(f"{y_yaw:.2f}")

        self.value_texts["x"].set_position((t_now, y_x))
        self.value_texts["x"].set_text(f"{y_x:.2f}")

        self.value_texts["y"].set_position((t_now, y_y))
        self.value_texts["y"].set_text(f"{y_y:.2f}")

        self.value_texts["z"].set_position((t_now, y_z))
        self.value_texts["z"].set_text(f"{y_z:.2f}")

        # 自适应坐标轴
        for r in range(3):
            for c in range(2):
                ax = self.canvas.axes[r, c]
                ax.relim()
                ax.autoscale_view()

        self.canvas.draw()

        # 发 UDP 正常播放命令
        if self.sock is not None and self.udp_target is not None:
            try:
                cmd = generate_a6t_command_for_index(data, idx, self.dt_ms) + "\n"
                self.sock.sendto(cmd.encode("utf-8"), self.udp_target)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "网络错误", f"发送失败，播放停止。\n{e}")
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                self.udp_target = None
                self.timer.stop()
                return

        # 更新时间显示
        t_display = t_now * 10
        total_display = self.total_time * 10
        self.info_label.setText(
            f"t = {t_display:.1f} s | 总时长 = {total_display:.1f} s"
        )

        self.play_index += 1

    # ---------- 停止阶段：线性插补到 0 ----------

    def stop_tick(self):
        """
        停止阶段：在 stop_total_steps 步内从 stop_start_values 线性减到 0
        每步仍按 dt_ms 间隔发送一条 @A6T 指令，并画出收尾直线
        """
        if self.data_cache is None:
            self.stopping_mode = False
            self.timer.stop()
            return

        # 插补完成：发送一条 0 指令并收尾
        if self.stop_step_index >= self.stop_total_steps:
            if self.sock is not None and self.udp_target is not None:
                try:
                    cmd = "@A6T:0.000,0.000,0.000,0.000,0.000,0.000,{}#\n".format(
                        self.dt_ms
                    )
                    self.sock.sendto(cmd.encode("utf-8"), self.udp_target)
                except Exception:
                    pass

            if self.sock is not None:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                self.udp_target = None

            self.timer.stop()
            self.stopping_mode = False
            self.play_index = 0

            total_display = self.total_time * 10
            self.info_label.setText(f"t = 0.0 s | 总时长 = {total_display:.1f} s")
            return

        # 插补比例：0→1
        ratio = (self.stop_step_index + 1) / self.stop_total_steps
        k = 1.0 - ratio  # 当前值 = 起始值 * k

        cur_vals = {
            name: self.stop_start_values[name] * k
            for name in ["roll", "pitch", "yaw", "x", "y", "z"]
        }

        # 时间从停止时刻开始向右延伸
        dt_s = self.dt_ms / 1000.0
        t_now = self.stop_start_time + self.stop_step_index * dt_s

        # 把新点追加到每条曲线末尾
        for name, line in self.play_lines.items():
            xdata, ydata = line.get_data()
            xdata = list(xdata)
            ydata = list(ydata)

            if self.stop_step_index == 0 and len(xdata) == 0:
                xdata = list(self.data_cache["t"])
                ydata = list(self.data_cache[name])

            xdata.append(t_now)
            ydata.append(cur_vals[name])
            line.set_data(xdata, ydata)

        # 标记点 + 文本
        self.marker_lines["roll"].set_data([t_now], [cur_vals["roll"]])
        self.marker_lines["pitch"].set_data([t_now], [cur_vals["pitch"]])
        self.marker_lines["yaw"].set_data([t_now], [cur_vals["yaw"]])
        self.marker_lines["x"].set_data([t_now], [cur_vals["x"]])
        self.marker_lines["y"].set_data([t_now], [cur_vals["y"]])
        self.marker_lines["z"].set_data([t_now], [cur_vals["z"]])

        self.value_texts["roll"].set_position((t_now, cur_vals["roll"]))
        self.value_texts["roll"].set_text(f"{cur_vals['roll']:.2f}")

        self.value_texts["pitch"].set_position((t_now, cur_vals["pitch"]))
        self.value_texts["pitch"].set_text(f"{cur_vals['pitch']:.2f}")

        self.value_texts["yaw"].set_position((t_now, cur_vals["yaw"]))
        self.value_texts["yaw"].set_text(f"{cur_vals['yaw']:.2f}")

        self.value_texts["x"].set_position((t_now, cur_vals["x"]))
        self.value_texts["x"].set_text(f"{cur_vals['x']:.2f}")

        self.value_texts["y"].set_position((t_now, cur_vals["y"]))
        self.value_texts["y"].set_text(f"{cur_vals['y']:.2f}")

        self.value_texts["z"].set_position((t_now, cur_vals["z"]))
        self.value_texts["z"].set_text(f"{cur_vals['z']:.2f}")

        # 发送停止阶段插补指令
        if self.sock is not None and self.udp_target is not None:
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
                self.sock.sendto(cmd.encode("utf-8"), self.udp_target)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "网络错误", f"停止插补发送失败：\n{e}")
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                self.udp_target = None
                self.timer.stop()
                self.stopping_mode = False
                return

        # 自适应坐标轴
        for r in range(3):
            for c in range(2):
                ax = self.canvas.axes[r, c]
                ax.relim()
                ax.autoscale_view()
                xmin, xmax = ax.get_xlim()
                if t_now > xmax:
                    ax.set_xlim(xmin, t_now)

        self.canvas.draw()

        # 信息栏提示正在停止
        t_display = t_now * 10
        total_display = self.total_time * 10
        self.info_label.setText(
            f"t = {t_display:.1f} s | 总时长 = {total_display:.1f} s (停止中…)"
        )

        self.stop_step_index += 1


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    window = MainWindow()
    window.resize(1100, 800)
    window.show()
    sys.exit(app.exec_())
