# 網頁佈局模組，定義 Dash 應用程式的 UI 結構
from dash import html, dcc
from data_manager import DataManager
from config import ConfigManager

class DashboardLayout:
    def __init__(self, config_manager: ConfigManager, data_manager: DataManager):
        # 初始化佈局，載入配置與數據管理（僅用於讀取下拉選項初始值）
        self.config = config_manager
        self.data_manager = data_manager

    def get_layout(self):
        """
        產生 Dash 應用程式的完整佈局
        """
        return html.Div(className="main-content", children=[

            # 頂部面板（燈號、即時資訊）
            html.Div(className="top-panel", children=[
                # 第一區塊：MQTT 資訊 (MAC, Power, PSN)
                html.Div(className="panel-group mqtt-info", children=[
                    html.Div(id="mac-display", children="MAC:"),
                    html.Div(id="power-display", children="Power:"),
                    html.Div(id="psn-display", children="PSN:"),
                ]),
                
                # 第二區塊：連線狀態 (Controller State, STH Link)
                html.Div(className="panel-group connection-status", children=[
                    html.Div(className="indicator-group", children=[
                        html.Span(id="ctl-state-indicator-text", children="Controller State"),
                        html.Div(id="ctl-state-indicator", className="indicator ctl-state-indicator")
                    ]),
                    html.Div(className="indicator-group", children=[
                        html.Span(id="sth-link-indicator-text", children="STH Link"),
                        html.Div(id="sth-link-indicator", className="indicator sth-link-indicator")
                    ]),
                ]),
                
                # 第三區塊：加工監控 (Machining State, Force Control Limit, Flute Control Limit)
                html.Div(className="panel-group machining-control", children=[
                    html.Div(className="indicator-group", children=[
                        html.Span(id="cycle-indicator-text", children="Machining State"),
                        html.Div(id="cycle-indicator", className="indicator cycle-indicator")
                    ]),
                    html.Div(className="indicator-group", children=[
                        html.Span(id="force-indicator-text", children="Force Control Limit"),
                        html.Div(id="force-indicator", className="indicator")
                    ]),
                    html.Div(className="indicator-group", children=[
                        html.Span(id="flute-indicator-text", children="Flute Control Limit"),
                        html.Div(id="flute-indicator", className="indicator")
                    ]),
                ]),
                
                # 控制按鈕
                html.Button(id="toggle-mqtt", children="Hide/Show MQTT"),
            ]),

            # 主體（左 / 中 / 右）
            html.Div(className="main-body", children=[

                # 左側面板容器
                html.Div(className="left-panel-container", children=[

                    # 左上：管理工件檔案、工單與輸出檔操作
                    html.Div(className="left-panel", children=[
                        html.Button(id="manage-part-files-button",children="Manage Part Files"),
                        html.Div(className="upload-yaml-container", children=[
                            dcc.Upload(id="upload-yaml", children=html.Button("Upload Work Order")),
                            html.Div(id="upload-yaml-message")
                        ]),
                        dcc.Dropdown(
                            id="yaml-dropdown",
                            options=self.data_manager.get_yaml_files(),
                            placeholder="Select Work Order"
                        ),
                        html.Div(id="machining-params"),
                        html.Button(id="send-holderid-button", children="Link STH"),

                        dcc.Dropdown(
                            id="csv-dropdown",
                            options=self.data_manager.get_csv_files(),
                            placeholder="Order Outcome"
                        ),
                        html.Button(id="download-csv-button", children="Download Outcome"),
                        dcc.Download(id="download-csv"),
                        html.Button(id="manage-cnc-output-button", children="Manage CNC Files"),
                    ]),

                    # 左下：連線/控制/報告
                    html.Div(className="lower-left-panel", children=[
                        # 第一區塊：連線相關按鈕
                        html.Div(className="panel-group connection-buttons", children=[
                            html.Button(id="send-cnc-ip-button", children="Send CNC IP"),
                            html.Button(id="connect-cnc-button", children="Connect CNC"),
                        ]),
                        # 第二區塊：加工控制按鈕
                        html.Div(className="panel-group control-buttons", children=[
                            html.Button(id="start-button", children="Manual Start"),
                            html.Button(id="end-button", children="Manual End", disabled=True),
                            html.Button(id="btn-generate-report", children="Generate Report", n_clicks=0),
                            dcc.Store(id="manual-end-state", data=False),  # 初始為 False，表示未按下 Manual End
                        ]),
                        # 第三區塊：配置與刪除按鈕
                        html.Div(className="panel-group config-buttons", children=[
                            html.Button(id="edit-config-button", children="Edit Config"),
                            html.Button(id="delete-files-button", children="Delete Orders"),
                        ]),
                    ]),
                ]),

                # 中間：3D 模型 / CNC View / Flute View / 趨勢圖
                html.Div(className="center-panel", children=[
                    html.Div(className="center-top", children=[
                        dcc.Graph(id="stl-graph"),
                        dcc.Graph(id="cnc-view-graph"),
                        dcc.Graph(id="flute-view-graph"),
                        dcc.Store(id="flute-buffer-store", data=[]),  # Flute View 緩衝
                    ]),
                    html.Div(className="center-bottom", children=[
                        dcc.Graph(id="torque-graph"),
                        dcc.Graph(id="bending-graph"),
                    ]),
                ]),

                # 右側：訊息區
                html.Div(className="right-panel", id="right-panel", children=[
                    html.Div(className="right-panel-sections", children=[
                        html.H2("MQTT Messages", className="mqtt-title"),
                        html.Div(className="mqtt-section", children=[html.Div(id="mqtt-messages")])]),
                    html.Div(className="status-panel-section", children=[
                        html.H2("System Status", className="status-title"),
                        html.Div(className="status-section", children=[
                            html.Div(id="status-messages", children=[
                                html.Div(id="yaml-status-message"),
                                html.Div(id="report-live-status"),
                                html.Div(id="report-result-status")
                            ])
                        ])
                    ]),
                ]),

                # 報告生成提示視窗
                html.Div(id="report-loading-modal", className="popup-overlay", style={"display": "none"}, children=[
                    html.Div(className="popup-content report-loading-popup", children=[
                        html.Div(className="report-loading-spinner"), # 旋轉載入動畫
                        html.H3("Report being generated...", className="report-loading-title"),
                        html.P("Please wait, the report will automatically close once generation is complete.", className="report-loading-text")
                    ])
                ]),

                # CNC CSV 輸出管理視窗
                html.Div(id="cnc-output-modal", className="popup-overlay", style={"display": "none"}, children=[
                    html.Div(className="popup-content", children=[
                        html.H4("Doenload or Delete CNC CSV Files", className="popup-title"),
                        html.Label("CNC CSV Files", className="label-inline"),
                        html.Div(className="file-list-container", children=[
                            dcc.Checklist(id="cnc-output-checklist", options=[], value=[],
                                          labelStyle={"display": "block", "overflowWrap": "anywhere"})
                        ]),
                        html.Div([
                            html.Button("Download", id="download-cnc-output-button", className="control-button", disabled=True),
                            html.Button("Delete", id="delete-cnc-output-button", className="control-button", disabled=True),
                            html.Button("Cancel", id="cancel-cnc-output-button", className="control-button cancel-button"),
                        ], className="modal-button-container"),
                        html.Div(id="cnc-output-message", className="part-files-message", role="status"),
                        dcc.Download(id="download-cnc-output"),
                    ])
                ]),

                # 工件管理視窗 (STL / PNG)
                html.Div(id="part-files-modal", className="popup-overlay", style={"display": "none"}, children=[
                    html.Div(className="popup-content part-files-popup", children=[
                        html.H4("Upload or Delete Part Files", className="popup-title"),
                        # 上傳區域
                        html.Label("Upload STL / PNG", className="label-inline"),
                        dcc.Upload(id="upload-part-files", className="part-files-upload-area", accept=".stl,.STL,.png,.jpg,.jpeg,",
                                    multiple=True, children=html.Div("Click or drag STL / PNG files here")),
                        # 工件檔案清單
                        html.Label( "Part Files",className="label-inline"),
                        html.Div(className="file-list-container part-files-list", id="part-files-list", children=[
                            dcc.Checklist(id="part-files-checklist", options=self.data_manager.get_part_files(), value=[])
                        ]),

                        html.Div(
                            "Warning: Deleting files used by a Work Order may affect Part View or reports.",
                            className="part-files-hint",style={"color": "#b03a2e"}),
                        
                        html.Div([
                            html.Button("Delete", id="delete-part-files-confirm-button", className="control-button"),
                            html.Button("Cancel", id="cancel-part-files-button", className="control-button cancel-button")
                        ], className="modal-button-container"),
                        html.Div(id="part-files-message"),
                    ])
                ]),

                # 設定視窗（YAML / config.json / coefficient.csv）
                html.Div(id="config-modal", className="popup-overlay", style={'display': 'none'}, children=[
                    html.Div(className="popup-content", children=[
                        html.H4("Edit Work Order / config.json / coefficient.csv", className="popup-title"),
                        dcc.Dropdown(
                            id="modal-yaml-dropdown",
                            options=self.data_manager.get_yaml_files(),
                            placeholder="Select Work Order"
                        ),
                        html.Label("Work Order", className="label-inline"),
                        dcc.Textarea(id="yaml-content", className="modal-textarea"),

                        html.Label("config.json", className="label-inline"),
                        dcc.Textarea(
                            id="config-json-content",
                            value=self.config.load_config(return_formatted=True),
                            className="modal-textarea"
                        ),

                        html.Label("coefficient.csv", className="label-inline"),
                        dcc.Textarea(
                            id="coeff-content",
                            value=self.config.load_coeff(return_formatted=True),
                            className="modal-textarea"
                        ),

                        html.Div([
                            html.Button("Save", id="save-config-button", className="control-button"),
                            html.Button("Cancel", id="close-modal-button", className="control-button cancel-button"),
                        ], className="modal-button-container"),

                        html.Div(id="modal-message"),
                    ]),
                    dcc.Store(id="original-yaml-content"),     # 儲存原始 YAML
                    dcc.Store(id="original-config-content"),   # 儲存原始 config.json
                    dcc.Store(id="original-coeff-content"),    # 儲存原始 coefficient.csv
                ]),

                # 刪除檔案視窗
                html.Div(id="delete-files-modal", className="popup-overlay", style={'display': 'none'}, children=[
                    html.Div(className="popup-content", children=[
                        html.H4("Delete Work Order and Order Outcome", className="popup-title"),
                        html.Label("Work Order", className="label-inline"),
                        html.Div(id="yaml-files-list", className="file-list-container", children=[
                            dcc.Checklist(id="delete-yaml-checklist", options=self.data_manager.get_yaml_files(), value=[])
                        ]),
                        html.Label("Order Outcome", className="label-inline"),
                        html.Div(id="csv-files-list", className="file-list-container", children=[
                            dcc.Checklist(id="delete-csv-checklist", options=self.data_manager.get_deletable_csv_files(), value=[])
                        ]),
                        html.P("Warning: Deleting these files is irreversible. Please ensure you have backups if necessary.",
                               className="part-files-hint",style={"color": "#b03a2e"}),
                        html.Div([
                            html.Button("Delete", id="delete-files-confirm-button", className="control-button"),
                            html.Button("Cancel", id="delete-files-cancel-button", className="control-button cancel-button"),
                        ], className="modal-button-container"),
                        html.Div(id="delete-files-message")
                    ])
                ]),
            ]),

            # 週期性更新
            dcc.Interval(id="interval-component", interval=self.config.WEB_UPDATE_RATE),

            # 其他狀態儲存
            dcc.Store(id="stl-path"),                # 由 YAML 決定的 STL 路徑
            dcc.Store(id="client-time", data=None),  # 用戶端時間（校時）
            dcc.Store(id="last-auto-report-timestamp"),  # 去重：最後一次 Cycle End 時刻
            dcc.Store(id="last-auto-report-csv"),        # 去重：最後一次報告的 CSV 名稱
            dcc.Store(id='cycle-status-store'),  # 用於儲存 Cycle 狀態
        ])
