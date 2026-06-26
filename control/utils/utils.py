import json
import os
import shutil
import sys

import sounddevice as sd
import numpy as np
from PyQt5.QtWidgets import QMessageBox, QApplication
from scipy.fft import fft
from scipy.signal import get_window, csd, welch, medfilt

from control.log_manager import LogManager
from control.output_voltage_interface import SoundcardCalibrationManager
from custom.running_consts import DEFAULT_DIR, base_dir


def set_adjust_button_enabled(button, enabled: bool):
    button.setEnabled(enabled)
    if enabled:
        button.setStyleSheet("""
               QToolButton {
                       padding-top: 6px;
                       padding-bottom: 3px;
                       color: black;
                }
           """)
    else:
        # 禁用样式（灰色）
        button.setStyleSheet("""
               QToolButton {
                       padding-top: 6px;
                       padding-bottom: 3px;
                       color: gray;
                   }
           """)
    QApplication.processEvents()


def set_run_button_enabled(button, enabled: bool):
    """
    控制 run_test_button 启用状态和样式
    :param enabled: True 启用按钮，False 禁用按钮
    """
    button.setEnabled(enabled)
    if enabled:
        # 启用样式（亮蓝色）
        button.setStyleSheet("""
             QToolButton {
                    background-color: rgb(0, 170, 255);
                    border-radius: 5px;
                    font: bold 12pt "Microsoft YaHei";
                }
        """)
    else:
        # 禁用样式（灰色）
        button.setStyleSheet("""
            QToolButton {
                    background-color: rgb(209, 209, 209);
                    border-radius: 5px;
                    font: bold 12pt "Microsoft YaHei";
                    color: gray;
                }
        """)

def is_float(str):
    try:
        float(str)
        return True
    except ValueError:
        return False


def show_error_message(msg: str, parent=None) -> None:
    """
    在主线程弹出错误提示框。
    parmas：
        msg (str): 错误提示文本。
        parent (QWidget): 父窗口对象，用于对话框定位（可选）。
    """
    QMessageBox.critical(parent, "错误", msg)

def show_success_message(msg: str, parent=None) -> None:
    """在主线程弹出成功提示框。"""
    QMessageBox.information(parent, "成功", msg)

def show_warning_message(msg: str, parent=None) -> None:
    """在主线程弹出警告提示框。"""
    QMessageBox.warning(parent, "警告", msg)

def generate_chirp_wrapper(info: dict, samplerate: int):
    return generate_chirp(
        duration=info["signal_time"],
        f_start=info["hz_down"],
        f_stop=info["hz_up"],
        amplitude=info["signal_amplitude"],
        sample_rate = samplerate
    )

def generate_chirp(duration: float,
                   f_start: float,
                   f_stop: float,
                   amplitude: float = 1.0,
                   sample_rate: int = 44100,
                   mirror: bool = False,
                   repeat_times: int = 1):
    """
    生成对数 chirp 信号 (logarithmic sweep)

    Parameters
    ----------
    duration      : float   单次信号时长 (s)
    f_start       : float   起始频率  (Hz)
    f_stop        : float   终止频率  (Hz)
    amplitude     : float   ±幅值   (默认 1.0)
    sample_rate   : int     采样率 (Hz，默认 44100Hz)
    mirror        : bool    True 时生成镜像扫频 (先↑再↓并反相)，时长加倍
    repeat_times  : int     将整段信号重复播放 N 次

    Returns
    -------
    t : np.ndarray   时间轴 (s)
    y : np.ndarray   波形数据 (float32)
    """
    # ---------- 单段 chirp ----------
    t_single = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    if f_start == f_stop:  # 万一两频率一样，就退化成恒频
        phase = 2 * np.pi * f_start * t_single
    else:
        ln_ratio = np.log(f_stop / f_start)
        phase = 2 * np.pi * f_start * duration / ln_ratio * (
                np.exp(ln_ratio * t_single / duration) - 1
        )

    y_single = amplitude * np.sin(phase)

    # ---------- 镜像扫频（可选） ----------
    if mirror:
        # 反向 + 反相，拼接在后
        y_single = np.concatenate([y_single[::-1], -y_single])
        t_single = np.linspace(0, duration * 2, y_single.size, endpoint=False)

    # ---------- 重复播放（可选） ----------
    if repeat_times > 1:
        y = np.tile(y_single, repeat_times)
        t = np.linspace(0, t_single[-1] * repeat_times + t_single[1], y.size, endpoint=False)
    else:
        y, t = y_single, t_single

    return t, y.astype(np.float32)


