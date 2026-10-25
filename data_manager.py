# 數據管理模組，負責儲存與處理即時數據
import pandas as pd
import yaml
import os
import logging
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from config import ConfigManager

logger = logging.getLogger(__name__)

class DataManager:
    def __init__(self, config_manager: ConfigManager):
        # 初始化數據管理器，儲存即時數據與配置
        self.config = config_manager
        self.live_data = {
            "df": None,  # 合併後的數據框架
            "machining_params": None,  # 加工參數
            "mqtt_messages": [],  # 最新 MQTT 訊息
            "cycle_status": "off",  # Cycle 狀態
            "pdata_list": [],  # Pdata 列表
            "cnc_list": [],  # CNC 列表
            "cnc_connection_status": "",  # CNC 連線狀態
            "job_state": "IDLE",  # 加工任務狀態
            "tmac": None,  # 當前 HolderID
            "pending_tmac": None, # 待處理 HolderID
            "coefficients": {},  # 儲存 MAC 對應的係數
            "cycle_window": {"start": None, "end": None},
            "last_ncfile": None,
            "selected_yaml": None,
            "selected_csv": None,
            "static_ref_df": None  # static reference
        }
        self.load_coefficients()  # 載入 coefficient.csv
        self.last_written_time = None  # 新增：記錄上次寫入的 TimeInSeconds
        self.csv_filepath = os.path.join(self.config.CSV_DIR, "reference.csv")
        self.initialize_csv_columns()
        self.window_size = 100 # UCL 滾動窗口大小
        self.ucl_shift_amount = 30  # UCL 平移筆數
        self.previous_cycle_status = "off"
        self.ucl_distance_threshold = 1 # 最近鄰距離門檻（Offset）
        self.ucl_forward_window = 50  # 最近鄰前瞻視窗大小（Offset）
        self.aligned_export_path = os.path.join(self.config.CSV_DIR, "sync_ucl_latest.csv")
        self._ref_cache = None  # 快取 reference.csv 的 numpy 陣列，加速 UCL 對齊
        self.live_data["flute_ref_ucl"] = None  # 快取 Flute UCL 常數值

    def initialize_csv_columns(self):
        """
        動態初始化 CSV 欄位列表與定義需要計算 UCL 的通道
        """
        self.columns_with_ucl = ['Torque', 'BendingX']
        base_columns = ['TimeTag','Torque', 'BendingX', 'BendingY', 'CH1', 'CH2','Offset_X', 'Offset_Y', 'Offset_Z', 'NC_Line']
        self.offset_columns = ['Offset_X', 'Offset_Y', 'Offset_Z']
        self.dynamic_columns = []
        self.flute_ucl_columns = []
        for n in self.config.UCL_SIGMA:
            for channel in self.columns_with_ucl:
                self.dynamic_columns.append(f"{channel}_UCL_{n}")
            self.flute_ucl_columns.append(f"Flute_UCL_{n}")
        self.csv_columns = base_columns + self.dynamic_columns

    def load_coefficients(self):
        """
        載入 coefficient.csv 檔案並儲存係數
        """
        try:
            coeff_path = self.config.COEFF_PATH
            if os.path.exists(coeff_path):
                coeff_df = pd.read_csv(coeff_path)
                for _, row in coeff_df.iterrows():
                    self.live_data["coefficients"][row["MAC"]] = {
                        "Torque": row["Torque"],
                        "BendingX": row["BendingX"],
                        "BendingY": row["BendingY"],
                        "CH1": row["CH1"],
                        "CH2": row["CH2"]
                    }
                # logger.info(f"成功載入 coefficient.csv: {self.live_data['coefficients']}")
            else:
                logger.warning("coefficient.csv 不存在，使用預設係數 1.0")
                self.live_data["coefficients"] = {}
        except Exception as e:
            logger.error(f"載入 coefficient.csv 失敗: {e}")
            self.live_data["coefficients"] = {}

    def apply_coefficients(self, data, mac):
        """
        根據 MAC 應用係數到數據
        """
        coeffs = self.live_data["coefficients"].get(mac, {
            "Torque": 1.0,
            "BendingX": 1.0,
            "BendingY": 1.0,
            "CH1": 1.0,
            "CH2": 1.0
        })
        # logger.info(f"應用係數 {coeffs} 到數據: {data}")
        data["Torque"] = data["Torque"] * coeffs["Torque"]
        data["BendingX"] = data["BendingX"] * coeffs["BendingX"]
        data["BendingY"] = data["BendingY"] * coeffs["BendingY"]
        data["CH1"] = data["CH1"] * coeffs["CH1"]
        data["CH2"] = data["CH2"] * coeffs["CH2"]
        return data
    
    def add_pdata(self, new_data_list):
        """
        新增 Pdata 數據，限制列表大小
        """
        # 對每筆數據應用係數
        self.live_data["pdata_list"].extend([
            self.apply_coefficients(d, d.get("MAC", "N/A")) for d in new_data_list
        ])
        if len(self.live_data["pdata_list"]) > self.config.PDATA_LENGTH:
            self.live_data["pdata_list"] = self.live_data["pdata_list"][-self.config.PDATA_LENGTH:]
        # logger.info(f"Pdata 數據列表長度: {len(self.live_data['pdata_list'])}")

    def add_cnc_data(self, new_data):
        """
        新增 CNC 數據，限制列表大小
        """
        self.live_data["cnc_list"].append(new_data)
        if len(self.live_data["cnc_list"]) > self.config.CNC_LENGTH:
            self.live_data["cnc_list"] = self.live_data["cnc_list"][-self.config.CNC_LENGTH:]
        #記錄 NC 檔名
        try:
            if "NCFile" in new_data and new_data["NCFile"]:
                self.live_data["last_ncfile"] = str(new_data["NCFile"])
            elif "NC_File" in new_data and new_data["NC_File"]:
                self.live_data["last_ncfile"] = str(new_data["NC_File"])
        except Exception:
            pass
        # logger.info(f"CNC 數據列表長度: {len(self.live_data['cnc_list'])}")

    def add_mqtt_message(self, message):
        """
        新增 MQTT 訊息，限制訊息數量
        """
        self.live_data["mqtt_messages"].append(message)
        self.live_data["mqtt_messages"] = self.live_data["mqtt_messages"][-10:]

    def update_cycle_status(self, status):
        """
        更新 Cycle 狀態
        """
        self.live_data["cycle_status"] = status
        #時間窗
        if status == "on":
            self.live_data["cycle_window"]["start"] = datetime.now()
            self.live_data["cycle_window"]["end"] = None
        else:
            self.live_data["cycle_window"]["end"] = datetime.now()

    def update_cnc_connection_status(self, status):
        """
        更新 CNC 連線狀態
        """
        self.live_data["cnc_connection_status"] = status
    
    def update_job_state(self, state):
        """
        更新加工任務狀態
        """
        self.live_data["job_state"] = state
        # logger.info(f"加工任務狀態更新為: {state}")
    
    def update_tmac(self, tmac, pending=False):
        """
        更新當前或待處理的 HolderID
        """
        if pending:
            self.live_data["pending_tmac"] = tmac
            # logger.info(f"更新待處理 TMAC: {tmac}")
        else:
            self.live_data["tmac"] = tmac
            # logger.info(f"更新當前 TMAC: {tmac}")

    def load_yaml_params(self, yaml_path):
        """
        載入 YAML 檔案並解析加工參數
        """
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            params = {
                "machine_name": config.get("Description", {}).get("NativeName", "N/A"),
                "controller": config.get("Description", {}).get("Controller", "N/A"),
                "spindle_speed": config.get("CNCSpindle", {}).get("S1", {}).get("CmdSpeed", "N/A"),
                "feed_rate": config.get("CNCSpindle", {}).get("S1", {}).get("FeedRate", "N/A"),
                "nc_file": config.get("Job", {}).get("NcFile", {}).get("FileName", "N/A"),
                "tool_holder": config.get("ToolRelated", {}).get("Binding", {}).get("No1", {}).get("HolderID", "N/A"),
                "tool": {
                    "type": config.get("ToolRelated", {}).get("ToolHouse", {}).get("T1", {}).get("Type", "N/A"),
                    "diameter": config.get("ToolRelated", {}).get("ToolHouse", {}).get("T1", {}).get("Apt", {}).get("Diameter", "N/A"),
                },
            }
            self.live_data["machining_params"] = params
            return params, config
        except Exception as e:
            logger.error(f"讀取 YAML config 失敗: {e}")
            self.live_data["machining_params"] = {}
            return {}, {}

    def get_part_files(self):
        """
        取得工件 STL 或是 PNG/JPG 檔案列表
        """
        try:
            files = [f for f in os.listdir(self.config.STL_DIR) if f.lower().endswith(('.stl', '.STL','.png', '.jpg', '.jpeg'))]
            return [{"label": f, "value": os.path.abspath(os.path.join(self.config.STL_DIR, f))} for f in files]
        except Exception as e:
            logger.error(f"無法讀取 STL 或是 PNG/JPG 檔案列表: {e}")
            return []

    def get_yaml_files(self):
        """
        取得 YAML 檔案列表
        """
        try:
            files = [f for f in os.listdir(self.config.YAML_DIR) if f.lower().endswith(('.yml', '.yaml'))]
            return [{"label": f, "value": os.path.abspath(os.path.join(self.config.YAML_DIR, f))} for f in files]
        except Exception as e:
            logger.error(f"無法讀取 YAML 檔案列表: {e}")
            return []

    def get_csv_files(self):
        """
        取得 Order Outcome 列表
        包含 CSV、PDF 及 CSV_DIR 底下的資料夾
        """
        try:
            items = []
            with os.scandir(self.config.CSV_DIR) as entries:
                for entry in entries:

                    if entry.is_symlink(): continue # 不列出符號連結

                    if entry.is_dir(follow_symlinks=False):
                        items.append({
                            "label": f"📁 {entry.name}/",
                            "value": os.path.abspath(entry.path),
                            "type": "folder"
                        })

                    elif entry.is_file(follow_symlinks=False):
                        name_lower = entry.name.lower()
                        if name_lower.endswith(".csv"):
                            items.append({
                                "label": f"📊 {entry.name}",
                                "value": os.path.abspath(entry.path),
                                "type": "file"
                            })
                        elif name_lower.endswith(".pdf"):
                            items.append({
                                "label": f"📕 {entry.name}",
                                "value": os.path.abspath(entry.path),
                                "type": "file"
                            })

            # 排序：資料夾在前，檔案在後，並依照 label 進行字母排序
            items.sort(key=lambda item: (item["type"] == "folder", item["label"].lower()))

            return [{"label": item["label"], "value": item["value"]} for item in items]

        except Exception as e:
            logger.error(f"無法讀取 Order Outcome 列表: {e}")
            return []
        
    def get_deletable_csv_files(self):
        """
        取得可刪除的 Order Outcome
        排除 reference.csv
        """
        return [
            item
            for item in self.get_csv_files()
            if os.path.basename(os.path.normpath(item["value"])).lower() != "reference.csv"
        ]
        
    def get_current_cycle_context(self): #取用上下文的方法
        pdata = self.live_data.get("pdata_list") or []
        last_mac = pdata[-1].get("MAC") if pdata else None
        return {
            "start": self.live_data["cycle_window"]["start"],
            "end": self.live_data["cycle_window"]["end"],
            "ncfile": self.live_data.get("last_ncfile"),
            "holder_id": (self.live_data.get("machining_params") or {}).get("tool_holder"),
            "mac": last_mac,
            "selected_yaml": self.live_data.get("selected_yaml"),
            "selected_csv": self.live_data.get("selected_csv"),
        }
    
    def time_sync(self, pdata_df: pd.DataFrame, cnc_df: pd.DataFrame) -> pd.DataFrame:
        """
        以 CNC 為主軸的最近點匹配：每筆 CNC 時間點，對應到最接近的 Pdata（不做內插）。
        """
        # pdata_df = pd.DataFrame(pdata_list)
        # cnc_df = pd.DataFrame(cnc_list)

        # 時間轉 float
        # cnc_df['TimeInSeconds'] = cnc_df['TimeInSeconds'].astype(float)
        # if cnc_df['TimeInSeconds'].max() > 0:
        #     return pdata_df

        pdata_df['TimeInSeconds'] = pdata_df['TimeInSeconds'].astype(float)

        if 'NC_Line' in cnc_df.columns:
            cnc_df['NC_Line'] = pd.to_numeric(cnc_df['NC_Line'], errors='coerce')
        else:
            cnc_df['NC_Line'] = np.nan

        # CNC Offset 數值化
        cnc_cols = ['Offset_X', 'Offset_Y', 'Offset_Z']
        for col in cnc_cols:
            cnc_df[col] = pd.to_numeric(cnc_df[col], errors='coerce')

        # 以 CNC 為左表，最近點抓取 Pdata
        sync_df = pd.merge_asof(
            cnc_df.sort_values('TimeInSeconds'),
            pdata_df.sort_values('TimeInSeconds'),
            on='TimeInSeconds',
            direction='nearest',
            suffixes=('', '_pdata')
        )

        # 另外保留 Pdata 的時間戳方便檢查
        if 'TimeInSeconds_pdata' in sync_df.columns:
            sync_df['Pdata_TimeInSeconds'] = sync_df['TimeInSeconds_pdata']
            sync_df = sync_df.drop(columns=['TimeInSeconds_pdata'])
        else:
            sync_df['Pdata_TimeInSeconds'] = None

        # 將 TimeTag 覆寫為 CNC 時間（優先使用 CNC 的 Time 欄位，否則用 TimeInSeconds 格式化）
        if 'Time' in sync_df.columns and not sync_df['Time'].isna().all():
            sync_df['TimeTag'] = sync_df['Time'].fillna(
                sync_df['TimeInSeconds'].apply(lambda x: f"{int(x // 3600):02d}:{int((x % 3600) // 60):02d}:{x % 60:06.3f}")
            )
        else:
            sync_df['TimeTag'] = sync_df['TimeInSeconds'].apply(
                lambda x: f"{int(x // 3600):02d}:{int((x % 3600) // 60):02d}:{x % 60:06.3f}"
            )

        sync_df['Times'] = sync_df['TimeInSeconds'].apply(
            lambda x: f"{int(x % 60):02d}.{int((x % 1) * 1000):03d}"
        )
        # Debug dump was removed to節省 I/O；如需再啟用，取消以下註解
        # try:
        #     self.last_sync_df = sync_df
        #     debug_path = os.path.join(self.config.CSV_DIR, "sync_df_latest.csv")
        #     sync_df.to_csv(debug_path, index=False, float_format="%.6f")
        # except Exception:
        #     pass

        return sync_df

    def calculate_ucl(self, sync_df: pd.DataFrame) -> pd.DataFrame:
        """
        計算 Torque、BendingX、CH1、CH2 的 UCL
        """
        df = sync_df.copy()
        # logger.info(df.shape)
        for raw_col in self.columns_with_ucl:
            rolling_window = df[raw_col].rolling(window=self.window_size, min_periods=2)
            rolling_mean = rolling_window.mean()
            rolling_std = rolling_window.std()

            for n in self.config.UCL_SIGMA:
                rolling_ucl_col = f"{raw_col}_UCL_{n}"
                df[rolling_ucl_col] = rolling_mean + n * rolling_std
                df[rolling_ucl_col] = df[rolling_ucl_col].fillna(df[raw_col])

        return df
    
    def reset_ref_csv(self):
        with open(self.csv_filepath, 'w') as f: f.write('')
        self.last_written_time = None
        self.live_data["flute_ref_ucl"] = None  # 清除 Flute UCL 快取

    def save_ref_csv(self, sync_df: pd.DataFrame):
        """
        只追加新資料到 csv 避免重複
        """
        # 提取 TimeInSeconds 欄位
        times = sync_df["TimeInSeconds"]

        if self.last_written_time is None:
            # 第一次：寫全部
            new_df = sync_df
            write_header = True
        else:
            # 只寫入 TimeInSeconds > 上次寫入時間的資料
            new_df = sync_df[times > self.last_written_time]
            write_header = False

        if 'NC_Line' not in new_df.columns:
            new_df['NC_Line'] = np.nan

        new_df = new_df.dropna(subset=self.csv_columns, how='any')
        new_df.to_csv(
            self.csv_filepath,
            mode='a',
            header=write_header,
            index=False,
            columns=self.csv_columns,
            float_format='%.4f'
        )
        # 更新最後寫入時間
        self.last_written_time = times.iloc[-1]
    
    def shift_ucl_data(self):
        """
        將 UCL 往前平移，並計算各 sigma 的 Flute_UCL (均值 + n*std)
        """
        df_shifted = pd.read_csv(self.csv_filepath)
        for col in self.csv_columns + self.flute_ucl_columns:
            if col not in df_shifted.columns:
                df_shifted[col] = np.nan
        shift_amount = self.ucl_shift_amount

        for col in self.dynamic_columns:  # 對所有動態欄位進行平移
            if col in df_shifted.columns:
                shifted_series = df_shifted[col].shift(-shift_amount)  # 往前平移
                # 找到最後一個有效值的索引
                last_valid_index = len(shifted_series) - shift_amount - 1
                fill_value = None
                # 確保索引有效且值非 NaN
                if last_valid_index >= 0 and pd.notna(shifted_series.iloc[last_valid_index]):
                    fill_value = shifted_series.iloc[last_valid_index]  # 使用最後一個有效值填充
                if fill_value is not None:
                    shifted_series = shifted_series.fillna(value=fill_value)

                df_shifted[col] = shifted_series

        # 計算各 sigma 的 Flute_UCL = mean + n * std （CH1、CH2 合併後）
        try:
            mean = pd.concat([df_shifted['CH1'], df_shifted['CH2']]).mean()
            std = pd.concat([df_shifted['CH1'], df_shifted['CH2']]).std()
            for n, col in zip(self.config.UCL_SIGMA, self.flute_ucl_columns):
                df_shifted[col] = mean + n * std
        except Exception as e:
            logger.error(f"計算 Flute_UCL 時發生錯誤: {e}")

        df_shifted.to_csv(
            self.csv_filepath,
            mode='w',
            header=True,
            index=False,
            columns=self.csv_columns + self.flute_ucl_columns,
            float_format='%.4f'
        )
        self.live_data["flute_ref_ucl"] = None  # 更新後清除快取
                


    def sync_ref_ucl(self, sync_df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
        """
        使用 reference.csv 中的 CNC offset 參考資料對 UCL 進行對齊與補齊
        """
        ref_df: Optional[pd.DataFrame] = None

        # 若 static reference 尚未載入，則嘗試讀取 reference.csv
        if self.live_data.get("static_ref_df") is None:
            self._ref_cache = None
            try:
                ref_path = os.path.join(self.config.CSV_DIR, "reference.csv")

                # 若 reference.csv 不存在，跳過 UCL 對齊
                if not os.path.exists(ref_path):
                    logger.warning(f"reference.csv not found at {ref_path}, skip UCL alignment")
                    self.live_data["static_ref_df"] = None
                    return sync_df, ref_df

                # 讀取 reference.csv
                ref_df = pd.read_csv(ref_path)

                # 需要的欄位 (offset + NC_Line + dynamic)
                required_cols = self.offset_columns + ['NC_Line'] + self.dynamic_columns
                for col in required_cols:
                    if col not in ref_df.columns:
                        ref_df[col] = np.nan

                # 取出需要的欄位
                static_ref_df = ref_df[required_cols].copy().reset_index(drop=True)

                # 移除 Offset 全為 0 的行，避免初始卡在 index 0
                zero_mask = (static_ref_df[self.offset_columns].fillna(0) == 0).all(axis=1)
                static_ref_df = static_ref_df[~zero_mask]

                # 存入記憶體 (避免每次重新讀檔)
                self.live_data["static_ref_df"] = static_ref_df
                # 預先建好 numpy 快取，避免每次對齊都重新轉陣列
                by_line = {}
                if "NC_Line" in static_ref_df.columns:
                    grouped = static_ref_df.reset_index().groupby("NC_Line")
                    for line, g in grouped:
                        if pd.isna(line):
                            continue
                        idx_arr = g["index"].to_numpy(dtype=int)
                        offsets_arr = g[self.offset_columns].to_numpy(dtype=float)
                        by_line[line] = (idx_arr, offsets_arr)
                self._ref_cache = {
                    "by_line": by_line,
                    "all_offsets": static_ref_df[self.offset_columns].to_numpy(dtype=float),
                    "all_indices": np.arange(len(static_ref_df), dtype=int),
                }

            except Exception as e:
                logger.error(f"讀取 static reference.csv 失敗: {e}")
                self.live_data["static_ref_df"] = None
                self._ref_cache = None
                return sync_df, ref_df

        # 已載入的 reference 資料
        static_ref_df = self.live_data.get("static_ref_df")
        if ref_df is None and static_ref_df is not None:
            ref_df = static_ref_df.copy()
        ref_cache = self._ref_cache or {}

        try:
            sync_offsets = sync_df[self.offset_columns].to_numpy(dtype=float)

            nearest_idx: list = []   # 儲存每列匹配到的 reference index
            nearest_dist: list = []  # 儲存距離
            last_idx_by_line: dict = {}  # 每個 NC_Line 的最後匹配位置 (維持 forward-only)

            # 對 sync_df 中每一筆 offset 執行最近鄰匹配
            for row_idx, row_offset in enumerate(sync_offsets):

                row_nc_line = sync_df.iloc[row_idx].get("NC_Line", np.nan)

                chosen_idx = None
                min_dist = np.nan

                if pd.notna(row_nc_line):
                    grouped = ref_cache.get("by_line", {})
                    if row_nc_line in grouped:
                        idx_arr, offsets_arr = grouped[row_nc_line]
                        last_idx = last_idx_by_line.get(row_nc_line)

                        if last_idx is not None and last_idx >= 0:
                            mask = (idx_arr >= last_idx) & (idx_arr <= last_idx + self.ucl_forward_window)
                        else:
                            mask = np.ones(len(idx_arr), dtype=bool)

                        # 直接在局部做距離計算（維持 forward window）
                        if mask.any():
                            offsets_slice = offsets_arr[mask]
                            idx_slice = idx_arr[mask]
                            dists = np.linalg.norm(offsets_slice - row_offset, axis=1)
                            min_pos = int(np.argmin(dists))
                            min_dist = float(dists[min_pos])
                            if self.ucl_distance_threshold is None or min_dist <= self.ucl_distance_threshold:
                                chosen_idx = int(idx_slice[min_pos])
                                last_idx_by_line[row_nc_line] = chosen_idx
                        # 如果這個 NC_Line 沒有可用候選，但之前有匹配過，沿用前一次
                        if chosen_idx is None and row_nc_line in last_idx_by_line:
                            chosen_idx = last_idx_by_line[row_nc_line]
                            min_dist = np.nan

                # 若行號不存在或未成功匹配，就視為無匹配
                if chosen_idx is None:
                    nearest_idx.append(None)
                    nearest_dist.append(np.nan)
                    continue

                nearest_idx.append(chosen_idx)
                nearest_dist.append(min_dist)

            # 將 dynamic_columns 從 reference 對齊到 sync_df
            for col in self.dynamic_columns:
                sync_df[col] = [
                    static_ref_df.iloc[idx][col] if idx is not None else np.nan
                    for idx in nearest_idx
                ]
                sync_df[col] = sync_df[col].ffill()  # 無法匹配時使用前值補齊

            # 下面欄位僅供除錯記錄，為減少負載已註解；需要時再解開
            # sync_df["Reference_NC_Line"] = [
            #     static_ref_df.iloc[idx]["NC_Line"] if idx is not None else np.nan
            #     for idx in nearest_idx
            # ]
            # sync_df["Reference_NC_Line"] = sync_df["Reference_NC_Line"].ffill()
            # sync_df["ReferenceIndex"] = nearest_idx
            # sync_df["ReferenceDistance"] = nearest_dist
            # try:
            #     self.last_sync_ucl_df = sync_df.copy()
            #     sync_df.to_csv(self.aligned_export_path, index=False, float_format="%.6f")
            # except Exception:
            #     pass

        except Exception as e:
            logger.error(f"計算 UCL 對齊發生錯誤: {e}")

        return sync_df, ref_df

    def load_ref_flute_ucl(self) -> Dict[int, float]:
        """
        直接載入 reference.csv 中的 Flute_UCL_{sigma} 常數值，供 SAVE_REFERENCE_CSV=false 時使用
        （不做對齊，因為全檔案都是同一組常數）
        """
        # 若已有快取且非空，直接回傳
        cached = self.live_data.get("flute_ref_ucl")
        if cached:
            return cached

        ref_path = os.path.join(self.config.CSV_DIR, "reference.csv")
        result: Dict[int, float] = {}

        if not os.path.exists(ref_path):
            logger.warning(f"reference.csv not found at {ref_path}, 無法載入 Flute_UCL")
            self.live_data["flute_ref_ucl"] = result
            return result

        try:
            ref_df = pd.read_csv(ref_path)
            if ref_df.empty:
                self.live_data["flute_ref_ucl"] = result
                return result

            for sigma in self.config.UCL_SIGMA:
                col = f"Flute_UCL_{sigma}"
                if col in ref_df.columns and not ref_df[col].empty:
                    try:
                        val = float(ref_df[col].iloc[0])
                    except (ValueError, TypeError):
                        continue
                    if not np.isnan(val):
                        result[sigma] = val
        except Exception as e:
            logger.error(f"讀取 Flute_UCL 失敗: {e}")

        self.live_data["flute_ref_ucl"] = result
        return result

