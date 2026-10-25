# 工作處理模組，整合 sth_job_V5.py 的狀態機與 MQTT 功能
import time
import threading
import logging
from config import ConfigManager
from data_manager import DataManager
from mqtt_handler import MQTTHandler
from pathlib import Path

logger = logging.getLogger(__name__)

class JobHandler:
    def __init__(self, config_manager: ConfigManager, data_manager: DataManager):
        # 初始化工作處理器，注入配置與數據管理器
        self.config = config_manager
        self.data_manager = data_manager
        self.mqtt_handler = None  # MQTT 處理器，稍後設置
        self.state = "IDLE"  # 狀態：IDLE, CONFIG, Reference, RECORD
        self.config_timeout = None  # 超時計時器
    
    def set_mqtt_handler(self, mqtt_handler: MQTTHandler):
        """
        設定 MQTT 處理器（延遲注入）
        """
        self.mqtt_handler = mqtt_handler


    def handle_mac_message(self, payload):
        """
        處理 STH/MAC 主題的 HolderID 訊息
        """
        holder_id = payload.get("HolderID")
        if not holder_id:
            logger.warning(f"無效的 HolderID: {payload}")
            return
        if holder_id == self.data_manager.live_data["tmac"]:
            logger.debug(f"忽略重複的 HolderID: {holder_id}，當前狀態: {self.state}")
            return
        if self.state in ["IDLE", "CONFIG", "Reference"]:
            self.data_manager.update_tmac(holder_id)
            self.data_manager.update_job_state("CONFIG")
            self.state = "CONFIG"
            self.publish_config()
        else:  # RECORD 狀態
            logger.info(f"收到新 HolderID: {holder_id}，但處於 RECORD 狀態，儲存待用")
            self.data_manager.update_tmac(holder_id, pending=True)

    def handle_cmd_response(self, payload):
        """
        處理 CMD/RESP 主題的回應訊息
        """
        logger.info(f"收到 CMD/RESP 訊息，當前狀態: {self.state}, Payload: {payload}")
        if payload.get("TYPE") == "ReSetConfig":
            if payload.get("ID") == 556 and payload.get("RESULT") in ["0:PUBLIC SUCCESS.\n", "-201:CONFIG FAIL BECAUSE ALREADY IN START MODE.\n"]:
                logger.info("配置成功，開始 Reference")
                self.data_manager.update_job_state("Reference")
                self.state = "Reference"
                if self.config_timeout:
                    self.config_timeout.cancel()  # 取消超時計時器
                    self.config_timeout = None
            else:
                logger.error(f"配置失敗: {payload.get('RESULT', '未知錯誤')}")
                self.data_manager.update_job_state("IDLE")
                self.state = "IDLE"
                if self.config_timeout:
                    self.config_timeout.cancel()
                    self.config_timeout = None
                # 檢查是否有待處理的 HolderID
                if self.data_manager.live_data["pending_tmac"] and self.data_manager.live_data["pending_tmac"] != self.data_manager.live_data["tmac"]:
                    logger.info(f"應用待處理的 HolderID: {self.data_manager.live_data['pending_tmac']}")
                    self.data_manager.update_tmac(self.data_manager.live_data["pending_tmac"])
                    self.data_manager.update_tmac(None, pending=True)
                    self.data_manager.update_job_state("CONFIG")
                    self.state = "CONFIG"
                    self.publish_config()
                elif self.data_manager.live_data["tmac"]:
                    logger.info(f"配置失敗後重新配置，TMAC: {self.data_manager.live_data['tmac']}")
                    self.data_manager.update_job_state("CONFIG")
                    self.state = "CONFIG"
                    self.publish_config()
        else:
            logger.warning(f"未知的 CMD/RESP 訊息類型: {payload.get('TYPE')}")

    def handle_cycle_message(self, payload):
        """
        處理 Cycle 主題的訊息
        """
        # logger.info(f"收到 Cycle 訊息，當前狀態: {self.state}, Payload: {payload}")
        if self.state not in ["Reference", "RECORD"]:
            # logger.warning(f"忽略 Cycle 訊息，當前狀態 {self.state} 不允許處理")
            return
        cycle = payload.get("Cycle")
        if cycle == "Start":
            logger.info("收到 Cycle Start")
            self.data_manager.update_job_state("RECORD")
            self.state = "RECORD"
            self.publish_start()
        elif cycle == "End":
            logger.info("收到 Cycle End")
            threading.Timer(5.0, self.stop_job).start()
        else:
            logger.warning(f"未知的 Cycle 值: {cycle}")

    def publish_config(self):
        """
        發送配置請求
        """
        if not self.data_manager.live_data["tmac"]:
            logger.error("無法發送配置：TMAC 未設定")
            self.data_manager.update_job_state("IDLE")
            self.state = "IDLE"
            return
        payload = {
            "CLASS": "CONFIG",
            "TYPE": "SetConfig",
            "VER": "01",
            "ID": 556,
            "PYD": {
                "SysTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                "TMAC": self.data_manager.live_data["tmac"]
            }
        }
        self.mqtt_handler.publish_message(self.config.CMD_REQ_TOPIC, payload)
        # logger.info(f"已發送配置: {payload}")
        # 啟動超時計時器（10秒）
        if self.config_timeout:
            self.config_timeout.cancel()
        self.config_timeout = threading.Timer(10.0, self.handle_config_timeout)
        self.config_timeout.start()

    def handle_config_timeout(self):
        """
        處理 SetConfig 超時
        """
        if self.state == "CONFIG":
            # logger.error("SetConfig 超時，未收到 ReSetConfig 回應，狀態切回 IDLE")
            self.data_manager.update_job_state("IDLE")
            self.state = "IDLE"
            self.config_timeout = None
            # 檢查是否有待處理的 HolderID
            if self.data_manager.live_data["pending_tmac"] and self.data_manager.live_data["pending_tmac"] != self.data_manager.live_data["tmac"]:
                logger.info(f"應用待處理的 HolderID: {self.data_manager.live_data['pending_tmac']}")
                self.data_manager.update_tmac(self.data_manager.live_data["pending_tmac"])
                self.data_manager.update_tmac(None, pending=True)
                self.data_manager.update_job_state("CONFIG")
                self.state = "CONFIG"
                self.publish_config()
            elif self.data_manager.live_data["tmac"]:
                # logger.info(f"超時後重新配置，TMAC: {self.data_manager.live_data['tmac']}")
                self.data_manager.update_job_state("CONFIG")
                self.state = "CONFIG"
                self.publish_config()

    def publish_start(self):
        """
        發送啟動指令
        """
        payload = {
            "CLASS": "START",
            "TYPE": "Start",
            "VER": "01",
            "ID": 5678,
            "PYD": {
                "Mode": "Reference",
                "IsDetail": True
            }
        }
        self.mqtt_handler.publish_message(self.config.CMD_REQ_TOPIC, payload)
        logger.info(f"已發送啟動指令: {payload}")

    def start_job(self, yaml_path):
        """
        啟動加工任務，從 YAML 檔案讀取 HolderID 並發送
        """
        try:
            params, _ = self.data_manager.load_yaml_params(yaml_path)
            holder_id = params.get("tool_holder", "N/A")
            if holder_id == "N/A":
                logger.error("無法啟動任務：無有效的 HolderID")
                return False
            self.data_manager.update_tmac(holder_id)
            self.data_manager.update_job_state("CONFIG")
            self.state = "CONFIG"
            self.publish_config()
            return True
        except Exception as e:
            logger.error(f"啟動加工任務失敗: {e}")
            return False

    def stop_job(self):
        """
        停止加工任務並保存數據
        """
        try:
            payload = {
                "CLASS": "RUN",
                "TYPE": "Stop",
                "VER": "01",
                "ID": 12345,
                "PYD": {
                    "SavePattern": True
                }
            }
            self.mqtt_handler.publish_message(self.config.CMD_REQ_TOPIC, payload)
            logger.info(f"已發送停止指令: {payload}")
            self.data_manager.update_job_state("IDLE")
            self.state = "IDLE"
            # 檢查是否有待處理的 HolderID
            if self.data_manager.live_data["pending_tmac"] and self.data_manager.live_data["pending_tmac"] != self.data_manager.live_data["tmac"]:
                logger.info(f"應用待處理的 HolderID: {self.data_manager.live_data['pending_tmac']}")
                self.data_manager.update_tmac(self.data_manager.live_data["pending_tmac"])
                self.data_manager.update_tmac(None, pending=True)
                self.data_manager.update_job_state("CONFIG")
                self.state = "CONFIG"
                self.publish_config()
            elif self.data_manager.live_data["tmac"]:
                logger.info(f"Cycle End 後重新配置，TMAC: {self.data_manager.live_data['tmac']}")
                self.data_manager.update_job_state("CONFIG")
                self.state = "CONFIG"
                self.publish_config()
            return True
        except Exception as e:
            logger.error(f"停止加工任務失敗: {e}")
            return False

    def validate_managed_path(self, path, root_dir, allowed_extensions, allow_folder=False):
        """
        驗證使用者選擇的檔案或資料夾

        僅允許操作指定根目錄下的第一層項目，
        防止選取其他目錄或符號連結。
        """
        root = Path(root_dir).resolve(strict=True)
        selected = Path(path).expanduser()

        if selected.is_symlink():
            raise logger.error("不允許操作符號連結")

        selected = selected.resolve(strict=True)

        if selected.parent != root:
            raise logger.error("選擇的路徑不在允許的目錄中")

        if selected.is_dir() and allow_folder:
            return selected

        if selected.is_file() and selected.suffix.lower() in allowed_extensions:
            return selected

        raise logger.error("不支援的檔案或資料夾")
