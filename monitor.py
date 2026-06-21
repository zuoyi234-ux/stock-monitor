#!/usr/bin/env python3
"""
股票日报监控 - 新易盛 / 中际旭创 / 宝丰能源
数据来源：东方财富 | Yahoo Finance | Alpha Vantage | NewsAPI
每日 09:00 (北京时间) 由 GitHub Actions 触发
"""

import os, re, json, smtplib, traceback, requests
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False
    print("[WARN] yfinance 未安装，Yahoo Finance 功能禁用")

# ── 监控标的 ─────────────────────────────────────────────────────────────────
COMPANIES = [
    {
        "name": "新易盛",
        "code": "300502",
        "ticker_yf": "300502.SZ",
        "name_en": "Eoptolink",
        "search_en": "Eoptolink optical transceiver AI data center",
        "av_topics": "technology",
    },
    {
        "name": "中际旭创",
        "code": "300308",
        "ticker_yf": "300308.SZ",
        "name_en": "Innolight",
        "search_en": "Innolight optical module silicon photonics",
        "av_topics": "technology",
    },
    {
        "name": "宝丰能源",
        "code": "600989",
        "ticker_yf": "600989.SS",
        "name_en": "Baofeng Energy",
        "search_en": "Baofeng Energy coal chemical green hydrogen China",
        "av_topics": "energy_transportation",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.eastmoney.com/",
}

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).date()
ANN_LOOKBACK  = 3   # 公告/东财新闻 天数
RPT_LOOKBACK  = 30  # 研报 天数
NEWS_LOOKBACK = 7   # 国际新闻 天数

