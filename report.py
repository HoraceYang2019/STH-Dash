"""
TODO:
源自 高科大 Dashbaord_E_20261216 release

# 20260114 修改 - CHEN WU LIN
改為直接呼叫wkhtmltopdf執行檔，修改 find_wkhtmltopdf()中的路徑尋找

# 20260316 修改 - CHEN WU LIN
修改 Dashboard_E (20251216) 中的 `report.py`，使程式能自動讀取 CSV 檔第一筆資料的日期時間，
並將其作為報告的 Date。

# 20261016 修改 - HONG KAI JHE
修正 CONFIG 無設定管制界線時，圖表也可以正常顯示
"""
import yaml
import jinja2
import markdown
import pdfkit
import os
import base64
import pandas as pd
import json
from datetime import datetime
import argparse
import logging
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import matplotlib.ticker as ticker
from matplotlib.patches import Circle
import trimesh
import plotly.graph_objects as go
import plotly.io as pio
import shutil
import platform
import sys

matplotlib.use("Agg")

# 放大 matplotlib 字體
matplotlib.rcParams.update({
    "font.size": 13,
    "axes.titlesize": 15,
    "axes.labelsize": 13,
    "legend.fontsize": 12,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
})

# ===================== 分級門檻（超敏感 & 僅看負載時長） =====================
# 區段邊界（相對 UCL）：0~0.2 / 0.2~0.6 / 0.6~1.0
BAND_LOW = 0.2    # 低: 0.0 ~ 0.2×UCL
BAND_MID = 0.6    # 中: 0.2 ~ 0.6×UCL
# 高: 0.6 ~ 1.0×UCL

# ——「整體判斷(穩定性)」更敏感——
EXCEED_RATIO_HIGH = 1.5         # 超限占比 ≥1.5% → 直接「較高波動」
EXCEED_RATIO_MID  = 0.2         # 超限占比 ≥0.2% → 視為有超限
HIGHLOAD_SHARE_MID = 18.0       # 高負載占比 ≥18% → 至少「中等穩定性」
HIGHLOAD_SHARE_HIGH = 8.0       # 超限<0.2% 且 高載<8% → 「高穩定性」條件之一
SHORT_RUN_SEC = 20.0            # 短工況門檻
SHORT_RUN_EXCEED_HIGH_SEC = 0.2 # 短工況且超限≥0.2s → 直接「較高波動」

# ——「建議(換刀分級)」只看負載占比——
EXCEED_RATIO_CRITICAL = 8.0     # 超限占比 ≥8% → 直接「建議更換(高風險)」
# 高負載/中+高負載對風險的敏感門檻(百分比)
HIGHLOAD_HEALTH_HIGH = 35.0     # 高負載占比 ≥35% 且有超限 → 高風險
HIGHLOAD_HEALTH_MID  = 20.0     # 高負載占比 ≥20% → 至少中風險
MIDHIGH_HEALTH_CRITICAL = 80.0  # (中+高) ≥80% 且有超限 → 高風險
MIDHIGH_HEALTH_WARN    = 60.0   # (中+高) ≥60% → 至少中風險

# ===================== 日誌 =====================
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('machining_report.log', mode='w', encoding='utf-8'),
#         logging.StreamHandler()
#     ]
# )
logger = logging.getLogger(__name__)

