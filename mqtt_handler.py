# MQTT 處理模組，負責連線與訊息處理
import paho.mqtt.client as mqtt
import json
from datetime import datetime, timedelta
import logging
from config import ConfigManager
from data_manager import DataManager
import pandas as pd

logger = logging.getLogger(__name__)

class MQTTHandler:
    def __init__(self, config_manager: ConfigManager, data_manager: DataManager, job_handler):
        self.config = config_manager
        self.data_manager = data_manager
        self.job_handler = job_handler
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_connected = False
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.connect()

    def connect(self):
        """
        連線到 MQTT Broker
        """
        try:
            self.client.connect(self.config.MQTT_BROKER, self.config.MQTT_PORT, keepalive=60)
            self.client.loop_start()
            # logger.info("MQTT 客戶端啟動")
        except Exception as e:
            logger.error(f"MQTT 連線失敗: {e}")
            self.mqtt_connected = False

    def on_connect(self, client, userdata, flags, rc, properties):
        """
        MQTT 連線回調函數，訂閱相關主題
        """
        if rc == 0:
            # logger.info("已連線至 MQTT Broker")
            self.client.subscribe([
                (self.config.PDATA_TOPIC, 0),
                (self.config.CNC_TOPIC, 0),
                (self.config.CYCLE_TOPIC, 0),
                (self.config.CNC_RE_TOPIC, 0),
                (self.config.CMD_RESP_TOPIC, 0),
                (self.config.MAC_TOPIC, 0)
            ])
            self.mqtt_connected = True
        else:
            logger.error(f"MQTT 連線失敗，錯誤碼: {rc}")
            self.mqtt_connected = False

    def on_message(self, client, userdata, msg):
        """
        MQTT 訊息接收回調，處理 Pdata、CNC 和 Cycle 訊息
        """
        try:
            payload = json.loads(msg.payload.decode())
            if msg.topic == self.config.CYCLE_TOPIC:
                self.handle_cycle_message(payload)
            elif msg.topic == self.config.CNC_RE_TOPIC:
                self.handle_cnc_response(payload)
            elif msg.topic == self.config.CMD_RESP_TOPIC:
                self.job_handler.handle_cmd_response(payload)
            elif msg.topic == self.config.MAC_TOPIC:
                self.job_handler.handle_mac_message(payload)
            else:
                self.handle_data_message(msg.topic, payload)
        except Exception as e:
            pass
            # logger.error(f"處理 MQTT 訊息失敗: {e}")

    def handle_cycle_message(self, payload):
        """
        處理 Cycle 主題的訊息，更新循環狀態
        """
        cycle_state = payload.get("Cycle", None)
        if cycle_state in ["Start", "End"]:
            self.data_manager.update_cycle_status("on" if cycle_state == "Start" else "off")
            self.job_handler.handle_cycle_message(payload)
            # logger.info(f"收到 CYCLE 訊息，狀態更新為: {self.data_manager.live_data['cycle_status']}")

    def handle_cnc_response(self, payload):
        """
        處理 CNC 回應訊息，更新連線狀態
        """
        response = payload.get("Response", None)
        self.data_manager.update_cnc_connection_status(response if response else "")
        logger.info(f"收到 CNC 連線訊息: {response}")

    def handle_data_message(self, topic, payload):
        """
        處理 Pdata 和 CNC 數據訊息
        """
        full_time_str = payload.get("timetag", payload.get("Time", None))
        try:
            time_obj = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError as e:
            logger.error(f"無效的時間格式: {full_time_str}, 錯誤: {e}")
            return

        time_str = full_time_str.split(" ")[1]
        time_components = time_str.split(":")
        try:
            time_in_seconds = (
                float(time_components[0]) * 3600 +
                float(time_components[1]) * 60 +
                float(time_components[2])
            )
        except (ValueError, IndexError) as e:
            logger.error(f"計算 TimeInSeconds 失敗: {time_str}, 錯誤: {e}")
            return

        if topic == self.config.PDATA_TOPIC:
            self.process_pdata_message(payload, time_obj, time_in_seconds)
        elif topic == self.config.CNC_TOPIC:
            self.process_cnc_message(payload, full_time_str, time_in_seconds)

    def process_pdata_message(self, payload, time_obj, time_in_seconds):
        """
        處理 Pdata 訊息，轉換溫度並儲存數據
        """
        raw_temperature = payload.get("Temperature", 0)
        processed_temperature = self.process_temperature(raw_temperature)
        torque_values = payload.get("Torque", [0.0])
        bending_x_values = payload.get("Bending_X", [0.0])
        bending_y_values = payload.get("Bending_Y", [0.0])
        ch1_values = payload.get("CH1", [0.0])
        ch2_values = payload.get("CH2", [0.0])

        base_data = {
            "MAC": payload.get("MAC", "N/A"),
            "Power": payload.get("Power", 0.0),
            "Temperature": processed_temperature,
            "Packet Sequence Number": payload.get("Packet Sequence Number", 0),
            "RSSI": payload.get("RSSI", 0),
            "TTOLP": payload.get("TTOLP", 0),
        }

        new_data_list = []
        for i in range(len(torque_values)):
            offset_seconds = (len(torque_values) - 1 - i) * 0.1
            point_time = time_obj - timedelta(seconds=offset_seconds)
            point_time_in_seconds = time_in_seconds - offset_seconds
            new_data = {
                **base_data,
                "Torque": torque_values[i],
                "BendingX": bending_x_values[i] if i < len(bending_x_values) else 0.0,
                "BendingY": bending_y_values[i] if i < len(bending_y_values) else 0.0,
                "CH1": ch1_values[i] if i < len(ch1_values) else 0.0,
                "CH2": ch2_values[i] if i < len(ch2_values) else 0.0,
                "TimeTag": point_time.strftime("%H:%M:%S.%f")[:-3],
                "TimeInSeconds": point_time_in_seconds,
            }
            new_data_list.append(new_data)

        self.data_manager.add_pdata(new_data_list)
        self.data_manager.add_mqtt_message({**payload, "Temperature": processed_temperature})

    def process_cnc_message(self, payload, full_time_str, time_in_seconds):
        """
        處理 CNC 訊息，儲存相關數據
        """
        new_data = {
            "Time": full_time_str,
            "NC_File": payload.get("NC_File", "N/A"),
            "Spindle_Override": payload.get("Spindle_Override", "0%"),
            "Feed_Override": payload.get("Feed_Override", "0%"),
            "Offset_X": payload.get("Offset_X", 0.0),
            "Offset_Y": payload.get("Offset_Y", 0.0),
            "Offset_Z": payload.get("Offset_Z", 0.0),
            "G54_X": payload.get("G54_X", 0.0),
            "G54_Y": payload.get("G54_Y", 0.0),
            "G54_Z": payload.get("G54_Z", 0.0),
            "Tool_Code": payload.get("Tool_Code", "0"),
            "Tool_Life": payload.get("Tool_Life", 0),
            "Radius_Comp": payload.get("Radius_Comp", 0.0),
            "Radius_Wear": payload.get("Radius_Wear", 0.0),
            "Length_Comp": payload.get("Length_Comp", 0.0),
            "Length_Wear": payload.get("Length_Wear", 0.0),
            "Tool_Group": payload.get("Tool_Group", 0),
            "Tool_Group_Info": payload.get("Tool_Group_Info", 0),
            "Spindle_Number": payload.get("Spindle_Number", 0),
            "Status": payload.get("Status", "N/A"),
            "TimeInSeconds": time_in_seconds,
        }
        self.data_manager.add_cnc_data(new_data)

    def process_temperature(self, raw_temp):
        """
        將原始溫度值轉換為攝氏溫度
        """
        temp_v = raw_temp * ((3.3 / 4) / 32767)
        processed_temp = (((620 * temp_v) / (3.3 - temp_v)) - 100) / 0.39
        return round(processed_temp, 2)

    def publish_message(self, topic, message):
        """
        發送 MQTT 訊息
        """
        if self.mqtt_connected:
            try:
                self.client.publish(topic, json.dumps(message))
                # logger.info(f"成功發送訊息到 {topic}: {message}")
                return True
            except Exception as e:
                logger.error(f"發送訊息到 {topic} 失敗: {e}")
                return False
        else:
            logger.warning(f"未發送訊息到 {topic}: MQTT 未連線")
            return False