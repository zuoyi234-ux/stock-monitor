#!/usr/bin/env python3
"""
股票日报监控 - 新易盛 / 中际旭创 / 宝丰能源
数据来源：东方财富  |  每日 09:00 (北京时间) 由 GitHub Actions 触发
"""

import os
import re
import json
import smtplib
import traceback
import requests
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── 监控标的 ─────────────────────────────────────────────────────────────────
COMPANIES = [
    {
        "name": "新易盛",
        "code": "300502",
    },
    {
        "name": "中际旭创",
        "code": "300308",
    },
    {
        "name": "宝丰能源",
        "code": "600989",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.eastmoney.com/",
}

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).date()
ANN_LOOKBACK = 3    # 公告/新闻回看天数
RPT_LOOKBACK = 30   # 研报回看天数


# ── 网络工具 ─────────────────────────────────────────────────────────────────

def safe_get(url, params=None, timeout=15):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  [WARN] {url} → {e}")
        return None


def parse_jsonp(text):
    """Strip JSONP callback wrapper and parse JSON."""
    m = re.search(r'[\w$]+\((.+)\)\s*;?\s*$', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except Exception:
        return None


def within_days(date_str, days):
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return d >= TODAY - timedelta(days=days)
    except Exception:
        return False


# ── 数据抓取 ─────────────────────────────────────────────────────────────────

def get_announcements(code):
    """东方财富 - 公司公告（近 ANN_LOOKBACK 天）"""
    # 逗号不能被 URL 编码，直接拼 URL
    r = safe_get(
        f"https://np-anotice-stock.eastmoney.com/api/security/ann"
        f"?sr=-1&page=1&pageSize=20&ann_type=SHA,CYB,SZA&client_source=web&stock_list={code}",
    )
    if not r:
        return []
    data = r.json()
    if data.get("state") != 1:
        return []

    items = []
    for ann in data.get("data", {}).get("list", []):
        date_str = (ann.get("notice_date") or "")[:10]
        if not within_days(date_str, ANN_LOOKBACK):
            continue
        art_code = ann.get("art_code", "")
        items.append({
            "title": ann.get("title", ""),
            "date": date_str,
            "url": f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html",
        })
    return items[:8]


def get_research_reports(code):
    """东方财富 - 个股研报（近 RPT_LOOKBACK 天）"""
    begin = (TODAY - timedelta(days=RPT_LOOKBACK)).strftime("%Y-%m-%d")
    end = TODAY.strftime("%Y-%m-%d")
    r = safe_get(
        "https://reportapi.eastmoney.com/report/list",
        params={
            "cb": "cb", "industryCode": "*", "pageSize": 8,
            "industry": "*", "rating": "*", "ratingChange": "*",
            "beginTime": begin, "endTime": end,
            "pageNo": 1, "fields": "", "qType": 0,
            "orgCode": "", "code": code, "rp": 1,
        },
    )
    if not r:
        return []
    data = parse_jsonp(r.text)
    if not data:
        return []

    items = []
    for rep in data.get("data", [])[:6]:
        items.append({
            "title": rep.get("title", ""),
            "org": rep.get("orgSName", ""),
            "rating": rep.get("starRating", ""),
            "date": (rep.get("publishDate") or "")[:10],
            "url": (
                f"https://data.eastmoney.com/report/zw_stock.jshtml"
                f"?encodeUrl={rep.get('encodeUrl', '')}"
            ),
        })
    return items


def get_stock_news(code):
    """东方财富 - 个股相关新闻（近 ANN_LOOKBACK 天）"""
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
    for news in data.get("LiveList", []):
        date_str = (news.get("News_PublishDate") or "")[:10]
        if not within_days(date_str, ANN_LOOKBACK):
            continue
        summary = (news.get("News_Summary") or "").strip()
        items.append({
            "title": news.get("News_Title", ""),
            "summary": summary[:130] + ("…" if len(summary) > 130 else ""),
            "date": date_str,
            "url": news.get("News_ShareUrl", ""),
        })
    return items[:6]


# ── HTML 渲染 ─────────────────────────────────────────────────────────────────

CSS = """
<style>
*{box-sizing:border-box}
body{margin:0;padding:20px;background:#f0f2f5;font-family:'PingFang SC',Arial,sans-serif}
.wrap{max-width:840px;margin:0 auto;background:#fff;border-radius:10px;
      overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.12)}
.hd{background:linear-gradient(135deg,#0d47a1,#1565c0);color:#fff;padding:24px 30px}
.hd h1{margin:0;font-size:22px;letter-spacing:1px}
.hd .sub{margin:6px 0 0;opacity:.75;font-size:13px}
.co-block{border-bottom:1px solid #e8eaf0;padding:22px 30px}
.co-name{font-size:18px;font-weight:700;color:#0d47a1;margin:0 0 18px}
.co-name .code{font-size:12px;font-weight:400;color:#888;margin-left:6px;
               background:#f0f2f5;padding:2px 6px;border-radius:4px}
.sec{margin-bottom:18px}
.sec-title{font-size:13px;font-weight:600;color:#333;
           border-left:3px solid #1565c0;padding-left:8px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#e8eaf6;color:#283593;padding:8px 10px;text-align:left;font-weight:600}
td{padding:8px 10px;border-bottom:1px solid #f3f3f3;vertical-align:top;line-height:1.5}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafbff}
a{color:#1565c0;text-decoration:none}
a:hover{text-decoration:underline}
.dt{white-space:nowrap;color:#999;font-size:12px;width:85px}
.org{color:#555;font-size:12px;width:80px}
.rating{color:#e65100;font-size:12px;width:60px}
.summary{color:#777;font-size:12px;margin-top:3px}
.empty{color:#bbb;font-style:italic;font-size:13px;padding:8px 0}
.ft{text-align:center;padding:14px;color:#bbb;font-size:12px;background:#fafafa}
</style>
"""


def tbl_announcements(items):
    if not items:
        return f'<div class="empty">近 {ANN_LOOKBACK} 天暂无新公告</div>'
    rows = "".join(
        f'<tr><td><a href="{i["url"]}" target="_blank">{i["title"]}</a></td>'
        f'<td class="dt">{i["date"]}</td></tr>'
        for i in items
    )
    return (
        f'<table><thead><tr><th>公告标题</th><th>日期</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def tbl_reports(items):
    if not items:
        return f'<div class="empty">近 {RPT_LOOKBACK} 天暂无研报</div>'
    rows = "".join(
        f'<tr><td><a href="{i["url"]}" target="_blank">{i["title"]}</a></td>'
        f'<td class="org">{i["org"]}</td>'
        f'<td class="rating">{i["rating"]}</td>'
        f'<td class="dt">{i["date"]}</td></tr>'
        for i in items
    )
    return (
        f'<table><thead><tr><th>研报标题</th><th>机构</th><th>评级</th><th>日期</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def tbl_news(items):
    if not items:
        return f'<div class="empty">近 {ANN_LOOKBACK} 天暂无相关新闻</div>'
    rows = "".join(
        f'<tr><td>'
        f'<a href="{i["url"]}" target="_blank">{i["title"]}</a>'
        + (f'<div class="summary">{i["summary"]}</div>' if i["summary"] else "")
        + f'</td><td class="dt">{i["date"]}</td></tr>'
        for i in items
    )
    return (
        f'<table><thead><tr><th>新闻标题</th><th>日期</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def build_html():
    date_str = datetime.now(CST).strftime("%Y年%m月%d日 %H:%M")
    blocks = ""

    for co in COMPANIES:
        print(f"  → {co['name']} ({co['code']})")
        anns    = get_announcements(co["code"])
        reports = get_research_reports(co["code"])
        news    = get_stock_news(co["code"])

        blocks += f"""
<div class="co-block">
  <div class="co-name">{co['name']}<span class="code">{co['code']}</span></div>
  <div class="sec">
    <div class="sec-title">📢 最新公告（近{ANN_LOOKBACK}天）</div>
    {tbl_announcements(anns)}
  </div>
  <div class="sec">
    <div class="sec-title">📊 最新研报（近{RPT_LOOKBACK}天）</div>
    {tbl_reports(reports)}
  </div>
  <div class="sec">
    <div class="sec-title">📰 相关新闻（近{ANN_LOOKBACK}天）</div>
    {tbl_news(news)}
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<title>股票日报 {date_str}</title>
{CSS}
</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>📈 股票监控日报</h1>
    <div class="sub">{date_str}（北京时间）&nbsp;|&nbsp;新易盛 · 中际旭创 · 宝丰能源</div>
  </div>
  {blocks}
  <div class="ft">数据来源：东方财富 &nbsp;|&nbsp; 由 GitHub Actions 自动生成推送</div>
</div>
</body>
</html>"""


# ── 发送邮件 ─────────────────────────────────────────────────────────────────

def send_email(html_content):
    sender   = os.environ["QQ_EMAIL"]
    password = os.environ["QQ_PASSWORD"]       # QQ 邮箱授权码，非 QQ 密码
    receiver = os.environ.get("RECEIVER_EMAIL", sender)

    date_label = datetime.now(CST).strftime("%Y-%m-%d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 股票日报 {date_label} | 新易盛·中际旭创·宝丰能源"
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    print(f"  发送邮件至 {receiver} ...")
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, [receiver], msg.as_string())
    print("  ✅ 邮件发送成功")


# ── 主入口 ───────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')} CST] 开始抓取数据...")
    try:
        html = build_html()
        send_email(html)
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