# ===================== 模板 =====================
template_content = """
<style>
  /* 放大整體字體 */
  body { font-size: 21px; }
  h1 { text-align: center !important; margin: 0.2em 0 0.6em 0; font-size: 26px; }
  h2, h3, h4, h5, h6, p, li { text-align: left; margin: 0.25em 0; }

  table {
    margin: 0 auto;
    border-collapse: collapse;
    font-size: 20px;              /* 表格內文字放大 */
    table-layout: fixed;
    width: 100%;
    max-width: 760px;
  }
  th, td { text-align: left; padding: 8px 12px; border: 1px solid #333; vertical-align: top; }
  th { background-color: #f2f2f2; }

  .two-col-table { width: 100%; max-width: 760px; border: none; margin-top: 10px; }
  .two-col-table .col-cell { width: 50%; border: 1px solid #333; vertical-align: top; }

  .two-col-analysis { width: 100%; max-width: 760px; border: none; margin: 12px auto; }
  .two-col-analysis td { border: 1px solid #333; vertical-align: top; padding: 8px; }
  .two-col-analysis .col-left  { width: 55%; }
  .two-col-analysis .col-right { width: 45%; }

  /* 讓圖置中 */
  .image-wrapper { text-align: center; width: 100%; padding: 6px; box-sizing: border-box; }
  .image-wrapper img { display: block; margin: 0 auto; max-width: 100%; height: auto; object-fit: contain; }
  .image-wrapper h3, .two-col-table h3 { text-align: center; margin: 0.5em 0; font-size: 22px; }

  .sub-title { font-weight: bold; margin: 8px 0 6px 0; font-size: 22px; }
  .note { font-size: 12px; color: #555; }

  .ucl-table { width: 100%; max-width: 760px; margin-top: 6px; }
  .ucl-table th, .ucl-table td { padding: 6px 10px; }

  /* 總結表格欄寬: 整體判斷70%｜建議30% */
  .summary-table { table-layout: fixed; width: 100%; }
  .summary-table col.col-judge  { width: 70%; }
  .summary-table col.col-adv    { width: 30%; }
  .summary-table th:nth-child(1), .summary-table td:nth-child(1) { width: 70%; }
  .summary-table th:nth-child(2), .summary-table td:nth-child(2) { width: 30%; }

  .summary-list { margin: 6px 0 0 16px; padding: 0; }
  .summary-list li { margin: 4px 0; line-height: 1.3; }
  .nowrap { white-space: nowrap; }

  .judge-header { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .judge-header * { white-space: nowrap; }

  .inline-note { font-size: 11px; color:#666; margin-left: 6px; }
</style>

<h1>加工履歷</h1>

**Date**: {{ sensor_data.Ext.start_date_Time | default('(空白)') }}

## 參數
| **項目** | **內容** | **項目** | **內容** | **項目** | **內容** |
|---|---|---|---|---|---|
| 夾具類型 | {{ Description.HolderType | default('(空白)') }} | YAML 版本 | {{ YAMLVersion | default('(空白)') }} | DesignStlFile 檔名 | {% if Job.DesignStlFile is defined %}{{ Job.DesignStlFile.FileName | default('(空白)') }}{% else %}(空白){% endif %} |
| 機台型號 | {{ Description.NativeName | default('(空白)') }} | HolderID | {{ ToolRelated.Binding.No1.HolderID | default('(空白)') }} | 材料類型 | {% if Job.Material is defined %}{{ Job.Material.Type | default('(空白)') }}{% else %}(空白){% endif %} |
| 控制器 | {{ Description.Controller | default('(空白)') }} | 狀態 | {{ State | default('(空白)') }} | NcFile 檔名 | {% if Job.NcFile is defined %}{{ Job.NcFile.FileName | default('(空白)') }}{% else %}(空白){% endif %} |
| MCID | {{ Description.MCID | default('(空白)') }} | 工件 PartID | {% if Job.Workpiece is defined %}{{ Job.Workpiece.PartIDList | default('(空白)') }}{% else %}(空白){% endif %} | 地點 | {{ Description.Location | default('(空白)') }} |

<table class="two-col-table">
  <tr>
    <!-- 左: Flute View -->
    <td class="col-cell">
      <div class="image-wrapper">
        <h3>Flute View</h3>
        {% if Job.FluteView and Job.FluteView.Image %}
          <img src="{{ Job.FluteView.Image | default('') }}" alt="Flute View">
        {% else %}
          <p class="note">(未提供 Flute View 圖片)</p>
        {% endif %}
      </div>
    </td>
    <!-- 右: Part View -->
    <td class="col-cell">
      <div class="image-wrapper">
        <h3>{{ Job.DesignStlFile.FileName | default('Part View') }}</h3>
        {% if Job.DesignStlFile.Image %}
          <img src="{{ Job.DesignStlFile.Image | default('') }}" alt="{{ Job.DesignStlFile.FileName | default('Part View') }}">
        {% else %}
          <p class="note">(無法生成 STL 圖片, 請檢查 STL 檔案或圖片路徑)</p>
        {% endif %}
      </div>
    </td>
  </tr>
</table>

<!-- ================== Torque ================== -->
<table class="two-col-analysis">
  <tr>
    <td class="col-left">
      <div class="image-wrapper">
        {% if sensor_data.Torque.plot %}
          <img src="{{ sensor_data.Torque.plot }}" alt="Torque">
        {% else %}
          <p class="note">(無 Torque 圖)</p>
        {% endif %}
      </div>
    </td>
    <td class="col-right">
      <div class="sub-title">切削力分析(Torque)</div>
      <table>
        <tr>
          <th>項目</th><th>最大值</th><th>最小值</th><th>平均值</th><th>標準差</th>
        </tr>
        <tr>
          <td>扭矩 (Nm)</td>
          <td>{{ sensor_data.Torque.max | floatformat(3) }}</td>
          <td>{{ sensor_data.Torque.min | floatformat(3) }}</td>
          <td>{{ sensor_data.Torque.mean | floatformat(3) }}</td>
          <td>{{ sensor_data.Torque.std | floatformat(3) }}</td>
        </tr>
      </table>

      <table class="ucl-table">
        <tr><th>管制界線</th><th>UCL</th><th>Warn</th><th>Ref</th></tr>
        <tr>
          <td>值</td>
          <td>{{ sensor_data.Torque.ucl_values_row[0] }}</td>
          <td>{{ sensor_data.Torque.ucl_values_row[1] }}</td>
          <td>{{ sensor_data.Torque.ucl_values_row[2] }}</td>
        </tr>
      </table>

      <div class="sub-title" style="margin-top:8px;">總結</div>
      <table class="summary-table">
        <colgroup>
          <col class="col-judge" />
          <col class="col-adv" />
        </colgroup>
        <tr>
          <th>整體判斷</th><th>建議</th>
        </tr>
        <tr>
          <td>
            <div class="judge-header">
              <b>{{ sensor_data.Torque.stability|default('-') }}</b>
            </div>
            <ul class="summary-list">
              <li>
                低負載時長({{ sensor_data.Torque.low_range_text }}): {{ sensor_data.Torque.low_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Torque.low_share_label }})</span>
                <span class="inline-note">(≤{{ sensor_data.Torque.low_note }})</span>
              </li>
              <li>
                中負載時長({{ sensor_data.Torque.mid_range_text }}): {{ sensor_data.Torque.mid_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Torque.mid_share_label }})</span>
                <span class="inline-note">({{ sensor_data.Torque.mid_note }})</span>
              </li>
              <li>
                高負載時長({{ sensor_data.Torque.high_range_text }}): {{ sensor_data.Torque.high_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Torque.high_share_label }})</span>
                <span class="inline-note">({{ sensor_data.Torque.high_note }})</span>
              </li>
              <li>
                超限時長: {{ sensor_data.Torque.exceed_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Torque.exceed_share_label }})</span>
              </li>
            </ul>
          </td>
          <td>
            <b>{{ sensor_data.Torque.tool_health.level }} ({{ sensor_data.Torque.tool_health.risk }})</b>
            <ul class="summary-list">
              {% for t in sensor_data.Torque.tool_health.triggers %}<li>{{ t }}</li>{% endfor %}
            </ul>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>

<!-- ================== Bending ================== -->
<table class="two-col-analysis">
  <tr>
    <td class="col-left">
      <div class="image-wrapper">
        {% if sensor_data.Bending.plot %}
          <img src="{{ sensor_data.Bending.plot }}" alt="Bending">
        {% else %}
          <p class="note">(無 Bending 圖)</p>
        {% endif %}
      </div>
    </td>
    <td class="col-right">
      <div class="sub-title">切削力分析(Bending)</div>
      <table>
        <tr>
          <th>項目</th><th>最大值</th><th>最小值</th><th>平均值</th><th>標準差</th>
        </tr>
        <tr>
          <td>彎矩 (N)</td>
          <td>{{ sensor_data.Bending.max | floatformat(3) }}</td>
          <td>{{ sensor_data.Bending.min | floatformat(3) }}</td>
          <td>{{ sensor_data.Bending.mean | floatformat(3) }}</td>
          <td>{{ sensor_data.Bending.std | floatformat(3) }}</td>
        </tr>
      </table>

      <table class="ucl-table">
        <tr><th>管制界線</th><th>UCL</th><th>Warn</th><th>Ref</th></tr>
        <tr>
          <td>值</td>
          <td>{{ sensor_data.Bending.ucl_values_row[0] }}</td>
          <td>{{ sensor_data.Bending.ucl_values_row[1] }}</td>
          <td>{{ sensor_data.Bending.ucl_values_row[2] }}</td>
        </tr>
      </table>

      <div class="sub-title" style="margin-top:8px;">總結</div>
      <table class="summary-table">
        <colgroup>
          <col class="col-judge" />
          <col class="col-adv" />
        </colgroup>
        <tr>
          <th>整體判斷</th><th>建議</th>
        </tr>
        <tr>
          <td>
            <div class="judge-header">
              <b>{{ sensor_data.Bending.stability|default('-') }}</b>
            </div>
            <ul class="summary-list">
              <li>
                低負載時長({{ sensor_data.Bending.low_range_text }}): {{ sensor_data.Bending.low_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Bending.low_share_label }})</span>
                <span class="inline-note">(≤{{ sensor_data.Bending.low_note }})</span>
              </li>
              <li>
                中負載時長({{ sensor_data.Bending.mid_range_text }}): {{ sensor_data.Bending.mid_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Bending.mid_share_label }})</span>
                <span class="inline-note">({{ sensor_data.Bending.mid_note }})</span>
              </li>
              <li>
                高負載時長({{ sensor_data.Bending.high_range_text }}): {{ sensor_data.Bending.high_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Bending.high_share_label }})</span>
                <span class="inline-note">({{ sensor_data.Bending.high_note }})</span>
              </li>
              <li>
                超限時長: {{ sensor_data.Bending.exceed_sec_disp|floatformat(1) }}s
                <span class="nowrap">( {{ sensor_data.Bending.exceed_share_label }})</span>
              </li>
            </ul>
          </td>
          <td>
            <b>{{ sensor_data.Bending.tool_health.level }} ({{ sensor_data.Bending.tool_health.risk }})</b>
            <ul class="summary-list">
              {% for t in sensor_data.Bending.tool_health.triggers %}<li>{{ t }}</li>{% endfor %}
            </ul>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
"""

