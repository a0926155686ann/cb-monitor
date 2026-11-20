# 發債突破 監測(CB Breakout)

## 目標
監測台股盤中「創五日新高」的股票,且該股票有已發行、仍流通的可轉債(CB),
把結果顯示在 `cb-breakout.html` 網頁上。

## 資料來源
- **即時報價**:元大 Spark API(Python,win-x64)。元件放在 **`C:\YuantaSparkAPI_win-x64_Python\`**
  (不放進 OneDrive 的 `api/`,避免同步 145 MB 的 dll)。腳本以環境變數 `YUANTA_API_DIR` 或此預設路徑找元件。
  - 官方文件:http://www.yuanta.com.tw/file-repository/content/sparkapi_docs/index.html
  - 元件內說明:`IO_Doc\FunctionList.xlsx`(功能對照、股名檔)、`IO_Doc\GetKLine_IO_Spec.doc`、`IO_Doc\GetWatchListAll_IO_Spec.doc`
  - 開通狀態:已簽風險預告書、已完成 API 測試上傳、已聯絡營業員開通、已下載元件。
  - ⚠️ **不要直接執行元件附的 `YSendOrder.py`**:檔尾 `send_emg_stock_order(...)` 沒有註解掉,執行會送出興櫃下單。
    只參考它的寫法:`Open(enumEnvironmentMode.PROD)` → 等 2 秒 → `Login(帳號, 密碼)` → 等 2 秒 →
    查詢函式;結果經 `OnResponse(intMark, dwIndex, strIndex, objHandle, objValue)` 事件非同步回傳(intMark 1 = 查詢回應)。
    - 報價:`GetWatchListAll(帳號, List[Quote])`,Quote 設 `MarketType`(enumMarketType.TWSE 等)與 `StockCode`;回應 `QueryWatchList[i].DealPrice / HighPrice / YstPrice …`
    - 日K:`GetKLine(帳號, KLineType(11), enumMarketType.TWSE, 代碼, "YYYY/MM/DD", "YYYY/MM/DD")`;回應 `KLineList[i].TimeStamp / HighPrice / ClosePrice …`
    - 結束:`LogOut()` → `Close()` → `Dispose()`
  - **已驗證(2026-11-20,`scripts\test_login.py`)**:正式環境登入成功(0001)、報價與日K皆正常。
    - 價格欄位是一般浮點數(例 1985.0),不需依「小數位」換算。
    - 日K 的 `TimeStamp` 為 .NET 日期字串(例 `2026/11/20 上午 12:00:00`);**盤中查詢會包含當天那根**,
      算「前五日最高」時要排除今天,取今天以前最近 5 根的 HighPrice 最大值。
  - 執行環境(已安裝並驗證,`scripts\check_env.py`):Python 3.13 64 位元、.NET 8 SDK 8.0.428、pythonnet 3.2.1。
    主控台輸出中文會亂碼時,先設 `$env:PYTHONIOENCODING='utf-8'`。
  - 市場代碼:上市 `enumMarketType.TWSE`、上櫃 `enumMarketType.TWOTC`、興櫃 `TWEMERGING`。
    元件為 .NET 8 的 `YuantaSparkAPI.dll`,以 pythonnet `load("coreclr")` + `clr.AddReference("YuantaSparkAPI")` 載入,
    範例程式為 `YSendOrder.py`(內含下單,只參考連線/登入/報價寫法)。
  - 登入(Windows):`Login(Account, Pass)`,憑證需**事先匯入 Windows 憑證存放區**,程式不需 .pfx 路徑。
    帳號與電子密碼**一律從環境變數讀取**,不要寫進程式碼或任何檔案:
    - `YUANTA_ACCOUNT`(S + 分公司 4 碼 + 帳號 7 碼,共 S+11 碼)、`YUANTA_PASSWORD`
  - 使用正式環境(測試環境需固定 IP 防火牆,未申請)。
  - 只做「查詢報價」,**不要呼叫任何下單、條件單、圈存相關的函式**。
  - 用到的功能:報價表查詢(單次最多 600 檔)取現價;K 線查詢(GetKline)取前五日最高價。
  - **呼叫限制(務必在程式內限速)**:
    - 登入失敗後重試至少間隔 4 秒;已登入不可重複登入;每帳號每日登入上限 1000 次
    - K 線查詢每秒最多 1 次;同功能報價類每秒最多 3 次
    - 行情類總呼叫每分鐘 1200 次,超過暫停 1 分鐘;**一小時內被暫停 10 次會停用帳號 API**
  - 本地 log 預設在 `C:\Yuanta\YuantaSparkAPI\Log`(可能含帳號資訊,不要上傳或貼出)。
- **CB 基本資料**:欄位定義以統一證券 CBAS 已發行 CB 資料為準
  https://cbas16889.pscnet.com.tw/marketInfo/issued
  背後 API:`GET https://cbas16889.pscnet.com.tw/api/CbasQuote/GetIssuedCBSchedule`(公開、免登入,JSON 的 `result` 陣列,
  約每日 17:00 更新)。`scripts\fetch_cb_list.py` 抓取後存 `data\cb_list.csv`(2026-11-20 實測 390 檔 CB、311 檔標的)。
  - API 沒有「標的股名稱、產業、上市/上櫃別」,需由元大報價(StkName、IndustryName)補上。
  - `period` 實測是「距最近賣回日」的年數,不是距到期年數。

