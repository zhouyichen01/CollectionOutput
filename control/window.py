import csv
import json
import os
import subprocess
import sys

import numpy as np
import sounddevice as sd
import pyqtgraph
from PyQt5 import QtWidgets
from PyQt5.QtCore import QFile, Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QMainWindow, QGraphicsScene, QGraphicsPixmapItem, QLabel, QMessageBox, \
    QVBoxLayout, QMenu, QAction, QFileDialog
from PyQt5.uic import loadUi
from pyqtgraph import mkPen
from scipy.signal import savgol_filter

from control.imp_tube_params_setting_interface import ImptubeParamsSetInterface
from control.log_manager import LogManager
from control.mic_adjust_interface import MicAdjustInterface
from control.output_signal_setting_interface import OutputSignalSetInterface
from control.output_voltage_interface import MicoutputVoltageInterface

from control.select_deivce_interface import SelectDeviceInterface
from control.utils import utils
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
        self.test_result = None
        self.soft_value = None
        self.plot_state = False
        self.is_testing = False

        self.logger = LogManager.set_log_handler("主窗口")
        self.init_ui()
        self.init_fun()
        self.init_image()
        self.init_view()
        self.load_basic_params_config()
        self.init_slider()

    def init_ui(self):
        ui_file = QFile(":ui/window.ui")
        ui_file.open(QFile.ReadOnly)
        loadUi(ui_file, self)
        # 设置窗口标题和大小
        self.setWindowTitle('采集输出软件V1.0')

        self.resize(1200, 800)
        # 设置窗口图标
        self.setWindowIcon(QIcon(':/images/dongyuan.png'))
        self.move_to_center()

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
        self.save_test_data.triggered.disconnect()
        self.save_test_data.triggered.connect(self.save_test_data_to_excel)
        self.plot_type_selector.currentIndexChanged.connect(self.update_plot3_by_selector)

    def only_view_all_menu(self):
        def context_menu(event):
            menu = QMenu()

            # 添加 View All 操作（等价于原生行为）
            view_all_action = QAction("View All")
            menu.addAction(view_all_action)

            # 设置触发行为：缩放视图范围以适应所有数据
            view_all_action.triggered.connect(lambda: self.plot3.plotItem.enableAutoRange())

            menu.exec_(event.screenPos())

        self.plot3.plotItem.scene().contextMenuEvent = context_menu

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
        self.plot1.setLabel('left', 'Amplitude', units='V')
        self.plot1.getAxis('bottom').setTextPen("black")
        self.plot1.getAxis('left').setTextPen("black")
        self.plot1.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot1.getAxis('left').enableAutoSIPrefix(False)
        self.plot1.showGrid(x=True, y=True, alpha=0.25)

        self.plot2 = pyqtgraph.PlotWidget()
        layout2 = QVBoxLayout()
        layout2.setContentsMargins(0, 0, 0, 0)
        layout2.addWidget(self.plot2)
        self.frame_2.setLayout(layout2)
        self.plot2.setBackground('white')
        self.plot2.setLabel('bottom', 'Time', units='s')
        self.plot2.setLabel('left', 'Amplitude', units='V')
        self.plot2.getAxis('bottom').setTextPen("black")
        self.plot2.getAxis('left').setTextPen("black")
        self.plot2.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot2.getAxis('left').enableAutoSIPrefix(False)
        self.plot2.showGrid(x=True, y=True, alpha=0.25)

        self.plot3 = pyqtgraph.PlotWidget()
        layout3 = QVBoxLayout()
        layout3.setContentsMargins(0, 0, 0, 0)
        layout3.addWidget(self.plot3)
        self.frame_3.setLayout(layout3)
        self.plot3.setBackground('white')
        self.plot3.setMenuEnabled(False)  # 禁用菜单
        self.only_view_all_menu()

        self.plot3.getAxis('bottom').enableAutoSIPrefix(False)  # 禁用自动转换单位
        self.plot3.getAxis('left').enableAutoSIPrefix(False)
        self.plot3.getAxis('bottom').setLogMode(True)  # 对数坐标轴，适用于频率
        self.plot3.getAxis('left').setLogMode(True)
        # 使用自定义的对数坐标轴刻度标签格式
        self.plot3.getAxis('bottom').logTickStrings = utils.custom_log_tick_strings
        # self.plot3.getAxis('bottom').setTickSpacing(levels=[(1, 1)])
        # 设置网格线和背景
        self.plot3.getPlotItem().showGrid(x=True, y=True)

        # 调整刻度字体大小
        font = pyqtgraph.QtGui.QFont()
        font.setPointSize(12)
        self.plot3.getAxis('bottom').setTickFont(font)
        self.plot3.getAxis('left').setTickFont(font)
        self.plot3.setLabel('left', 'Z abs', units='Rayl')
        self.plot3.setLabel('bottom', 'Freq', units='Hz')
        self.plot3.getAxis('bottom').setTextPen("black")
        self.plot3.getAxis('left').setTextPen("black")
        # 清空范围限制，允许滚轮缩放
        self.plot3.setAutoVisible(True)  # 启用自动范围调整
        self.plot3.plotItem.scene().sigMouseMoved.connect(self.mov)

        self.plot4 = pyqtgraph.PlotWidget()
        layout4 = QVBoxLayout()
        layout4.setContentsMargins(0, 0, 0, 0)
        layout4.addWidget(self.plot4)
        self.frame_4.setLayout(layout4)
        self.plot4.setBackground('white')
        self.plot4.setLabel('bottom', 'Time', units='s')
        self.plot4.setLabel('left', 'Amplitude', units='V')
        self.plot4.getAxis('bottom').setTextPen("black")
        self.plot4.getAxis('left').setTextPen("black")
        self.plot4.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot4.getAxis('left').enableAutoSIPrefix(False)
        self.plot4.showGrid(x=True, y=True, alpha=0.25)

        self.plot5 = pyqtgraph.PlotWidget()
        layout5 = QVBoxLayout()
        layout5.setContentsMargins(0, 0, 0, 0)
        layout5.addWidget(self.plot5)
        self.frame_5.setLayout(layout5)
        self.plot5.setBackground('white')
        self.plot5.setLabel('bottom', 'Time', units='s')
        self.plot5.setLabel('left', 'Amplitude', units='V')
        self.plot5.getAxis('bottom').setTextPen("black")
        self.plot5.getAxis('left').setTextPen("black")
        self.plot5.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot5.getAxis('left').enableAutoSIPrefix(False)
        self.plot5.showGrid(x=True, y=True, alpha=0.25)

    def on_plot3_clicked(self, event):
        if event.double():
            mouse_point = self.plot3.getViewBox().mapSceneToView(event.scenePos())
            x_log_clicked = mouse_point.x()
            freq_clicked = 10 ** x_log_clicked  # 实际频率

            plot_type = self.plot_type_selector.currentText()

            def safe_log(a):
                a = np.asarray(a, dtype=float)
                a[a <= 0] = np.nan  # 防止取对数报错
                return np.log10(a)

            if plot_type == "传输阻抗率Z abs":
                # 获取当前显示的曲线数据
                freq_array = np.asarray(self.test_result["ff"], dtype=float)
                y_array = self.test_result["Z_abs"]
            elif plot_type == "传输阻抗率Z Re":
                freq_array = np.asarray(self.test_result["ff"], dtype=float)
                y_array = np.abs(self.test_result["Z_Re"])
            elif plot_type == "传输阻抗率Z Im":
                freq_array = np.asarray(self.test_result["ff"], dtype=float)
                y_array = np.abs(self.test_result["Z_Im"])
            elif plot_type == "质点速度v abs":
                freq_array = np.asarray(self.test_result["ff"], dtype=float)
                y_array = self.test_result["V_abs"]
            elif plot_type == "质点速度v Re":
                freq_array = np.asarray(self.test_result["ff"], dtype=float)
                y_array = self.test_result["V_Re"]
            elif plot_type == "质点速度v Im":
                freq_array = np.asarray(self.test_result["ff"], dtype=float)
                y_array = self.test_result["V_Im"]
            else:
                return
            y_disp = safe_log(y_array)
            x_disp = np.log10(freq_array)
            # 如果启用了平滑处理
            if self.soft_value > 3:
                y_disp = savgol_filter(y_disp, window_length=self.soft_value, polyorder=3)
            # 找出频率中最接近点击频率的点
            index = np.abs(freq_array - freq_clicked).argmin()
            x_log = float(x_disp[index])  # 显示坐标（log10 频率）
            y_log = float(y_disp[index])  # 显示坐标（log10 幅值）
            x_lin = float(freq_array[index])  # 线性频率x
            y_lin = float(10 ** y_disp[index])  # 线性幅值y, 根据对数平滑生成的,而非原始数据

            self.logger.info(f"双击事件: 频率(x): {freq_clicked:.2f} Hz, 最近数据索引: {index}")
            self.logger.info(f"对数频率位置: {x_log:.4f}), 对数幅值位置: {y_log:.4f}")
            self.logger.info(f"频率线性值: {x_lin:.2f} Hz, 幅值线性值: {y_lin:.4f}")
            # 初始化十字线和文字提示
            if not self.crosshair_enabled:
                self.vLine = pyqtgraph.InfiniteLine(angle=90, movable=False, pen='r')
                self.hLine = pyqtgraph.InfiniteLine(angle=0, movable=False, pen='r')
                self.text = pyqtgraph.TextItem("", anchor=(0, 1), fill=pyqtgraph.mkBrush(255, 255, 255, 200),
                                               border='k')
                self.plot3.addItem(self.vLine, ignoreBounds=True)
                self.plot3.addItem(self.hLine, ignoreBounds=True)
                self.plot3.addItem(self.text)
                self.plot3.plotItem.scene().sigMouseMoved.connect(self.mov)
                self.crosshair_enabled = True

            self.vLine.setPos(x_log)
            self.hLine.setPos(y_log)

            # 添加点击标记
            if hasattr(self, "click_marker"):
                self.plot3.removeItem(self.click_marker)
            self.click_marker = pyqtgraph.ScatterPlotItem(
                [x_log], [y_log],
                symbol='o', size=4, brush=pyqtgraph.mkBrush(255, 255, 0), pen='k'
            )
            self.plot3.addItem(self.click_marker)

            # 提示框（显示线性频率和与图一致的线性幅值）
            self.text.setHtml(
                f"<div style='background-color:white; padding:2px;'>"
                f"<b>频率(x):</b> {x_lin:.2f} Hz<br>"
                f"<b>幅值(y):</b> {y_lin:.4f}</div>"
            )
            self.text.setPos(x_log, y_log)

    def mov(self, pos):
        if self.plot3.sceneBoundingRect().contains(pos):
            mouse_point = self.plot3.getViewBox().mapSceneToView(pos)
            x = mouse_point.x()
            y = mouse_point.y()
            real_x = 10 ** x
            real_y = 10 ** y
            threshold = 1e10
            if real_x > threshold:
                x_str = "∞"
            else:
                x_str = f"{real_x:.2f}"
            if real_y > threshold:
                y_str = "∞"
            else:
                y_str = f"{real_y:.2f}"
                self.common_pos_value.setText(f"普通计数坐标: x={x_str}, y={y_str}")

    def init_slider(self):
        self.slider = self.findChild(QtWidgets.QSlider, "slider")
        # 添加浮动标签
        self.float_label = QLabel(self)
        self.float_label.setStyleSheet("background-color: white; border: 1px solid gray;")
        self.float_label.setFixedSize(60, 20)
        self.float_label.setAlignment(Qt.AlignCenter)
        # 初始化浮动标签
        self.slider.setMinimum(0)
        self.slider.setMaximum(100)
        self.slider.setTickInterval(10)
        self.slider.setValue(self.soft_value)
        self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)

        self.slider.valueChanged.connect(self.update_float_label)

    def _reposition_slider_label(self):
        if hasattr(self, "slider") and self.slider is not None:
            self.update_float_label(self.slider.value())

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._reposition_slider_label)  # 首次显示后再定位

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._reposition_slider_label)  # 窗口尺寸变化后再定位

    def update_float_label(self, value):
        float_value = value / 1
        self.float_label.setText(f"{float_value:.1f}")
        self.float_label.setStyleSheet("""
            background-color: #f5f5f5;
            border: 1px solid #999;
            border-radius: 4px;
            padding: 2px;
            font-size: 10pt;
        """)
        # 获取 slider 左上角全局位置 → 相对于 self 的偏移
        slider_pos = self.slider.mapTo(self, self.slider.rect().topLeft())
        slider_width = self.slider.width()
        value_ratio = (value - self.slider.minimum()) / (self.slider.maximum() - self.slider.minimum())

        # 更精确地估计 handle 的像素位置（减去10调整）
        handle_x = int(value_ratio * (slider_width - 20))

        # 设置浮动标签的位置（居中显示）
        self.float_label.move(
            slider_pos.x() + handle_x - self.float_label.width() // 2 + 10,
            slider_pos.y() - self.float_label.height() - 5
        )
        soft_value = int(float(self.float_label.text()))
        self.save_basic_params_config(soft_value)
        self.load_basic_params_config()
        if self.plot_state is True:
            self.update_plot3_by_selector()
        else:
            # 不更新界面
            pass

    def load_basic_params_config(self):
        basic_params_path = utils.get_config_path("basic_params.json")
        try:
            with open(basic_params_path , "r", encoding="utf-8") as f:
                basic_config  = json.load(f)
                self.soft_value = basic_config.get("basic_params").get("soft_value")
        except Exception as e:
            self.logger.error(f"读取配置失败: {e}")
            QMessageBox.warning(self, "错误", f"读取{basic_params_path}配置失败：{e}")

    def save_basic_params_config(self, soft_value=None, **kwargs):
        basic_params_path = utils.get_config_path("basic_params.json")
        try:
            with open(basic_params_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            if "basic_params" not in config:
                config["basic_params"] = {}

            config["basic_params"]["soft_value"] = soft_value

            with open(basic_params_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"写入配置失败：{e}")


    def move_to_center(self):
        desktop = QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        # self.resize(w, h)
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

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
        utils.set_run_button_enabled(self.run_test_button, False)
        self.init_config()
        self.test_state.setText("测试中...")
        QtWidgets.QApplication.processEvents()
        # threading.Thread(target=self.record_and_plot).start()
        self.record_and_plot()
        self.run_test_button.setEnabled(True)
        # 启用按钮
        utils.set_run_button_enabled(self.run_test_button, True)

    def record_and_plot(self):
        try:
            self.plot1.clear()
            self.plot2.clear()
            self.plot3.clear()
            self.plot4.clear()
            self.plot5.clear()
            # 获取设备采样率
            samplerate = utils.get_device_info()
            duration = self.signal_info['signal_time']
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

            input_mapping = [i + 1 for i in range(input_channels)]
            output_mapping = [i + 1 for i in range(output_channels)]

            stimulus_data = np.asarray(data, dtype=np.float32)
            if stimulus_data.ndim == 1:  # 看维度
                stimulus_data = np.tile(stimulus_data.reshape(-1, 1), len(output_mapping))
            elif stimulus_data.shape[1] != len(output_mapping):  # 不是一维组数
                stimulus_data = np.tile(stimulus_data[:, [0]], len(output_mapping))

            self.logger.info("开始播放并录音...")
            recording = sd.playrec(
                stimulus_data,
                samplerate=samplerate,
                channels=input_channels,
                input_mapping=input_mapping,
                output_mapping=output_mapping,
                blocking=True
            )
            self.logger.info("录音完成")
            # 处理录音数据
            mic1_data, mic2_data, mic3_data, mic4_data, real_spl1, real_spl2, real_spl3, real_spl4 = (
                MicAdjustInterface.process_mic_channels_data(recording))
            if real_spl1 > 120:
                self.logger.error(f"麦克风1实际声压级 {real_spl1:.2f} dB, 超过阈值 {120} dB，已饱和")
                QMessageBox.warning(self, "警告", f"麦克风1实际声压级 {real_spl1:.2f} dB, 超过阈值 {120} dB，已饱和")
            if real_spl2 > 120:
                self.logger.error(f"麦克风2实际声压级 {real_spl2:.2f} dB, 超过阈值 {120} dB，已饱和")
                QMessageBox.warning(self, "警告", f"麦克风2实际声压级 {real_spl2:.2f} dB, 超过阈值 {120} dB，已饱和")
            if real_spl3 > 120:
                self.logger.error(f"麦克风3实际声压级 {real_spl3:.2f} dB, 超过阈值 {120} dB，已饱和")
                QMessageBox.warning(self, "警告", f"麦克风3实际声压级 {real_spl3:.2f} dB, 超过阈值 {120} dB，已饱和")
            if real_spl4 > 120:
                self.logger.error(f"麦克风4实际声压级 {real_spl4:.2f} dB, 超过阈值 {120} dB，已饱和")
                QMessageBox.warning(self, "警告", f"麦克风4实际声压级 {real_spl4:.2f} dB, 超过阈值 {120} dB，已饱和")

            # 创建采集保存目录
            save_dir = os.path.join(os.getcwd(), "！采集")
            os.makedirs(save_dir, exist_ok=True)
            mic1_txt = os.path.join(save_dir, "MIC1.txt")
            mic2_txt = os.path.join(save_dir, "MIC2.txt")
            mic3_txt = os.path.join(save_dir, "MIC3.txt")
            mic4_txt = os.path.join(save_dir, "MIC4.txt")
            np.savetxt(mic1_txt, mic1_data)
            np.savetxt(mic2_txt, mic2_data)
            np.savetxt(mic3_txt, mic3_data)
            np.savetxt(mic4_txt, mic4_data)
            self.logger.info(f"MIC1 采集已保存: {mic1_txt}")
            self.logger.info(f"MIC2 采集已保存: {mic2_txt}")
            self.logger.info(f"Mic3 采集已保存: {mic3_txt}")
            self.logger.info(f"Mic4 采集已保存: {mic4_txt}")

            time_axis = np.linspace(0, duration, len(mic1_data))
            self.plot1.plot(time_axis, mic1_data, pen=mkPen(color=(222, 222, 222)))
            self.plot2.plot(time_axis, mic2_data, pen=mkPen(color=(190, 190, 190)))
            self.plot4.plot(time_axis, mic3_data, pen='gray')
            self.plot5.plot(time_axis, mic4_data, pen='k')

            mic1_cal_data, mic2_cal_data, mic3_cal_data, mic4_cal_data = self.load_calibration_data()
            out_ff, out_absZ, out_realZ, out_imagZ, out_absV, out_realV, out_imagV = utils.calculate_mit_4mic(
                ax=mic1_data,
                bx=mic2_data,
                cx=mic3_data,
                dx=mic4_data,
                ax_cal=mic1_cal_data,
                bx_cal=mic2_cal_data,
                cx_cal=mic3_cal_data,
                dx_cal=mic4_cal_data,
                sf=samplerate,
                temp=self.tube_params.get("tube_temperature"),
                dia_tube_mm=self.tube_params.get("tubu_inner_diameter"),
                L_mm=self.tube_params.get("mic4_to_sample_distance"),
                x1_mm=self.tube_params.get("mic1_to_sample_distance"),
                x2_mm=self.tube_params.get("mic2_to_sample_distance"),
                x3_mm=self.tube_params.get("mic3_to_sample_distance"),
                s2=self.tube_params.get("sample_area"),
                sens=self.tube_params.get("mic4_sensitivity")
            )
            self.test_result = {
                "ff": out_ff,
                "Z_abs": out_absZ,
                "Z_Re": out_realZ,
                "Z_Im": out_imagZ,
                "V_abs": out_absV,
                "V_Re": out_realV,
                "V_Im": out_imagV
            }
            def trim_last9(tr):
                for k in tr:
                    tr[k] = tr[k][:-9]  # 直接去掉最后 9 个
                return tr
            self.test_result = trim_last9(self.test_result)

            ff = self.test_result["ff"]
            Z_abs = self.test_result["Z_abs"]
            # 统计0的个数
            print("ff 里 0 的个数：", np.sum(ff == 0))

            # 找出0的索引位置
            print("ff 为 0 的索引：", np.where(ff == 0)[0])
            print("Z_abs 为 0 的索引：", np.where(Z_abs == 0)[0])

            self.update_plot3_by_selector()

            self.logger.info(f"画图完成！")
            self.test_state.setText("测试完成")

        except Exception as e:
            self.logger.error(f"录音或保存失败: {e}")
            QMessageBox.warning(self, "错误", f"录音或保存失败：{e}")
            self.test_state.setText(f"测试失败: {e}")

    @staticmethod
    def load_calibration_data():
        # 构造校准文件路径
        cal_dir = os.path.join(os.getcwd(), "！校准")
        mic1_path = os.path.join(cal_dir, "MIC1.txt")
        mic2_path = os.path.join(cal_dir, "MIC2.txt")
        mic3_path = os.path.join(cal_dir, "MIC3.txt")
        mic4_path = os.path.join(cal_dir, "MIC4.txt")

        # 加载校准数据（float32 精度）
        mic1_cal = np.loadtxt(mic1_path, dtype=np.float32)
        mic2_cal = np.loadtxt(mic2_path, dtype=np.float32)
        mic3_cal = np.loadtxt(mic3_path, dtype=np.float32)
        mic4_cal = np.loadtxt(mic4_path, dtype=np.float32)
        return mic1_cal, mic2_cal, mic3_cal, mic4_cal

    @staticmethod
    def load_record_data():
        record_dir = os.path.join(os.getcwd(), "！采集")
        mic1_path = os.path.join(record_dir, "MIC1.txt")
        mic2_path = os.path.join(record_dir, "MIC2.txt")

        # 加载校准数据（float32 精度）
        mic1_record = np.loadtxt(mic1_path, dtype=np.float32)
        mic2_record = np.loadtxt(mic2_path, dtype=np.float32)
        return mic1_record, mic2_record

    def save_test_data_to_excel(self):
        if not self.test_result:
            QMessageBox.warning(self, "提示", "无测试结果，请先进行测试！")
            return
        log_ff = self.test_result["ff"]
        log_Z_abs = self.test_result["Z_abs"]
        log_Z_Re = np.abs(self.test_result["Z_Re"])
        log_Z_Im = np.abs(self.test_result["Z_Im"])

        log_V_abs = self.test_result["V_abs"]
        log_V_Re = self.test_result["V_Re"]
        log_V_Im = self.test_result["V_Im"]

        if self.soft_value > 3:
            log_Z_abs = savgol_filter(log_Z_abs, window_length=self.soft_value, polyorder=3)
            log_Z_Re = savgol_filter(log_Z_Re, window_length=self.soft_value, polyorder=3)
            log_Z_Im = savgol_filter(log_Z_Im, window_length=self.soft_value, polyorder=3)
            log_V_abs = savgol_filter(log_V_abs, window_length=self.soft_value, polyorder=3)
            log_V_Re = savgol_filter(log_V_Re, window_length=self.soft_value, polyorder=3)
            log_V_Im = savgol_filter(log_V_Im, window_length=self.soft_value, polyorder=3)

        save_dir = QFileDialog.getExistingDirectory(self, "选择保存文件夹")
        if not save_dir:
            return  # 用户取消

        try:
            file1 = os.path.join(save_dir, "传输阻抗率测试结果.csv")
            with open(file1, "w", newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["ff", "Z_abs", "Z_Re", "Z_Im"])
                for i in range(len(log_ff)):
                    writer.writerow([log_ff[i], log_Z_abs[i], log_Z_Re[i], log_Z_Im[i]])

            file2 = os.path.join(save_dir, "质点速度测试结果.csv")
            with open(file2, "w", newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["f", "v_abs", "v_Re", "v_Im"])
                for i in range(len(log_ff)):
                    writer.writerow([log_ff[i], log_V_abs[i], log_V_Re[i], log_V_Im[i]])

            msg = f"保存成功！\n文件已保存至：\n{file1}\n{file2}"
            QMessageBox.information(self, "Success", msg)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{str(e)}")

    def update_plot3_by_selector(self):
        """
        根据平滑值来重新画图
        """
        text = self.plot_type_selector.currentText()
        if text == "传输阻抗率Z abs":
            self.plot3.setLabel('left', 'Z abs', units='Rayl')
        elif text == "传输阻抗率Z Re":
            self.plot3.setLabel('left', 'Z Re', units='Rayl')
        elif text == "传输阻抗率Z Im":
            self.plot3.setLabel('left', 'Z Im', units='Rayl')
        elif text == "质点速度v abs":
            self.plot3.setLabel('left', 'v abs', units='m/s')
        elif text == "质点速度v Re":
            self.plot3.setLabel('left', 'v Re', units='m/s')
        elif text == "质点速度v Im":
            self.plot3.setLabel('left', 'v Im', units='m/s')
        else:
            print("没这个选择项")

        if not self.test_result:
            QMessageBox.warning(self, "提示", "无测试结果，请先进行测试！")
            return

        text = self.plot_type_selector.currentText()
        self.plot3.clear()

        # 十字线和提示框初始化但不添加到图上
        self.vLine = pyqtgraph.InfiniteLine(angle=90, movable=False, pen='r')
        self.hLine = pyqtgraph.InfiniteLine(angle=0, movable=False, pen='r')
        self.text = pyqtgraph.TextItem("", anchor=(0, 1), fill=pyqtgraph.mkBrush(255, 255, 255, 200), border='k')

        # 十字线显示开关
        self.crosshair_enabled = False

        # 绑定双击事件
        try:
            self.plot3.scene().sigMouseClicked.disconnect(self.on_plot3_clicked)
        except Exception:
            pass
        self.plot3.scene().sigMouseClicked.connect(self.on_plot3_clicked)

        if text == "传输阻抗率Z abs":
            log_ff = np.log10(self.test_result["ff"])
            log_Z_abs = np.log10(self.test_result["Z_abs"])
            if self.soft_value > 3:
                log_Z_abs = savgol_filter(log_Z_abs, window_length=self.soft_value, polyorder=3)
            # index = np.where(self.test_result["ff"] == 1000)[0]
            # print(index, self.test_result["Z_abs"][index], np.log10(self.test_result["Z_abs"])[index], log_Z_abs[index])
            self.plot3.plot(log_ff, log_Z_abs, pen=pyqtgraph.mkPen(color='black', width=2))

        elif text == "传输阻抗率Z Re":
            log_ff = np.log10(self.test_result["ff"])
            log_Z_Re = np.log10(np.abs(self.test_result["Z_Re"]))
            if self.soft_value > 3:
                log_Z_Re = savgol_filter(log_Z_Re, window_length=self.soft_value, polyorder=3)
            self.plot3.plot(log_ff, log_Z_Re, pen=pyqtgraph.mkPen(color='black', width=2))

        elif text == "传输阻抗率Z Im":
            log_ff = np.log10(self.test_result["ff"])
            log_Z_Im = np.log10(np.abs(self.test_result["Z_Im"]))
            if self.soft_value > 3:
                log_Z_Im = savgol_filter(log_Z_Im, window_length=self.soft_value, polyorder=3)
            self.plot3.plot(log_ff, log_Z_Im, pen=pyqtgraph.mkPen(color='black', width=2))

        elif text == "质点速度v abs":
            log_f = np.log10(self.test_result["ff"])
            log_V_abs = np.log10(self.test_result["V_abs"])
            if self.soft_value > 3:
                log_V_abs = savgol_filter(log_V_abs, window_length=self.soft_value, polyorder=3)
            self.plot3.plot(log_f, log_V_abs, pen=pyqtgraph.mkPen(color='black', width=2))

        elif text == "质点速度v Re":
            log_f = np.log10(self.test_result["ff"])
            log_V_Re = np.log10(self.test_result["V_Re"])
            if self.soft_value > 3:
                log_V_Re = savgol_filter(log_V_Re, window_length=self.soft_value, polyorder=3)
            self.plot3.plot(log_f, log_V_Re, pen=pyqtgraph.mkPen(color='black', width=2))

        elif text == "质点速度v Im":
            log_f = np.log10(self.test_result["ff"])
            log_V_Im = np.log10(self.test_result["V_Im"])
            if self.soft_value > 3:
                log_V_Im = savgol_filter(log_V_Im, window_length=self.soft_value, polyorder=3)
            self.plot3.plot(log_f, log_V_Im, pen=pyqtgraph.mkPen(color='black', width=2))
        else:
            print("无")

        self.plot3.plotItem.enableAutoRange(axis='xy', enable=True)  # X 和 Y 轴的自动范围调整
        self.plot_state = True

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