# ===================== 小工具 =====================
def parse_time_tag(time_str):
    try:
        time_str = time_str.strip('"')
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f')
        return dt.timestamp()
    except Exception as e:
        logger.warning(f"無法解析 TimeTag {time_str}: {e}")
        return None

def format_time_axis(seconds, _):
    if seconds is None or np.isnan(seconds):
        return "00:00"
    minutes = int(seconds // 60)
    seconds_part = int(seconds % 60)
    return f"{minutes:02d}:{seconds_part:02d}"

def image_to_base64(image_path):
    try:
        with open(image_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
        return f"data:image/png;base64,{encoded}"
    except FileNotFoundError:
        logger.warning(f"圖片文件 {image_path} 不存在, 使用空字符串代替")
        return ""

def find_wkhtmltopdf():
    p = shutil.which('wkhtmltopdf')
    if p and os.path.exists(p):
        logger.info(f"在 PATH 找到 wkhtmltopdf: {p}")
        return p
    system = platform.system().lower()

    relative_path = r'./wkhtmltox/bin/wkhtmltopdf.exe'
    if 'windows' in system:

        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))


        relative_path = os.path.join(base_path, relative_path)

    candidates = ([
        f"{relative_path}",
        r'C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe',
        r'C:\\Program Files (x86)\\wkhtmltopdf\\bin\\wkhtmltopdf.exe',

    ] if 'windows' in system else [
        '/usr/bin/wkhtmltopdf',
        '/usr/local/bin/wkhtmltopdf'
    ])
    for c in candidates:
        if os.path.exists(c):
            logger.info(f"在常見路徑找到 wkhtmltopdf: {c}")
            return c
    logger.warning("未偵測到 wkhtmltopdf(將跳過 PDF 輸出)")
    return None

def round_preserving_sum(values, target_sum, decimals=0):
    """Largest Remainder: 顯示位數四捨五入, 同時保證加總=目標。"""
    import math
    scale = 10 ** decimals
    vals = [0.0 if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v) for v in values]
    floors = [math.floor(v * scale) for v in vals]
    need = int(round(target_sum * scale)) - sum(floors)
    fracs = [(i, (vals[i] * scale) - floors[i]) for i in range(len(vals))]
    fracs.sort(key=lambda x: x[1], reverse=True)
    rounded = floors[:]
    if need >= 0:
        for i in range(need):
            rounded[fracs[i % len(vals)][0]] += 1
    else:
        fracs.reverse()
        for i in range(-need):
            rounded[fracs[i % len(vals)][0]] -= 1
    return [r / scale for r in rounded]

def _pct_label(pct_disp, sec_disp):
    """顯示用: 若有秒數但整數百分比為0, 顯示 <1% 。"""
    p = int(round(pct_disp))
    return "<1%" if (sec_disp > 0 and p == 0) else f"{p}%"

# ========= 全域標點半形化 =========
_HALFWIDTH_TRANS = str.maketrans({
    "，": ",", "。": ".", "、": ",", "；": ";", "：": ":", "！": "!", "？": "?",
    "（": "(", "）": ")", "【": "[", "】": "]", "「": "\"", "」": "\"",
    "『": "\"", "』": "\"", "～": "~", "—": "-", "－": "-", "…": "...",
    "＂": "\"", "＇": "'", "％": "%", "｜": "|", "／": "/", "＼": "\\",
    "＃": "#", "＆": "&", "＊": "*", "＠": "@", "＋": "+", "＝": "=",
    "＜": "<", "＞": ">", "｛": "{", "｝": "}", "　": " "
})
def to_halfwidth_punct(s):
    if not isinstance(s, str):
        return s
    return s.translate(_HALFWIDTH_TRANS)

