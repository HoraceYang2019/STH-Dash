import time
import logging
from config import ConfigManager
from data_manager import DataManager
from mqtt_handler import MQTTHandler
from job_handler import JobHandler

logger = logging.getLogger(__name__)

def wait_for_mqtt(mqtt_handler, timeout=5):
    """
    等待 MQTT 成功連線
    """
    for _ in range(timeout * 10):
        if mqtt_handler.mqtt_connected:
            logger.info("MQTT 已連線，系統開始運作")
            return True
        time.sleep(0.1)

    logger.error("MQTT 在指定時間內無法連線")
    return False

def main():
   
    # -------------------------------------
    # 初始化設定
    # -------------------------------------
    config_manager = ConfigManager()
    data_manager = DataManager(config_manager)
    job_handler = JobHandler(config_manager, data_manager)

    # -------------------------------------
    # 建立 MQTTHandler（自動 connect + loop_start）
    # -------------------------------------
    mqtt_handler = MQTTHandler(config_manager, data_manager, job_handler)
    job_handler.set_mqtt_handler(mqtt_handler)


    # -------------------------------------
    # 等待 MQTT 連上
    # -------------------------------------
    mqtt_connected = wait_for_mqtt(mqtt_handler)
    if not mqtt_connected:
            return "MQTT 連線失敗，程式終止，請檢察是否連接ST_Router"
    payload_end = {
                "CLASS": "RUN",
                "TYPE": "Stop",
                "VER": "01",
                "ID": 12345,
                "PYD": {
                    "SavePattern": True
                }
            }


    mqtt_handler.publish_message(config_manager.CMD_REQ_TOPIC, payload_end)
    print("END message sent.")
        
    time.sleep(0.2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        main()
    except KeyboardInterrupt:
        print("END message sent.")
        print("程式終止")

        