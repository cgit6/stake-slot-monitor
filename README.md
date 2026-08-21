# Stake Slot Monitor

監測 Stake Casino Slots 熱門排名，目標為每次完整取得 Top 50，並保留每款遊戲的熱門排名、在線玩家數與 provider。

## 執行規則

- 台北時間週五、週六、週日執行。
- GitHub Actions 每小時整點觸發；非週五～週日會直接跳過。
- 只有完整取得 50 筆才會更新 `data/stake_top50_latest.json`。
- 少於 50 筆視為失敗，不會以部分資料覆蓋上一份完整快照。
- Stake 對 GitHub hosted runner / Azure 類機房 IP 會回 Cloudflare 403，因此 workflow 使用 `self-hosted` runner。

## 檔案

- `stake_top50.py`：Stake GraphQL / browser fallback 抓取器。
- `.github/workflows/stake_top50.yml`：每小時排程。
- `data/stake_top50_latest.json`：最近一次完整 50 筆快照，成功後由 workflow 自動 commit。

## Self-hosted runner

到此 repo 的 **Settings → Actions → Runners → New self-hosted runner**，依 GitHub 畫面指示在一般網路環境的機器上完成一次設定。不要把 runner registration token 或其他憑證 commit 到 repo。