# ===================== 僅依負載時長的換刀判斷 =====================
def derive_tool_health_by_duration(share_low, share_mid, share_high, exceed_pct):
    """
    只根據負載區間占比(低/中/高/超限)輸出建議。
    """
    triggers = []
    level = "可續用"; risk = "低風險"

    mid_high_sum = share_mid + share_high

    # 高風險(任一)
    if exceed_pct >= EXCEED_RATIO_CRITICAL:
        level, risk = "建議更換", "高風險"
        triggers.append("超限占比高")
        return {"level": level, "risk": risk, "triggers": triggers}

    if (share_high >= HIGHLOAD_HEALTH_HIGH and exceed_pct >= EXCEED_RATIO_MID):
        level, risk = "建議更換", "高風險"
        triggers.append("高負載占比長且伴隨超限")
        return {"level": level, "risk": risk, "triggers": triggers}

    if (mid_high_sum >= MIDHIGH_HEALTH_CRITICAL and exceed_pct > 0.0):
        level, risk = "建議更換", "高風險"
        triggers.append("中高負載占比極高且出現超限")
        return {"level": level, "risk": risk, "triggers": triggers}

    # 中風險(任一)
    if exceed_pct >= EXCEED_RATIO_HIGH:
        level, risk = "觀察中", "中風險"
        triggers.append("超限占比偏高")
    elif share_high >= HIGHLOAD_HEALTH_MID:
        level, risk = "觀察中", "中風險"
        triggers.append("高負載占比偏高")
    elif mid_high_sum >= MIDHIGH_HEALTH_WARN:
        level, risk = "觀察中", "中風險"
        triggers.append("中高負載占比偏高")
    else:
        triggers = ["超限占比低, 主導負載在低/中區"]

    return {"level": level, "risk": risk, "triggers": triggers}

# ===================== STL → PNG =====================
def generate_stl_image(stl_path, output_path):
    try:
        if not os.path.exists(stl_path):
            raise FileNotFoundError(f"STL 檔案不存在: {stl_path}")
        mesh = trimesh.load(stl_path, file_type='stl', force='mesh')
        logger.info(f"成功載入 STL: {stl_path}, 頂點數: {len(mesh.vertices)}")
        mesh.apply_translation(-mesh.centroid)
        bounds = mesh.bounds
        size = bounds[1] - bounds[0]
        max_dim = float(np.max(size))
        norm_scale = 1.0 if (max_dim <= 0 or np.isnan(max_dim)) else (0.8 / max_dim)
        if abs(norm_scale - 1.0) > 1e-12:
            mesh.apply_scale(norm_scale)
        size_norm = mesh.bounds[1] - mesh.bounds[0]
        max_dim_norm = float(np.max(size_norm)) if size_norm.size else 1.0

        base_eye = np.array([1.5, 1.5, 1.4]) * 1.6
        eye_vec = tuple(base_eye.tolist())
        aspectratio = dict(
            x=float(size_norm[0]) / max_dim_norm if max_dim_norm > 0 else 1.0,
            y=float(size_norm[1]) / max_dim_norm if max_dim_norm > 0 else 1.0,
            z=float(size_norm[2]) / max_dim_norm if max_dim_norm > 0 else 1.0
        )
        v = mesh.vertices; f = mesh.faces
        fig = go.Figure(data=[go.Mesh3d(
            x=v[:, 0], y=v[:, 1], z=v[:, 2],
            i=f[:, 0], j=f[:, 1], k=f[:, 2],
            color='#4682b4', opacity=0.5, flatshading=True,
            lighting=dict(ambient=0.5, diffuse=0.2, specular=0.2, fresnel=1)
        )])
        fig.update_layout(
            scene=dict(
                xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False),
                aspectmode='data', aspectratio=aspectratio,
                camera=dict(eye=dict(x=eye_vec[0], y=eye_vec[1], z=eye_vec[2]), center=dict(x=0, y=0, z=0))
            ),
            margin=dict(l=0, r=0, b=0, t=0), width=350, height=350
        )
        pio.write_image(fig, file=output_path, format='png')
        logger.info(f"成功生成 PNG: {output_path}")
        return True
    except Exception as e:
        logger.error(f"處理 STL 失敗: {e}")
        return False