def calculate_mit_4mic(
        ax=None, bx=None, cx=None, dx=None,
        ax_cal=None, bx_cal=None, cx_cal=None, dx_cal=None,
        sf=44100, temp=25, atm=101, dia_tube_mm=20,
        L_mm=100, x1_mm=10, x2_mm=30, x3_mm=50,
        s2=28, sens=0.212, vfactor=1.0
):
    """
    基于四传声器法计算阻抗管的声阻抗 Z 和体积速度 V。

    参数:
    - ax, bx, cx, dx : ndarray
        采集数据：四个麦克风的时域数据
    - ax_cal, bx_cal, cx_cal, dx_cal : ndarray
        校准数据：四个麦克风的时域数据
    - sf : int, default=44100
        采样率（Hz）
    - temp : float, default=25
        实验温度（摄氏度）
    - atm : float, default=101
        实验大气压（kPa）
    - dia_tube_mm : float, default=20
        管道直径（mm）
    - L_mm : float, default=40
        管道长度（mm）
    - x1_mm, x2_mm, x3_mm : float, default=270,75,50
        麦克风位置（mm）
    - s2 : float, default=28
        参考面积（mm²）
    - sens : float, default=0.212
        传感器灵敏度
    - vfactor : float, default=1.0
        速度因子

    返回:
    - out_ff : ndarray
        频率向量 (列向量)
    - out_absZ : ndarray
        Z 的模 (列向量)
    - out_realZ : ndarray
        Z 的实部绝对值 (列向量)
    - out_imagZ : ndarray
        Z 的虚部绝对值 (列向量)
    - out_absV : ndarray
        V 的模 (列向量)
    - out_realV : ndarray
        V 的实部绝对值 (列向量)
    - out_imagV : ndarray
        V 的虚部绝对值 (列向量)
    """

    # 常量定义
    atm0 = 101.325  # 标准大气压 千帕斯卡
    temp0 = 298  # 298 K, 25 摄氏度
    rho0 = 1.186  # 空气标准密度 千克立方米

    # 计算声速、密度、特性阻抗
    c0 = 343.2 * np.sqrt((temp + 273) / temp0)  # 实际声速 米每秒
    rho = rho0 * (atm / atm0) * (temp0 / (temp + 273))  # 空气实际密度 千克立方米
    Z0 = c0 * rho0

    # 单位转换：mm -> m
    dia_tube = dia_tube_mm / 1000
    L = L_mm / 1000
    x1 = x1_mm / 1000
    x2 = x2_mm / 1000
    x3 = x3_mm / 1000

    # 计算面积因子
    s1 = np.pi * ((dia_tube * 1000) / 2) ** 2  # 圆管横截面积
    factor = s1 / s2  # 实际截面积比例

    # FFT参数设置
    nfft = sf
    w = get_window('hann', nfft)  # 汉宁窗

    # 传递函数估计函数
    def tfestimate(x, y, fs, nfft, window):
        f, Pxy = csd(x, y, fs=fs, window=window, nperseg=nfft, noverlap=nfft // 2, nfft=nfft)
        f = f[1:]
        Pxy = Pxy[1:]
        _, Pxx = welch(x, fs=fs, window=window, nperseg=nfft, noverlap=nfft // 2, nfft=nfft)
        Pxx = Pxx[1:]
        Hxy = Pxy / Pxx
        return Hxy, f

    # 传递函数计算
    tf43, ff = tfestimate(dx, cx, fs=sf, nfft=nfft, window=w)  # H43, frequency
    tf13, _ = tfestimate(ax, cx, fs=sf, nfft=nfft, window=w)  # H13, frequency, 221Hz - 1500Hz
    tf23, _ = tfestimate(bx, cx, fs=sf, nfft=nfft, window=w)  # H23, frequency, 1501Hz - 10kHz
    tf43_cal, _ = tfestimate(dx_cal, cx_cal, fs=sf, nfft=nfft, window=w)  # H43 calibrate, frequency
    tf13_cal, _ = tfestimate(ax_cal, cx_cal, fs=sf, nfft=nfft, window=w)  # H13 calibrate, frequency, 221Hz - 1500Hz
    tf23_cal, _ = tfestimate(bx_cal, cx_cal, fs=sf, nfft=nfft, window=w)  # H23, frequency, 1501Hz - 10kHz

    # MIT方法计算
    tf = np.zeros(len(ff), dtype=complex)
    k = np.zeros(len(ff))
    Z1 = np.zeros(len(ff), dtype=complex)

    for n in range(len(ff)):
        tf[n] = tf43[n] / tf43_cal[n]
        k[n] = 2 * np.pi * ff[n] / c0 - 0.0194 * np.sqrt(ff[n]) / (c0 * dia_tube)
        Z1[n] = Z0 / (1j * np.sin(k[n] * L)) * (tf[n] - np.cos(k[n] * L)) / factor

    # 计算速度
    N = len(dx)
    n = np.arange(N)
    p4fft = fft(dx, N)
    p4fftmag = vfactor * p4fft * 2 / N  # 转化为实际幅值
    f = n * sf / N

    k_v = np.zeros(len(f))
    v = np.zeros(len(f), dtype=complex)

    for n in range(len(f)):
        k_v[n] = 2 * np.pi * f[n] / c0 - 0.0194 * np.sqrt(f[n]) / (c0 * dia_tube)
        v[n] = p4fftmag[n] / Z0 * 1j * np.sin(k_v[n] * L) * factor / sens

    # 221Hz - 1500Hz 有效
    tf2 = np.zeros(len(ff), dtype=complex)
    Z2 = np.zeros(len(ff), dtype=complex)
    r13 = np.zeros(len(ff), dtype=complex)

    for n in range(len(ff)):
        tf2[n] = tf13[n] / tf13_cal[n]
        k[n] = 2 * np.pi * ff[n] / c0 - 0.0194 * np.sqrt(ff[n]) / (c0 * dia_tube)
        r13[n] = (tf2[n] * np.exp(1j * k[n] * x1) - np.exp(1j * k[n] * x3)) / (
                    np.exp(-1j * k[n] * x3) - tf2[n] * np.exp(-1j * k[n] * x1))
        Z2[n] = Z0 / (1j * np.sin(k[n] * L)) * (
                    tf[n] * ((1 + r13[n]) / (np.exp(1j * k[n] * x3) + r13[n] * np.exp(-1j * k[n] * x3))) - np.cos(
                k[n] * L)) / factor

    # 1501Hz - 10kHz 有效
    tf3 = np.zeros(len(ff), dtype=complex)
    Z3 = np.zeros(len(ff), dtype=complex)
    r23 = np.zeros(len(ff), dtype=complex)

    for n in range(len(ff)):
        tf3[n] = tf23[n] / tf23_cal[n]
        k[n] = 2 * np.pi * ff[n] / c0 - 0.0194 * np.sqrt(ff[n]) / (c0 * dia_tube)
        r23[n] = (tf3[n] * np.exp(1j * k[n] * x2) - np.exp(1j * k[n] * x3)) / (
                    np.exp(-1j * k[n] * x3) - tf3[n] * np.exp(-1j * k[n] * x2))
        Z3[n] = Z0 / (1j * np.sin(k[n] * L)) * (
                    tf[n] * ((1 + r23[n]) / (np.exp(1j * k[n] * x3) + r23[n] * np.exp(-1j * k[n] * x3))) - np.cos(
                k[n] * L)) / factor

    # 合并数据
    V = np.zeros(10000, dtype=complex)
    fre = np.zeros(10000)
    Z = np.zeros(10000, dtype=complex)

    # 速度数据 (11:10001)
    for n in range(10, 10001):
        V[n - 10] = v[n]

    # 频率和阻抗数据 (11:221)
    for n in range(10, 221):
        fre[n - 10] = ff[n]
        Z[n - 10] = Z1[n]

    # 频率和阻抗数据 (222:1501)
    for n in range(221, 1501):
        fre[n - 10] = ff[n]
        Z[n - 10] = Z2[n]

    # 频率和阻抗数据 (1502:10001)
    for n in range(1501, 10001):
        fre[n - 10] = ff[n]
        Z[n - 10] = Z3[n]

    # 数据输出（中值滤波）
    out_ff = fre
    out_absZ = medfilt(np.abs(Z), 11)
    out_realZ = medfilt(np.abs(np.real(Z)), 11)
    out_imagZ = medfilt(np.abs(np.imag(Z)), 11)
    out_absV = medfilt(np.abs(V), 11)
    out_realV = medfilt(np.abs(np.real(V)), 11)
    out_imagV = medfilt(np.abs(np.imag(V)), 11)

    return out_ff, out_absZ, out_realZ, out_imagZ, out_absV, out_realV, out_imagV

def copy_all_configs_to_base_dir():
    logger = LogManager.set_log_handler("拷贝配置文件")
    # 创建目录
    target_config_dir = os.path.join(base_dir, "resources", "config")
    os.makedirs(target_config_dir, exist_ok=True)

    json_files = [
        "imp_tube_params_setting.json",
        "output_signal_setting.json",
        "basic_params.json",
        "calibration_coefficients.json",
        "mic_calibration.json"
    ]

    for filename in json_files:
        target_path = os.path.join(target_config_dir, filename)
        # 若已存在就跳过，避免覆盖用户数据
        if os.path.exists(target_path):
            continue

        try:
            # 判断运行模式：打包或源码
            if getattr(sys, 'frozen', False):
                # exe 模式下资源路径
                sys_path = os.path.join(sys._MEIPASS, "resources", "config", filename)
                shutil.copyfile(sys_path, target_path)

                logger.info(f"[已复制] {filename} → {target_path}")
            else:
                # 源码运行时路径
                pass

        except Exception as e:
            logger.info(f"[错误] 复制 {filename} 失败: {e}")


def get_config_path(filename):
    """
    获取配置文件路径，兼容打包与源码运行
    """
    try:
        if getattr(sys, 'frozen', False):
            # exe 打包后, 从迁移的 base_dir中获取
            return os.path.join(base_dir, "resources", "config", filename)
        else:
            # 源码运行时, 根目录下
            return os.path.join(DEFAULT_DIR, "resources", "config", filename)
    except Exception as e:
        print(f"获取配置路径失败: {e}")
        return None

def get_config_content(filename):
    """
    读取配置文件内容（JSON）。
    参数:
        filename (str): 配置文件名，例如 "basic_params.json"
    返回:
            - (True, config) : 读取成功，返回配置字典
            - (False, None) : 读取失败
    """
    path = get_config_path(filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return True, config
    except Exception:
        return False, None

def write_config_content(filename, config):
    """
    将更新后的配置内容保存回文件。
    参数:
        filename (str): 配置文件名，例如 "mic_calibration.json"
        config (dict): 要保存的配置字典
    返回:
        - True : 保存成功
        - False : 保存失败
    """
    path = get_config_path(filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"写入文件失败: {e}")
        return False

def get_device_info():
    """获取选择设备的详细信息"""
    logger = LogManager.set_log_handler("获取设备采样率")
    try:
        # 获取默认输入/输出设备 ID（返回的是一个元组）
        default_input, default_output = sd.default.device

        output_device = sd.query_devices(default_output)
        # 获取并返回默认采样率
        name = output_device['name']
        default_samplerate = int(output_device['default_samplerate'])
        return default_samplerate

    except Exception as e:
        logger.info(f"获取采样率失败: {e}")
        return None

def init_selected_devide():
    """
    初始化输入输出设备。
    - 从 basic_params.json 读取配置（设备名、类型、采样率）。
    - 在本机设备中查找匹配的输入/输出设备。
    - 找到后设置为默认设备，否则报错。
    """
    logger = LogManager.set_log_handler("初始化选择设备")

    try:
        config_path = get_config_path("basic_params.json")
        if not os.path.exists(config_path):
            logger.critical(f"配置文件{config_path}不存在")
            raise FileNotFoundError(f"配置文件{config_path}不存在")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            input_name = config["basic_params"]["input_selected_device_name"]
            input_type = config["basic_params"]["input_selected_device_type"]
            input_rate = config["basic_params"]["input_selected_device_samplerate"]
            output_name = config["basic_params"]["output_selected_device_name"]
            output_type = config["basic_params"]["output_selected_device_type"]
            output_rate = config["basic_params"]["output_selected_device_samplerate"]
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()

            input_index = None
            output_index = None

            # 匹配输入设备
            for idx, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    dev_name = dev["name"]
                    dev_type = hostapis[dev["hostapi"]]["name"]
                    dev_rate = str(int(dev.get("default_samplerate", 0)))
                    if dev_name == input_name and dev_type == input_type and dev_rate == input_rate:
                        input_index = idx
                        logger.info(f"匹配到输入设备 index={input_index}：{dev_name} ({dev_type}, {dev_rate})")
                        break

            # 匹配输出设备
            for idx, dev in enumerate(devices):
                if dev["max_output_channels"] > 0:
                    dev_name = dev["name"]
                    dev_type = hostapis[dev["hostapi"]]["name"]
                    dev_rate = str(int(dev.get("default_samplerate", 0)))
                    if dev_name == output_name and dev_type == output_type and dev_rate == output_rate:
                        output_index = idx
                        logger.info(f"匹配到输出设备 index={output_index}：{dev_name} ({dev_type}, {dev_rate})")
                        break
            # 如果都匹配到了，则设置默认设备
            if input_index is not None and output_index is not None:
                sd.default.device = (input_index, output_index)
                logger.info(f"已设置默认输入输出设备: {input_index}, {output_index}")
            else:
                logger.critical(f"找不到匹配的输入或输出设备，请重新选择")
                raise RuntimeError("提示：默认设备已改变, 请重新选择设备！")

    except Exception as e:
        QMessageBox.warning(None, "初始化设备失败", f"{e}")

def save_selected_devices(input_device_index, output_device_index, input_device_name, output_device_name, input_type,
                          output_type, input_samplerate, output_samplerate, input_channel_count):
    """
    保存选择的设备信息到 basic_params.json。
    - 打开配置文件并更新输入/输出设备参数。
    - 将修改后的配置写回文件。
    """
    try:
        config_path = get_config_path("basic_params.json")

        # 如果文件不存在，直接报错
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        # 加载配置文件
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 确保 basic_params 存在
        if "basic_params" not in config:
            raise KeyError("配置文件缺少 'basic_params' 字段")
        # 更新设备信息
        if (
                config["basic_params"].get("input_selected_device_id") != input_device_index
                or config["basic_params"].get("input_selected_device_name") != input_device_name
                or config["basic_params"].get("input_selected_device_type") != input_type
                or config["basic_params"].get("input_selected_device_samplerate") != input_samplerate
        ):
            config["basic_params"]["is_clear"] = 1  # 1是清空mic_cal.json
        config["basic_params"]["input_selected_device_id"] = input_device_index
        config["basic_params"]["input_selected_device_name"] = input_device_name
        config["basic_params"]["input_selected_device_type"] = input_type
        config["basic_params"]["input_selected_device_samplerate"] = input_samplerate

        config["basic_params"]["output_selected_device_id"] = output_device_index
        config["basic_params"]["output_selected_device_name"] = output_device_name
        config["basic_params"]["output_selected_device_type"] = output_type
        config["basic_params"]["output_selected_device_samplerate"] = output_samplerate
        config["basic_params"]["input_channel_count"] = input_channel_count
        # 写入文件
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        raise RuntimeError(f"保存 selected_devices 到 basic_params.json 失败: {e}")

def refresh_mic_config_json(obj):
    try:
        config_path = get_config_path("basic_params.json")

        # 如果文件不存在，直接报错
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        # 加载配置文件
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            count = config["basic_params"]["input_channel_count"]
        mic_json_path = get_config_path("mic_calibration.json")
        if config["basic_params"]["is_clear"] == 1:
            # 按 count 生成 { "In1": {...}, ..., "InN": {...} }
            mic_cfg = {
                f"In{i}": {
                    "deviation_value": "0",
                    "binding_index": i - 1
                }
                for i in range(1, count + 1)
            }
            if count == 0:
                mic_cfg = {}
            with open(mic_json_path, "w", encoding="utf-8") as file:
                json.dump(mic_cfg, file, ensure_ascii=False, indent=4)
            config["basic_params"]["is_clear"] = 0
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            obj.logger.info(
                f"is_clear=1，已按通道数({count})重建 mic_calibration.json -> {mic_json_path}"
            )
        else:
            obj.logger.info("is_clear=0，mic_calibration.json 保持不变")
    except Exception as e:
        raise RuntimeError(f"重载mic_calibration.json 失败: {e}")

def custom_log_tick_strings(values, scale, spacing):
    estrings = ["%0.1g" % x for x in 10 ** np.array(values).astype(float) * np.array(scale)]
    convdict = {
        "0": "⁰",
        "1": "¹",
        "2": "²",
        "3": "³",
        "4": "⁴",
        "5": "⁵",
        "6": "⁶",
        "7": "⁷",
        "8": "⁸",
        "9": "⁹",
    }
    dstrings = []
    for i, e in enumerate(estrings):
        if "e" in e:
            v, p = e.split("e")
            sign = "⁻" if p[0] == "-" else ""
            pot = "".join([convdict[pp] for pp in p[1:].lstrip("0")])
            if v == "1":
                v = ""
                dstrings.append(v + "10" + sign + pot)
            elif v == "2" or v == "5":
                v = v + "·"
                dstrings.append(v + "10" + sign + pot)
            else:
                dstrings.append("")
        else:
            dstrings.append(e)
    return dstrings

def generate_calibrated_signal(signal_info, samplerate):
    """
    生成校准后的激励信号
    参数:
        signal_info: dict, 包含信号参数，其中 "signal_amplitude" 表示目标电压幅值 (V)
        samplerate: int, 采样率

    返回:
        success (bool): 是否成功
        data (ndarray): 已按校准幅值缩放后的信号数据
        cal_amplitude (float): 校准后的幅值（实际用于缩放的因子，单位 V）
        error_msg (str): 失败时的错误信息，否则为 None
    """
    params_voltage = signal_info["signal_amplitude"]
    scm = SoundcardCalibrationManager()
    # 用y=ax+b校准函数求幅值因子cal_amplitude
    calibrate_code, calibrate_result = scm.calibrate_amplitude(params_voltage)
    if calibrate_code != True:
        return False, None, None, f"校准幅值失败：{calibrate_result}"
    cal_amplitude, max_voltage = calibrate_result
    if params_voltage > max_voltage:
        return False, None, None, f"参数电压过大（{params_voltage}V），最大可达 {max_voltage}V。"
    # 信号归一化
    signal_info['signal_amplitude'] = 1
    _, data = generate_chirp_wrapper(signal_info, samplerate)
    # 用幅值因子进行缩放
    data = data * cal_amplitude
    return True, data, cal_amplitude, None

def compute_fft(y, sr):
    """
    计算输入信号的快速傅里叶变换（FFT）并返回频率和幅值谱

    参数:
        y : 输入信号（一维数组）
        sr: 采样率（Hz）

    返回:
        f  : 频率数组
        mag: 幅值谱
    """
    Y = np.fft.rfft(y)  # 对信号进行实数快速傅里叶变换，返回正频率部分
    f = np.fft.rfftfreq(len(y), 1/sr)  # 计算对应的频率坐标
    return f, np.abs(Y)  # 返回频率和幅值谱