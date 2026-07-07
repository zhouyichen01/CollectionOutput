import csv
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

import numpy as np
import sounddevice as sd
import pyqtgraph
from PyQt5.QtCore import QFile, Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QGraphicsScene, QGraphicsPixmapItem,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout
)
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
        self.last_output_data = None

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
        self.action_3.triggered.disconnect()
        self.action_3.triggered.connect(self.open_output_signal_setting_interface)
        self.action_9.triggered.disconnect()
        self.action_9.triggered.connect(self.open_mic_adjust_interface)
        self.action_4.triggered.disconnect()
        self.action_4.triggered.connect(self.open_output_voltage_interface)
        self.contact_us_action.triggered.connect(self.show_contact_us)
        self.save_output_action.triggered.connect(self.save_output)
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

    def show_contact_us(self):
        dialog = QDialog(self)
        dialog.setObjectName("contactDialog")
        dialog.setWindowTitle("联系我们")
        dialog.setModal(True)
        dialog.setMinimumWidth(460)
        dialog.setStyleSheet("""
            QDialog#contactDialog {
                background-color: rgb(240, 240, 240);
            }
            QLabel#contactTitle {
                color: #1f2937;
                font: bold 18pt "Microsoft YaHei";
            }
            QFrame#contactCard {
                background-color: #ffffff;
                border: 1px solid #d8e0ea;
                border-radius: 8px;
            }
            QLabel#contactLabel {
                color: #64748b;
                font: bold 10pt "Microsoft YaHei";
            }
            QLabel#contactValue {
                color: #111827;
                font: 11pt "Microsoft YaHei";
            }
            QPushButton#contactCloseButton {
                background-color: #0f6db6;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 24px;
                font: bold 10pt "Microsoft YaHei";
            }
            QPushButton#contactCloseButton:hover {
                background-color: #0b5f9f;
            }
        """)

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(16)

        title = QLabel("苏州东原电子", dialog)
        title.setObjectName("contactTitle")
        main_layout.addWidget(title)

        card = QFrame(dialog)
        card.setObjectName("contactCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(22, 18, 22, 18)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)

        contact_items = [
            ("联系人", "王庆"),
            ("联系电话", "18362654625"),
            ("联系地址", "江苏省苏州市相城区荣泰街活力大厦D座1407-1408室"),
        ]
        for row, (label_text, value_text) in enumerate(contact_items):
            label = QLabel(label_text, card)
            label.setObjectName("contactLabel")
            value = QLabel(value_text, card)
            value.setObjectName("contactValue")
            value.setWordWrap(True)
            grid.addWidget(label, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        main_layout.addWidget(card)

        close_button = QPushButton("关闭", dialog)
        close_button.setObjectName("contactCloseButton")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(dialog.accept)
        main_layout.addWidget(close_button, 0, Qt.AlignRight)

        dialog.exec_()

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
        self.last_output_data = None
        utils.set_run_button_enabled(self.run_test_button, False)
        self.test_state.setText("测试中...")
        QApplication.processEvents()
        self.record_and_plot()

    def record_and_plot(self):
        # 防止多个界面同时占用声卡
        if not AudioSessionManager.acquire(self):
            QMessageBox.warning(self, "提示", "音频设备正在被其它界面占用，请先停止/关闭其它录音功能。")
            self.test_state.setText("音频被占用")
            utils.set_run_button_enabled(self.run_test_button, True)
            return

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
            finally:
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
        self.last_output_data = {
            "time": time_axis,
            "mic1_pa": self.mic1_pa,
            "mic2_pa": self.mic2_pa,
            "mic3_pa": self.mic3_pa,
            "mic4_pa": self.mic4_pa,
        }
        self.update_plot(time_axis, self.mic1_pa, self.mic2_pa, self.mic3_pa, self.mic4_pa)

        self.logger.info("采集完成，已更新时域图")
        self.test_state.setText("测试完成")

    def save_output(self):
        if not self.last_output_data:
            QMessageBox.warning(self, "提示", "未进行测试")
            return

        output_format = self._show_save_output_dialog()
        if not output_format:
            return

        save_base_path = self._get_output_save_path(output_format)
        if not save_base_path:
            return

        save_paths = self._build_channel_save_paths(save_base_path, output_format)
        if not self._confirm_output_save(save_paths, output_format):
            return

        try:
            self._save_output_to_files(save_paths, output_format)
        except Exception as e:
            self.logger.exception("保存输出失败")
            QMessageBox.critical(self, "保存失败", f"保存输出失败：{e}")
            return

        saved_files_text = "\n".join(save_paths)
        self.logger.info(f"输出已保存: {saved_files_text}")
        QMessageBox.information(self, "保存成功", f"输出已保存：\n{saved_files_text}")

    def _show_save_output_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("保存输出")
        dialog.setModal(True)
        dialog.setMinimumWidth(320)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        label = QLabel("请选择保存类型：", dialog)
        combo = QComboBox(dialog)
        combo.addItem("TXT 文本 (*.txt)", "txt")
        combo.addItem("CSV 表格 (*.csv)", "csv")
        combo.addItem("Excel 工作簿 (*.xlsx)", "xlsx")
        combo.setMinimumHeight(32)

        button_layout = QHBoxLayout()
        cancel_button = QPushButton("取消", dialog)
        save_button = QPushButton("下一步", dialog)
        cancel_button.clicked.connect(dialog.reject)
        save_button.clicked.connect(dialog.accept)
        button_layout.addStretch(1)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)

        layout.addWidget(label)
        layout.addWidget(combo)
        layout.addLayout(button_layout)

        if dialog.exec_() != QDialog.Accepted:
            return None
        return combo.currentData()

    def _get_output_save_path(self, output_format):
        extensions = {
            "txt": ".txt",
            "csv": ".csv",
            "xlsx": ".xlsx",
        }
        filters = {
            "txt": "TXT 文本 (*.txt)",
            "csv": "CSV 表格 (*.csv)",
            "xlsx": "Excel 工作簿 (*.xlsx)",
        }

        extension = extensions[output_format]
        base_name = datetime.now().strftime("采集输出_%Y%m%d_%H%M%S")
        default_path = os.path.join(os.getcwd(), f"{base_name}{extension}")
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择保存位置和文件名前缀",
            default_path,
            filters[output_format],
        )
        if not save_path:
            return None

        current_extension = os.path.splitext(save_path)[1].lower()
        if current_extension != extension:
            if current_extension:
                save_path = os.path.splitext(save_path)[0] + extension
            else:
                save_path = save_path + extension
        return save_path

    def _build_channel_save_paths(self, save_base_path, output_format):
        extension = self._output_extension(output_format)
        base_path, current_extension = os.path.splitext(save_base_path)
        if current_extension.lower() != extension:
            base_path = save_base_path
        return [
            f"{base_path}_{channel_name}{extension}"
            for channel_name, _ in self._output_channels()
        ]

    def _confirm_output_save(self, save_paths, output_format):
        format_names = {
            "txt": "TXT 文本",
            "csv": "CSV 表格",
            "xlsx": "Excel 工作簿",
        }
        files_text = "\n".join(save_paths)
        reply = QMessageBox.question(
            self,
            "确认保存",
            f"保存类型：{format_names.get(output_format, output_format)}\n"
            f"将生成 {len(save_paths)} 个文件：\n{files_text}\n\n确认保存吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return reply == QMessageBox.Yes

    def _save_output_to_files(self, save_paths, output_format):
        for save_path, (channel_name, channel_data) in zip(save_paths, self._output_channels()):
            if output_format == "txt":
                self._write_delimited_output(save_path, "\t", channel_name, channel_data)
            elif output_format == "csv":
                self._write_delimited_output(save_path, ",", channel_name, channel_data)
            elif output_format == "xlsx":
                self._write_xlsx_output(save_path, channel_name, channel_data)
            else:
                raise ValueError(f"不支持的保存格式：{output_format}")

    @staticmethod
    def _output_extension(output_format):
        extensions = {
            "txt": ".txt",
            "csv": ".csv",
            "xlsx": ".xlsx",
        }
        return extensions[output_format]

    def _output_channels(self):
        return [
            ("MIC1", self.last_output_data["mic1_pa"]),
            ("MIC2", self.last_output_data["mic2_pa"]),
            ("MIC3", self.last_output_data["mic3_pa"]),
            ("MIC4", self.last_output_data["mic4_pa"]),
        ]

    def _output_headers(self, channel_name):
        return ["Time(s)", f"{channel_name}(Pa)"]

    def _output_matrix(self, channel_data):
        return np.column_stack([
            self.last_output_data["time"],
            channel_data,
        ])

    def _write_delimited_output(self, save_path, delimiter, channel_name, channel_data):
        with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(self._output_headers(channel_name))
            for row in self._output_matrix(channel_data):
                writer.writerow([self._format_float(value) for value in row])

    def _write_xlsx_output(self, save_path, channel_name, channel_data):
        matrix = self._output_matrix(channel_data)
        if matrix.shape[0] + 1 > 1048576:
            raise ValueError("Excel 单个工作表最多支持 1048576 行，请改用 TXT 或 CSV 保存。")

        with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as workbook:
            workbook.writestr("[Content_Types].xml", self._xlsx_content_types())
            workbook.writestr("_rels/.rels", self._xlsx_root_relationships())
            workbook.writestr("xl/workbook.xml", self._xlsx_workbook(channel_name))
            workbook.writestr("xl/_rels/workbook.xml.rels", self._xlsx_workbook_relationships())

            with workbook.open("xl/worksheets/sheet1.xml", "w") as sheet:
                sheet.write(
                    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    b'<sheetData>'
                )
                sheet.write(self._xlsx_row_xml(1, self._output_headers(channel_name)).encode("utf-8"))
                for row_index, row in enumerate(matrix, start=2):
                    sheet.write(self._xlsx_row_xml(row_index, row).encode("utf-8"))
                sheet.write(b"</sheetData></worksheet>")

    @staticmethod
    def _format_float(value):
        value = float(value)
        if not np.isfinite(value):
            return ""
        return f"{value:.12g}"

    @staticmethod
    def _xlsx_content_types():
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        )

    @staticmethod
    def _xlsx_root_relationships():
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '</Relationships>'
        )

    @staticmethod
    def _xlsx_workbook(sheet_name):
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>'
        )

    @staticmethod
    def _xlsx_workbook_relationships():
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        )

    def _xlsx_row_xml(self, row_index, values):
        cells = []
        for column_index, value in enumerate(values, start=1):
            cells.append(self._xlsx_cell_xml(row_index, column_index, value))
        return f'<row r="{row_index}">{"".join(cells)}</row>'

    def _xlsx_cell_xml(self, row_index, column_index, value):
        cell_ref = f"{self._xlsx_column_name(column_index)}{row_index}"
        if isinstance(value, str):
            return f'<c r="{cell_ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'

        formatted_value = self._format_float(value)
        if formatted_value == "":
            return f'<c r="{cell_ref}"/>'
        return f'<c r="{cell_ref}"><v>{formatted_value}</v></c>'

    @staticmethod
    def _xlsx_column_name(column_index):
        name = ""
        while column_index:
            column_index, remainder = divmod(column_index - 1, 26)
            name = chr(65 + remainder) + name
        return name

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

