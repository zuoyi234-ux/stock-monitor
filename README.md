# 📈 股票监控日报

自动监控 **新易盛（300502）/ 中际旭创（300308）/ 宝丰能源（600989）** 的最新公告、研报、新闻，每天北京时间 09:00 通过 QQ 邮件推送，完全免费。

## 推送内容

| 类型 | 数据源 | 时间范围 |
|------|--------|---------|
| 公司公告 | 东方财富 | 近 3 天 |
| 最新研报 | 东方财富 | 近 30 天 |
| 相关新闻 | 东方财富 | 近 3 天 |

## 部署步骤

### 第一步：上传代码到 GitHub

```bash
cd stock-monitor
git init
git add .
git commit -m "init stock monitor"
# 在 GitHub 新建一个仓库，然后：
git remote add origin https://github.com/你的用户名/stock-monitor.git
git push -u origin main
```

### 第二步：获取 QQ 邮箱授权码

1. 登录 [QQ 邮箱](https://mail.qq.com) → **设置** → **账户**
2. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务」
3. 开启 **SMTP 服务** → 按提示发短信验证
4. 复制生成的**授权码**（16位字母，不是 QQ 密码）

### 第三步：配置 GitHub Secrets

进入 GitHub 仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret 名称 | 填写内容 |
|-------------|---------|
| `QQ_EMAIL` | 你的 QQ 邮箱地址（如 `123456@qq.com`） |
| `QQ_PASSWORD` | 上一步获取的**授权码** |
| `RECEIVER_EMAIL` | 接收日报的邮箱（可填同一个 QQ 邮箱） |

### 第四步：启用 GitHub Actions

1. 进入仓库 → **Actions** 标签
2. 如果看到提示「Workflows aren't being run on this forked repository」，点击绿色按钮启用

### 第五步：手动测试

Actions → **股票监控日报** → **Run workflow** → 稍等 1-2 分钟 → 检查邮箱

## 自定义

修改 `monitor.py` 中的 `COMPANIES` 列表可以添加/修改监控标的：

```python
COMPANIES = [
    {"name": "新易盛", "code": "300502"},
    {"name": "中际旭创", "code": "300308"},
    {"name": "宝丰能源", "code": "600989"},
    # 添加更多：
    # {"name": "英伟达A股概念", "code": "xxxxxx"},
]
```

修改 `ANN_LOOKBACK`（公告/新闻天数）和 `RPT_LOOKBACK`（研报天数）调整过滤范围。

## 本地测试

```bash
pip install -r requirements.txt
export QQ_EMAIL="你的QQ邮箱"
export QQ_PASSWORD="你的授权码"
export RECEIVER_EMAIL="接收邮箱"
python monitor.py
```