## 可轉債報價表(cb-quotes.html)
- `scripts\cb_quotes.py` 合併 CBAS + 櫃買 `bond_ISSBD5_data`(發行/流通金額、擔保)+ 元大報價,輸出 `data\cb_quotes.js`(網頁讀)與 `.json`。
- 日K 歷史快取 `data\cb_hist.json`(每天第一次執行更新,約 8 分鐘);標的市場別快取 `data\stock_market.json`。
- 發行張數由募得金額推估(取 ≤ 金額/10萬 的最大 500 張倍數),可能有誤差。
- **排程**:Windows 工作排程器 `CB-Quotes-Daily`,週一到週五 08:40(更新歷史 → 每 30 秒更新到 13:35)與 17:30(抓收盤後 CBAS 新資料)。
  執行 `scripts\run_daily.ps1`,log 在 `data\logs\YYYYMMDD.log`(保留 30 天)。電腦需開機且已登入 Windows。

## 發債庫藏(cb-treasury.html)
- 來源:MOPS「買回自己公司股份彙總統計表」`POST https://mopsov.twse.com.tw/mops/web/ajax_t35sc09`
  (TYPEK=sii/otc、d1/d2 民國年 YYYMMDD、RD=1),`scripts\treasury.py` 解析,抓近 3 年,快取 `data\treasury.json`,每天抓一次。
- `cb_quotes.py` 的 `build_treasury` 對應到 CB 標的,輸出 `data\cb_treasury.js`:**只顯示正在進行或即將開始的庫藏股**(使用者指定,不含已結束),
  欄位含實施期間、預計買回張數、金額上限、價格區間、現價位置、已買回與執行率、目的、上次庫藏股(期間、張數、執行率)。
- 同一董事會決議日的多筆(不同買回目的)合併成一次計算。
- 「目前已買回」:執行中的庫藏股 MOPS 彙總表是空白,改用「買回達一定標準」申報
  `POST https://mopsov.twse.com.tw/mops/web/ajax_t35sb01`(colorchg=1、step=2、TYPEK、co_id、firstin=true),
  取本次買回期間內最新一筆「於買回期間內累積已持有股數」。公司累積達已發行 2% 或 3 億元才需申報,
  所以是「至少」值;沒申報顯示「未達申報門檻」。快取 `data\treasury_progress.json`,3 小時內不重抓,每家間隔 2 秒。
- 表頭固定:頁面 body 用 flex 100dvh,只有 `.wrap` 捲動,`th` 用 sticky(cb-breakout、cb-treasury 相同)。

## GitHub(公開)
- 儲存庫:https://github.com/a0926155686ann/cb-monitor(main = 程式碼;`data/*.js`、快取不進 main)
- 網址:https://a0926155686ann.github.io/cb-monitor/ (GitHub Pages,來源 gh-pages 分支)
- `scripts\publish.ps1`:把 *.html + data\cb_*.js 以單一 commit 強制推到 gh-pages(不留歷史)。
  排程 `--publish-every 600` 盤中每 10 分鐘發布一次(Pages 約每小時 10 次建置上限),收盤最後一輪再發布。
- commit 身分用 GitHub noreply 信箱;公開儲存庫,**任何檔案都不能放帳號、密碼、憑證**。

## 篩選邏輯(目前版本)
1. 取得所有有已發行 CB 的標的股清單。
2. 盤中現價 > 前五個交易日最高價 → 視為「突破五日新高」。
3. 一檔股票有多檔 CB 時,每檔 CB 各列一行(與網頁一致)。

目前採用的**暫定定義**(2026-11-20 使用者同意先用,之後可能再改;程式在 `cb_quotes.py` 的 `build_breakout`):
- 「符合燈數」:每符合一項一顆星 ①突破五日新高 ②股價漲幅 ≥ 3% ③CB 今日有成交 ④轉換溢價率 ≤ 20% ⑤距到期 ≥ 180 天
- 「市值」:CB 轉換價值 = 標的現價 ÷ 轉換價 × 100
- 「停」:今天落在 CBAS 停止轉換起迄日之間
- 「前五日最高價」:今天以前最近 5 個交易日日K的 HighPrice 最大值;突破 = 今日成交價 > 前五日最高價

## 網頁
- `cb-breakout.html`:單一 HTML 檔,深色版型,分頁列(發債突破為主,其餘分頁尚未實作)、
  列表/分析切換、摘要卡片、篩選、可排序欄位、匯入 CSV。
- 網頁目前內嵌範例資料;實際資料由 Python 腳本產生 CSV,再用「匯入資料」載入,
  或之後改為腳本直接把資料寫進 HTML。

## 資料格式(CSV,UTF-8)
標題列固定為:
`燈數,名稱,代碼,產業,漲幅,現價,CB名稱,CB代碼,CB價,市值,剩餘天數,停`
- 漲幅為百分比數字(4.79 代表 4.79%)
- 停:1 = 有停標記,0 = 無
- 範例見 `data/sample.csv`

## 資料夾結構
位置:`C:\Users\User\OneDrive\文件\CB\`
```
CB/
├─ CLAUDE.md
├─ cb-breakout.html
├─ data/            # 產出的 CSV
├─ api/             # 元大 API 解壓縮在這裡
└─ scripts/         # Python 腳本
```

## 工作原則
- 回覆一律使用繁體中文。
- 先讓最小可行版本跑起來(登入 → 抓一檔報價 → 印出),再擴充。
- 不要把憑證、密碼、身分證字號等敏感資訊寫進檔案、log 或對話。