# ===================== 讀 config =====================
def load_config(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as file:
            cfg = json.load(file)
        for key in ['TORQUE_UCL', 'BENDING_UCL']:
            if key not in cfg:
                raise KeyError(f"config.json 缺少必要鍵: {key}")
            for ucl in cfg[key]:
                if not isinstance(ucl, dict) or 'value' not in ucl or 'color' not in ucl:
                    raise ValueError(f"{key} 項需含 'value' 與 'color'")
                if isinstance(ucl['value'], list):
                    if len(ucl['value']) == 1:
                        ucl['value'] = float(ucl['value'][0])
                    else:
                        raise ValueError(f"{key} 的 value 應為單一數值")
                if not isinstance(ucl['value'], (int, float)):
                    raise ValueError(f"{key} 的 value 必須為數值: {ucl['value']}")
                
        flute_ucl = []
        if isinstance(cfg.get("FLUTE_UCL"), list):
            flute_ucl = sorted(cfg["FLUTE_UCL"], key=lambda x: float(x["value"])
                               )
        return {'TORQUE_UCL': cfg['TORQUE_UCL'], 'BENDING_UCL': cfg['BENDING_UCL'], 'FLUTE_UCL': flute_ucl}
    except Exception as e:
        logger.error(f"讀取 config.json 失敗: {e}")
        raise

# ===================== 係數工具 =====================
def _to_float(x, default=1.0):
    try: return float(x)
    except Exception: return float(default)

def _get_keys_like(row_like):
    if hasattr(row_like, "index"): return list(row_like.index)
    if hasattr(row_like, "keys"):  return list(row_like.keys())
    return []

def _pick_coeff(row_like, base_name, default=1.0):
    keys = set(_get_keys_like(row_like))
    if f"{base_name}_Coeff" in keys: return _to_float(row_like[f"{base_name}_Coeff"], default)
    if base_name in keys:            return _to_float(row_like[base_name], default)
    return float(default)

# ===================== 感測資料處理 =====================
def process_sensor_data(coeff_file, sensor_file, holder_id, config):
    try:
        # 係數
        coeff_df = pd.read_csv(coeff_file)
        coeff_row = coeff_df[coeff_df['MAC'] == holder_id]
        row = coeff_row.iloc[0] if not coeff_row.empty else (coeff_df.iloc[0] if not coeff_df.empty else {})
        coeffs = {
            'Torque':   _pick_coeff(row, 'Torque',   1.0),
            'BendingX': _pick_coeff(row, 'BendingX', 1.0),
            'BendingY': _pick_coeff(row, 'BendingY', 1.0),
            'CH1':      _pick_coeff(row, 'CH1',      1.0),
            'CH2':      _pick_coeff(row, 'CH2',      1.0),
        }

        # 讀取感測
        use_cols = ['TimeTag','Torque','BendingX','BendingY']
        df = pd.read_csv(sensor_file, skipinitialspace=True, na_values=['', 'NA', 'N/A', 'null', 'Null', '--'])
        df.columns = df.columns.str.strip()
        df = df[[c for c in use_cols if c in df.columns]]
        for c in ['Torque','BendingX','BendingY']:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=[c for c in ['Torque','BendingX','BendingY'] if c in df.columns])
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

        # 時間軸
        start_date_Time = ""
        try:

            df['TimeTag'] = df['TimeTag'].apply(parse_time_tag)
            TimeTag_st = datetime.fromtimestamp(df['TimeTag'][0])
            if isinstance(TimeTag_st,datetime) is True:
                start_date_Time = TimeTag_st.strftime("%Y-%m-%d %H:%M:%S")
            if df['TimeTag'].isnull().any():
                df['TimeTag'] = np.arange(len(df)) * 0.01
            else:
                df['TimeTag'] -= df['TimeTag'].iloc[0]
        except Exception:
            df['TimeTag'] = np.arange(len(df)) * 0.01

        # 套係數
        df['Torque']   = df['Torque']   * coeffs['Torque']
        df['BendingX'] = df['BendingX'] * coeffs['BendingX']
        df['BendingY'] = df['BendingY'] * coeffs['BendingY']

        # UCL
        t_sorted = sorted(config['TORQUE_UCL'], key=lambda x: x['value'], reverse=True)
        torque_ucl_val = float(t_sorted[0]['value'])
        b_val = float(config['BENDING_UCL'][0]['value'])

        # 顯示用區間字串(~)與註記
        torque_low_text   = f"0.000~{BAND_LOW*torque_ucl_val:.3f}"
        torque_mid_text   = f"{BAND_LOW*torque_ucl_val:.3f}~{BAND_MID*torque_ucl_val:.3f}"
        torque_high_text  = f"{BAND_MID*torque_ucl_val:.3f}~{torque_ucl_val:.3f}"
        bending_low_text  = f"0.000~{BAND_LOW*b_val:.3f}"
        bending_mid_text  = f"{BAND_LOW*b_val:.3f}~{BAND_MID*b_val:.3f}"
        bending_high_text = f"{BAND_MID*b_val:.3f}~{b_val:.3f}"

        low_note  = f"{BAND_LOW:.1f}×UCL"
        mid_note  = f"{BAND_LOW:.1f}~{BAND_MID:.1f}×UCL"
        high_note = f"{BAND_MID:.1f}~1.0×UCL"

        # 時間/比例
        t = df['TimeTag'].to_numpy(dtype=float)
        total_sec = float(t[-1] - t[0]) if len(t) >= 2 else 0.0
        total_sec = max(total_sec, 0.0)

        def _sum_time(mask, t_arr):
            if t_arr is None or len(t_arr) < 2 or mask is None or len(mask) != len(t_arr):
                return 0.0
            dt = np.diff(t_arr)
            return float(np.sum(dt[mask[1:]])) if dt.size == (len(mask)-1) else 0.0

        # Torque 四段(0~0.2 / 0.2~0.6 / 0.6~1.0 / >1.0)
        torque = df['Torque'].to_numpy(dtype=float)
        mask_low_t  = (torque <= BAND_LOW*torque_ucl_val)
        mask_mid_t  = (torque > BAND_LOW*torque_ucl_val) & (torque <= BAND_MID*torque_ucl_val)
        mask_high_t = (torque > BAND_MID*torque_ucl_val) & (torque <= torque_ucl_val)
        exceed_t_mask = (torque > torque_ucl_val)

        low_t_sec   = _sum_time(mask_low_t, t)
        mid_t_sec   = _sum_time(mask_mid_t, t)
        high_t_sec  = _sum_time(mask_high_t, t)
        exceed_t_sec= _sum_time(exceed_t_mask, t)

        low_t_share   = (low_t_sec   / total_sec * 100.0) if total_sec > 0 else 0.0
        mid_t_share   = (mid_t_sec   / total_sec * 100.0) if total_sec > 0 else 0.0
        high_t_share  = (high_t_sec  / total_sec * 100.0) if total_sec > 0 else 0.0
        exceed_t_ratio= (exceed_t_sec/ total_sec * 100.0) if total_sec > 0 else 0.0

        # 彎矩(用 BendingX 絕對值)
        bending = df['BendingX'].to_numpy(dtype=float)
        b_abs = np.abs(bending)
        mask_low_b  = (b_abs <= BAND_LOW*b_val)
        mask_mid_b  = (b_abs > BAND_LOW*b_val) & (b_abs <= BAND_MID*b_val)
        mask_high_b = (b_abs > BAND_MID*b_val) & (b_abs <= b_val)
        exceed_b_mask = (b_abs > b_val)

        low_b_sec   = _sum_time(mask_low_b, t)
        mid_b_sec   = _sum_time(mask_mid_b, t)
        high_b_sec  = _sum_time(mask_high_b, t)
        exceed_b_sec= _sum_time(exceed_b_mask, t)

        low_b_share   = (low_b_sec   / total_sec * 100.0) if total_sec > 0 else 0.0
        mid_b_share   = (mid_b_sec   / total_sec * 100.0) if total_sec > 0 else 0.0
        high_b_share  = (high_b_sec  / total_sec * 100.0) if total_sec > 0 else 0.0
        exceed_b_ratio= (exceed_b_sec/ total_sec * 100.0) if total_sec > 0 else 0.0

        # ===== 顯示用保和四捨五入(秒: 0.1; 占比: 整數%) =====
        # Torque
        t_sec_disp = round_preserving_sum([low_t_sec, mid_t_sec, high_t_sec, exceed_t_sec], total_sec, decimals=1)
        t_pct_disp = round_preserving_sum([low_t_share, mid_t_share, high_t_share, exceed_t_ratio], 100.0, decimals=0)
        (low_t_sec_d, mid_t_sec_d, high_t_sec_d, exceed_t_sec_d) = t_sec_disp
        (low_t_pct_d, mid_t_pct_d, high_t_pct_d, exceed_t_pct_d) = t_pct_disp
        # 彎矩
        b_sec_disp = round_preserving_sum([low_b_sec, mid_b_sec, high_b_sec, exceed_b_sec], total_sec, decimals=1)
        b_pct_disp = round_preserving_sum([low_b_share, mid_b_share, high_b_share, exceed_b_ratio], 100.0, decimals=0)
        (low_b_sec_d, mid_b_sec_d, high_b_sec_d, exceed_b_sec_d) = b_sec_disp
        (low_b_pct_d, mid_b_pct_d, high_b_pct_d, exceed_b_pct_d) = b_pct_disp

        # 顯示用占比標籤(避免有秒數卻顯示 0%)
        t_low_label    = _pct_label(low_t_pct_d,   low_t_sec_d)
        t_mid_label    = _pct_label(mid_t_pct_d,   mid_t_sec_d)
        t_high_label   = _pct_label(high_t_pct_d,  high_t_sec_d)
        t_exceed_label = _pct_label(exceed_t_pct_d, exceed_t_sec_d)

        b_low_label    = _pct_label(low_b_pct_d,   low_b_sec_d)
        b_mid_label    = _pct_label(mid_b_pct_d,   mid_b_sec_d)
        b_high_label   = _pct_label(high_b_pct_d,  high_b_sec_d)
        b_exceed_label = _pct_label(exceed_b_pct_d, exceed_b_sec_d)

        # ===== 整體穩定性(更敏感) =====
        def grade(total, exceed_sec, exceed_ratio, high_share):
            if (exceed_ratio >= EXCEED_RATIO_HIGH) or (total <= SHORT_RUN_SEC and exceed_sec >= SHORT_RUN_EXCEED_HIGH_SEC):
                return "較高波動"
            if (EXCEED_RATIO_MID <= exceed_ratio < EXCEED_RATIO_HIGH) or (high_share >= HIGHLOAD_SHARE_MID):
                return "中等穩定性"
            if (exceed_ratio < EXCEED_RATIO_MID) and (high_share < HIGHLOAD_SHARE_HIGH):
                return "高穩定性"
            return "中等穩定性"

        torque_grade  = grade(total_sec, exceed_t_sec, exceed_t_ratio, high_t_share)
        bending_grade = grade(total_sec, exceed_b_sec, exceed_b_ratio, high_b_share)

        # ===== 換刀判斷(僅依負載時長) =====
        torque_health  = derive_tool_health_by_duration(low_t_share, mid_t_share, high_t_share, exceed_t_ratio)
        bending_health = derive_tool_health_by_duration(low_b_share, mid_b_share, high_b_share, exceed_b_ratio)

        # 圖輸出
        csv_base_name = os.path.splitext(os.path.basename(sensor_file))[0]
        csv_dir = os.path.dirname(sensor_file)
        plot_dir = os.path.join(csv_dir, csv_base_name); os.makedirs(plot_dir, exist_ok=True)

        # Torque 圖 — 固定 Y 軸上限為 3×UCL
        plt.figure(figsize=(8, 4))
        plt.plot(df['TimeTag'], df['Torque'], label='Torque')

        for i, ucl in enumerate(t_sorted):
            # UCL 為零時不繪製
            if float(ucl["value"]) <= 0: continue

            label = 'UCL' if i == 0 else 'Warn' if i == 1 else 'Ref'
            plt.axhline(y=ucl['value'], color=ucl['color'], linestyle='--', label=label)
        plt.xlabel('Time (mm:ss)'); plt.ylabel('Torque (Nm)'); plt.title('Torque')
        plt.legend(); plt.grid(True)
        plt.gca().xaxis.set_major_formatter(ticker.FuncFormatter(format_time_axis))
        if torque_ucl_val > 0:
            plt.ylim(0, 3.0 * torque_ucl_val)
        torque_plot_path = os.path.join(plot_dir, f"{csv_base_name}_torque_plot.png")
        plt.savefig(torque_plot_path, dpi=110, bbox_inches="tight"); plt.close()

        # 彎矩 圖(N) — 固定 Y 軸為 ±(3×UCL)
        plt.figure(figsize=(8, 4))
        plt.plot(df['TimeTag'], df['BendingX'], label='Bending')
        if b_val > 0.0:

            bend_color = config['BENDING_UCL'][0]['color']
            plt.axhline(y=b_val,  color=bend_color, linestyle='--', label='UCL')
            plt.axhline(y=-b_val, color=bend_color, linestyle='--')
        plt.xlabel('Time (mm:ss)'); plt.ylabel('Bending (N)'); plt.title('Bending')
        plt.legend(); plt.grid(True)
        plt.gca().xaxis.set_major_formatter(ticker.FuncFormatter(format_time_axis))
        if b_val > 0:
            plt.ylim(-3.0 * b_val, 3.0 * b_val)
        bending_plot_path = os.path.join(plot_dir, f"{csv_base_name}_bending_plot.png")
        plt.savefig(bending_plot_path, dpi=110, bbox_inches="tight"); plt.close()

        # UCL 列
        torque_ucl_values_row = [f'{float(t_sorted[i]["value"]):.3f}' if i < len(t_sorted) else '-' for i in range(3)]
        bending_ucl_values_row = [f'±{b_val:.3f}', '-', '-']

        # 統計輸出
        stats = {
            'Ext':{

              'start_date_Time':start_date_Time
            },
            'Torque': {
                'name': '扭矩 (Nm)',
                'max': df['Torque'].max(), 'min': df['Torque'].min(),
                'mean': df['Torque'].mean(), 'std': df['Torque'].std(),
                'ucl_values_row': torque_ucl_values_row,
                'ucl_values': [ucl['value'] for ucl in t_sorted],
                'plot': image_to_base64(torque_plot_path),
                'total_sec': total_sec,

                'low_range_text': torque_low_text,
                'mid_range_text': torque_mid_text,
                'high_range_text': torque_high_text,
                'low_note': low_note, 'mid_note': mid_note, 'high_note': high_note,

                'low_sec': low_t_sec, 'mid_sec': mid_t_sec, 'high_load_sec': high_t_sec, 'exceed_total_sec': exceed_t_sec,
                'low_share': low_t_share, 'mid_share': mid_t_share, 'high_load_share': high_t_share, 'exceed_ratio': exceed_t_ratio,

                # 顯示用
                'low_sec_disp': low_t_sec_d, 'mid_sec_disp': mid_t_sec_d, 'high_sec_disp': high_t_sec_d, 'exceed_sec_disp': exceed_t_sec_d,
                'low_share_disp': low_t_pct_d, 'mid_share_disp': mid_t_pct_d, 'high_share_disp': high_t_pct_d, 'exceed_share_disp': exceed_t_pct_d,
                'low_share_label': t_low_label, 'mid_share_label': t_mid_label, 'high_share_label': t_high_label, 'exceed_share_label': t_exceed_label,

                'stability': torque_grade,
                'tool_health': torque_health
            },
            'Bending': {
                'name': '彎矩 (N)',
                'max': df['BendingX'].max(), 'min': df['BendingX'].min(),
                'mean': df['BendingX'].mean(), 'std': df['BendingX'].std(),
                'ucl_values_row': bending_ucl_values_row,
                'ucl_values': [ucl['value'] for ucl in config['BENDING_UCL']],
                'plot': image_to_base64(bending_plot_path),
                'total_sec': total_sec,

                'low_range_text': bending_low_text,
                'mid_range_text': bending_mid_text,
                'high_range_text': bending_high_text,
                'low_note': low_note, 'mid_note': mid_note, 'high_note': high_note,

                'low_sec': low_b_sec, 'mid_sec': mid_b_sec, 'high_load_sec': high_b_sec, 'exceed_total_sec': exceed_b_sec,
                'low_share': low_b_share, 'mid_share': mid_b_share, 'high_load_share': high_b_share, 'exceed_ratio': exceed_b_ratio,

                # 顯示用
                'low_sec_disp': low_b_sec_d, 'mid_sec_disp': mid_b_sec_d, 'high_sec_disp': high_b_sec_d, 'exceed_sec_disp': exceed_b_sec_d,
                'low_share_disp': low_b_pct_d, 'mid_share_disp': mid_b_pct_d, 'high_share_disp': high_b_pct_d, 'exceed_share_disp': exceed_b_pct_d,
                'low_share_label': b_low_label, 'mid_share_label': b_mid_label, 'high_share_label': b_high_label, 'exceed_share_label': b_exceed_label,

                'stability': bending_grade,
                'tool_health': bending_health
            }
        }
        return stats

    except Exception as e:
        logger.error(f"處理感測器數據失敗: {e}")
        return None

