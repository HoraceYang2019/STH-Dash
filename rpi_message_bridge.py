
    # ---------------------------
    # 以下是你的測試訊息（保留原樣）
    # ---------------------------
    # payload = {
    #     "CLASS": "CONFIG",
    #     "TYPE": "SetConfig",
    #     "VER": "01",
    #     "ID": 556,
    #     "PYD": {
    #         "SysTime": time.strftime("%Y-%m-%d %H:%M:%S"),
    #         "TMAC": "84f703ce69b6"
    #     }
    # }
    # mqtt_handler.publish_message(config_manager.CMD_REQ_TOPIC, payload)

    # payload_start = {
    #     "CLASS": "START",
    #     "TYPE": "Start",
    #     "VER": "01",
    #     "ID": 557,
    #     "PYD": {
    #         "SysTime": time.strftime("%Y-%m-%d %H:%M:%S"),
    #         "TMAC": "84f703ce69b6"
    #     }
    # }

    # payload_end = {
    #     "CLASS": "END",
    #     "TYPE": "End",
    #     "VER": "01",
    #     "ID": 558,
    #     "PYD": {
    #         "SysTime": time.strftime("%Y-%m-%d %H:%M:%S"),
    #         "TMAC": "84f703ce69b6"
    #     }
    # }
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
    wait_for_mqtt(mqtt_handler)
    # -------------------------------------

      # 一代工作刀把
    # 84f703cdc020 1mm
    # 84f703cdbe7c 6mm
      # 二代工作刀把
    # 6055f9e3d0d6 10mm
    # 6055f9e3d0e4
    # 1K
    # 6055f9e38c14
    
    # 15.15
    #連線慢
    # 84f703cdb854
    work_MAC_list = ["84f703cdc020"]
    # 需改成Handler_list 
    
    # MAC_list=  ["84f703cdbe7c","6055f9e3d0d6",'84f703ce2d10','84f703cdc020','6055f9e3d0e4','6555f9e3d804','84f703ce69b6',  '84f703cd4664','84f703cd4f7a','84f703cdb854','84f703ce235e']
    MAC_list = work_MAC_list
    # 再輸入位置顯示清單
    print("Available Handlers:")
    for idx, mac in enumerate(MAC_list):
        print(f"{idx}: {mac}")
    handler_NO = int(input("Press Enter to send CONF0IG: "))
    MAC = MAC_list[handler_NO]
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
    
    payload_end = {
                "CLASS": "RUN",
                "TYPE": "Stop",
                "VER": "01",
                "ID": 12345,
                "PYD": {
                    "SavePattern": True
                }
            }


    # 新增數據流
    print("Sending CONFIG message...")
    mqtt_handler.publish_message(config_manager.CMD_REQ_TOPIC, payload)
    print("Successfully sent CONFIG message." + str(MAC))
    time.sleep(0.5)  # 等待 0.5 秒以確保 CONFIG 訊息被處理
    #樹梅派有最低0.1秒的mqtt處理延遲 

    # input("Press Enter to send start")
    start = time.time()
    mqtt_handler.publish_message(config_manager.CMD_REQ_TOPIC, payload_start)

    input()
    
    # if inp == "" or inp == "end":
    mqtt_handler.publish_message(config_manager.CMD_REQ_TOPIC, payload_end)
    print("END message sent.")
        
    elapsed = int(time.time() - start)
    time.sleep(0.2)
    print(f"總共加工時間: {elapsed} 秒")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        while True:
            main()
    except KeyboardInterrupt:
        print("END message sent.")
        print("程式終止")

        
    

# Pdata
# mqtt_maneger.live_data["message_"]


# 4 ~ 11 秒
#14 ~ 30