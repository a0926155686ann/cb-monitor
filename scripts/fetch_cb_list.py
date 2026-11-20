r"""抓取統一證券 CBAS「已發行 CB 資料」,存成 data\cb_list.csv。

資料來源:https://cbas16889.pscnet.com.tw/marketInfo/issued
背後 API:GET /api/CbasQuote/GetIssuedCBSchedule(公開、不需登入,約每日 17:00 更新)

用法:python scripts\fetch_cb_list.py
"""
import csv
import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

URL = "https://cbas16889.pscnet.com.tw/api/CbasQuote/GetIssuedCBSchedule"
OUT = Path(__file__).resolve().parent.parent / "data" / "cb_list.csv"

# API 欄位 → 中文欄名(依 CBAS 網頁)
FIELDS = {
    "bond_code": "CB代碼",
    "underlying_bond": "CB名稱",
    "convert_target_code": "標的代碼",
    "underlying_stock_market_price": "標的股價",
    "convertible_bond_market_price": "CB市價",
    "conversion_price": "轉換價",
    "conversion_ratio": "轉換比例",
    "conversion_value": "轉換價值",
    "premium_rate": "溢價率",
    "the_degree_of_price_inside_and_outside": "價內外程度",
    "issue_date": "發行日",
    "expiry_date": "到期日",
    "period": "距賣回年限",  # 實測 = 今天到「最近賣回日」的年數,不是到期年限
    "latest_sale_date": "最近賣回日",
    "latest_sale_price": "最近賣回價",
    "sell_back_yield": "賣回殖利率",
    "circulating_balance": "流通餘額(張)",
    "circulation": "流通餘額(億)",
    "balance_ratio": "餘額比例",
    "convertible_bond_turnover": "CB成交量",
    "average_daily_volume_of_convertible_bonds_5d": "CB五日均量",
    "average_daily_volume_of_convertible_bonds_20d": "CB二十日均量",
    "underlying_stock_historical_volatility": "標的歷史波動率",
    "tcri": "TCRI",
    "guarantee_situation": "擔保情形",
    "stop_conversion_date": "停止轉換起日",
    "stop_converting_until_date": "停止轉換迄日",
    "mandatory_redemption_date": "強制贖回日",
    "reset_conversion_day": "重設轉換日",
    "reset_conversion_price": "重設轉換價",
    "reset_price": "重設價",
    "ten_percent_interest_tax_deduction": "扣10%利息稅",
    "create_date": "資料時間",
}


def fetch() -> list[dict]:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    rows = j.get("result")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"API 回傳格式不符預期:{list(j)[:10]}")
    return rows


def main() -> None:
    rows = fetch()
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:  # 含 BOM,Excel 開啟不亂碼
        w = csv.writer(f)
        w.writerow(FIELDS.values())
        for r in sorted(rows, key=lambda x: x.get("bond_code", "")):
            w.writerow([str(r.get(k, "")).strip() for k in FIELDS])
    stocks = {r.get("convert_target_code") for r in rows}
    unknown = set(rows[0]) - set(FIELDS)
    print(f"已存 {len(rows)} 檔 CB(標的股 {len(stocks)} 檔)→ {OUT}")
    print(f"資料時間:{rows[0].get('create_date', '')}")
    if unknown:
        print(f"注意:API 有未對應的新欄位 {sorted(unknown)}")


if __name__ == "__main__":
    main()