# ===================== Flute View(選配) =====================
def _flute_color_by_threshold(distances, warn_value, warn_color):
    """
    根據 UCL 計算 Flute View 散點顏色。
    當 UCL <= 0 時，不判斷超限，所有點使用藍色。
    """
    if warn_value <= 0: return ["blue"] * len(distances)
    colors = []
    ucl_value = 2.0 * warn_value
    for d in distances:
        if d <= warn_value: colors.append("blue")
        elif d <= ucl_value: colors.append(warn_color)
        else: colors.append("red")
    return colors

def _flute_plot_and_save(ch1, ch2, warn_value, warn_color, out_png):
    """
    將 Flute View 轉成 PNG。

    UCL > 0:
        顯示 Warn / UCL 圓圈，使用原本固定範圍。

    UCL <= 0:
        不顯示管制圓圈，依據 CH1 / CH2 資料自動設定座標範圍。
    """
    # 固定座標範圍到 ±(3×UCL) = ±(6×warn_value)
    # ucl_value = 2.0 * warn_value
    # axis_lim = 3.0 * ucl_value  # = 6×warn
    distances = np.sqrt(ch1**2 + ch2**2)
    colors = _flute_color_by_threshold(distances, warn_value, warn_color)

    fig, ax = plt.subplots(figsize=(6.5, 6.5), dpi=120)
    ax.scatter(ch1, ch2, s=12, c=colors, edgecolors="none", alpha=0.8)
  
    if warn_value > 0: # 有 UCL
        ucl_value = 2.0 * warn_value
        axis_lim = 3.0 * ucl_value

        # 圓圈
        ax.add_patch(Circle((0, 0), radius=warn_value,   fill=False, linestyle="--", linewidth=2, edgecolor=warn_color, label=f"Warn ({warn_value:.3f})"))
        ax.add_patch(Circle((0, 0), radius=ucl_value,    fill=False, linestyle="--", linewidth=2, edgecolor="red", label=f"UCL ({ucl_value:.3f})"))
        ax.legend(loc="upper right")

    else: # 無 UCL
        # 根據 CH1 / CH2 的絕對值設定座標範圍
        max_ch1 = float(np.max(np.abs(ch1))) if len(ch1) else 0.0
        max_ch2 = float(np.max(np.abs(ch2))) if len(ch2) else 0.0

        max_data_val = max(max_ch1, max_ch2)
        axis_lim = max(max_data_val * 3, 0.01) # 留出 3 倍邊界

        # 沒有 UCL 時不繪製管制圓圈
        logger.info(f"Flute UCL 未設定，使用資料範圍 ±{axis_lim:.4f}")

    ax.set_xlim(-axis_lim, axis_lim)
    ax.set_ylim(-axis_lim, axis_lim)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.9)

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_png

