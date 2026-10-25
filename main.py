# 主應用程式檔案，負責初始化並運行 Dash 應用
from dash import Dash
from layout import DashboardLayout
from callbacks import register_callbacks
from config import ConfigManager
from data_manager import DataManager
from job_handler import JobHandler
from mqtt_handler import MQTTHandler
from cnc_network_manager import CNCNetworkManager
import logging

# 設定日誌記錄，方便追蹤應用程式運行狀態
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VisualizationDashboard:
    def __init__(self):
        # 初始化配置管理與數據管理
        self.config_manager = ConfigManager()
        self.data_manager = DataManager(self.config_manager)
        self.job_handler = JobHandler(self.config_manager, self.data_manager)
        self.mqtt_handler = MQTTHandler(self.config_manager, self.data_manager, self.job_handler)
        self.job_handler.set_mqtt_handler(self.mqtt_handler)
        self.cnc_network_manager = CNCNetworkManager(self.config_manager)
        # 創建 Dash 應用實例
        self.app = Dash(__name__, external_stylesheets=[self.config_manager.CSS_PATH])
        # 設定應用程式的網頁佈局
        self.app.layout = DashboardLayout(self.config_manager, self.data_manager).get_layout()
        # 註冊所有的回調函數
        register_callbacks(self.app, self.config_manager, self.data_manager, self.job_handler, self.mqtt_handler, self.cnc_network_manager)

    def run(self):
        # 啟動 Dash 伺服器，指定主機與端口
        self.app.run(debug=True, host=self.config_manager.MQTT_BROKER, port=self.config_manager.PORT, threaded=True)

if __name__ == "__main__":
    # 創建並運行應用程式
    VisualizationDashboard().run()