# scripts/

Python 腳本放這裡。規劃：

1. `test_login.py`：登入 → 查一檔（2330）報價 → 印出 → 登出（API 開通後撰寫）
2. `cb_breakout.py`：讀 CB 標的清單 → 抓前五日最高價與現價 → 輸出 `data\YYYYMMDD.csv`

帳號密碼從環境變數 `YUANTA_ACCOUNT`、`YUANTA_PASSWORD` 讀取。
