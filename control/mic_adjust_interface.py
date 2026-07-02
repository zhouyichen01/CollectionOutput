import json
import os

import pyqtgraph
import numpy as np
import sounddevice as sd

from PyQt5.QtCore import QFile, Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QGraphicsScene, QGraphicsPixmapItem, QMessageBox, QVBoxLayout, QApplication
from PyQt5.uic import loadUi
from pyqtgraph import mkPen

from control.log_manager import LogManager
from control.utils import utils
from control.utils.audio_session_manager import AudioSessionManager
from control.utils.audio_thd_frequency_response_analysis import AudioThdFrequencyResponseAnalysis
from control.utils.streaming_audio_processor import DuplexStreamingPlayRec
from custom.customSignals import sign

class MicAdjustInterface(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        # ===== 不依赖 UI=====
        self.ui = None
        self.signal_info = None
        self.mic1_pa = None
        self.mic2_pa = None
        self.mic3_pa = None
        self.mic4_pa = None
        self.mic_binding = (0, 1, 2, 3)
        self.mic_deviation_db = (0, 0, 0, 0)
        # 实时显示用的滚动缓存（只保留最近 N 秒的数据，避免越画越卡）
        self.streaming_buffer = []
        # 保存“所有 chunk”（用于录完后拼成完整 recording 做后处理）
        self._stream_chunks = []
        # 当前这一轮流式录音的处理器（负责打开声卡流、把录音分块放进队列）
        self.stream_instance = None
        self.logger = LogManager.set_log_handler("麦克风校准")

        # ===== UI =====
        self.init_ui()

        # Qt 定时器：主线程每隔一段时间轮询一次队列，更新波形/判断是否录完（依赖 UI 已存在）
        self.stream_timer = QTimer(self)
        self.stream_timer.timeout.connect(self._handle_queue_and_update_ui)
        self.init_fun()

        # ===== UI 数据回填（依赖控件已存在）=====
        self.init_voltage_value()

    def init_ui(self):
        ui_file = QFile(":ui/mic_adjust.ui")
        if not ui_file.exists():
            self.logger.error("未找到资源文件 mic_adjust.ui")
            raise FileNotFoundError("未找到资源文件 mic_adjust.ui")
        ui_file.open(QFile.ReadOnly)
        self.ui = loadUi(ui_file, self)
        ui_file.close()
        self.setWindowTitle("麦克风校准")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint| Qt.WindowMaximizeButtonHint)
        self.init_images()
        self.init_view()
        # 调整界面大小
        utils.resize_by_ui_with_screen(self)
        self.logger.info("打开麦克风校准界面")

    def init_fun(self):
        self.start_adjust_button.clicked.connect(self.start_adjust)
        # 连接失去焦点事件
        self.target_voltage_value.focusOutEvent = self.focusOutEvent  # 将自定义的事件绑定到控件上

        sign.play_adjust_audio_sign.connect(self.play_adjust_audio,Qt.AutoConnection)
        sign.error_message_signal.connect(utils.show_error_message)
        sign.update_plot_sign.connect(self.update_plot)

    def init_voltage_value(self):
        ok, config = utils.get_config_content("output_signal_setting.json")
        if not ok:
            self.logger.error("读取配置失败: output_signal_setting.json")
            QMessageBox.warning(self, "错误", "读取配置失败：output_signal_setting.json")
            return
        mic_adj_v = config.get("mic_adjust_voltage", None)
        self.target_voltage_value.setText(str(mic_adj_v if mic_adj_v is not None else "0.01"))

    def focusOutEvent(self, event):
        """
        当控件失去焦点时触发，进行电压值的校验和保存操作。
        """
        self.validate_and_save_voltage()  # 触发校验和保存操作

        # 调用父类的 focusOutEvent（如果需要其他默认行为）
        super().focusOutEvent(event)

    def validate_and_save_voltage(self):
        text = self.target_voltage_value.text().strip()

        try:
            value = float(text)
            if value < 0:
                raise ValueError("电压必须大于 0")

            ok, config = utils.get_config_content("output_signal_setting.json")
            if ok:
                config["mic_adjust_voltage"] = value
                if utils.write_config_content("output_signal_setting.json", config):
                    self.logger.info(f"保存 mic_adjust_voltage = {value}")
                else:
                    QMessageBox.warning(self, "保存失败", "配置文件保存失败，请重试！")
            else:
                QMessageBox.warning(self, "读取失败", "配置文件读取失败，请检查文件是否存在！")

        except Exception as e:
            # 回退到上次保存的合法值
            QMessageBox.warning(self, "输入错误", f"请输入正确的有效数字: {e}")
            ok, cfg = utils.get_config_content("output_signal_setting.json")
            if ok:
                last_value = cfg.get("mic_adjust_voltage", 0.01)  # 默认值为 0.01
                self.target_voltage_value.setText(str(last_value))
            else:
                self.target_voltage_value.setText("0.01")

    def init_images(self):
        scene = QGraphicsScene()
        pixmap = QPixmap(":/images/4mic同步校准_画板.png")
        scaled_pixmap = pixmap.scaled(400, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap_item = QGraphicsPixmapItem(scaled_pixmap)
        scene.addItem(pixmap_item)
        self.graphicsView.setScene(scene)

        scene_2 = QGraphicsScene()
        pixmap_2 = QPixmap(":/images/4mic薄层_画板.png")
        scaled_pixmap_2 = pixmap_2.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap_item_2 = QGraphicsPixmapItem(scaled_pixmap_2)
        scene_2.addItem(pixmap_item_2)
        self.graphicsView_2.setScene(scene_2)

    def init_view(self):
        pyqtgraph.setConfigOptions(antialias=True)
        # Mic1 - Time
        self.plot1 = pyqtgraph.PlotWidget()
        layout1 = QVBoxLayout()
        layout1.setContentsMargins(0, 0, 0, 0)
        layout1.addWidget(self.plot1)
        self.ui.frame_plot1.setLayout(layout1)
        self.plot1.setBackground('white')
        self.plot1.setLabel('bottom', 'Time', units='s')
        self.plot1.setLabel('left', 'Amplitude', units='Pa')
        self.plot1.getAxis('bottom').setTextPen("black")
        self.plot1.getAxis('left').setTextPen("black")
        self.plot1.showGrid(x=True, y=True, alpha=0.25)
        self.curve1 = self.plot1.plot([], [], pen=mkPen(color=(76, 120, 168)))

        # Mic1 - Freq
        self.plot1_freq = pyqtgraph.PlotWidget()
        lay1f = QVBoxLayout()
        lay1f.setContentsMargins(0, 0, 0, 0)
        lay1f.addWidget(self.plot1_freq)
        self.ui.frame_plot1_2.setLayout(lay1f)
        self.plot1_freq.setBackground('white')
        self.plot1_freq.setLabel('bottom', 'Frequency(Hz)')
        self.plot1_freq.setLabel('left', 'Magnitude')
        self.plot1_freq.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot1_freq.getAxis('left').enableAutoSIPrefix(False)  # 禁用自动转换单位
        self.plot1_freq.getAxis('bottom').setTextPen("black")
        self.plot1_freq.getAxis('left').setTextPen("black")
        self.plot1_freq.showGrid(x=True, y=True, alpha=0.25)
        # 调整刻度字体大小
        font = pyqtgraph.QtGui.QFont()
        font.setPointSize(11)
        self.plot1_freq.getAxis('bottom').setTickFont(font)
        # 使用自定义的对数坐标轴刻度标签格式
        self.plot1_freq.setLogMode(x=True, y=False)
        self.plot1_freq.getAxis('bottom').logTickStrings = utils.custom_log_tick_strings

        # Mic2 - Time
        self.plot2 = pyqtgraph.PlotWidget()
        layout2 = QVBoxLayout()
        layout2.setContentsMargins(0, 0, 0, 0)
        layout2.addWidget(self.plot2)
        self.ui.frame_plot2.setLayout(layout2)
        self.plot2.setBackground('white')
        self.plot2.setLabel('bottom', 'Time', units='s')
        self.plot2.setLabel('left', 'Amplitude', units='Pa')
        self.plot2.getAxis('bottom').setTextPen("black")
        self.plot2.getAxis('left').setTextPen("black")
        self.plot2.showGrid(x=True, y=True, alpha=0.25)
        self.curve2 = self.plot2.plot([], [], pen=mkPen(color=(84, 162, 75)))

        # Mic2 - Freq
        self.plot2_freq = pyqtgraph.PlotWidget()
        lay2f = QVBoxLayout()
        lay2f.setContentsMargins(0, 0, 0, 0)
        lay2f.addWidget(self.plot2_freq)
        # 这里假设你的 UI 中有 frame_plot2_2
        self.ui.frame_plot2_2.setLayout(lay2f)
        self.plot2_freq.setBackground('white')
        self.plot2_freq.setLabel('bottom', 'Frequency(Hz)')
        self.plot2_freq.setLabel('left', 'Magnitude')
        self.plot2_freq.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot2_freq.getAxis('left').enableAutoSIPrefix(False)
        self.plot2_freq.getAxis('bottom').setTextPen("black")
        self.plot2_freq.getAxis('left').setTextPen("black")
        self.plot2_freq.showGrid(x=True, y=True, alpha=0.25)
        self.plot2_freq.getAxis('bottom').setTickFont(font)
        self.plot2_freq.setLogMode(x=True, y=False)
        self.plot2_freq.getAxis('bottom').logTickStrings = utils.custom_log_tick_strings

        # Mic3 - Time
        self.plot3 = pyqtgraph.PlotWidget()
        layout3 = QVBoxLayout()
        layout3.setContentsMargins(0, 0, 0, 0)
        layout3.addWidget(self.plot3)
        self.ui.frame_plot3.setLayout(layout3)
        self.plot3.setBackground('white')
        self.plot3.setLabel('bottom', 'Time', units='s')
        self.plot3.setLabel('left', 'Amplitude', units='Pa')
        self.plot3.getAxis('bottom').setTextPen("black")
        self.plot3.getAxis('left').setTextPen("black")
        self.plot3.showGrid(x=True, y=True, alpha=0.25)
        self.curve3 = self.plot3.plot([], [], pen=mkPen(color=(245, 133, 24)))

        # Mic3 - Freq
        self.plot3_freq = pyqtgraph.PlotWidget()
        lay3f = QVBoxLayout()
        lay3f.setContentsMargins(0, 0, 0, 0)
        lay3f.addWidget(self.plot3_freq)
        self.ui.frame_plot3_2.setLayout(lay3f)
        self.plot3_freq.setBackground('white')
        self.plot3_freq.setLabel('bottom', 'Frequency(Hz)')
        self.plot3_freq.setLabel('left', 'Magnitude')
        self.plot3_freq.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot3_freq.getAxis('left').enableAutoSIPrefix(False)  # 禁用自动转换单位
        self.plot3_freq.getAxis('bottom').setTextPen("black")
        self.plot3_freq.getAxis('left').setTextPen("black")
        self.plot3_freq.showGrid(x=True, y=True, alpha=0.25)
        # 调整刻度字体大小
        self.plot3_freq.getAxis('bottom').setTickFont(font)
        # 使用自定义的对数坐标轴刻度标签格式
        self.plot3_freq.setLogMode(x=True, y=False)
        self.plot3_freq.getAxis('bottom').logTickStrings = utils.custom_log_tick_strings

        # Mic4 - Time
        self.plot4 = pyqtgraph.PlotWidget()
        layout4 = QVBoxLayout()
        layout4.setContentsMargins(0, 0, 0, 0)
        layout4.addWidget(self.plot4)
        self.ui.frame_plot4.setLayout(layout4)
        self.plot4.setBackground('white')
        self.plot4.setLabel('bottom', 'Time', units='s')
        self.plot4.setLabel('left', 'Amplitude', units='Pa')
        self.plot4.getAxis('bottom').setTextPen("black")
        self.plot4.getAxis('left').setTextPen("black")
        self.plot4.showGrid(x=True, y=True, alpha=0.25)
        self.curve4 = self.plot4.plot([], [], pen=mkPen(color=(178, 121, 162)))

        # Mic4 - Freq
        self.plot4_freq = pyqtgraph.PlotWidget()
        lay4f = QVBoxLayout()
        lay4f.setContentsMargins(0, 0, 0, 0)
        lay4f.addWidget(self.plot4_freq)
        # 这里同样假设 UI 中有 frame_plot4_2
        self.ui.frame_plot4_2.setLayout(lay4f)
        self.plot4_freq.setBackground('white')
        self.plot4_freq.setLabel('bottom', 'Frequency(Hz)')
        self.plot4_freq.setLabel('left', 'Magnitude')
        self.plot4_freq.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot4_freq.getAxis('left').enableAutoSIPrefix(False)
        self.plot4_freq.getAxis('bottom').setTextPen("black")
        self.plot4_freq.getAxis('left').setTextPen("black")
        self.plot4_freq.showGrid(x=True, y=True, alpha=0.25)
        self.plot4_freq.getAxis('bottom').setTickFont(font)
        self.plot4_freq.setLogMode(x=True, y=False)
        self.plot4_freq.getAxis('bottom').logTickStrings = utils.custom_log_tick_strings

    def init_config(self):
        config_path = utils.get_config_path("output_signal_setting.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.signal_info = config.get("signal_info", {})
        except Exception as e:
            self.logger.error(f"读取配置失败: {e}")
            QMessageBox.warning(self, "错误", f"读取配置失败：{e}")

    def record_and_plot(self):
        if not AudioSessionManager.acquire(self):
            QMessageBox.warning(self, "提示", "音频设备正在被其它界面占用，请先停止/关闭其它录音功能。")
            utils.set_adjust_button_enabled(self.start_adjust_button, True)
            return
        self._load_mic_binding_indices()
        try:
            # 清空时域曲线数据（不要 clear plot）
            self.curve1.setData([], [])
            self.curve2.setData([], [])
            self.curve3.setData([], [])
            self.curve4.setData([], [])

            self.plot1_freq.clear()
            self.plot2_freq.clear()
            self.plot3_freq.clear()
            self.plot4_freq.clear()
            self.streaming_buffer = []
            QApplication.processEvents()
            # 获取设备采样率
            samplerate = utils.get_device_info()
            duration = self.signal_info['signal_time']

            # 根据目标电压，校准并生成激励信号
            target_voltage = float(self.target_voltage_value.text())
            self.signal_info['signal_amplitude'] = target_voltage
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

            self.logger.info("开始播放并录音...")
            # 2) 读设备（你已经保存到 basic_params.json）
            ok, config = utils.get_config_content("basic_params.json")
            input_device = config["basic_params"]["input_selected_device_id"]
            output_device = config["basic_params"]["output_selected_device_id"]


            # 3) 启动流式（非阻塞）
            self._stream_chunks = []
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
            self.stream_timer.start(50)
            return
        except Exception as e:
            self.logger.error(f"录音或保存失败: {e}")
            sign.error_message_signal.emit(f"录音或保存失败：{e}", self)
            utils.set_adjust_button_enabled(self.start_adjust_button, True)
            AudioSessionManager.release(self)

    def _handle_queue_and_update_ui(self):
        """
        仿 SpeakerAnomalyDetection 的写法：
        - 定时器里只做三件事：处理队列、实时更新显示、判断结束并触发收尾
        """
        if self.stream_instance is None:
            return

        # 1) 处理队列：把回调线程塞进来的 chunk 取出来
        chunks = self.stream_instance.process_queue()
        if chunks:
            # 2) 实时显示：只画最近 N 秒（避免越画越卡）
            sr = self.stream_instance.sample_rate
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

            self.update_time_plot(time_axis, pa1, pa2, pa3, pa4)

        # 3) 录音结束：录音停止-> stream停timer-> 收集结果(recording/err)-> stop/释放stream-> (FFT/保存/画图)-> 恢复按钮&释放占用锁
        if not self.stream_instance.is_recording:

            self.stream_timer.stop()

            err = getattr(self.stream_instance, "error", None)
            recording = self.stream_instance.get_recorded_data()  # (N,4)

            self.stream_instance.stop()
            self.stream_instance = None

            try:
                if err:
                    raise RuntimeError(f"流式录音出错：{err}")

                self._handle_recording_fft(recording, sr)

            except Exception as e:
                self.logger.exception("录音后处理失败")
                sign.error_message_signal.emit(f"录音失败：{e}", self)

            finally:
                utils.set_adjust_button_enabled(self.start_adjust_button, True)
                AudioSessionManager.release(self)

    def _handle_recording_fft(self, recording, samplerate):
        """
        流式录音结束后的收尾：
        1) 从多通道 recording 中按 binding_index 拆出 4 路麦克
        2) 计算 SPL/scale，得到 Pa 数据
        3) 饱和提示
        4) 保存 MIC1~MIC4 原始数据到 txt
        5) 最终画时域 + FFT
        6) 恢复按钮
        """
        self.logger.info("录音完成(流式),开始处理音频数据")
        self.logger.info(f"recording shape: {getattr(recording, 'shape', None)}")

        # 1) 处理录音数据（拆通道 + 计算 real_spl/scale）
        (mic1_data, mic2_data, mic3_data, mic4_data,
         real_spl1, real_spl2, real_spl3, real_spl4,
         scale1, scale2, scale3, scale4) = MicAdjustInterface.process_mic_channels_data(recording, self.mic_binding,
                                                                                           self.mic_deviation_db)

        # 2) 转成 Pa
        self.mic1_pa = mic1_data * scale1
        self.mic2_pa = mic2_data * scale2
        self.mic3_pa = mic3_data * scale3
        self.mic4_pa = mic4_data * scale4

        # 3) 饱和提示
        if real_spl1 > 130:
            self.logger.error(f"麦克风1实际声压级 {real_spl1:.2f} dB, 超过阈值 130 dB，已饱和")
        if real_spl2 > 130:
            self.logger.error(f"麦克风2实际声压级 {real_spl2:.2f} dB, 超过阈值 130 dB，已饱和")
        if real_spl3 > 130:
            self.logger.error(f"麦克风3实际声压级 {real_spl3:.2f} dB, 超过阈值 130 dB，已饱和")
        if real_spl4 > 130:
            self.logger.error(f"麦克风4实际声压级 {real_spl4:.2f} dB, 超过阈值 130 dB，已饱和")
        utils.spl_warning(self, [real_spl1, real_spl2, real_spl3, real_spl4], 130)

        # 4) 保存 txt（保存的是 mic*_data 原始通道数据）
        cal_dir = os.path.join(os.getcwd(), "！隔声校准")
        os.makedirs(cal_dir, exist_ok=True)

        mic1_txt = os.path.join(cal_dir, "MIC1.txt")
        mic2_txt = os.path.join(cal_dir, "MIC2.txt")
        mic3_txt = os.path.join(cal_dir, "MIC3.txt")
        mic4_txt = os.path.join(cal_dir, "MIC4.txt")

        np.savetxt(mic1_txt, mic1_data)
        np.savetxt(mic2_txt, mic2_data)
        np.savetxt(mic3_txt, mic3_data)
        np.savetxt(mic4_txt, mic4_data)

        self.logger.info(f"MIC1 校准已保存: {mic1_txt}")
        self.logger.info(f"MIC2 校准已保存: {mic2_txt}")
        self.logger.info(f"MIC3 校准已保存: {mic3_txt}")
        self.logger.info(f"MIC4 校准已保存: {mic4_txt}")

        # 5) 最终画图（时域（pa）+FFT（原始数据））
        duration = float(self.signal_info.get("signal_time", 0))
        if duration <= 0:
            # 如果没有 signal_time，就用数据长度反推
            duration = len(self.mic1_pa) / float(samplerate)

        time_axis = np.linspace(0, duration, len(self.mic1_pa))
        self.update_plot_and_fft(time_axis, mic1_data, mic2_data, mic3_data, mic4_data, samplerate)
        self.logger.info("画图完成")

    @staticmethod
    def process_chunks(buf, mic_binding, mic_deviation_db):
        """
        处理chunks一段数据
        """
        mic1_data = buf[:, mic_binding[0]]
        mic2_data = buf[:, mic_binding[1]]
        mic3_data = buf[:, mic_binding[2]]
        mic4_data = buf[:, mic_binding[3]]
        spl_smooth1 = AudioThdFrequencyResponseAnalysis.spl_calculation(buf[:, mic_binding[0]])
        real_1 = np.max(spl_smooth1)
        spl_smooth2 = AudioThdFrequencyResponseAnalysis.spl_calculation(buf[:, mic_binding[1]])
        real_2 = np.max(spl_smooth2)
        spl_smooth3 = AudioThdFrequencyResponseAnalysis.spl_calculation(buf[:, mic_binding[2]])
        real_3 = np.max(spl_smooth3)
        spl_smooth4 = AudioThdFrequencyResponseAnalysis.spl_calculation(buf[:, mic_binding[3]])
        real_4 = np.max(spl_smooth4)

        real_spl1 = real_1 + mic_deviation_db[0]
        real_spl2 = real_2 + mic_deviation_db[1]
        real_spl3 = real_3 + mic_deviation_db[2]
        real_spl4 = real_4 + mic_deviation_db[3]
        rms1 = utils.calculate_rms(buf[:, mic_binding[0]])
        rms2 = utils.calculate_rms(buf[:, mic_binding[1]])
        rms3 = utils.calculate_rms(buf[:, mic_binding[2]])
        rms4 = utils.calculate_rms(buf[:, mic_binding[3]])
        scale1 = utils.calculate_scale(real_spl1, rms1)
        scale2 = utils.calculate_scale(real_spl2, rms2)
        scale3 = utils.calculate_scale(real_spl3, rms3)
        scale4 = utils.calculate_scale(real_spl4, rms4)
        pa1 = mic1_data * scale1
        pa2 = mic2_data * scale2
        pa3 = mic3_data * scale3
        pa4 = mic4_data * scale4
        return pa1, pa2, pa3, pa4

    @staticmethod
    def process_mic_channels_data(recording, mic_binding, mic_deviation_db):
        """
        处理麦克风通道数据
        """
        mic1_data = recording[:, mic_binding[0]]
        mic2_data = recording[:, mic_binding[1]]
        mic3_data = recording[:, mic_binding[2]]
        mic4_data = recording[:, mic_binding[3]]
        spl_smooth1 = AudioThdFrequencyResponseAnalysis.spl_calculation(recording[:, mic_binding[0]])
        real_1 = np.max(spl_smooth1)
        spl_smooth2 = AudioThdFrequencyResponseAnalysis.spl_calculation(recording[:, mic_binding[1]])
        real_2 = np.max(spl_smooth2)
        spl_smooth3 = AudioThdFrequencyResponseAnalysis.spl_calculation(recording[:, mic_binding[2]])
        real_3 = np.max(spl_smooth3)
        spl_smooth4 = AudioThdFrequencyResponseAnalysis.spl_calculation(recording[:, mic_binding[3]])
        real_4 = np.max(spl_smooth4)

        real_spl1 = real_1 + mic_deviation_db[0]
        real_spl2 = real_2 + mic_deviation_db[1]
        real_spl3 = real_3 + mic_deviation_db[2]
        real_spl4 = real_4 + mic_deviation_db[3]
        print(f"real_1实测: {real_1}, +偏差值后: {real_spl1}")
        print(f"real_2实测: {real_2}, +偏差值后: {real_spl2}")
        print(f"real_3实测: {real_3}, +偏差值后: {real_spl3}")
        print(f"real_4实测: {real_4}, +偏差值后: {real_spl4}")
        rms1 = utils.calculate_rms(recording[:, mic_binding[0]])
        rms2 = utils.calculate_rms(recording[:, mic_binding[1]])
        rms3 = utils.calculate_rms(recording[:, mic_binding[2]])
        rms4 = utils.calculate_rms(recording[:, mic_binding[3]])
        scale1 = utils.calculate_scale(real_spl1, rms1)
        scale2 = utils.calculate_scale(real_spl2, rms2)
        scale3 = utils.calculate_scale(real_spl3, rms3)
        scale4 = utils.calculate_scale(real_spl4, rms4)
        print(f"RMS: {rms1:.8f}, {rms2:.8f}, {rms3:.8f}, {rms4:.8f}")
        print(f"Scale: {scale1:.2f}, {scale2:.2f}, {scale3:.2f}, {scale4:.2f}")
        return (mic1_data, mic2_data, mic3_data, mic4_data, real_spl1, real_spl2, real_spl3,
                real_spl4, scale1, scale2, scale3, scale4)

    def start_adjust(self):
        self.init_config()
        utils.set_adjust_button_enabled(self.start_adjust_button, False)
        sign.play_adjust_audio_sign.emit()

    def play_adjust_audio(self):
        self.record_and_plot()

    def update_plot_and_fft(self, time, mic1_data, mic2_data, mic3_data, mic4_data, samplerate):
        # 时域图
        self.update_time_plot(time, self.mic1_pa, self.mic2_pa, self.mic3_pa, self.mic4_pa)

        # fft
        f1, m1 = utils.compute_fft(mic1_data, samplerate)
        f2, m2 = utils.compute_fft(mic2_data, samplerate)
        f3, m3 = utils.compute_fft(mic3_data, samplerate)
        f4, m4 = utils.compute_fft(mic4_data, samplerate)
        # 只显示到 Nyquist（rfft 本身就是正频段）
        # 且限制频率范围为 20–20000 Hz
        f1_range = (f1 >= 20) & (f1 <= 20000)
        f2_range = (f2 >= 20) & (f2 <= 20000)
        f3_range = (f3 >= 20) & (f3 <= 20000)
        f4_range = (f4 >= 20) & (f4 <= 20000)
        self.plot1_freq.plot(f1[f1_range], m1[f1_range], pen=mkPen(color=(76, 120, 168)))
        self.plot2_freq.plot(f2[f2_range], m2[f2_range], pen=mkPen(color=(84, 162, 75)))
        self.plot3_freq.plot(f3[f3_range], m3[f3_range], pen=mkPen(color=(245, 133, 24)))
        self.plot4_freq.plot(f4[f4_range], m4[f4_range], pen=mkPen(color=(178, 121, 162)))

        self.plot1.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
        self.plot2.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
        self.plot3.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
        self.plot4.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整

        self.plot1_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
        self.plot2_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
        self.plot3_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
        self.plot4_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整

    def update_plot(self, time, mic1_data, mic2_data, mic3_data, mic4_data, samplerate):
        self.plot1.plot(time, mic1_data, pen=mkPen(color=(222, 222, 222)))
        self.plot2.plot(time, mic2_data, pen=mkPen(color=(190, 190, 190)))
        self.plot3.plot(time, mic3_data, pen='gray')
        self.plot4.plot(time, mic4_data, pen='k')
        if samplerate is not None:
            f1, m1 = utils.compute_fft(mic1_data, samplerate)
            f2, m2 = utils.compute_fft(mic2_data, samplerate)
            f3, m3 = utils.compute_fft(mic3_data, samplerate)
            f4, m4 = utils.compute_fft(mic4_data, samplerate)

            # 只显示到 Nyquist（rfft 本身就是正频段）
            self.plot1_freq.plot(f1, m1, pen=mkPen(color=(222, 222, 222)))
            self.plot2_freq.plot(f2, m2, pen=mkPen(color=(190, 190, 190)))
            self.plot3_freq.plot(f3, m3, pen='gray')
            self.plot4_freq.plot(f4, m4, pen='k')

            self.plot1.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
            self.plot2.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
            self.plot3.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
            self.plot4.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
            self.plot1_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
            self.plot2_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
            self.plot3_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
            self.plot4_freq.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整

    def update_time_plot(self, time, mic1_pa, mic2_pa, mic3_pa, mic4_pa):
        self.curve1.setData(time, mic1_pa)
        self.curve2.setData(time, mic2_pa)
        self.curve3.setData(time, mic3_pa)
        self.curve4.setData(time, mic4_pa)

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
        print(f"mic_binding:{self.mic_binding}")

    def closeEvent(self, event):
        if self.parent:
            self.parent.mic_window = None
        sign.update_plot_sign.disconnect(self.update_plot)
        sign.error_message_signal.disconnect(utils.show_error_message)
        sign.play_adjust_audio_sign.disconnect(self.play_adjust_audio)
        self.logger.info("关闭麦克风校准界面")
        event.accept()