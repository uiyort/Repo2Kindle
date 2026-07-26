# Repo2Kindle

把任何"按日期命名子目录发布文件"的 GitHub 仓库，定时自动送到你的 Kindle（或任意邮箱）。

不限于某一个仓库——只要目标仓库的更新方式是"每期/每周/每月出一个新目录，
目录里放 epub/mobi/pdf 文件"，改改 `config.yaml` 就能拿来用，不需要碰代码。

默认配置示例已经接好了 [hehonghui/awesome-english-ebooks](https://github.com/hehonghui/awesome-english-ebooks)
（经济学人 / 纽约客 / 大西洋月刊 / 连线），开箱即用。

---

## 效果

每周（或你设置的任意周期），GitHub Actions 自动：

1. 检查 `config.yaml` 里每个 source 对应仓库路径下"最新一期"的目录名
2. 和上次记录对比，有新内容才继续
3. 按格式优先级下载文件（默认 epub → mobi → pdf）
4. 通过邮件把文件当附件发到 Kindle 的"个人文档邮箱"（Send to Kindle）
5. 更新发送记录并提交回仓库，避免重复发送

全程运行在 GitHub Actions 上，免费、不需要自己开服务器。

---

## 快速开始

### 1. Kindle / Amazon 端

1. 打开 <https://www.amazon.com/mycd>（国内是 <https://www.amazon.cn/mycd>）→
   **首选项 → 个人文档设置（Personal Document Settings）**。
2. 记下你 Kindle 设备的收件地址，形如 `yourname_ab12@kindle.com`。
3. 在同一页面的 **"已认可的个人文档电子邮件列表"** 里，加入你要用来发信的邮箱地址
   （不加这一步，邮件会被亚马逊当垃圾邮件拒收）。
4. 确认 Kindle 已连接 Wi-Fi（个人文档是通过 Wi-Fi 自动同步的）。

### 2. 准备一个发件邮箱

需要"应用专用密码/授权码"，不是登录密码：

| 邮箱服务 | SMTP_HOST | SMTP_PORT | 获取方式 |
|---|---|---|---|
| Gmail | `smtp.gmail.com` | `587` | 开启两步验证后在 <https://myaccount.google.com/apppasswords> 生成 |
| QQ 邮箱 | `smtp.qq.com` | `465` | 设置 → 账户 → 开启 SMTP → 生成授权码 |
| 163 邮箱 | `smtp.163.com` | `465` | 同上，设置里开启 SMTP 服务 |

### 3. Fork / 新建仓库

把这几个文件放进你的 GitHub 仓库：

```
your-repo/
├── config.yaml
├── repo2kindle.py
├── requirements.txt
├── state.json
├── LICENSE
└── .github/
    └── workflows/
        └── send-to-kindle.yml
```

> 网页上传时若没有"新建文件夹"按钮：点 **Add file → Create new file**，
> 文件名直接输入完整路径 `.github/workflows/send-to-kindle.yml`，
> 输入 `/` 时 GitHub 会自动建出对应目录。

### 4. 配置 Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**：

| Secret | 说明 |
|---|---|
| `KINDLE_EMAIL` | 你的 Kindle 收件邮箱 |
| `SMTP_HOST` | 见上表 |
| `SMTP_PORT` | 见上表 |
| `SMTP_USER` | 发件邮箱地址 |
| `SMTP_PASS` | 应用专用密码/授权码 |
| `SOURCES`（可选） | 只想跑部分订阅源时填，如 `economist,new_yorker` |

### 5. 手动测试

仓库 → **Actions** → 选择 "Repo2Kindle" → **Run workflow** 手动触发一次，
看日志确认没有报错。也可以在本地先跑：

```bash
pip install -r requirements.txt
python repo2kindle.py --dry-run    # 只打印会发送什么，不真正发邮件
```

---

## 监控别的仓库 / 加订阅源

打开 `config.yaml`，在 `sources` 下面照抄一段改一下就行，不用改代码：

```yaml
  - name: my_source            # 唯一标识，会用来记录发送状态
    label: "显示名称"
    repo: someuser/somerepo    # 目标 GitHub 仓库
    path: some/sub/path        # 仓库里存放"日期目录"的路径
    pattern: '^(\d{4})-(\d{2})-(\d{2})$'  # 日期目录名的正则，捕获组顺序需为 年/月/日
    format_priority: [pdf, epub]          # 可选，覆盖默认格式优先级
    recipient: another@kindle.com         # 可选，发到别的邮箱/设备
```

脚本会自动按"目录名里的日期"找最新的一个，不需要额外写抓取逻辑。

## 调整发送时间

改 `.github/workflows/send-to-kindle.yml` 里的 `cron` 表达式
（分 时 日 月 周，均为 **UTC 时间**），例如：

- 每周一北京时间 9:00 → `0 1 * * 1`
- 每周六多伦多时间早 6:00（夏令时 UTC-4）→ `0 10 * * 6`

## 常见问题

- **收不到邮件**：先看 Actions 日志邮件是否真的发出去了；再检查发件邮箱是否已加入
  Amazon"已认可发件人列表"；最后确认 Kindle 是否联网。
- **403 / rate limit**：确认 workflow 里传了 `GITHUB_TOKEN`（模板已包含），
  未认证的 GitHub API 限额只有 60 次/小时，认证后是 5000 次/小时。
- **月刊类订阅源"没更新"**：属于正常现象，月刊几周才出一期，脚本只在检测到
  新目录时才发送。

## 贡献

欢迎提 PR 增加新的官方"config.yaml 示例"（比如别的杂志源、别的发送渠道），
或者在 Issues 里分享你接入的新仓库。

## License

MIT，见 [LICENSE](LICENSE)。
