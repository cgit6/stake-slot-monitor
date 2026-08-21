# Stake Slot Monitor

監測 Stake Casino Slots 熱門排名，目標為每次完整取得 Top 50，並保留每款遊戲的熱門排名、在線玩家數與 provider。

## 執行規則

- 台北時間週五、週六、週日執行。
- GitHub Actions 每小時整點觸發；非週五～週日會直接跳過。
- 只有完整取得 50 筆才會更新 `data/stake_top50_latest.json`。
- 少於 50 筆視為失敗，不會以部分資料覆蓋上一份完整快照。
- Workflow 使用 `self-hosted` runner。

## 為什麼需要一次人工驗證

Stake 對自動化瀏覽器會顯示 Cloudflare「驗證您是人類」頁面。程式不會自動點擊或繞過這個驗證；改用持久化瀏覽器 profile，讓 runner 重用你人工驗證過的 session。

人工驗證後的 profile 預設存放在：

`~/.stake-slot-monitor-profile`

這個目錄位於 runner 使用者的 Home，不在 repo workspace，因此不會被 `actions/checkout` 清除，也不會 commit 到 GitHub。

## 第一次設定 Cloudflare profile

在 **同一台 self-hosted runner、同一個 Linux/WSL 使用者** 的終端機執行：

```bash
cd ~/actions-runner/_work/stake-slot-monitor/stake-slot-monitor
git fetch origin master
git checkout master
git reset --hard origin/master
bash bootstrap_cloudflare.sh
```

會開啟一個 Chromium 視窗。看到 Stake 的 Cloudflare 頁面後，請人工勾選「驗證您是人類」。終端機顯示：

`Cloudflare verification passed. Profile has been saved.`

之後即可關閉瀏覽器。未來每小時 workflow 會重用同一份 profile。

如果未來 Cloudflare clearance 過期，workflow 會以 `bootstrapRequired=true` 失敗；再執行一次 `bash bootstrap_cloudflare.sh` 即可更新 profile。

## 檔案

- `stake_top50.py`：Stake GraphQL / 持久化 browser profile 抓取器。
- `bootstrap_cloudflare.sh`：一次性人工 Cloudflare 驗證工具。
- `.github/workflows/stake_top50.yml`：每小時排程。
- `data/stake_top50_latest.json`：最近一次完整 50 筆快照，成功後由 workflow 自動 commit。

## Self-hosted runner

到此 repo 的 **Settings → Actions → Runners → New self-hosted runner**，依 GitHub 畫面指示完成一次設定。不要把 runner registration token、cookie、瀏覽器 profile 或其他憑證 commit 到 repo。
