import json
import os
import subprocess
import sys

import numpy as np
import sounddevice as sd
import pyqtgraph
from PyQt5.QtCore import QFile, Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QMainWindow, QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QVBoxLayout
from PyQt5.uic import loadUi
from pyqtgraph import mkPen

from control.imp_tube_params_setting_interface import ImptubeParamsSetInterface
from control.log_manager import LogManager
from control.mic_adjust_interface import MicAdjustInterface
from control.output_signal_setting_interface import OutputSignalSetInterface
from control.output_voltage_interface import MicoutputVoltageInterface

from control.select_deivce_interface import SelectDeviceInterface
from control.utils import utils
from control.utils.audio_session_manager import AudioSessionManager
from control.utils.streaming_audio_processor import DuplexStreamingPlayRec
from custom.customSignals import sign
from resources import icons_rc, ui_rc # 导入资源


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.device_window = None
        self.imptube_window = None
        self.output_window = None
        self.mic_window = None
        self.output_voltage_window = None
        self.signal_info = None
        self.tube_params = None
        self.is_testing = False

        self.mic_binding = (0, 1, 2, 3)
        self.mic_deviation_db = (0, 0, 0, 0)

        # ===== 流式录音相关 =====
        self.stream_instance = None
        self.stream_timer = QTimer(self)
        self.stream_timer.timeout.connect(self._handle_stream_queue_and_update_ui)

        self.streaming_buffer = []  # 实时显示缓存

        self.logger = LogManager.set_log_handler("主窗口")
        self.init_ui()
        self.init_fun()
        self.init_image()
        self.init_view()

    def init_ui(self):
        ui_file = QFile(":ui/window.ui")
        ui_file.open(QFile.ReadOnly)
        loadUi(ui_file, self)
        # 设置窗口标题和大小
        self.setWindowTitle('采集输出软件V1.0')
        self.showMaximized()

        # 设置窗口图标
        self.setWindowIcon(QIcon(':/images/dongyuan.png'))
        # 获取主界面的布局并设置内容的边距
        layout = self.centralWidget().layout()  # 获取 QMainWindow 的中心控件的布局
        if layout:
            layout.setContentsMargins(1, 1, 1, 1)

    def init_fun(self):
        self.action_2.triggered.disconnect()
        self.action_2.triggered.connect(self.open_select_device_interface)
        self.action.triggered.disconnect()
        self.action.triggered.connect(self.open_imptube_params_setting_interface)
        self.action_3.triggered.disconnect()
        self.action_3.triggered.connect(self.open_output_signal_setting_interface)
        self.action_9.triggered.disconnect()
        self.action_9.triggered.connect(self.open_mic_adjust_interface)
        self.action_4.triggered.disconnect()
        self.action_4.triggered.connect(self.open_output_voltage_interface)
        self.action_14.triggered.disconnect()
        self.action_14.triggered.connect(self.popup_pdf)
        self.run_test_button.clicked.connect(self.run_test)

    def init_image(self):
        scene = QGraphicsScene()
        pixmap = QPixmap(":/images/4mic薄层_画板.png")
        scaled_pixmap = pixmap.scaled(390, 282, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # 缩小图像
        pixmap_item = QGraphicsPixmapItem(scaled_pixmap)
        scene.addItem(pixmap_item)
        self.schematic1.setScene(scene)


    def init_view(self):
        self.plot1 = pyqtgraph.PlotWidget()
        layout1 = QVBoxLayout()
        layout1.setContentsMargins(0, 0, 0, 0)
        layout1.addWidget(self.plot1)
        self.frame.setLayout(layout1)
        self.plot1.setBackground('white')
        self.plot1.setLabel('bottom', 'Time', units='s')
        self.plot1.setLabel('left', 'Amplitude', units='Pa')
        self.plot1.getAxis('bottom').setTextPen("black")
        self.plot1.getAxis('left').setTextPen("black")
        self.plot1.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot1.getAxis('left').enableAutoSIPrefix(False)
        self.plot1.showGrid(x=True, y=True, alpha=0.25)
        self.curve1 = self.plot1.plot([], [], pen=mkPen(color=(76, 120, 168)))

        self.plot2 = pyqtgraph.PlotWidget()
        layout2 = QVBoxLayout()
        layout2.setContentsMargins(0, 0, 0, 0)
        layout2.addWidget(self.plot2)
        self.frame_2.setLayout(layout2)
        self.plot2.setBackground('white')
        self.plot2.setLabel('bottom', 'Time', units='s')
        self.plot2.setLabel('left', 'Amplitude', units='Pa')
        self.plot2.getAxis('bottom').setTextPen("black")
        self.plot2.getAxis('left').setTextPen("black")
        self.plot2.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot2.getAxis('left').enableAutoSIPrefix(False)
        self.plot2.showGrid(x=True, y=True, alpha=0.25)
        self.curve2 = self.plot2.plot([], [], pen=mkPen(color=(84, 162, 75)))

        self.plot4 = pyqtgraph.PlotWidget()
        layout4 = QVBoxLayout()
        layout4.setContentsMargins(0, 0, 0, 0)
        layout4.addWidget(self.plot4)
        self.frame_4.setLayout(layout4)
        self.plot4.setBackground('white')
        self.plot4.setLabel('bottom', 'Time', units='s')
        self.plot4.setLabel('left', 'Amplitude', units='Pa')
        self.plot4.getAxis('bottom').setTextPen("black")
        self.plot4.getAxis('left').setTextPen("black")
        self.plot4.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot4.getAxis('left').enableAutoSIPrefix(False)
        self.plot4.showGrid(x=True, y=True, alpha=0.25)
        self.curve4 = self.plot4.plot([], [], pen=mkPen(color=(245, 133, 24)))

        self.plot5 = pyqtgraph.PlotWidget()
        layout5 = QVBoxLayout()
        layout5.setContentsMargins(0, 0, 0, 0)
        layout5.addWidget(self.plot5)
        self.frame_5.setLayout(layout5)
        self.plot5.setBackground('white')
        self.plot5.setLabel('bottom', 'Time', units='s')
        self.plot5.setLabel('left', 'Amplitude', units='Pa')
        self.plot5.getAxis('bottom').setTextPen("black")
        self.plot5.getAxis('left').setTextPen("black")
        self.plot5.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot5.getAxis('left').enableAutoSIPrefix(False)
        self.plot5.showGrid(x=True, y=True, alpha=0.25)
        self.curve5 = self.plot5.plot([], [], pen=mkPen(color=(178, 121, 162)))

    def open_select_device_interface(self):
        if self.device_window is None:
            self.device_window = SelectDeviceInterface(self)
        self.device_window.show()
        self.device_window.raise_()  # 窗口置顶
        self.device_window.activateWindow()


    def open_imptube_params_setting_interface(self):
        if self.imptube_window is None:
            self.imptube_window = ImptubeParamsSetInterface(self)
        self.imptube_window.show()
        self.imptube_window.raise_()  # 窗口置顶
        self.imptube_window.activateWindow()

    def open_output_signal_setting_interface(self):
        if self.output_window is None:
            self.output_window = OutputSignalSetInterface(self)
        self.output_window.show()
        self.output_window.raise_()
        self.output_window.activateWindow()

    def open_mic_adjust_interface(self):
        if self.mic_window is None:
            self.mic_window = MicAdjustInterface(self)
        self.mic_window.show()
        self.mic_window.raise_()
        self.mic_window.activateWindow()

    def open_output_voltage_interface(self):
        if self.output_voltage_window is None:
            self.output_voltage_window = MicoutputVoltageInterface(self)
        self.output_voltage_window.show()
        self.output_voltage_window.raise_()
        self.output_voltage_window.activateWindow()

    def init_config(self):
        output_path = utils.get_config_path("output_signal_setting.json")
        try:
            with open(output_path , "r", encoding="utf-8") as f:
                output_config  = json.load(f)
                self.signal_info = output_config .get("signal_info", {})
        except Exception as e:
            self.logger.error(f"读取配置失败: {e}")
            QMessageBox.warning(self, "错误", f"读取{output_path}配置失败：{e}")

        tube_path = utils.get_config_path("imp_tube_params_setting.json")
        try:
            with open(tube_path , "r", encoding="utf-8") as f:
                tube_config  = json.load(f)
                self.tube_params = tube_config.get("tube_params", {})

        except Exception as e:
            self.logger.error(f"读取配置失败: {e}")
            QMessageBox.warning(self, "错误", f"读取{tube_path}配置失败：{e}")

    def run_test(self):
        self.init_config()
        # 防止多个界面同时占用声卡
        if not AudioSessionManager.acquire(self):
            QMessageBox.warning(self, "提示", "音频设备正在被其它界面占用，请先停止/关闭其它录音功能。")
            self.test_state.setText("音频被占用")
            return
        utils.set_run_button_enabled(self.run_test_button, False)
        self.test_state.setText("测试中...")
        QApplication.processEvents()
        self.record_and_plot()
        self.run_test_button.setEnabled(True)
        # 启用按钮
        utils.set_run_button_enabled(self.run_test_button, True)

    def record_and_plot(self):
        try:
            self.curve1.setData([], [])
            self.curve2.setData([], [])
            self.curve4.setData([], [])
            self.curve5.setData([], [])

            QApplication.processEvents()
            # 获取设备采样率
            samplerate = utils.get_device_info()
            duration = self.signal_info['signal_time']

            self.streaming_buffer = []

            # 根据目标电压，校准并生成激励信号
            result, data, amplitude, msg = utils.generate_calibrated_signal(self.signal_info, samplerate)
            if result is False:
                raise ValueError(f"{msg}")
            input_channels = sd.query_devices(sd.default.device[0], 'input')['max_input_channels']
            output_channels = sd.query_devices(sd.default.device[1], 'output')['max_output_channels']
            print(f"最大输入通道数: {input_channels},输出通道: {output_channels}")
            self.logger.info(f"最大输入通道数: {input_channels},输出通道: {output_channels}")

            # 最多只处理 6 路麦克, 防止录音时通道数超过设备实际支持数导致程序崩溃
            if input_channels < 4:
                raise ValueError(f"检测到的输入通道数为 {input_channels},不足 4 个，无法进行完整校准，请选择别的设备！")

            stimulus_data = np.asarray(data, dtype=np.float32)

            if output_channels > 1:
                stimulus_data = np.column_stack([stimulus_data] * output_channels)

            # 读设备（你已经保存到 basic_params.json）
            ok, config = utils.get_config_content("basic_params.json")
            input_device = config["basic_params"]["input_selected_device_id"]
            output_device = config["basic_params"]["output_selected_device_id"]
            self.logger.info(
                f"开始流式播放并录音... dev=({input_device},{output_device})")

            self.stream_instance = DuplexStreamingPlayRec()
            self.stream_instance.start(
                stimulus_data=stimulus_data,
                sample_rate=samplerate,
                input_device=input_device,
                output_device=output_device,
                input_channels=int(input_channels),
                output_channels=int(output_channels),
                duration=duration,  # 你没有 prepare/prolong 就用 duration
                blocksize=2048,
            )
            self.stream_timer.start(50)  # 50ms 刷一次队列/判断结束
            return

        except Exception as e:
            self.record_stage = 0
            self.logger.exception("录音启动失败")
            self.test_state.setText(f"测试失败: {e}")
            sign.error_message_signal.emit(f"录音失败：{e}", self)
            utils.set_run_button_enabled(self.run_test_button, True)
            AudioSessionManager.release(self)

    def _handle_stream_queue_and_update_ui(self):
        if self.stream_instance is None:
            return

        # 1) 处理队列：把回调线程塞进来的 chunk 取出来
        chunks = self.stream_instance.process_queue()
        sr = self.stream_instance.sample_rate

        if chunks:
            # 2) 实时显示：只画最近 N 秒（避免越画越卡）
            duration = float(self.signal_info.get("signal_time", 5))
            keep_sr = int(duration * sr)

            # 维护滚动窗口（只保留最近 keep 个采样点）
            new_block = np.vstack(chunks)  # (k,4)
            self.streaming_buffer.append(new_block)  # 用 list 装块更快
            buf = np.vstack(self.streaming_buffer)
            if buf.shape[0] > keep_sr:
                buf = buf[-keep_sr:, :]
                self.streaming_buffer = [buf]  # 只保留一块，避免 list 无限增长

            # 时间轴：用累计样本数推算起点
            total_samples = self.stream_instance.samples_captured
            start_sample = max(0, total_samples - buf.shape[0])
            time_axis = (start_sample + np.arange(buf.shape[0])) / sr

            # 只做“时域实时更新”
            pa1, pa2, pa3, pa4 = MicAdjustInterface.process_chunks(buf, self.mic_binding, self.mic_deviation_db)

            self.update_plot(time_axis, pa1, pa2, pa3, pa4)

        # 3) 录音结束：录音停止-> 停timer-> 收集recording-> 释放stream流资源-> 处理recording
        if not self.stream_instance.is_recording:

            self.stream_timer.stop()

            err = getattr(self.stream_instance, "error", None)
            recording = self.stream_instance.get_recorded_data()  # (N, in_ch)

            self.stream_instance.stop()
            self.stream_instance = None

            try:
                if err:
                    raise RuntimeError(f"流式录音出错：{err}")

                self._handle_recording(recording, sr)

            except Exception as e:
                self.record_stage = 0
                self.logger.exception("录音后处理失败")
                self.test_state.setText(f"测试失败: {e}")
                utils.set_run_button_enabled(self.run_test_button, True)
                AudioSessionManager.release(self)

    def _handle_recording(self, recording, samplerate):
        duration = float(self.signal_info.get("signal_time", 0))

        # 1) 处理录音数据（拆通道 + 计算 real_spl/scale）
        (self.mic1_data, self.mic2_data, self.mic3_data, self.mic4_data,
         real_spl1, real_spl2, real_spl3, real_spl4, scale1, scale2, scale3, scale4) = \
            MicAdjustInterface.process_mic_channels_data(recording, self.mic_binding, self.mic_deviation_db)

        # 2) 转成 Pa
        self.mic1_pa = self.mic1_data * scale1
        self.mic2_pa = self.mic2_data * scale2
        self.mic3_pa = self.mic3_data * scale3
        self.mic4_pa = self.mic4_data * scale4
        # 3) 饱和提示
        if real_spl1 > 130:
            self.logger.error(f"麦克风1实际声压级 {real_spl1:.2f} dB, 超过阈值 {130} dB，已饱和")
        if real_spl2 > 130:
            self.logger.error(f"麦克风2实际声压级 {real_spl2:.2f} dB, 超过阈值 {130} dB，已饱和")
        if real_spl3 > 130:
            self.logger.error(f"麦克风3实际声压级 {real_spl3:.2f} dB, 超过阈值 {130} dB，已饱和")
        if real_spl4 > 130:
            self.logger.error(f"麦克风4实际声压级 {real_spl4:.2f} dB, 超过阈值 {130} dB，已饱和")
        utils.spl_warning(self,[real_spl1, real_spl2, real_spl3,real_spl4], 130)

        # 创建采集保存目录
        save_dir = os.path.join(os.getcwd(), "！采集")
        os.makedirs(save_dir, exist_ok=True)
        mic1_txt = os.path.join(save_dir, "MIC1.txt")
        mic2_txt = os.path.join(save_dir, "MIC2.txt")
        mic3_txt = os.path.join(save_dir, "MIC3.txt")
        mic4_txt = os.path.join(save_dir, "MIC4.txt")
        np.savetxt(mic1_txt, self.mic1_data)
        np.savetxt(mic2_txt, self.mic2_data)
        np.savetxt(mic3_txt, self.mic3_data)
        np.savetxt(mic4_txt, self.mic4_data)

        self.logger.info(f"采集已保存: {mic1_txt}")
        self.logger.info(f"采集已保存: {mic2_txt}")
        self.logger.info(f"采集已保存: {mic3_txt}")
        self.logger.info(f"采集已保存: {mic4_txt}")

        # 画最终 Pa 曲线（保持原信号）
        time_axis = np.linspace(0, duration, len(self.mic1_pa))
        self.update_plot(time_axis, self.mic1_pa, self.mic2_pa, self.mic3_pa, self.mic4_pa)

        self.logger.info("采集完成，已更新时域图")
        self.test_state.setText("测试完成")

    def _load_mic_binding_indices(self):
        # 默认顺序
        idx1, idx2, idx3, idx4 = 0, 1, 2, 3
        temporary_dev_db = [0.0, 0.0, 0.0, 0.0]
        try:
            path = utils.get_config_path("mic_calibration.json")
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            idx1 = int(cfg.get("In1", {}).get("binding_index", idx1))
            idx2 = int(cfg.get("In2", {}).get("binding_index", idx2))
            idx3 = int(cfg.get("In3", {}).get("binding_index", idx3))
            idx4 = int(cfg.get("In4", {}).get("binding_index", idx4))

            dev1 = float(cfg.get("In1", {}).get("deviation_value", 0))
            dev2 = float(cfg.get("In2", {}).get("deviation_value", 0))
            dev3 = float(cfg.get("In3", {}).get("deviation_value", 0))
            dev4 = float(cfg.get("In4", {}).get("deviation_value", 0))
            temporary_dev_db = [dev1, dev2, dev3, dev4]

        except Exception as e:
            self.logger.warning(f"读取麦克风绑定顺序失败：{e}")
            sign.error_message_signal.emit(f"读取麦克风绑定顺序失败：{e}", self)
        self.mic_binding = (idx1, idx2, idx3, idx4)
        self.mic_deviation_db = (
            temporary_dev_db[idx1], temporary_dev_db[idx2], temporary_dev_db[idx3], temporary_dev_db[idx4])


    def update_plot(self, time, mic1_pa, mic2_pa, mic3_pa, mic4_pa):
        self.curve1.setData(time, mic1_pa)
        self.curve2.setData(time, mic2_pa)
        self.curve4.setData(time, mic3_pa)
        self.curve5.setData(time, mic4_pa)

    def popup_pdf(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        pdf_path = os.path.join(base_dir, "resources", "file", "4MIC薄层材料测试系统V1.0操作使用手册.pdf")
        if os.path.exists(pdf_path):
            if sys.platform.startswith("win"):
                os.startfile(pdf_path)  # Windows
            else:
                subprocess.run(["open", pdf_path])  # macOS 用 open；Linux 可用 xdg-open
        else:
            print("❌ PDF 文件不存在！")

