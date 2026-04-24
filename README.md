# Six-axis-controller

六自由度平台实时控制器，用于生成 Roll / Pitch / Yaw / X / Y / Z 六轴运动曲线，并通过 UDP 按固定时间间隔向外部控制器发送 `@A6T` 指令，实现六自由度平台、执行器或实验设备的实时运动控制。

项目主要基于 Python、PyQt5 和 Matplotlib 构建，提供图形化参数配置、实时曲线显示、UDP 指令发送和平滑停止功能。

## 功能特点

- 支持六轴独立配置：`roll`、`pitch`、`yaw`、`x`、`y`、`z`
- 支持每个轴启用 / 禁用、相位角设置和分段运动参数输入
- 支持多段周期运动配置，格式为：`T,A,N;T,A,N;...`
  - `T`：周期，单位秒
  - `A`：幅值，角度轴单位为度，位移轴单位为 mm
  - `N`：周期个数
- 支持启动缓冲，前几个周期自动按较小幅值逐步过渡
- 支持实时绘制 6 个通道的运动曲线
- 支持 UDP 实时发送控制指令
- 支持点击停止后线性插补衰减到 0，避免设备突停
- `real_time_controller.py` 使用 `QThread + QTimer(Qt.PreciseTimer)` 实现独立发送线程，降低 UI 绘图对发送周期的影响

## 适用场景

- 六自由度运动平台控制
- 执行器、舵机、机构的同步轨迹控制
- 水下机器人 / 具身智能机器人轨迹调度
- 实验设备的周期激励、扰动模拟与实时控制
- 任意需要“波形生成 + 实时曲线显示 + UDP 周期发送”的硬件控制任务

## 项目文件

```text
Six-axis-controller/
├── real_time_controller.py   # 推荐使用：实时多线程六轴控制器
├── six_wave_app.py           # 简化版六轴波形控制程序
├── .gitignore
└── README.md
```

> 注：仓库历史中曾包含与本项目无关的模型下载 / 多模态模型脚本，最新提交已删除。

## 环境要求

建议使用 Python 3.10 或更高版本。

依赖库：

```bash
pip install PyQt5 matplotlib
```

如果需要打包为可执行程序，可额外安装：

```bash
pip install pyinstaller
```

## 快速开始

克隆仓库：

```bash
git clone https://github.com/UTSJiyaoLi/Six-axis-controller.git
cd Six-axis-controller
```

安装依赖：

```bash
pip install PyQt5 matplotlib
```

运行推荐版本：

```bash
python real_time_controller.py
```

或者运行简化版本：

```bash
python six_wave_app.py
```

## 使用说明

1. 打开程序后，设置目标设备的 IP 和端口。
2. 勾选需要启用的轴。
3. 在每个轴的“分段配置”中输入运动参数。
4. 设置相位角，例如 `0`、`90`、`180` 等。
5. 点击“开始”或“开始播放”，程序会：
   - 生成六轴时序数据；
   - 绘制实时曲线；
   - 按 `dt_ms` 周期发送 UDP 指令。
6. 点击“停止”，程序会从当前值开始线性衰减到 0，并发送最终归零指令。

## 分段配置格式

每个轴的配置格式为：

```text
T,A,N;T,A,N;...
```

示例：

```text
2,3,5;1,5,10
```

表示：

- 第一段：周期 `2 s`，幅值 `3`，重复 `5` 个周期
- 第二段：周期 `1 s`，幅值 `5`，重复 `10` 个周期

程序会自动将多段运动拼接成完整轨迹。

## UDP 指令格式

程序发送的指令格式为：

```text
@A6T:roll,pitch,yaw,x,y,z,dt_ms#
```

示例：

```text
@A6T:1.234,0.000,-2.500,10.000,0.000,40.000,10#
```

字段含义：

| 字段 | 含义 |
|---|---|
| `roll` | Roll 角度 |
| `pitch` | Pitch 角度 |
| `yaw` | Yaw 角度 |
| `x` | X 位移 |
| `y` | Y 位移 |
| `z` | Z 位移 |
| `dt_ms` | 当前指令时间间隔，单位 ms |

## 核心实现逻辑

### 1. 波形生成

程序通过 `WaveSegment` 和 `AxisProgram` 描述每个轴的运动参数，并根据 `dt_ms` 生成真实时间轴上的离散数据。

### 2. 六轴数据计算

`generate_a6t_data()` 会生成以下数据：

```python
{
    "t": [...],
    "roll": [...],
    "pitch": [...],
    "yaw": [...],
    "x": [...],
    "y": [...],
    "z": [...],
}
```

### 3. 指令生成

`generate_a6t_command_for_index()` 会把某一时刻的六轴数据转换为 `@A6T` 控制指令。

### 4. 实时发送

`real_time_controller.py` 中的 `SenderWorker` 使用独立线程发送 UDP 数据，避免 UI 绘图阻塞实时发送。

### 5. 平滑停止

停止时，程序会记录当前六轴值，并在 `stop_duration_ms` 时间内线性插补到 0，最后发送一条全 0 指令。

## 打包为 exe

如果需要在 Windows 上打包：

```bash
pyinstaller -F -w real_time_controller.py
```

如果需要包含图标文件：

```bash
pyinstaller -F -w -i icon.ico real_time_controller.py
```

打包完成后，可执行文件通常位于：

```text
dist/real_time_controller.exe
```

## 注意事项

- 运行前请确认目标 IP 和端口正确。
- `dt_ms` 不宜设置过小，否则可能受系统定时器、网络和设备处理能力影响。
- 若用于真实硬件设备，请先在安全环境下低幅值测试。
- 停止功能采用线性衰减，但具体硬件仍需自行确认是否具备安全限位和急停保护。
- Matplotlib 中文显示依赖系统字体，程序会优先尝试 `Microsoft YaHei`、`SimHei`、`Arial Unicode MS`。

## License

本项目当前未声明开源许可证。如需公开复用、二次开发或商业使用，建议后续补充 LICENSE 文件。