def build_flute_from_csv(sensor_csv_path, coeff_file, holder_id, config):
    try:
        coeff_df = pd.read_csv(coeff_file)
        coeff_row = coeff_df[coeff_df['MAC'] == holder_id] if 'MAC' in coeff_df.columns else pd.DataFrame()
        row = coeff_row.iloc[0] if not coeff_row.empty else (coeff_df.iloc[0] if not coeff_df.empty else {})
        ch1_k = _pick_coeff(row, 'CH1', 1.0); ch2_k = _pick_coeff(row, 'CH2', 1.0)

        df = pd.read_csv(sensor_csv_path, skipinitialspace=True, na_values=['', 'NA', 'N/A', 'null', 'Null', '--'])
        df.columns = df.columns.str.strip(); df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        if 'CH1' not in df.columns or 'CH2' not in df.columns:
            logger.warning("CSV 缺少 CH1/CH2, 略過 Flute View。"); return '', ''

        mask_dup = df['CH1'].astype(str).eq('CH1') | df['CH2'].astype(str).eq('CH2')
        df = df[~mask_dup].copy()
        df['CH1'] = pd.to_numeric(df['CH1'], errors='coerce')
        df['CH2'] = pd.to_numeric(df['CH2'], errors='coerce')
        df = df.dropna(subset=['CH1','CH2']).reset_index(drop=True)

        ch1 = df['CH1'].to_numpy(dtype=float) * float(ch1_k)
        ch2 = df['CH2'].to_numpy(dtype=float) * float(ch2_k)

        # 讀取 FLUTE_UCL，沒有正值時停用管制線，但仍生成圖片
        flute_ucls = config.get("FLUTE_UCL") or []

        valid_ucls = [item for item in flute_ucls if float(item.get("value", 0)) > 0]

        if valid_ucls:
            warn_item = min(valid_ucls, key=lambda item: float(item["value"]))
            warn_value = float(warn_item["value"])
            warn_color = str(warn_item.get("color", "orange"))

        else:
            warn_value = 0.0
            warn_color = "orange"

        csv_base_name = os.path.splitext(os.path.basename(sensor_csv_path))[0]
        png = os.path.join(os.path.dirname(sensor_csv_path), csv_base_name, f"{csv_base_name}_flute_view.png")
        os.makedirs(os.path.dirname(png), exist_ok=True)
        _flute_plot_and_save(ch1, ch2, warn_value, warn_color, png)
        return png, image_to_base64(png)
    except Exception as e:
        logger.error(f"Flute View 生成失敗: {e}")
        return '', ''

