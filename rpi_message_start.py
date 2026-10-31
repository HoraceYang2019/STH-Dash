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


def main(mac):
   
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
    MAC = mac
    print(MAC)
    payload = {
        "CLASS": "CONFIG",
        "TYPE": "SetConfig",
        "VER": "01",
        "ID": 556,
        "PYD": {
            "SysTime": time.strftime("%Y-%m-%d %H:%M:%S"),

            "TMAC": MAC
        }
    }
    
    payload_start = {
            "CLASS": "START",
            "TYPE": "Start",
            "VER": "01",
            "ID": 5678,
            "PYD": {
                "Mode": "Reference",
                "IsDetail": True
            }
        }

    # 新增數據流
    print("Sending CONFIG message...")
    mqtt_handler.publish_message(config_manager.CMD_REQ_TOPIC, payload)
    print("Successfully sent CONFIG message." + str(MAC))
    time.sleep(0.5)  # 等待 0.5 秒以確保 CONFIG 訊息被處理
    #樹梅派有最低0.1秒的mqtt處理延遲 

    # input("Press Enter to send start")
    mqtt_handler.publish_message(config_manager.CMD_REQ_TOPIC, payload_start)
        
    


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        # 6055f9e3d0e4 
        # 6055f9e3d0d6
        main("6055f9e38c14")
    except KeyboardInterrupt:
        print("END message sent.")
        print("程式終止")

        
    

# Pdata
# mqtt_maneger.live_data["message_"]


# 4 ~ 11 秒
#14 ~ 30