AV_KEY   = os.environ.get("ALPHA_VANTAGE_KEY", "")
NEWS_KEY = os.environ.get("NEWS_API_KEY", "")


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def safe_get(url, params=None, hdrs=None, timeout=15):
    try:
        r = requests.get(url, params=params, headers=hdrs or HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  [WARN] {url[:80]} → {e}")
        return None


def parse_jsonp(text):
    m = re.search(r'[\w$]+\((.+)\)\s*;?\s*$', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    try:
        return json.loads(text)
    except Exception:
        return None


def within_days(date_str, days):
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date() >= TODAY - timedelta(days=days)
    except Exception:
        return False


def fmt_vol(n):
    if n is None:
        return "-"
    if n >= 1e8:
        return f"{n/1e8:.1f}亿"
    if n >= 1e4:
        return f"{n/1e4:.0f}万"
    return str(int(n))


# ── 1. 东方财富 ───────────────────────────────────────────────────────────────

def get_announcements(code):
    r = safe_get(
        f"https://np-anotice-stock.eastmoney.com/api/security/ann"
        f"?sr=-1&page=1&pageSize=20&ann_type=SHA,CYB,SZA&client_source=web&stock_list={code}"
    )
    if not r:
        return []
    data = r.json()
    if data.get("state") != 1:
        return []
    items = []
    for ann in data.get("data", {}).get("list", []):
        ds = (ann.get("notice_date") or "")[:10]
        if not within_days(ds, ANN_LOOKBACK):
            continue
        items.append({
            "title": ann.get("title", ""),
            "date": ds,
            "url": f"https://data.eastmoney.com/notices/detail/{code}/{ann.get('art_code','')}.html",
        })
    return items[:8]


def get_research_reports(code):
    r = safe_get(
        "https://reportapi.eastmoney.com/report/list",
        params={
            "cb": "cb", "industryCode": "*", "pageSize": 8,
            "industry": "*", "rating": "*", "ratingChange": "*",
            "beginTime": (TODAY - timedelta(days=RPT_LOOKBACK)).strftime("%Y-%m-%d"),
            "endTime": TODAY.strftime("%Y-%m-%d"),
            "pageNo": 1, "fields": "", "qType": 0, "orgCode": "", "code": code, "rp": 1,
        },
    )
    if not r:
        return []
    data = parse_jsonp(r.text)
    if not data:
        return []
    return [
        {
            "title": rep.get("title", ""),
            "org": rep.get("orgSName", ""),
            "rating": rep.get("starRating", ""),
            "date": (rep.get("publishDate") or "")[:10],
            "url": f"https://data.eastmoney.com/report/zw_stock.jshtml?encodeUrl={rep.get('encodeUrl','')}",
        }
        for rep in data.get("data", [])[:6]
    ]


def get_em_news(code):
    r = safe_get(
        "https://np-listapi.eastmoney.com/comm/web/getListInfo",
        params={
            "cb": "cb", "client": "web", "type": 1,
            "mTypeAndCode": f"1|{code}",
            "fields": "News_Title,News_Summary,News_ShareUrl,News_PublishDate",
            "pageSize": 10, "pageIndex": 1,
        },
    )
    if not r:
        return []
    data = parse_jsonp(r.text)
    if not data:
        return []
    items = []
    for n in data.get("LiveList", []):
        ds = (n.get("News_PublishDate") or "")[:10]
        if not within_days(ds, ANN_LOOKBACK):
            continue
        summary = (n.get("News_Summary") or "").strip()
        items.append({
            "title": n.get("News_Title", ""),
            "summary": summary[:130] + ("…" if len(summary) > 130 else ""),
            "date": ds,
            "url": n.get("News_ShareUrl", ""),
            "source": "东方财富",
        })
    return items[:6]


# ── 2. Yahoo Finance ──────────────────────────────────────────────────────────

def get_yahoo_quote(ticker):
    if not HAS_YF:
        return None
    try:
        fi = yf.Ticker(ticker).fast_info
        price  = fi.last_price
        change = fi.regular_market_change
        pct    = fi.regular_market_change_percent
        return {
            "price":      round(price, 2)  if price  else None,
            "change":     round(change, 2) if change else None,
            "change_pct": round(pct, 2)    if pct    else None,
            "volume":     fi.regular_market_volume,
            "year_high":  round(fi.year_high, 2) if fi.year_high else None,
            "year_low":   round(fi.year_low, 2)  if fi.year_low  else None,
        }
    except Exception as e:
        print(f"  [WARN] Yahoo quote {ticker}: {e}")
        return None


def get_yahoo_news(ticker):
    if not HAS_YF:
        return []
    try:
        news_list = yf.Ticker(ticker).news or []
        items = []
        for n in news_list[:8]:
            if "content" in n:                              # yfinance ≥ 0.2.50
                ct     = n["content"]
                title  = ct.get("title", "")
                ds     = (ct.get("pubDate") or "")[:10]
                url    = ((ct.get("canonicalUrl") or {}).get("url")
                          or (ct.get("clickThroughUrl") or {}).get("url", ""))
                source = (ct.get("provider") or {}).get("displayName", "Yahoo Finance")
            else:                                            # older yfinance
                title  = n.get("title", "")
                ts     = n.get("providerPublishTime", 0)
                ds     = datetime.fromtimestamp(ts, tz=CST).strftime("%Y-%m-%d") if ts else ""
                url    = n.get("link", "")
                source = n.get("publisher", "Yahoo Finance")
            if not title or (ds and not within_days(ds, NEWS_LOOKBACK)):
                continue
            items.append({"title": title, "date": ds, "url": url, "source": source})
        return items[:5]
    except Exception as e:
        print(f"  [WARN] Yahoo news {ticker}: {e}")
        return []


# ── 3. Alpha Vantage ──────────────────────────────────────────────────────────

SENTIMENT_ZH = {
    "Bullish": "📈 看多", "Somewhat-Bullish": "↑ 偏多",
    "Bearish": "📉 看空", "Somewhat-Bearish": "↓ 偏空",
    "Neutral": "➡ 中性",
}


def get_alphavantage_news(topics):
    if not AV_KEY:
        return []
    r = safe_get(
        "https://www.alphavantage.co/query",
        params={"function": "NEWS_SENTIMENT", "topics": topics,
                "limit": 6, "sort": "LATEST", "apikey": AV_KEY},
        hdrs={"User-Agent": "Mozilla/5.0"},
    )
    if not r:
        return []
    data = r.json()
    if "Information" in data:
        print(f"  [WARN] Alpha Vantage: {data['Information'][:80]}")
        return []
    items = []
    for feed in data.get("feed", [])[:6]:
        pub = feed.get("time_published", "")
        ds = f"{pub[:4]}-{pub[4:6]}-{pub[6:8]}" if len(pub) >= 8 else ""
        if ds and not within_days(ds, NEWS_LOOKBACK):
            continue
        items.append({
            "title": feed.get("title", ""),
            "date": ds,
            "url": feed.get("url", ""),
            "source": feed.get("source", "Alpha Vantage"),
            "sentiment": SENTIMENT_ZH.get(feed.get("overall_sentiment_label", ""), ""),
        })
    return items


# ── 4. NewsAPI ────────────────────────────────────────────────────────────────

def get_newsapi_news(search_en):
    if not NEWS_KEY:
        return []
    r = safe_get(
        "https://newsapi.org/v2/everything",
        params={
            "q": search_en,
            "from": (TODAY - timedelta(days=NEWS_LOOKBACK)).strftime("%Y-%m-%d"),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 5,
            "apiKey": NEWS_KEY,
        },
        hdrs={"User-Agent": "Mozilla/5.0"},
    )
    if not r:
        return []
    data = r.json()
    items = []
    for art in data.get("articles", []):
        ds = (art.get("publishedAt") or "")[:10]
        if ds and not within_days(ds, NEWS_LOOKBACK):
            continue
        raw_title = art.get("title") or ""
        title = raw_title.split(" - ")[0].strip()
        if not title or title == "[Removed]":
            continue
        desc = (art.get("description") or "").strip()
        items.append({
            "title": title,
            "date": ds,
            "url": art.get("url", ""),
            "source": (art.get("source") or {}).get("name", "NewsAPI"),
            "desc": desc[:120] + ("…" if len(desc) > 120 else ""),
        })
    return items[:5]


# ── HTML 渲染 ─────────────────────────────────────────────────────────────────

CSS = """
<style>
*{box-sizing:border-box}
body{margin:0;padding:20px;background:#f0f2f5;font-family:'PingFang SC',Arial,sans-serif}
.wrap{max-width:860px;margin:0 auto;background:#fff;border-radius:10px;
      overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.12)}
.hd{background:linear-gradient(135deg,#0d47a1,#1565c0);color:#fff;padding:24px 30px}
.hd h1{margin:0;font-size:22px;letter-spacing:1px}
.hd .sub{margin:6px 0 0;opacity:.75;font-size:13px}
.co-block{border-bottom:1px solid #e8eaf0;padding:20px 30px}

/* 股价卡片 */
.price-card{display:flex;align-items:center;gap:20px;background:#f8f9ff;
            border:1px solid #e0e4f0;border-radius:8px;padding:12px 16px;margin-bottom:18px}
.price-val{font-size:26px;font-weight:700;color:#1a1a2e}
.price-chg{font-size:14px;font-weight:600;padding:3px 8px;border-radius:4px}
.up{background:#fff1f0;color:#c62828}
.dn{background:#e8f5e9;color:#2e7d32}
.flat{background:#f5f5f5;color:#666}
.price-meta{font-size:12px;color:#888;line-height:1.8}
.price-meta b{color:#555}

/* 章节 */
.co-name{font-size:18px;font-weight:700;color:#0d47a1;margin:0 0 14px}
.co-name .code{font-size:12px;font-weight:400;color:#888;background:#f0f2f5;
               padding:2px 6px;border-radius:4px;margin-left:6px}
.sec{margin-bottom:16px}
.sec-title{font-size:13px;font-weight:600;color:#333;
           border-left:3px solid #1565c0;padding-left:8px;margin-bottom:8px}

/* 表格 */
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#e8eaf6;color:#283593;padding:8px 10px;text-align:left;font-weight:600}
td{padding:7px 10px;border-bottom:1px solid #f3f3f3;vertical-align:top;line-height:1.5}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafbff}
a{color:#1565c0;text-decoration:none}
a:hover{text-decoration:underline}
.dt{white-space:nowrap;color:#999;font-size:12px;width:82px}
.org{color:#555;font-size:12px;width:72px}
.rating{color:#e65100;font-size:12px;width:56px}
.src-badge{display:inline-block;font-size:11px;color:#fff;border-radius:3px;
           padding:1px 5px;margin-right:4px;white-space:nowrap}
.badge-em{background:#e53935}
.badge-yf{background:#6a0dad}
.badge-av{background:#0277bd}
.badge-na{background:#388e3c}
.summary{color:#777;font-size:12px;margin-top:2px}
.sentiment{font-size:11px;color:#555}
.empty{color:#bbb;font-style:italic;font-size:13px;padding:6px 0}
.ft{text-align:center;padding:14px;color:#bbb;font-size:12px;background:#fafafa}
.no-key{color:#f57c00;font-size:12px;font-style:italic}
</style>
"""


def price_card(quote):
    if not quote or quote.get("price") is None:
        return '<div class="empty">行情数据暂不可用（Yahoo Finance）</div>'
    p   = quote["price"]
    chg = quote["change"] or 0
    pct = quote["change_pct"] or 0
    cls = "up" if chg > 0 else ("dn" if chg < 0 else "flat")
    sign = "+" if chg > 0 else ""
    yh = quote.get("year_high") or "-"
    yl = quote.get("year_low") or "-"
    vol = fmt_vol(quote.get("volume"))
    return f"""
<div class="price-card">
  <span class="price-val">¥{p}</span>
  <span class="price-chg {cls}">{sign}{chg} ({sign}{pct}%)</span>
  <div class="price-meta">
    <b>52周</b> 高 ¥{yh} / 低 ¥{yl}&nbsp;&nbsp;
    <b>成交量</b> {vol}
    <br><small>数据来源：Yahoo Finance（延迟）</small>
  </div>
</div>"""


def tbl_announcements(items):
    if not items:
        return f'<div class="empty">近 {ANN_LOOKBACK} 天暂无新公告</div>'
    rows = "".join(
        f'<tr><td><a href="{i["url"]}" target="_blank">{i["title"]}</a></td>'
        f'<td class="dt">{i["date"]}</td></tr>'
        for i in items
    )
    return f'<table><thead><tr><th>公告标题</th><th>日期</th></tr></thead><tbody>{rows}</tbody></table>'


def tbl_reports(items):
    if not items:
        return f'<div class="empty">近 {RPT_LOOKBACK} 天暂无研报</div>'
    rows = "".join(
        f'<tr><td><a href="{i["url"]}" target="_blank">{i["title"]}</a></td>'
        f'<td class="org">{i["org"]}</td><td class="rating">{i["rating"]}</td>'
        f'<td class="dt">{i["date"]}</td></tr>'
        for i in items
    )
    return (
        f'<table><thead><tr><th>研报标题</th><th>机构</th><th>评级</th><th>日期</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def tbl_em_news(items):
    if not items:
        return f'<div class="empty">近 {ANN_LOOKBACK} 天暂无相关新闻</div>'
    rows = "".join(
        f'<tr><td><a href="{i["url"]}" target="_blank">{i["title"]}</a>'
        + (f'<div class="summary">{i["summary"]}</div>' if i.get("summary") else "")
        + f'</td><td class="dt">{i["date"]}</td></tr>'
        for i in items
    )
    return f'<table><thead><tr><th>新闻标题</th><th>日期</th></tr></thead><tbody>{rows}</tbody></table>'


BADGE = {
    "yf": '<span class="src-badge badge-yf">Yahoo</span>',
    "av": '<span class="src-badge badge-av">AV</span>',
    "na": '<span class="src-badge badge-na">NewsAPI</span>',
}


def tbl_intl_news(yf_items, av_items, na_items):
    merged = (
        [("yf", i) for i in yf_items]
        + [("av", i) for i in av_items]
        + [("na", i) for i in na_items]
    )
    # Sort by date desc
    def sort_key(x):
        return x[1].get("date", "") or ""
    merged.sort(key=sort_key, reverse=True)

    if not merged:
        lines = []
        if not HAS_YF:
            lines.append("Yahoo Finance：yfinance 未安装")
        if not AV_KEY:
            lines.append("Alpha Vantage：未配置 ALPHA_VANTAGE_KEY")
        if not NEWS_KEY:
            lines.append("NewsAPI：未配置 NEWS_API_KEY")
        hint = "；".join(lines) if lines else f"近 {NEWS_LOOKBACK} 天暂无国际资讯"
        return f'<div class="no-key">{hint}</div>'

    rows = ""
    for tag, item in merged[:10]:
        badge = BADGE.get(tag, "")
        src   = item.get("source", "")
        title = item.get("title", "")
        url   = item.get("url", "")
        date  = item.get("date", "")
        extra = item.get("sentiment") or item.get("desc") or ""
        rows += (
            f'<tr><td>{badge}'
            f'<a href="{url}" target="_blank">{title}</a>'
            + (f'<div class="summary">{extra}</div>' if extra else "")
            + f'</td><td class="org">{src}</td>'
            f'<td class="dt">{date}</td></tr>'
        )
    return (
        f'<table><thead><tr><th>标题</th><th>来源</th><th>日期</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def build_html():
    date_str = datetime.now(CST).strftime("%Y年%m月%d日 %H:%M")
    blocks = ""

    for co in COMPANIES:
        print(f"  → {co['name']} ({co['code']})")
        quote   = get_yahoo_quote(co["ticker_yf"])
        anns    = get_announcements(co["code"])
        reports = get_research_reports(co["code"])
        em_news = get_em_news(co["code"])
        yf_news = get_yahoo_news(co["ticker_yf"])
        av_news = get_alphavantage_news(co["av_topics"])
        na_news = get_newsapi_news(co["search_en"])

        blocks += f"""
<div class="co-block">
  <div class="co-name">{co['name']}<span class="code">{co['code']}</span></div>
  {price_card(quote)}
  <div class="sec">
    <div class="sec-title">📢 最新公告（近{ANN_LOOKBACK}天 · 东方财富）</div>
    {tbl_announcements(anns)}
  </div>
  <div class="sec">
    <div class="sec-title">📊 最新研报（近{RPT_LOOKBACK}天 · 东方财富）</div>
    {tbl_reports(reports)}
  </div>
  <div class="sec">
    <div class="sec-title">📰 国内新闻（近{ANN_LOOKBACK}天 · 东方财富）</div>
    {tbl_em_news(em_news)}
  </div>
  <div class="sec">
    <div class="sec-title">🌐 国际资讯（近{NEWS_LOOKBACK}天 · Yahoo / Alpha Vantage / NewsAPI）</div>
    {tbl_intl_news(yf_news, av_news, na_news)}
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>股票日报 {date_str}</title>{CSS}</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>📈 股票监控日报</h1>
    <div class="sub">{date_str}（北京时间）&nbsp;|&nbsp;新易盛 · 中际旭创 · 宝丰能源</div>
  </div>
  {blocks}
  <div class="ft">
    数据来源：东方财富 · Yahoo Finance · Alpha Vantage · NewsAPI
    &nbsp;|&nbsp; 由 GitHub Actions 自动生成推送
  </div>
</div>
</body>
</html>"""


# ── 发送邮件 ─────────────────────────────────────────────────────────────────

def send_email(html_content):
    sender   = os.environ["QQ_EMAIL"]
    password = os.environ["QQ_PASSWORD"]
    receiver = os.environ.get("RECEIVER_EMAIL", sender)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 股票日报 {TODAY} | 新易盛·中际旭创·宝丰能源"
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    print(f"  发送邮件至 {receiver} ...")
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, [receiver], msg.as_string())
    print("  ✅ 邮件发送成功")


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')} CST] 开始抓取数据...")
    av_status   = "✓" if AV_KEY   else "✗ 未配置 ALPHA_VANTAGE_KEY"
    news_status = "✓" if NEWS_KEY else "✗ 未配置 NEWS_API_KEY"
    yf_status   = "✓" if HAS_YF  else "✗ yfinance 未安装"
    print(f"  数据源：东方财富 ✓ | Yahoo Finance {yf_status} | Alpha Vantage {av_status} | NewsAPI {news_status}")
    try:
        html = build_html()
        send_email(html)
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
