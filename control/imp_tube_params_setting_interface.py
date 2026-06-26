import json

from PyQt5.QtCore import QFile, Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QGraphicsScene, QGraphicsPixmapItem, QMessageBox
from PyQt5.uic import loadUi

from control.log_manager import LogManager
from control.utils import utils

class ImptubeParamsSetInterface(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.ui = None
        self.logger = LogManager.set_log_handler("阻抗管参数设置")
        self.init_ui()
        self.init_fun()

    def init_ui(self):
        ui_file = QFile(":ui/imp_tube_params_setting.ui")
        if not ui_file.exists():
            self.logger.error("未找到资源文件 imp_tube_params_setting.ui")
            raise FileNotFoundError("未找到资源文件 imp_tube_params_setting.ui")
        ui_file.open(QFile.ReadOnly)
        self.ui = loadUi(ui_file, self)
        ui_file.close()
        self.setWindowTitle("阻抗管参数设置")
        # 最小化|最大化
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint)
        self.init_images()
        self.init_config()
        self.show()
        self.logger.info("打开阻抗管参数设置界面")

    def init_images(self):
        # 加载图片
        scene = QGraphicsScene()
        pixmap = QPixmap(":/images/4mic薄层_画板.png")
        scaled_pixmap = pixmap.scaled(390, 282, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap_item = QGraphicsPixmapItem(scaled_pixmap)
        scene.addItem(pixmap_item)
        self.graphicsView.setScene(scene)

    def init_fun(self):
        self.label_9.setStyleSheet("background-color: transparent; border: none; color: transparent;")
        self.yingcang1.setStyleSheet("background-color: transparent; border: none; color: transparent;")
        self.yingcang1.setEnabled(False)
        self.save_button.clicked.connect(self.save)

    def init_config(self):
        config_path = utils.get_config_path("imp_tube_params_setting.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.tube_params = config.get("tube_params", {})
                self.tube_temperature_value.setText(str(self.tube_params.get("tube_temperature", "")))
                self.mic1_to_sample_distance_value.setText(str(self.tube_params.get("mic1_to_sample_distance", "")))
                self.mic4_to_sample_distance_value.setText(str(self.tube_params.get("mic4_to_sample_distance", "")))
                self.mic4_sensitivity_value.setText(str(self.tube_params.get("mic4_sensitivity", "")))
                self.mic2_to_sample_distance_value.setText(str(self.tube_params.get("mic2_to_sample_distance", "")))
                self.sample_area_value.setText(str(self.tube_params.get("sample_area", "")))
                self.tubu_inner_diameter_value.setText(str(self.tube_params.get("tubu_inner_diameter", "")))
                self.mic3_to_sample_distance_value.setText(str(self.tube_params.get("mic3_to_sample_distance", "")))
        except Exception as e:
            self.logger.error(f"读取配置失败: {e}")
            QMessageBox.warning(self, "错误", f"读取配置失败：{e}")

    def save(self):
        config_path = utils.get_config_path("imp_tube_params_setting.json")
        try:
            config = {
                "tube_params": {
                    "tube_temperature": float(self.tube_temperature_value.text()),
                    "mic1_to_sample_distance": float(self.mic1_to_sample_distance_value.text()),
                    "mic4_to_sample_distance": float(self.mic4_to_sample_distance_value.text()),
                    "mic4_sensitivity": float(self.mic4_sensitivity_value.text()),
                    "mic2_to_sample_distance": float(self.mic2_to_sample_distance_value.text()),
                    "sample_area": float(self.sample_area_value.text()),
                    "tubu_inner_diameter": float(self.tubu_inner_diameter_value.text()),
                    "mic3_to_sample_distance": float(self.mic3_to_sample_distance_value.text())
                }
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "成功", "参数保存成功")
            self.logger.info("参数保存成功")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败：{e}")
            self.logger.error(f"保存失败：{e}")

    def closeEvent(self, event):
        if self.parent:
            self.parent.imptube_window = None
        self.logger.info("关闭阻抗管参数设置界面")
        event.accept()
