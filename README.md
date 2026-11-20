# CB 監測(發債突破/可轉債/發債庫藏)

台股可轉換公司債(CB)監測網頁。資料由本機 Python 腳本盤中抓取後發布到 GitHub Pages。

| 頁面 | 內容 |
|---|---|
| `cb-breakout.html` 發債突破 | 有流通 CB 的標的股,盤中現價突破前五個交易日最高價 |
| `cb-quotes.html` 可轉債 | 全部已發行 CB 報價、轉換價值、溢價率、週/月/年漲跌、發行券商 |
| `cb-treasury.html` 發債庫藏 | 標的股正在實施或即將實施庫藏股的 CB,含預計/目前已買回、上次庫藏股 |

## 資料來源
- 即時報價:元大 Spark API(需自己的元大帳號與 API 權限)
- CB 基本資料:統一證券 CBAS 已發行 CB
- 發行張數、擔保、承銷商:櫃買中心 OpenAPI `bond_ISSBD5_data`
- 庫藏股:公開資訊觀測站 買回自己公司股份彙總統計表、買回達一定標準申報

> 本網頁僅供參考,不構成投資建議。資料可能延遲或有誤,請以官方公告為準。

## 自己執行
需要 Windows、Python 3.8+(64 位元)、.NET 8 SDK、`pip install pythonnet`,以及元大 Spark API 元件(放在 `C:\YuantaSparkAPI_win-x64_Python`,或用環境變數 `YUANTA_API_DIR` 指定)。

帳號密碼只從環境變數讀取,不要寫進任何檔案:
```powershell
[Environment]::SetEnvironmentVariable('YUANTA_ACCOUNT', 'S+11碼帳號', 'User')
[Environment]::SetEnvironmentVariable('YUANTA_PASSWORD', '電子密碼', 'User')
```

```powershell
python scripts\cb_quotes.py                       # 抓一次
python scripts\cb_quotes.py --loop 30 --until 13:35   # 盤中每 30 秒
```
產生 `data\*.js` 後直接開 html 檔即可。程式只呼叫查詢函式,不含任何下單功能。
