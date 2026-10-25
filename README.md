樹莓派機邊黑盒子所運行的 Dash 程式，可在 PC 執行

# 下面是版本更新所新增或修改的內容

## C2 版修改內容:
1. Upload YAML 按鈕改名為 Upload Work Order
2. Select YAML file 改名為 Select Work Order
3. 刪除 Machining Parameters 標題
4. Edit Config 移到最下方
5. Send HolderID 改名為 Start Order
6. Send CNC IP 下面分成獨立區塊
7. Select CSV file 改名為 Order Outcome
8. Download CSV 改名為 Download Outcome
9. Cycle Start / End 改名為  Manual Start / End 後移到左下
10. Torque UCL Light Signal 改名為 Force Control Limit
11. Connection Start / End 改名為 Machining State
12. 新增 Flute Life 燈號
13. 刪除 Flute View 的 CH1 CH2 文字
14. Torque Over Time 的 UCL 改名為 UCL_R、UCL_O 和 Ref
15. Torque / Bending Over Time 改名為 Torque / Bending
16. Edit YAML and config.json 改名為 Edit Order Outcome and config.json
17. YAML Content 改名為 Order Outcome Content
18. Btnding UCL 改名為 Control Limit
19. 新增 STH link 判斷是否連線上智慧刀把

## C3 版修改內容:
1. 首次開啟網頁或是手動刷新網頁時會更新 Raspberry Pi 系統時間以及重製圖表數據為零
2. 當視窗較小時會自動調整布局
3. 檔案名稱統一小寫
4. 修正 Edit Config 功能中的名詞錯誤
5. Order Outcome 位置改為 ../holder_main/data/cov
6. 當 FLUTE_UCL、BENDING_UCL、TORQUE_UCL 設為零可以關閉管制界線功能
7. 新增按鈕按下 Generate Report 產生加工履歷
8. 將燈號 Force Control Limit 和 Flute Control Limit 預設改為灰色
9. 將按鈕 Start Order 改為 Link STH 
10. 修改頂部以及左下面板內容的佈局
11. 將 Job State 更改為 Control State

## D 版修改內容:
1.  首次開啟網頁或是手動刷新網頁時會更新 Raspberry Pi 系統時間以及重製圖表數據為零
2.  當 FLUTE_UCL、BENDING_UCL、TORQUE_UCL 設為零可以關閉管制界線功能
3.  新增按鈕按下 Generate Report 產生加工履歷
4.  將燈號 Force Control Limit 和 Flute Control Limit 預設改為灰色
5.  將按鈕 Start Order 改為 Link STH 
6.  修改頂部以及左下面板內容的佈局與邏輯
7.  將 Job State 更改為 Control State 燈號
8.  csv  資料夾位置改為 ../holder_main/data/cov
9.  yaml 資料夾位置改為 ../holder_main/data/yml
10. stl  資料夾位置改為 ../holder_main/data/stl
11. 新增版本資訊
12. 修改 Tool 顯示錯誤

## E 版修改內容:
1. 將 STH 與 CNC 資料做時間同步後畫圖
2. config.json 中 "SAVE_REFERENCE_CSV"= true 可以計算 UCL 後儲存 reference.csv (第一次加工)
3. config.json 中 "SAVE_REFERENCE_CSV"= false 可以讀取 reference.csv 於加工時繪製 UCL
4. config.json 中 "UCL_SIGMA" 決定標準差倍數
5. Torque 與 Bending 的 UCL 計算使用移動視窗前 100 筆資料的平均值 + N 倍標準差
6. Flute UCL 使用整筆資料的平均值 + N 倍標準差
7. Controller State: 判斷是否有控制器資料，預設灰燈，當收到 STH/CNC 訊息會變成綠燈
8. STH Link: 判斷是否有 STH 資料預設灰燈，當收到 STH/Pdata 訊息會變成綠燈
9. Machining State: 判斷是否加工，當 STH/CNC/CYCLE 的訊息為 {"Cycle": "Start"} 變綠燈，訊息為 {"Cycle": "End"} 變綠燈
10. Force Control Limit: 判斷 Bending 資料是否超過管制界線，當開始加工後變成綠色，超過橘色管制線變成橘色，超過紅色管制線變成紅色
11. Flute Control Limit: 判斷 CH1、CH2 資料是否超過管制界線，當開始加工後變成綠色，超過橘色管制線變成橘色，超過紅色管制線變成紅色

## F 版修改內容:
1. 新增按鈕按下 Manage Part Files 會跳出視窗可以選擇上傳或是刪除 STL/PNG 檔案
2. 優化 Delete Orders 按鈕內部功能，加入刪除提示文字
3. 新增 cnc_network_manager.py ，設定樹莓派端口 IP 連接 CNC
4. 新增 System Status 窗格顯示狀態資訊
5. 按下 Generate Report 後，新增視窗等待報告產生
6. 修正無管制界線時，Report 的 Flute View 無法顯示錯誤
7. 新增資料同步模式設定，讓 CNC 與 STH 的資料可以選擇是否經過同步，再顯示於儀表板