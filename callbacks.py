# 回調函數模組，處理 Dash 應用程式的交互邏輯
import dash
from dash import html, dcc, Input, Output, State, clientside_callback
import plotly.graph_objs as go
import pandas as pd
import yaml
import os
import io
import base64
from datetime import datetime
import trimesh
import logging
import numpy as np
import subprocess
from config import ConfigManager
from data_manager import DataManager
from mqtt_handler import MQTTHandler
from job_handler import JobHandler
import time
import platform
from report import generate_machining_report
from cnc_network_manager import CNCNetworkManager
from pathlib import Path
import shutil
import zipfile

_prev_cycle_status = "off"  # 模組層記住上一輪的 cycle 狀態  

logger = logging.getLogger(__name__)


def register_callbacks(app, config_manager: ConfigManager, data_manager: DataManager, 
                       job_handler: JobHandler, mqtt_handler: MQTTHandler, cnc_network_manager: CNCNetworkManager):
    """
    註冊所有的 Dash 回調函數
    """
    # 客戶端回調，頁面載入時自動獲取客戶端本地時間
    clientside_callback(
        """
        function(n_intervals, existing_time) {
            if (existing_time) {
                return window.dash_clientside.no_update; // 如果已有時間，則不更新
            }
            console.log("clientside_callback triggered for initial time");
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            const day = String(now.getDate()).padStart(2, '0');
            const hours = String(now.getHours()).padStart(2, '0');
            const minutes = String(now.getMinutes()).padStart(2, '0');
            const seconds = String(now.getSeconds()).padStart(2, '0');
            const timeString = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
            console.log("Generated client time:", timeString);
            return timeString;
        }
        """,
        Output('client-time', 'data'),
        Input('interval-component', 'n_intervals'),
        State('client-time', 'data'),
        prevent_initial_call=False  # 允許頁面載入時自動執行
    )

    @app.callback(
        [
            Output('client-time', 'data', allow_duplicate=True),
            Output('flute-buffer-store', 'data', allow_duplicate=True)
        ],
        Input('client-time', 'data'),
        prevent_initial_call=True
    )
    def update_time_and_reset_data(client_time):
        """
        使用網頁客戶端時間更新樹莓派系統，並設定預設圖表數據為 0
        """
        if client_time is None: return dash.no_update, dash.no_update
        try:
            # 檢測當前作業系統
            system = platform.system()
            if system == "Windows": pass  # Windows 系統不執行時間同步
            else:
                # 更新樹莓派系統時間
                cmd = f"sudo date -s '{client_time}'"
                logger.info(f"執行命令: {cmd}")
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    logger.info(f"成功更新樹莓派時間為: {client_time}")
                else:
                    logger.error(f"更新時間失敗: {result.stderr}")
        except Exception as e:
            logger.error(f"更新時間發生錯誤: {e}")

        # 設定圖表預設數據
        data_manager.live_data["pdata_list"] = [{
            "Times": "00.000",
            "Torque": 0.0,
            "BendingX": 0.0,
            "BendingY": 0.0,
            "CH1": 0.0,
            "CH2": 0.0,
            "TimeInSeconds": 0.0,
            "MAC": 0,
            "Power": 0.00,
            "Temperature": 0,
            "Packet Sequence Number": 0,
            "RSSI": 0,
            "TTOLP": 0,
            "TimeTag": "00:00:00.0"
        }]
        data_manager.live_data["cnc_list"] = [{
            "Offset_X": 0.0,
            "Offset_Y": 0.0,
            "Offset_Z": 0.0,
            "TimeInSeconds": 0.0
        }]
        data_manager.live_data["mqtt_messages"] = []

        return dash.no_update, []
    
    @app.callback(
        [
            Output("config-modal", "style"),
            Output("yaml-content", "value"),
            Output("config-json-content", "value"),
            Output("coeff-content", "value"),
            Output("original-yaml-content", "data"),
            Output("original-config-content", "data"),
            Output("original-coeff-content", "data")
        ],
        [
            Input("edit-config-button", "n_clicks"),
            Input("close-modal-button", "n_clicks"),
            Input("save-config-button", "n_clicks"),
            Input("modal-yaml-dropdown", "value")
        ],
        [State("config-modal", "style")],
        prevent_initial_call=True
    )
    def toggle_modal_and_load_content(edit_clicks, close_clicks, save_clicks, selected_yaml, current_style):
        """
        切換模態視窗顯示狀態並載入 YAML、config.json 和 coefficient.csv 內容
        """
        ctx = dash.callback_context
        if not ctx.triggered:
            return (
                {'display': 'none'},
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update
            )

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        
        # 載入原始內容
        yaml_content = ""
        if selected_yaml:
            try:
                with open(selected_yaml, "r", encoding="utf-8") as f:
                    yaml_content = f.read()
            except Exception as e:
                # logger.error(f"無法載入 YAML 檔案 {selected_yaml}: {e}")
                yaml_content = "Error loading YAML file"
        
        config_content = config_manager.load_config(return_formatted=True)
        coeff_content = config_manager.load_coeff(return_formatted=True)

        if button_id == "edit-config-button" and edit_clicks:
            # 開啟模態視窗並載入原始內容
            return (
                {'display': 'flex', 'justify-content': 'center', 'align-items': 'center', 'z-index': '10000'},
                yaml_content,
                config_content,
                coeff_content,
                yaml_content,
                config_content,
                coeff_content
            )
        elif button_id == "modal-yaml-dropdown" and selected_yaml:
            # 切換 YAML 檔案時更新內容
            return (
                current_style or {'display': 'flex', 'justify-content': 'center', 'align-items': 'center', 'z-index': '10000'},
                yaml_content,
                config_content,
                coeff_content,
                yaml_content,
                config_content,
                coeff_content
            )
        elif button_id in ["close-modal-button"] and (close_clicks):
            # 關閉模態視窗並重置內容
            return (
                {'display': 'none'},
                yaml_content,
                config_content,
                coeff_content,
                yaml_content,
                config_content,
                coeff_content
            )
        return (
            current_style or {'display': 'none'},
            yaml_content,
            config_content,
            coeff_content,
            yaml_content,
            config_content,
            coeff_content
        )

    @app.callback(
        [
            Output("status-messages", "children", allow_duplicate=True),
            Output("yaml-dropdown", "options"),
            Output("modal-message", "children"),
            Output("config-modal", "style", allow_duplicate=True),
            Output("yaml-content", "value", allow_duplicate=True),
            Output("config-json-content", "value", allow_duplicate=True),
            Output("coeff-content", "value", allow_duplicate=True)
        ],
        [
            Input("save-config-button", "n_clicks"),
            Input("close-modal-button", "n_clicks"),
            Input("upload-yaml", "contents")
        ],
        [
            State("modal-yaml-dropdown", "value"),
            State("yaml-content", "value"),
            State("config-json-content", "value"),
            State("coeff-content", "value"),
            State("upload-yaml", "filename"),
            State("original-yaml-content", "data"),
            State("original-config-content", "data"),
            State("original-coeff-content", "data")
        ],
        prevent_initial_call=True
    )
    def handle_config_and_upload(save_clicks, close_clicks, upload_contents, yaml_path, 
        yaml_content, config_json_content, coeff_content, upload_filename, original_yaml, 
        original_config, original_coeff):
        '''
        處理 config.json、YAML 和 coefficient.csv 儲存與檔案上傳
        '''
        ctx = dash.callback_context
        if not ctx.triggered:
            return "", dash.no_update, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        yaml_options = data_manager.get_yaml_files()
        modal_message = ""

        if button_id == "save-config-button" and save_clicks:
            # 儲存 YAML 檔案
            if yaml_path and yaml_content and yaml_content != original_yaml:
                try:
                    with open(yaml_path, "w", encoding="utf-8") as f:
                        f.write(yaml_content)
                    logger.info(f"成功儲存 YAML 檔案: {yaml_path}")
                    modal_message = "YAML file saved successfully."
                except Exception as e:
                    logger.error(f"儲存 YAML 檔案失敗: {e}")
                    modal_message = f"Error saving YAML file: {str(e)}"

            # 儲存 config.json
            if config_json_content != original_config:
                success, error_message = config_manager.save_config(config_json_content)
                if success:
                    logger.info(f"成功儲存 config.json: {config_json_content}")
                    modal_message += " config.json saved successfully."
                else:
                    modal_message += f" {error_message}"

            # 儲存 coefficient.csv
            if coeff_content != original_coeff:
                try:
                    # 驗證 CSV 格式
                    test_df = pd.read_csv(io.StringIO(coeff_content))
                    required_columns = ["MAC", "Torque", "BendingX", "BendingY", "CH1", "CH2"]
                    if not all(col in test_df.columns for col in required_columns):
                        modal_message += " Invalid CSV format: missing required columns."
                    else:
                        success, error_message = config_manager.save_coeff(coeff_content)
                        if success:
                            # modal_message += " coefficient.csv saved successfully."
                            data_manager.load_coefficients()  # 重新載入係數
                        else:
                            modal_message += f" {error_message}"
                except Exception as e:
                    logger.error(f"驗證或儲存 coefficient.csv 失敗: {e}")
                    # modal_message += f" Error processing coefficient.csv: {str(e)}"

            return (
                dash.no_update,
                yaml_options,
                modal_message,
                {'display': 'flex', 'justify-content': 'center', 'align-items': 'center', 'z-index': '10000'},
                dash.no_update,
                dash.no_update,
                dash.no_update
            )

        elif button_id == "close-modal-button" and close_clicks:
            return (
                dash.no_update,
                yaml_options,
                "",
                {'display': 'none'},
                dash.no_update,
                dash.no_update,
                dash.no_update
            )

        elif button_id == "upload-yaml" and upload_contents:
            try:
                content_type, content_string = upload_contents.split(',')
                decoded = base64.b64decode(content_string)
                yaml_content = decoded.decode('utf-8')
                if not upload_filename.endswith(('.yml', '.yaml')):
                    # return "Invalid file type. Please upload a YAML file.", yaml_options, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update
                    return "Invalid file type. Please upload a YAML file.", yaml_options, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update
                
                yaml_path = os.path.join(config_manager.YAML_DIR, upload_filename)
                with open(yaml_path, "w", encoding="utf-8") as f:
                    f.write(yaml_content)
                logger.info(f"成功上傳 YAML 檔案: {yaml_path}")
                yaml_options = data_manager.get_yaml_files()
                # return f"File {upload_filename} uploaded successfully.", yaml_options, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update
                return f"File {upload_filename} uploaded successfully.", yaml_options, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update
            except Exception as e:
                logger.error(f"上傳 YAML 檔案失敗: {e}")
                # return f"Error uploading file: {str(e)}", yaml_options, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update
                return f"Error uploading file: {str(e)}", yaml_options, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update

        return "", yaml_options, "", dash.no_update, dash.no_update, dash.no_update, dash.no_update

    @app.callback(
        Output("modal-yaml-dropdown", "options"),
        Input("yaml-dropdown", "options"),
        prevent_initial_call=True
    )
    def sync_yaml_dropdown_options(yaml_options):
        """
        同步 YAML 下拉選單選項到模態視窗中的下拉選單
        """
        return yaml_options

    @app.callback(
        Output("part-files-message", "children", allow_duplicate=True),
        Output("part-files-modal", "style"),
        Input("manage-part-files-button", "n_clicks"),
        Input("cancel-part-files-button", "n_clicks"),
        prevent_initial_call=True
    )
    def toggle_part_files_modal(open_clicks, close_clicks):
        """
        切換工件管理視窗的顯示狀態
        """
        trigger_id = dash.callback_context.triggered[0]["prop_id"].split(".")[0]

        if trigger_id == "manage-part-files-button":
            return "", {
                "display": "flex",
                "justify-content": "center",
                "align-items": "center",
                "z-index": "10000"
            }

        return "", {"display": "none"}

    @app.callback(
        Output("part-files-message", "children"),
        Output("part-files-checklist", "options"),
        Input("upload-part-files", "contents"),
        State("upload-part-files", "filename"),
        prevent_initial_call=True
    )
    def upload_part_files(contents, filenames):
        """
        處理工件檔案上傳
        """
        if contents is None or filenames is None:
            return "No files uploaded.", dash.no_update

        messages = []
        for content, filename in zip(contents, filenames):
            try:
                content_type, content_string = content.split(',')
                decoded = base64.b64decode(content_string)
                part_file_path = os.path.join(config_manager.STL_DIR, filename)
                with open(part_file_path, "wb") as f:
                    f.write(decoded)
                logger.info(f"成功上傳工件檔案: {part_file_path}")
                messages.append(f"File {filename} uploaded successfully.")
            except Exception as e:
                logger.error(f"上傳工件檔案失敗: {e}")
                messages.append(f"Error uploading file {filename}: {str(e)}")
        return " ".join(messages), data_manager.get_part_files()  # 更新工件檔案清單


    @app.callback(
        Output("part-files-message", "children", allow_duplicate=True),
        Output("part-files-checklist", "options", allow_duplicate=True),
        Output("part-files-checklist", "value"),
        Input("delete-part-files-confirm-button", "n_clicks"),
        State("part-files-checklist", "value"),
        prevent_initial_call=True
    )
    def delete_part_files(button_clicks, selected_files):
        """
        刪除選中的工件檔案
        """
        button_id = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
        delete_message = ""

        if button_id == "delete-part-files-confirm-button" and button_clicks:

            if selected_files is None or len(selected_files) == 0:
                return "No files selected for deletion.", dash.no_update, dash.no_update
            if selected_files:
                for filename in selected_files:
                    part_file_path = os.path.join(config_manager.STL_DIR, filename)
                    try:
                        if os.path.exists(part_file_path):
                            os.remove(part_file_path)
                            logger.info(f"成功刪除工件檔案: {part_file_path}")
                            delete_message += f"File {os.path.basename(part_file_path)} deleted successfully. "
                        else:
                            logger.warning(f"工件檔案不存在: {part_file_path}")
                            delete_message += f"File {os.path.basename(part_file_path)} not found. "
                    except Exception as e:
                        logger.error(f"刪除工件檔案失敗: {e}")
                        delete_message += f"Error deleting file {os.path.basename(part_file_path)}: {str(e)}"


        return delete_message, data_manager.get_part_files(), []

    @app.callback(
        Output('stl-path', 'data'),
        Input('yaml-dropdown', 'value')
    )
    def update_stl_path(selected_yaml):
        """
        更新 STL 檔案路徑
        """
        if selected_yaml is None:
            return None

        with open(selected_yaml, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        stl_path = config.get('Job', {}).get('DesignStlFile', {}).get('FileLink', None)
        # if not os.path.isabs(stl_path):
        #     program_dir = os.path.dirname(os.path.abspath(__file__))
        #     stl_path = os.path.abspath(os.path.join(program_dir, stl_path))
        
        if not os.path.exists(stl_path):
            logger.error(f"STL 檔案不存在: {stl_path}")
            return None

        return stl_path

    @app.callback(
        Output('stl-graph', 'figure'),
        Input('stl-path', 'data')
    )
    def update_stl_figure(stl_path):
        """
        更新 STL 圖表
        """
        if stl_path is None or not os.path.exists(stl_path):
            fig = go.Figure(data=[go.Scatter3d(
                x=[], y=[], z=[],
                mode='markers',
                marker=dict(size=1, color='rgba(0,0,0,0)')
            )])
            fig.update_layout(title=dict(text="Part View", font=dict(family="Arial Black, Gadget, sans-serif")), margin=dict(l=10, r=10, t=40, b=10))
            return fig

        try:
            mesh = trimesh.load(stl_path)
            vertices = mesh.vertices
            faces = mesh.faces
            fig = go.Figure(data=[go.Mesh3d(
                x=vertices[:, 0],
                y=vertices[:, 1],
                z=vertices[:, 2],
                i=faces[:, 0],
                j=faces[:, 1],
                k=faces[:, 2],
                color='#4682b4',
                opacity=0.50
            )])
            fig.update_layout(
                title=dict(
                    text="Part View",
                    font=dict(family="Arial Black, Gadget, sans-serif")
                ),
                scene=dict(
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False),
                    zaxis=dict(visible=False),
                    aspectmode='data',
                    camera=dict(
                    eye=dict(x=2.5, y=1.7, z=1.4)  # 調整視角位置
                )
                ),
                margin=dict(l=10, r=10, t=40, b=10)
            )
            return fig
        except Exception as e:
            logger.error(f"加載 STL 檔案失敗: {e}")
            return go.Figure()

    @app.callback(
        [
            Output('mac-display', 'children'),
            Output('power-display', 'children'),
            Output('psn-display', 'children'),
            Output("sth-link-indicator", "style"),
            Output('ctl-state-indicator', 'style')
        ],
        Input('interval-component', 'n_intervals'),
        State("manual-end-state", "data"),
        prevent_initial_call=True
    )
    def update_displays(n, manual_end_state):
        """
        更新頂部面板顯示的 MAC、Power 和 PSN 資訊 以及燈號狀態
        根據 Manual End 狀態強制燈號為灰色
        """
        latest_data = pd.DataFrame(data_manager.live_data["pdata_list"]).iloc[-1].to_dict()
        mac = f"MAC: {str(latest_data.get('MAC'))}"
        power = f"Power: {(latest_data.get('Power')):.2f} V"
        psn = f"PSN: {int(latest_data.get('Packet Sequence Number'))}"

        if manual_end_state:
            # 如果 Manual End 已按下，強制燈號為灰色
            return mac, power, psn, {"background-color": "grey"}, {"background-color": "grey"}
        
        # 更新 STH Link 燈號
        sth_link_style = {"background-color": "grey"}  # 預設灰色
        # logger.info(f"MQTT Messages: {data_manager.live_data['mqtt_messages']}")
        if data_manager.live_data["mqtt_messages"]:  # 如果 mqtt_messages 不為空
            sth_link_style = {"background-color": "green"}  # 連線狀態

        # 更新 Controller State 燈號
        cnc_list = data_manager.live_data.get("cnc_list", [])
        ctl_state_style = {"background-color": "grey"}
        if cnc_list:  # 如果 cnc_list 不為空
            cnc_df = pd.DataFrame(cnc_list)
            # 檢查 Offset_X, Offset_Y, Offset_Z 是否有任一非零值
            has_non_zero = (cnc_df[["Offset_X", "Offset_Y", "Offset_Z"]] != 0).any().any()
            if has_non_zero:
                ctl_state_style = {"background-color": "green"}  # 連線狀態

        return mac, power, psn, sth_link_style, ctl_state_style

    @app.callback(
        Output('right-panel', 'style'),
        Input('toggle-mqtt', 'n_clicks')
    )
    def toggle_mqtt(n_clicks):
        """
        切換右側 MQTT 訊息面板的顯示狀態
        """
        if n_clicks is None or n_clicks % 2 == 0:
            return {"display": "flex"}
        else:
            return {'display': 'none'}

    @app.callback(
        Output("machining-params", "children"),
        Output("send-holderid-button", "disabled"),
        Input("interval-component", "n_intervals"),
        Input("yaml-dropdown", "value"),
        prevent_initial_call=True,
    )
    def initialize_dashboard(n, yaml_path):
        """
        初始化儀表板，載入加工參數並控制 HolderID 按鈕狀態
        """
        if n is None or yaml_path is None:
            return [], True

        params, config = data_manager.load_yaml_params(yaml_path)
        if not params:
            return [], True

        params_display = {
            "Machine": params.get("machine_name", "N/A"),
            "Controller": params.get("controller", "N/A"),
            "Spindle Speed": params.get("spindle_speed", "N/A"),
            "Feed Rate": params.get("feed_rate", "N/A"),
            "Nc File": params.get("nc_file", "N/A"),
            "Tool Holder": params.get("tool_holder", "N/A"),
            "Tool": params.get('tool', {}).get('type', 'N/A'),
            "Diameter": f"{params.get('tool', {}).get('diameter', 'N/A')} mm",
        }

        params_div = [html.Div([html.P(f"{key}: {value}") for key, value in params_display.items()])]

        return params_div, params.get("tool_holder", "N/A") == "N/A"

    @app.callback(
        Output("status-messages", "children", allow_duplicate=True),
        Input("send-holderid-button", "n_clicks"),
        State("yaml-dropdown", "value"),
        prevent_initial_call=True,
    )
    def send_holder_id(n_clicks, yaml_path):
        """
        處理 HolderID 發送按鈕點擊事件，發送到 STH/MAC 主題
        """
        if n_clicks is None or yaml_path is None:
            return dash.no_update

        params, _ = data_manager.load_yaml_params(yaml_path)
        holder_id = params.get("tool_holder", "N/A")
        if holder_id != "N/A" and mqtt_handler.mqtt_connected:
            mqtt_handler.publish_message("STH/MAC", {"HolderID": holder_id})
            data_manager.load_coefficients()  # 發送 HolderID 後重新載入係數
            return f"Sent HolderID: {holder_id}"
        else:
            logger.warning(f"未發送 HolderID: MQTT 未連線或 HolderID 為 N/A")
            return f"HolderID not sent: MQTT not connected or HolderID is N/A"

    @app.callback(
        Output("status-messages", "children", allow_duplicate=True),
        Input("send-cnc-ip-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def send_cnc_ip(n_clicks):
        """
        設定 Raspberry Pi CNC 網路 IP，並發送 CNC IP 到指定主題
        """
        if not n_clicks:
            return dash.no_update

        try:
            # 設定 Raspberry Pi 網卡
            host_ip = cnc_network_manager.configure_network()
            logger.info(f"CNC 網卡設定完成: {host_ip}")

            if mqtt_handler.mqtt_connected:
                mqtt_handler.publish_message(config_manager.CNC_IP_TOPIC, {"CNC_IP": config_manager.CNC_IP})
                return f"Sent CNC IP: {config_manager.CNC_IP}"
            else:
                logger.warning("未發送 CNC IP: MQTT 未連線")
                return f"CNC IP not sent: MQTT not connected"
            
        except Exception as e:
            logger.error(f"Send CNC IP 失敗: {e}")
            return f"Send CNC IP Error: {e}"

    @app.callback(
        Output("status-messages", "children", allow_duplicate=True),
        Input("connect-cnc-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def send_connect_cnc(n_clicks):
        """
        發送 CNC 連線指令
        """
        if n_clicks is None:
            return dash.no_update

        if mqtt_handler.mqtt_connected:
            mqtt_handler.publish_message(config_manager.CNC_BUTTON_TOPIC, {"Button": "Connect_Button"})
            return "Sent Connect_Button: CNC connecting..."
        else:
            logger.warning("未發送 Connect_Button: MQTT 未連線")
            return "CNC Connect_Button not sent: MQTT not connected"

    @app.callback(
        Output("download-csv-button", "disabled"),
        Input("csv-dropdown", "value"),
    )
    
    def enable_csv_download_button(csv_path):
        """
        根據是否選擇 CSV 檔案啟用或禁用下載按鈕
        """
        return csv_path is None

    @app.callback(
        Output("download-csv", "data"),
        Input("download-csv-button", "n_clicks"),
        State("csv-dropdown", "value"),
        prevent_initial_call=True,
    )
    def download_csv_file(n_clicks, csv_path):
        """
        下載 Order Outcome

        CSV / PDF: 直接下載
        資料夾: 壓縮成 ZIP 後下載
        """
        if n_clicks is None or csv_path is None:
            return dash.no_update

        try:
            selected = job_handler.validate_managed_path(csv_path, config_manager.CSV_DIR,
                    allowed_extensions={".csv", ".pdf"}, allow_folder=True)

            if selected.is_dir(): # 下載資料夾

                def write_zip(buffer):
                    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:

                        for root_dir, dirs, files in os.walk(selected, followlinks=False):
                            current_dir = Path(root_dir)

                            # 避免打包指向其他位置的符號連結
                            dirs[:] = [name for name in dirs if not (current_dir / name).is_symlink()]

                            # 保留空資料夾
                            if not dirs and not files:
                                folder_name = (Path(selected.name) / current_dir.relative_to(selected)
                                ).as_posix().rstrip("/") + "/"

                                zip_file.writestr(folder_name, "")

                            for filename in files:
                                file_path = current_dir / filename

                                if file_path.is_symlink() or not file_path.is_file():
                                    continue

                                archive_name = (Path(selected.name) / file_path.relative_to(selected)
                                ).as_posix()

                                zip_file.write(file_path, arcname=archive_name)

                return dcc.send_bytes(write_zip, filename=f"{selected.name}.zip")

            # 下載一般檔案
            return dcc.send_file(str(selected))

        except Exception as e:
            logger.error(f"下載 Order Outcome 失敗: {e}")
            return dash.no_update
        
    @app.callback(
        [
            Output("torque-graph", "figure"),
            Output("bending-graph", "figure"),
            Output("flute-view-graph", "figure"),
            Output("cnc-view-graph", "figure"),
            Output("mqtt-messages", "children"),
            Output("status-messages", "children"),
            Output("force-indicator", "style"),
            Output("cycle-indicator", "style"),
            Output("csv-dropdown", "options"),
            Output("yaml-dropdown", "options", allow_duplicate=True),
            Output("modal-yaml-dropdown", "options", allow_duplicate=True),
            Output("flute-buffer-store", "data"),  # 輸出回儲存緩衝資料
            Output("flute-indicator", "style"),  # Flute Control Limit 燈號輸出
        ],
        [
            Input("interval-component", "n_intervals"), # 定時更新
            State("flute-buffer-store", "data"),  # 接收緩衝資料
            Input("cycle-status-store", "data")
        ],
        prevent_initial_call=True
    )
    def update_graphs_and_indicators(n, flute_buffer_store_data, cycle_status):
        """
        更新圖表與 MQTT 訊息顯示
        SYNC:
            CNC/STH 時間同步
            啟用 Reference CSV 計算、儲存、讀取與對齊
        DIRECT:
            CNC/STH 獨立顯示
            停用 Reference CSV 相關功能
        """
        # 取得 DATA_SYNC_MODE
        sync_mode = config_manager.DATA_SYNC_MODE
        if sync_mode not in ("SYNC", "DIRECT"):
            sync_mode = "DIRECT"

        # 讀取原始資料
        pdata_df = pd.DataFrame(data_manager.live_data.get("pdata_list", []).copy())
        cnc_df = pd.DataFrame(data_manager.live_data.get("cnc_list", []).copy())

        # 避免尚未收到 MQTT 資料時缺少欄位
        for col in ["TimeInSeconds", "Torque", "BendingX", "BendingY", "CH1", "CH2"]:
            if col not in pdata_df.columns:
                pdata_df[col] = pd.Series(dtype="float64")

        for col in ["TimeInSeconds", "Offset_X", "Offset_Y", "Offset_Z"]:
            if col not in cnc_df.columns:
                cnc_df[col] = pd.Series(dtype="float64")

            cnc_df[col] = pd.to_numeric(cnc_df[col],errors="coerce") 

        # 初始化資料與狀態
        ref_df = None
        current_status = data_manager.live_data.get("cycle_status", "off")
        previous_status = data_manager.previous_cycle_status

        # 依 DATA_SYNC_MODE 決定資料處理方式
        if sync_mode == "DIRECT": # DIRECT：不執行 CNC/STH 時間同步
            sync_df = pdata_df.copy()
            # 直接使用 STH 時間建立圖表 X 軸
            time_seconds = pd.to_numeric(sync_df["TimeInSeconds"], errors="coerce")
            sync_df["Times"] = time_seconds.apply(
                lambda x: (
                    f"{int(x % 60):02d}."
                    f"{int((x % 1) * 1000):03d}"
                    if pd.notna(x) else ""
                )
            )

            # 不讀取、不計算、不儲存 reference.csv
            data_manager.live_data["static_ref_df"] = None

        else: # SYNC：維持原本時間同步功能
            cnc_time = pd.to_numeric(cnc_df["TimeInSeconds"], errors="coerce")

            has_cnc_data = (
                not cnc_df.empty
                and cnc_time.notna().any()
                and cnc_time.max() > 0
            )

            if has_cnc_data and not pdata_df.empty:

                # CNC/STH 時間同步
                sync_df = data_manager.time_sync(
                    pdata_df, cnc_df
                )

                # Reference CSV 功能
                if config_manager.SAVE_REFERENCE_CSV: # 模式 1 即時計算並儲存 csv
                    if current_status == "on":
                        if previous_status == "off":  # 檢查是否「剛從 OFF 轉變為 ON」
                            data_manager.reset_ref_csv()
                        try: # 執行計算與儲存 (無論是剛重置還是加工中)
                            ucl_df = data_manager.calculate_ucl(sync_df) # 計算 UCL
                            data_manager.save_ref_csv(ucl_df) # 儲存到 CSV
                        except Exception as e:
                            # logger.warning(f"計算 UCL 或儲存 CSV 時發生錯誤: {e}")
                            pass
                    elif current_status == "off" and previous_status == "on": # 檢查是否「剛從 ON 轉變為 OFF」
                        try:
                            data_manager.shift_ucl_data() # 計算 Offset Distance、將 UCL 往前平移、計算 Flute_UCL
                        except Exception as e:
                            logger.error(f"處理 reference.csv 時發生錯誤: {e}")
                    data_manager.live_data["static_ref_df"] = None  # 清除快取，避免模式切換誤用
                else: # 模式 2 載入 csv 後對齊座標
                    sync_df, ref_df = data_manager.sync_ref_ucl(sync_df)
                        
            else: # SYNC 模式下，尚無可同步的 CNC 資料
                sync_df = pdata_df.copy()
                time_seconds = pd.to_numeric(sync_df["TimeInSeconds"], errors="coerce")
                sync_df["Times"] = time_seconds.apply(
                    lambda x: (
                        f"{int(x % 60):02d}."
                        f"{int((x % 1) * 1000):03d}"
                        if pd.notna(x) else ""
                    )
                )

        # 更新 Cycle 狀態
        data_manager.previous_cycle_status = current_status

        # 最新 Torque / Bending 數值
        latest_torque = sync_df["Torque"].iloc[-1] if not sync_df["Torque"].empty else 0.0
        latest_bending = sync_df["BendingX"].iloc[-1] if not sync_df["BendingX"].empty else 0.0

        # CNC 路徑獨立取得
        cnc_path_data = cnc_df[["Offset_X", "Offset_Y", "Offset_Z"]].copy()

        # 檢查管制界線是否全為 0
        torque_ucl_non_zero = any(ucl["value"] != 0 for ucl in config_manager.TORQUE_UCL)
        bending_ucl_non_zero = any(ucl["value"] != 0 for ucl in config_manager.BENDING_UCL)

        # 判斷載入模式加入 reference.csv UCL 與越線判斷
        has_ref_ucl = False
        ref_ucl_columns = []
        ref_exceeded_sigma = {col: None for col in data_manager.columns_with_ucl}  # 記錄最高超限的 sigma
        sigma_colors = {config_manager.UCL_SIGMA[0]: 'orange', config_manager.UCL_SIGMA[-1]: 'red'}  # 3σ: 橘線, 5σ: 紅線


        if (sync_mode == "SYNC" and not config_manager.SAVE_REFERENCE_CSV):
            ref_cols_to_check = [col for col in data_manager.dynamic_columns if col in sync_df.columns and sync_df[col].notna().any()]
            ref_ucl_columns = ref_cols_to_check
            has_ref_ucl = len(ref_ucl_columns) > 0

            # 檢查 reference.csv UCL 是否被超越
            for col in ref_ucl_columns:
                sigma = int(col.split('_')[-1])
                ref_vals = sync_df[col]
                if 'Torque' in col and (sync_df["Torque"] > ref_vals).any():
                    ref_exceeded_sigma['Torque'] = max(ref_exceeded_sigma['Torque'] or 0, sigma)
                elif 'BendingX' in col and (sync_df["BendingX"].abs() > ref_vals).any():
                    ref_exceeded_sigma['BendingX'] = max(ref_exceeded_sigma['BendingX'] or 0, sigma)

        # 計算 Torque 標題顏色
        torque_title_color = "black"
        has_valid_torque_data = (sync_df["Torque"] != 0.0).any()
        if has_valid_torque_data and torque_ucl_non_zero:
            torque_val = float(latest_torque)
            for ucl in config_manager.TORQUE_UCL:
                if ucl["color"] != "green" and torque_val >= ucl["value"]:
                    torque_title_color = ucl["color"]
                    break

        # reference.csv UCL 超限 
        # if ref_exceeded_sigma['Torque']:
        #     if ref_exceeded_sigma['Torque'] == config.UCL_SIGMA[-1]:
        #         torque_title_color = "red"
        #     elif ref_exceeded_sigma['Torque'] == config.UCL_SIGMA[0] and torque_title_color == "black":
        #         torque_title_color = "orange"
        
        # 計算 Bending 標題顏色與 Force 燈號
        bending_title_color = "black"
        if bending_ucl_non_zero:
            for ucl in config_manager.BENDING_UCL:
                if latest_bending >= abs(ucl["value"]):
                    bending_title_color = ucl["color"]
                    break

        # reference.csv UCL 超限 
        # if ref_exceeded_sigma['BendingX']:
        #     if ref_exceeded_sigma['BendingX'] == config.UCL_SIGMA[-1]:
        #         bending_title_color = "red"
        #     elif ref_exceeded_sigma['BendingX'] == config.UCL_SIGMA[0] and bending_title_color == "black":
        #         bending_title_color = "orange"

        # Force 燈號
        force_indicator_style = {"background-color": "grey"}
        if (sync_df["BendingX"] != 0).any() or has_valid_torque_data:
            force_indicator_style = {"background-color": "green"}

        # 即時 UCL 超限
        instant_exceeded = False
        if has_valid_torque_data and torque_ucl_non_zero:
            torque_val = float(latest_torque)
            for ucl in config_manager.TORQUE_UCL:
                if ucl["color"] != "green" and torque_val >= ucl["value"]:
                    instant_exceeded = True
                    break
        if bending_ucl_non_zero and latest_bending >= abs(config_manager.BENDING_UCL[0]["value"]):
            instant_exceeded = True

        # 歷史 UCL 超限等級
        ref_max_sigma = max(
            ref_exceeded_sigma['Torque'] or 0,
            ref_exceeded_sigma['BendingX'] or 0
        )

        if instant_exceeded or ref_max_sigma == config_manager.UCL_SIGMA[-1]:
            force_indicator_style = {"background-color": "red"}
        elif ref_max_sigma == config_manager.UCL_SIGMA[0]:
            force_indicator_style = {"background-color": "orange"}

        # Torque 圖表
        torque_figure = go.Figure(
            data=[
                go.Scatter(
                    x=sync_df["Times"],
                    y=sync_df["Torque"],
                    mode="lines+markers",
                    line=dict(color="blue", width=2),
                    marker=dict(size=1),
                    name="Torque",
                    showlegend=False,
                ),
            ]
        )

        # 管制界線與參考線
        for ucl in config_manager.TORQUE_UCL:
            if ucl["value"] != 0:
                if ucl["color"] == "orange":
                    name = f"Warn ({ucl['value']})"
                elif ucl["color"] == "red":
                    name = f"UCL ({ucl['value']})"
                else:  # green
                    name = f"Ref ({ucl['value']})"
                torque_figure.add_trace(
                    go.Scatter(
                        x=[sync_df["Times"].iloc[0], sync_df["Times"].iloc[-1]],
                        y=[ucl["value"], ucl["value"]],
                        mode="lines",
                        line=dict(color=ucl["color"], width=2, dash="dot"),
                        name=name,
                    )
                )
        # reference.csv UCL
        if has_ref_ucl:
            for col in ref_ucl_columns:
                if 'Torque' in col:
                    sigma = int(col.split('_')[-1])
                    color = sigma_colors.get(sigma, 'red')
                    torque_figure.add_trace(
                        go.Scatter(
                            x=sync_df["Times"],
                            y=sync_df[col],
                            mode="lines",
                            line=dict(color=color, width=2, dash="dashdot"),
                            name=f"{sigma}σ UCL",
                            # hovertemplate="UCL: %{y:.3f}<extra></extra>"
                        )
                    )
        # 計算 Torque 最大 UCL
        torque_max_ucl = 0.0
        if config_manager.TORQUE_UCL and config_manager.TORQUE_UCL[0]["value"] > 0:
            torque_max_ucl = config_manager.TORQUE_UCL[0]["value"]

        if has_ref_ucl:
            for col in ref_ucl_columns:
                if 'Torque' in col and sync_df[col].notna().any():
                    ref_val = sync_df[col].max()
                    torque_max_ucl = max(torque_max_ucl, ref_val)

        # Torque 圖表 Y 軸範圍
        torque_yaxis = dict(title="Torque (Nm)")
        if torque_max_ucl > 0:
            torque_yaxis["range"] = [0, torque_max_ucl * 1.5]

        torque_figure.update_layout(
            title=dict(
                text="Torque",
                font=dict( 
                    family="Arial Black, Gadget, sans-serif",
                    color=torque_title_color
                )
            ),
            xaxis=dict(title="Time (s)", fixedrange=True, automargin=True, range=[0, config_manager.PDATA_LENGTH]),
            yaxis=torque_yaxis,
            legend=dict(orientation="h", yanchor="bottom", y=1, xanchor="right", x=1),
            showlegend=True,
            margin=dict(l=10, r=10, t=40, b=10)
        )

        # Bending 圖表
        bending_figure = go.Figure(
            data=[go.Scatter(
                x=sync_df["Times"],
                y=sync_df["BendingX"],
                mode="lines+markers",
                line=dict(color="green", width=2),
                marker=dict(size=1),
                name="Bending",
                showlegend=False
                )]
        )

        # 管制界線（UCL 和 LCL）
        for ucl in config_manager.BENDING_UCL:
            if ucl["value"] != 0:
                for sign, label in [(1, "UCL"), (-1, "LCL")]:
                    value = sign * ucl["value"]
                    bending_figure.add_trace(
                        go.Scatter(
                            x=[sync_df["Times"].iloc[0], sync_df["Times"].iloc[-1]],
                            y=[value, value],
                            mode="lines",
                            line=dict(color=ucl["color"], width=2, dash="dot"),
                            name=f"{label} ({value})",
                        )
                    )

        # reference.csv UCL
        if has_ref_ucl:
            for col in ref_ucl_columns:
                if 'BendingX' in col:
                    sigma = int(col.split('_')[-1])
                    color = sigma_colors.get(sigma, 'red')
                    ref = sync_df[col]
                    if ref.notna().any():
                        bending_figure.add_trace(go.Scatter(
                            x=sync_df["Times"], y=ref,
                            mode="lines", line=dict(color=color, width=2, dash="dashdot"),
                            name=f"±{sigma}σ UCL"
                        ))
                        bending_figure.add_trace(go.Scatter(
                            x=sync_df["Times"], y=-ref,
                            mode="lines", line=dict(color=color, width=2, dash="dashdot"),
                            showlegend=False
                        ))

        # 計算 Bending 最大 UCL
        bending_max_ucl = 0.0
        if config_manager.BENDING_UCL and config_manager.BENDING_UCL[0]["value"] > 0:
            bending_max_ucl = config_manager.BENDING_UCL[0]["value"]

        if has_ref_ucl:
            for col in ref_ucl_columns:
                if 'BendingX' in col and sync_df[col].notna().any():
                    ref_val = sync_df[col].max()
                    bending_max_ucl = max(bending_max_ucl, ref_val)

        # Bending 圖表 Y 軸範圍
        bending_yaxis = dict(title="Bending (N)")
        if bending_max_ucl > 0:
            bending_yaxis["range"] = [-bending_max_ucl * 1.5, bending_max_ucl * 1.5]
    
        bending_figure.update_layout(
            title=dict(
                text="Bending",
                font=dict(family="Arial Black, Gadget, sans-serif", color=bending_title_color)
            ),
            xaxis=dict(title="Time (s)", fixedrange=True, automargin=True, range=[0, config_manager.PDATA_LENGTH]),
            yaxis=bending_yaxis,
            legend=dict(orientation="h", yanchor="bottom", y=1, xanchor="right", x=1),
            showlegend=True,
            margin=dict(l=10, r=10, t=40, b=10)
        )

        # Flute View 圖表
        raw_tail = sync_df.tail(config_manager.FLUTE_VIEW_LENGTH)
        flute_data = raw_tail.dropna(subset=["CH1", "CH2"]).copy()
        distances = np.sqrt(flute_data["CH1"]**2 + flute_data["CH2"]**2)  # 計算每點距離
        
        flute_buffer_df = (
            pd.DataFrame(flute_buffer_store_data)
            if flute_buffer_store_data
            else pd.DataFrame({"CH1": pd.Series(dtype="float"), "CH2": pd.Series(dtype="float"), "Distance": pd.Series(dtype="float")})
        )
        # 讀取 reference.csv Flute_UCL_{sigma}（常數載入，不需對齊）
        ref_flute_ucl_dict = {}
        if (sync_mode == "SYNC" and not config_manager.SAVE_REFERENCE_CSV):
            ref_flute_ucl_dict = data_manager.load_ref_flute_ucl()
        

        # UCL 數值
        config_flute_ucl = config_manager.FLUTE_UCL[0]["value"] if config_manager.FLUTE_UCL and config_manager.FLUTE_UCL[0]["value"] > 0 else 0
        if config_flute_ucl > 0:
            final_ucl_1x = config_flute_ucl
            final_ucl_2x = config_flute_ucl * 2

        else:  # 改用 reference.csv 的值 (對應各 sigma)
            sigma_1 = config_manager.UCL_SIGMA[0]
            sigma_2 = config_manager.UCL_SIGMA[1] if len(config_manager.UCL_SIGMA) > 1 else sigma_1
            ucl_sigma_1 = ref_flute_ucl_dict.get(sigma_1)
            ucl_sigma_2 = ref_flute_ucl_dict.get(sigma_2)

            final_ucl_1x = float(ucl_sigma_1) if ucl_sigma_1 and ucl_sigma_1 > 0 else 0.0
            final_ucl_2x = float(ucl_sigma_2) if ucl_sigma_2 and ucl_sigma_2 > 0 else 0.0

        has_valid_ucl = final_ucl_1x > 0

        # === 緩衝區邏輯（使用 final_ucl_1x）===
        if has_valid_ucl:
            exceed_mask = distances > final_ucl_1x
            if exceed_mask.any():
                flute_data_exceed = flute_data[exceed_mask][["CH1", "CH2"]].copy()
                flute_data_exceed["Distance"] = distances[exceed_mask]
                flute_buffer_df = pd.concat([flute_buffer_df, flute_data_exceed], ignore_index=True)
                flute_buffer_df = flute_buffer_df.drop_duplicates(subset=["CH1", "CH2"], keep="last")
                if len(flute_buffer_df) > config_manager.FLUTE_VIEW_LENGTH // 2:
                    flute_buffer_df = flute_buffer_df.sort_values(by="Distance", ascending=False).head(
                        config_manager.FLUTE_VIEW_LENGTH // 2
                    )

        flute_buffer_output = flute_buffer_df.to_dict("records")

        # 計算 Flute View 點的顏色
        plot_data = pd.concat([flute_data[["CH1", "CH2"]], flute_buffer_df[["CH1", "CH2"]]], ignore_index=True).drop_duplicates()
        plot_distances = np.sqrt(plot_data["CH1"]**2 + plot_data["CH2"]**2)

        colors = ["blue"] * len(plot_data)
        if has_valid_ucl:
            colors = np.where(plot_distances > final_ucl_2x, "red",
                              np.where(plot_distances > final_ucl_1x, "orange", "blue"))
        
        # 繪製散點
        flute_traces = [go.Scatter(
            x=plot_data["CH1"], y=plot_data["CH2"],
            mode="markers", marker=dict(size=6, color=colors),
            name="Points", showlegend=False, hovertemplate="%{x:.3f}, %{y:.3f}<extra></extra>"
        )]

        # 繪製 UCL 圓圈（根據來源畫不同樣式）
        theta = np.linspace(0, 2 * np.pi, 100)
        if config_flute_ucl > 0: # 來自 config
            for r, color, name in [(final_ucl_1x, "orange", "UCL"), (final_ucl_2x, "red", "2×UCL")]:
                if r > 0:
                    x = r * np.cos(theta)
                    y = r * np.sin(theta)
                    flute_traces.append(go.Scatter(
                        x=x, y=y, mode="lines",
                        line=dict(color=color, width=2, dash="dot"),
                        name=name,
                        hovertemplate="%{x:.3f}, %{y:.3f}<extra></extra>"
                    ))
        elif ref_flute_ucl_dict: # 來自 reference.csv
            for sigma, val in sorted(ref_flute_ucl_dict.items()):
                color = "red" if sigma >= 5 else "orange"
                x = val * np.cos(theta)
                y = val * np.sin(theta)
                flute_traces.append(go.Scatter(
                    x=x, y=y, mode="lines",
                    line=dict(color=color, width=2, dash="dashdot"),
                    name=f"{sigma}σ UCL",
                    hovertemplate="%{x:.3f}, %{y:.3f}<extra></extra>"
                ))
        
        flute_figure = go.Figure(data=flute_traces)

        # 初始化軸設定 (保持 x, y 比例一致)
        flute_xaxis = dict()
        flute_yaxis = dict(scaleanchor="x", scaleratio=1)
        limit_range = 0.1 # 預設值
        if has_valid_ucl: # 有管制線
            limit_range = final_ucl_2x * 1.5 
            flute_xaxis.update(dict(dtick=final_ucl_1x, range=[-limit_range, limit_range]))
            flute_yaxis.update(dict(dtick=final_ucl_1x, range=[-limit_range, limit_range]))
        
        else: # 無管制線
            max_data_val = 0.0 # 計算資料最大範圍
            if not plot_data.empty:
                max_x = plot_data["CH1"].abs().max()
                max_y = plot_data["CH2"].abs().max()
                max_data_val = max(max_x, max_y)
            
            if max_data_val == 0:
                max_data_val = 0.01 # 給一個極小的預設值避免為 0

            # 設定範圍為資料的 5 倍
            limit_range = max_data_val * 5.0
            
            #手動計算刻度間距範圍的一半
            # 這樣強迫 Plotly 在 X 和 Y 使用相同的間隔畫線
            tick_step = limit_range / 2.0 
            flute_xaxis.update(dict(dtick=tick_step, range=[-limit_range, limit_range]))
            flute_yaxis.update(dict(dtick=tick_step, range=[-limit_range, limit_range]))

        # 2. 將設定好的字典傳入 update_layout
        flute_figure.update_layout(
            title=dict(text="Flute View", font=dict(family="Arial Black, Gadget, sans-serif")),
            xaxis=flute_xaxis,     # 使用上面動態生成的字典
            yaxis=flute_yaxis,     # 使用上面動態生成的字典
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=40, b=10),
        )

        # Flute Control Limit 燈號
        flute_indicator_style = {"background-color": "grey"}  # 預設為灰色
        has_valid_flute_data = (sync_df["CH1"] != 0.0).any() or (sync_df["CH2"] != 0.0).any()
        if has_valid_flute_data:
            flute_indicator_style = {"background-color": "green"}  # 有資料時預設為綠色正常狀態
            if not flute_buffer_df.empty:
                exceed_distances = flute_buffer_df["Distance"]
                ucl_count = sum(exceed_distances > final_ucl_1x)
                second_ucl_count = sum(exceed_distances > final_ucl_2x)
                total_count = len(flute_buffer_df)
                if total_count > 0:
                    if second_ucl_count / total_count >= 0.8:
                        flute_indicator_style = {"background-color": "red"}
                    elif ucl_count / total_count >= 0.2:
                        flute_indicator_style = {"background-color": "orange"}

        
        # CNC View 圖表
        cnc_path_figure = go.Figure()
        if not cnc_path_data.empty:
            cnc_path_figure.add_trace(
                go.Scatter3d(
                    x=cnc_path_data["Offset_X"],
                    y=cnc_path_data["Offset_Y"],
                    z=cnc_path_data["Offset_Z"],
                    mode="lines+markers",
                    line=dict(color="blue", width=2),
                    marker=dict(size=3, color="blue"),
                    name="",
                )
            )
            latest_point = cnc_path_data.iloc[-1] if not cnc_path_data.empty else {"Offset_X": 0, "Offset_Y": 0, "Offset_Z": 0}
            cnc_path_figure.add_trace(
                go.Scatter3d(
                    x=[latest_point["Offset_X"]],
                    y=[latest_point["Offset_Y"]],
                    z=[latest_point["Offset_Z"]],
                    mode="markers",
                    marker=dict(size=6, color="red"),
                    name="",
                )
            )
        cnc_path_figure.update_layout(
            title=dict(
                text="CNC View (mm)",
                font=dict(family="Arial Black, Gadget, sans-serif")
            ),
            scene=dict(
                xaxis_title="X",
                yaxis_title="Y",
                zaxis_title="Z",
                camera=dict(eye=dict(x=1, y=-2., z=0.5)),  # 設定 CNC 視角與 STL 相同
                xaxis=dict(backgroundcolor="#FFFFFF"),
                yaxis=dict(backgroundcolor="#FFFFFF", gridcolor="#FFFFFF"),
                zaxis=dict(gridcolor="#FFFFFF"),
            ),
            showlegend=False,
            margin=dict(l=10, r=10, t=40, b=10)
        )

        # MQTT 訊息顯示
        if not data_manager.live_data["mqtt_messages"]:
            mqtt_display = [
                
            ]
        else:
            latest_msg = data_manager.live_data["mqtt_messages"][-1]
            mqtt_display = [
                html.Div([
                    html.P(f"MAC: {latest_msg.get('MAC', 'N/A')}"),
                    html.P(f"Power: {latest_msg.get('Power', 0.0):.2f} V"),
                    html.P(f"Temperature: {latest_msg.get('Temperature', 0)} °C"),
                    html.P(f"Packet Sequence Number: {latest_msg.get('Packet Sequence Number', 'N/A')}"),
                    html.P(f"RSSI: {latest_msg.get('RSSI', 'N/A')} dBm"),
                    html.P(f"TTOLP: {latest_msg.get('TTOLP', 'N/A')}"),
                    html.P("Torque:[\n" + "\n".join(f"      {v:.8f}" for v in latest_msg.get("Torque", [])) + "\n]", style={'whiteSpace': 'pre'}),
                    html.P("Bending:[\n" + "\n".join(f"      {v:.8f}" for v in latest_msg.get("Bending_X", [])) + "\n]", style={'whiteSpace': 'pre'}),
                    # html.P("Bending_Y (N):[\n" + "\n".join(f"      {v:.8f}" for v in latest_msg.get("Bending_Y", [])) + "\n]", style={'whiteSpace': 'pre'}),
                    html.P("CH1:[\n" + "\n".join(f"      {v:.8f}" for v in latest_msg.get("CH1", [])) + "\n]", style={'whiteSpace': 'pre'}),
                    html.P("CH2:[\n" + "\n".join(f"      {v:.8f}" for v in latest_msg.get("CH2", [])) + "\n]", style={'whiteSpace': 'pre'}),
                    html.P(f"timetag: {datetime.strptime(latest_msg.get('timetag', ''), '%Y-%m-%d %H:%M:%S.%f').strftime('%H:%M:%S.%f')[:-3] if latest_msg.get('timetag', '') else 'N/A'}"),
                ]),
            ]
        status_messages = [
            html.Div([
                html.P(f"Web ver.: {config_manager.WEB_VERSION}"),
                html.P(f"holder_main ver.: {config_manager.HOLDE_MAIN_VERSION}")
            ])
        ]

        # 更新 Cycle 燈號
        cycle_style = {"background-color": "green" if cycle_status == "on" else "grey"}

        # 更新 CSV 和 YAML 選項
        csv_options = data_manager.get_csv_files()
        yaml_options = data_manager.get_yaml_files()

        return (
            torque_figure,
            bending_figure,
            flute_figure,
            cnc_path_figure,
            mqtt_display,
            status_messages,
            force_indicator_style,
            cycle_style,
            csv_options,
            yaml_options,
            yaml_options,
            flute_buffer_output,
            flute_indicator_style,
        )
    
    @app.callback(
        Output("status-messages", "children", allow_duplicate=True),
        Input("yaml-dropdown", "value"),
        prevent_initial_call=True
    )
    def on_yaml_selected(selected_yaml):
        """
        處理使用者選擇 YAML 檔案事件
        """
        if not selected_yaml:
            return dash.no_update
        abs_yaml = os.path.abspath(selected_yaml)
        data_manager.live_data["selected_yaml"] = abs_yaml
        logger.info(f"使用者選擇了 YAML 檔案: {abs_yaml}")
        return html.Div(f"{os.path.basename(abs_yaml)} chosen")

    @app.callback(
        Output("status-messages", "children", allow_duplicate=True),
        Input("csv-dropdown", "value"),
        prevent_initial_call=True
    )
    def on_csv_selected(selected_csv):
        """
        處理使用者選擇 CSV 檔案事件
        """
        if not selected_csv:
            return dash.no_update
        abs_csv = os.path.abspath(selected_csv)
        data_manager.live_data["selected_csv"] = abs_csv
        logger.info(f"使用者選擇了 CSV 檔案: {abs_csv}")
        return html.Div(f"{os.path.basename(abs_csv)} chosen")

    # ===== 報告產生：路徑自動選取策略 =====
    def _select_paths_for_report():
        """
        依優先序自動選 YAML / CSV / STL / 係數，並決定輸出檔名。
        優先序（CSV/YAML）：
        1) 先用 UI/邏輯已選（data_manager.live_data）
        2) 檔名含 tmac 優先
        3) 依 mtime 最新
        """
        # 基本目錄
        yaml_dir = config_manager.YAML_DIR
        csv_dir  = config_manager.CSV_DIR
        coeff    = config_manager.COEFF_PATH

        # 取當前 HolderID（由 YAML/作業流或 MQTT 更新）
        tmac = data_manager.live_data.get("tmac")  # 可能是 "N/A" 或 None
        tmac_str = str(tmac) if tmac else ""

        # 1) YAML：若 UI/邏輯已有選擇 → 最高優先；否則從 yaml_dir 挑（先嘗試含 tmac，否則最新）
        selected_yaml = None
        try:
            # 1-1 使用者已選
            chosen_yaml = (data_manager.live_data.get("selected_yaml") or "").strip()
            if chosen_yaml:
                sel_path = os.path.abspath(chosen_yaml)
                if os.path.exists(sel_path):
                    selected_yaml = sel_path

            # 1-2 沒有使用者選擇時，再走 tmac → 最新
            if not selected_yaml:
                yaml_files = [os.path.join(yaml_dir, f) for f in os.listdir(yaml_dir)
                            if f.lower().endswith((".yml", ".yaml"))]
                if tmac_str:
                    yaml_tmac = [p for p in yaml_files if tmac_str in os.path.basename(p)]
                else:
                    yaml_tmac = []
                candidates = yaml_tmac if yaml_tmac else yaml_files
                selected_yaml = max(candidates, key=lambda p: os.path.getmtime(p)) if candidates else None
        except Exception:
            selected_yaml = None

        # 2) CSV：若 UI/邏輯已有選擇 → 最高優先；否則從 csv_dir 挑（先嘗試含 tmac，否則最新）
        selected_csv = None
        try:
            # 2-1 使用者已選
            chosen_csv = (data_manager.live_data.get("selected_csv") or "").strip()
            if chosen_csv:
                sel_path = os.path.abspath(chosen_csv)
                if os.path.exists(sel_path):
                    selected_csv = sel_path

            # 2-2 沒有使用者選擇時，再走 tmac → 最新
            if not selected_csv:
                csv_files = [os.path.join(csv_dir, f) for f in os.listdir(csv_dir)
                            if f.lower().endswith(".csv")]
                if tmac_str:
                    csv_tmac = [p for p in csv_files if tmac_str in os.path.basename(p)]
                else:
                    csv_tmac = []
                candidates = csv_tmac if csv_tmac else csv_files
                selected_csv = max(candidates, key=lambda p: os.path.getmtime(p)) if candidates else None
        except Exception:
            selected_csv = None

        # 3) STL：優先從 YAML 的 Job.DesignStlFile.FileLink 解析；抓不到就不放
        stl_path = None
        try:
            if selected_yaml:
                with open(selected_yaml, "r", encoding="utf-8") as f:
                    yobj = yaml.safe_load(f)
                stl_path = yobj.get("Job", {}).get("DesignStlFile", {}).get("FileLink")
                if stl_path and (not os.path.isabs(stl_path)):
                    program_dir = os.path.dirname(os.path.abspath(__file__))
                    stl_path = os.path.abspath(os.path.join(program_dir, stl_path))
                if not stl_path or not os.path.exists(stl_path):
                    stl_path = None
        except Exception:
            stl_path = None

        # 輸出檔名（csv 檔名 + _report.pdf / .md），若沒有 csv 就用 YAML 名稱替代
        base_for_name = os.path.splitext(os.path.basename(selected_csv or selected_yaml or f"report_{int(time.time())}.csv"))[0]

        # 建立以 base_for_name 命名的資料夾（放中間產物）
        report_dir = os.path.join(csv_dir, base_for_name)
        os.makedirs(report_dir, exist_ok=True)

        out_md     = os.path.join(report_dir, f"{base_for_name}_report.md")
        temp_html  = os.path.join(report_dir, f"{base_for_name}_temp.html")
        out_pdf    = os.path.join(csv_dir,  f"{base_for_name}_report.pdf")  # 最終 PDF 放在 CSV_DIR 根層

        return {
            "yaml": selected_yaml,
            "csv": selected_csv,
            "coeff": coeff,
            "stl": stl_path,
            "out_md": out_md,
            "out_pdf": out_pdf,
            "temp_html": temp_html
        }

    def _run_make_report():
        """
        執行 test.generate_machining_report；回傳(成功:bool, msg:str, 產出PDF路徑)
        """
        sel = _select_paths_for_report()
        if not sel["yaml"] or not sel["csv"]:
            return False, f"選檔失敗：yaml={sel['yaml']} csv={sel['csv']}", None

        try:
            generate_machining_report(
                yaml_path=sel["yaml"],
                coeff_file=sel["coeff"],
                sensor_file=sel["csv"],
                config_path=config_manager.CONFIG_PATH,
                stl_path=sel["stl"],
                flute_img_path=None,           # 交給 report.py 自動從 CSV 生成
                output_md_path=sel["out_md"],
                output_pdf_path=sel["out_pdf"],
                temp_html_path=sel["temp_html"]
            )
            return True, f"報告已產生：{sel['out_pdf']}", sel["out_pdf"]
        except Exception as e:
            logger.error(f"產報告失敗：{e}")
            return False, f"產報告失敗：{e}", None

    # 手動：按鈕觸發報告生成
    @app.callback(
        Input("btn-generate-report", "n_clicks"),
        running=[
            (Output("btn-generate-report", "disabled"), True, False),
            (Output("report-loading-modal", "style"),
                {"display": "flex"},
                {"display": "none"})
        ],
        prevent_initial_call=True
    )
    def on_click_generate_report(n_clicks):
        """
        手動生成加工報告，並顯示執行狀態
        """
        logger.info("使用者按下 [產生報告] 按鈕")
        try:
            ok, msg, pdf_path = _run_make_report()
            # if ok:
            #     # status_message = f"報告生成完畢：{os.path.basename(pdf_path)}" if pdf_path else "報告生成完畢"
            #     # logger.info(status_message)
            # else:
            #     status_message = f"報告生成失敗：{msg}"
            #     logger.error(status_message)

        except Exception as e:
            status_message = f"報告生成失敗：{e}"
            logger.exception(status_message)

    # 自動：偵測 Cycle End（on -> off）觸發報告
    @app.callback(
        Output("mqtt-messages", "children", allow_duplicate=True),
        Input("interval-component", "n_intervals"),
        prevent_initial_call=True
    )
    def on_cycle_end_auto_report(_n):
        global _prev_cycle_status
        # 從 live_data 讀當前狀態（MQTT handler 會更新到這）
        curr = data_manager.live_data.get("cycle_status", "off")
        # 偵測到 "on" -> "off" 的 falling edge
        if _prev_cycle_status == "on" and curr == "off" and config_manager.AUTO_REPORT_ON_CYCLE_END:
            ok, msg, pdf_path = _run_make_report()
            _prev_cycle_status = curr
            # return html.Div([html.H2("Messages"), html.P(f"[Cycle End] {msg}")])
            return dash.no_update
        _prev_cycle_status = curr
        return dash.no_update

    @app.callback(
        [
            Output("delete-files-modal", "style"),
            Output("delete-yaml-checklist", "options"),
            Output("delete-csv-checklist", "options"),
            Output("delete-yaml-checklist", "value"),
            Output("delete-csv-checklist", "value"),
            Output("delete-files-message", "children"),
            Output("csv-dropdown", "options", allow_duplicate=True),
            Output("csv-dropdown", "value")
        ],
        [
            Input("delete-files-button", "n_clicks"),
            Input("delete-files-confirm-button", "n_clicks"),
            Input("delete-files-cancel-button", "n_clicks")
        ],
        [
            State("delete-yaml-checklist", "value"),
            State("delete-csv-checklist", "value"),
            State("delete-files-modal", "style"),
            State("csv-dropdown", "value")
        ],
        prevent_initial_call=True
    )
    def toggle_delete_files_modal_and_handle_delete(button_clicks, confirm_clicks, cancel_clicks, 
                                                    selected_yaml_files, selected_csv_files, 
                                                    current_style, current_csv_value):
        """
        切換刪除檔案模態視窗並處理檔案刪除
        """
        trigger_id = dash.ctx.triggered_id

        modal_style = current_style or {"display": "none"}
        messages = []
        reset_csv_value = dash.no_update

        # 開啟視窗
        if trigger_id == "delete-files-button":
            modal_style = {'display': 'flex', 'justify-content': 'center', 'align-items': 'center', 'z-index': '10000'}
            
        elif trigger_id == "delete-files-confirm-button":

            # 刪除 YAML
            for yaml_path in selected_yaml_files or []:
                try:
                    target = job_handler.validate_managed_path(yaml_path, config_manager.YAML_DIR, allowed_extensions={".yaml", ".yml"})

                    target.unlink()
                    logger.info(f"成功刪除 YAML: {target}")
                    messages.append(f"YAML {target.name} deleted successfully.")

                except Exception as e:
                    logger.error(f"刪除 YAML 失敗: {e}")
                    messages.append(f"Error deleting YAML: {e}")
                
            # 刪除 CSV、PDF 或資料夾
            for csv_path in selected_csv_files or []:
                try:
                    target = job_handler.validate_managed_path(csv_path, config_manager.CSV_DIR,allowed_extensions={".csv", ".pdf"},
                        allow_folder=True)
                    
                    # 判斷是不是目前選中的 Order Outcome
                    if current_csv_value:
                        current_selected = Path(current_csv_value).resolve()

                        if current_selected == target:
                            reset_csv_value = None

                    # 資料夾
                    if target.is_dir():
                        shutil.rmtree(target)

                        logger.info(f"成功刪除資料夾: {target}")

                        messages.append(f"Folder {target.name} deleted successfully.")

                    # 一般檔案
                    else:
                        target.unlink()
                        logger.info(f"成功刪除檔案: {target}")
                        messages.append(f"File {target.name} deleted successfully.")

                except Exception as e:
                    logger.error(f"刪除 Order Outcome 失敗: {e}")

                    messages.append(f"Error deleting {Path(csv_path).name}: {e}")

            if not messages:
                messages.append("No files selected for deletion.")
                modal_style = {'display': 'flex', 'justify-content': 'center', 'align-items': 'center', 'z-index': '10000'}

        # 取消
        elif trigger_id == "delete-files-cancel-button":
            modal_style = {'display': 'none'}

        yaml_options = data_manager.get_yaml_files()
        # 所有 Order Outcome，提供給下載下拉選單
        csv_options = data_manager.get_csv_files()

        # 可以刪除的 Order Outcome，提供給 Delete Orders
        delete_csv_options = data_manager.get_deletable_csv_files()

        return (
            modal_style,
            yaml_options,
            delete_csv_options,  # Delete Orders 清單
            [],
            [],
            " ".join(messages),
            csv_options,
            reset_csv_value
        )

    @app.callback(
    
        Output("start-button", "disabled"),
        Output("end-button", "disabled"),
        Output("send-cnc-ip-button", "disabled"),
        Output("connect-cnc-button", "disabled"),
        Output("manual-end-state", "data"),

        Input("start-button", "n_clicks"),
        Input("end-button", "n_clicks"),
        Input("cycle-status-store", "data"),
       
        prevent_initial_call=True
    )
    def handle_button_states(start_clicks, end_clicks, cycle_status):
        """
        統一處理手動點擊和自動狀態同步
        """    
        # 狀態 1：運行中 (Running)
        # 禁用：Start, Send CNC IP, Connect | 啟用：End | Manual End 狀態：False
        running_state_ui = (True, False, True, True, False)
        
        # 狀態 2：已停止 (Stopped)
        # 啟用：Start, Send CNC IP, Connect | 禁用：End | Manual End 狀態：True
        stopped_state_ui = (False, True, False, False, True)

        ctx = dash.callback_context
        if not ctx.triggered: return stopped_state_ui # 預設為停止狀態
        button_id = ctx.triggered[0]["prop_id"].split(".")[0]
        
        target_state = None
        if button_id == "start-button": # 手動點擊 Start
            target_state = "Start"
            if mqtt_handler.mqtt_connected:
                mqtt_handler.publish_message(config_manager.CYCLE_TOPIC, {"Cycle": "Start"})

        elif button_id == "end-button": # 手動點擊 End
            target_state = "End"
            if mqtt_handler.mqtt_connected:
                mqtt_handler.publish_message(config_manager.CYCLE_TOPIC, {"Cycle": "End"})

        elif button_id == "cycle-status-store": # 自動狀態同步
            if cycle_status == "on": target_state = "Start"
            else: target_state = "End"

        # 根據目標狀態更新 UI
        if target_state == "Start": return running_state_ui
        elif target_state == "End": return stopped_state_ui

        # 如果沒有任何目標狀態（例如初始化時），則不更新
        return dash.no_update
    
    @app.callback(Output('cycle-status-store', 'data'), 
                  Input('interval-component', 'n_intervals')
    )
    def update_cycle_status(n):
        """
        定期從 data_manager 獲取最新的 cycle_status
        """
        try:
            status = data_manager.live_data["cycle_status"]
            return status
        except KeyError:
            # 處理 live_data 尚未初始化或 key 不存在的狀況
            return "off"