# ===================== 報告主流程 =====================
def generate_machining_report(yaml_path, coeff_file, sensor_file, config_path,
                              stl_path, flute_img_path, output_md_path, output_pdf_path, temp_html_path):
    config = load_config(config_path)
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"找不到 YAML: {yaml_path}")
        return

    # 圖片欄位
    for key in ['ReviewImage']:
        if yaml_data.get('Description', {}).get(key):
            yaml_data['Description'][key] = image_to_base64(yaml_data['Description'][key])

    yaml_data.setdefault('Job', {}).setdefault('DesignStlFile', {})

    # 預設從 YAML 讀取原始圖片路徑
    yaml_image_path = yaml_data['Job']['DesignStlFile'].get('Image')

    if stl_path:
        csv_base = os.path.splitext(os.path.basename(sensor_file))[0]
        out_dir = os.path.join(os.path.dirname(sensor_file), csv_base); os.makedirs(out_dir, exist_ok=True)
        stl_png = os.path.join(out_dir, f"{csv_base}_part_view.png")
        if generate_stl_image(stl_path, stl_png):
            yaml_data['Job']['DesignStlFile']['Image'] = image_to_base64(stl_png)
        else:
            logger.warning(f"STL 處理失敗, 嘗試使用 YAML 中 DesignStlFile.Image: {yaml_image_path}")
            yaml_data['Job']['DesignStlFile']['Image'] = image_to_base64(yaml_image_path) if yaml_image_path else ''
    else:
        # 沒有提供 STL 路徑: 嘗試使用 YAML 提供的圖片路徑
        yaml_data['Job']['DesignStlFile']['Image'] = image_to_base64(yaml_image_path) if yaml_image_path else ''

    # Flute View
    yaml_data['Job'].setdefault('FluteView', {})
    holder_id = yaml_data.get('ToolRelated', {}).get('Binding', {}).get('No1', {}).get('HolderID', '')
    if flute_img_path:
        yaml_data['Job']['FluteView']['Image'] = image_to_base64(flute_img_path)
    else:
        auto_png, auto_b64 = build_flute_from_csv(sensor_file, coeff_file, holder_id, config)
        yaml_data['Job']['FluteView']['Image'] = auto_b64 if auto_b64 else ''

    # 感測統計
    sensor_data = process_sensor_data(coeff_file, sensor_file, holder_id, config)
    yaml_data['sensor_data'] = sensor_data if sensor_data else {}

    # 渲染
    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    def default_filter(value, default_value='(空白)'):
        return value if value not in (None, '', []) else default_value
    def floatformat(value, digits=3):
        try:
            return f"{float(value):.{digits}f}"
        except (ValueError, TypeError):
            return default_filter(value, '')
    env.filters['default'] = default_filter
    env.filters['floatformat'] = floatformat

    template = env.from_string(template_content)
    rendered_md = template.render(**yaml_data)

    # ===== 全域標點半形化 =====
    rendered_md = to_halfwidth_punct(rendered_md)

    # 輸出 MD
    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write(rendered_md)

    # MD → HTML
    md = markdown.Markdown(extensions=['tables'])
    html_content = md.convert(rendered_md)
    html_with_style = f"""<html><head><meta charset="UTF-8"></head><body>{html_content}</body></html>"""
    with open(temp_html_path, 'w', encoding='utf-8') as f:
        f.write(html_with_style)

    # HTML → PDF(自動偵測)
    wkhtmltopdf_path = find_wkhtmltopdf()
    if wkhtmltopdf_path:
        try:
            pdf_config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
            pdfkit.from_file(
                temp_html_path, output_pdf_path, configuration=pdf_config,
                options={
                    'encoding': 'UTF-8','page-size': 'A4',
                    'margin-top': '5mm','margin-bottom': '5mm','margin-left': '5mm','margin-right': '5mm',
                    'zoom': 0.664
                }
            )
            logger.info(f"已輸出 PDF: {output_pdf_path}")
        except Exception as e:
            logger.error(f"無法生成 PDF: {e}")
    else:
        logger.warning("wkhtmltopdf 未找到, PDF 生成跳過。")

def generate_report(yaml, coeff, sensor, config, stl=None, flute_img=None,
                    output_md=None, output_pdf=None, temp_html="temp.html"):
    base = os.path.splitext(os.path.basename(sensor))[0]
    output_md = output_md or os.path.join(os.path.dirname(sensor), f"{base}.md")
    output_pdf = output_pdf or os.path.join(os.path.dirname(sensor), f"{base}_report.pdf")
    temp_html = temp_html or os.path.join(os.path.dirname(sensor), f"{base}.tmp.html")
    generate_machining_report(yaml, coeff, sensor, config, stl, flute_img, output_md, output_pdf, temp_html)
    return output_pdf

# ===================== CLI =====================
def main():
    parser = argparse.ArgumentParser(description="加工履歷(只看負載時長, 超敏感門檻, 放大字體, 固定Y軸到3×UCL, 圖置中, 全域標點半形化, 視圖交換, wkhtmltopdf 自動偵測)")
    parser.add_argument('--yaml', required=True)
    parser.add_argument('--coeff', required=True)
    parser.add_argument('--sensor', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--stl', required=False)
    parser.add_argument('--flute-img', required=False)
    parser.add_argument('--output-md', required=False)
    parser.add_argument('--output-pdf', required=False)
    parser.add_argument('--temp-html', default='temp.html')
    args = parser.parse_args()
    generate_machining_report(args.yaml, args.coeff, args.sensor, args.config,
                              args.stl, args.flute_img, args.output_md, args.output_pdf, args.temp_html)


if __name__ == "__main__":
    main()
