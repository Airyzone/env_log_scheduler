# az02 VM 服務與目錄交接手冊

> 本文件是給未來維運或接手人員的現況參考。內容以 2026-08-19（Asia/Taipei）對 `az02` 的多次只讀盤點，以及 22:17 完成重啟後、22:28 的健康驗證為基準。
>
> 文件不包含密碼、token、私鑰或完整連線字串。需要查看秘密設定時，請直接在 VM 上以適當權限讀取，不要把值貼到 ticket、聊天或 Git。

## 1. VM 摘要

| 項目 | 現況 |
|---|---|
| Hostname | `az02` |
| SSH 入口 | `azureuser@env.airyzone.com`；私鑰位於管理者本機，不放在 repository |
| OS | Ubuntu 18.04.6 LTS |
| Kernel | `5.4.0-1109-azure` |
| Python virtualenv | API、scheduler、pet 均為 Python 3.8.20 |
| 磁碟 | `/` 約 29 GB、使用 41%；`/mnt` 使用 32%；`/mnt/mongodb` 使用 66% |
| 記憶體 | 最新登入資訊顯示使用約 13%，swap 0% |
| uptime | 2026-08-19 22:28 盤點時約 11 分鐘；本次已完成重啟 |
| 系統狀態 | `systemd` running、failed units 0、`dpkg --audit` clean |
| 升級狀態 | Ubuntu 大版本升級尚未執行；仍維持 Ubuntu 18.04.6 LTS |

## 2. 整體流量與資料關係

```text
Internet / Life App / EnvSys
              |
       Nginx :80 / :443
              |
   +----------+-----------------------------+
   |                                        |
env.airyzone.com                       靜態網站
current_env.conf                       envsys / cemesys /
        |                               cosafetysys / test
        v
   env_b :5002  <---目前 active
   env_a :5000  <---備用槽位
        |
        +--> MongoDB :27017       一般 Life / Env 資料與 log
        |
        +--> PostgreSQL :5432     Life Chat 的 life_chat DB
                  |
                  v
        chat_outbox_events
                  |
        chat_outbox_worker
                  |
        Centrifugo :8001 <--- Redis :6379
                  |
                  +--> WebSocket / FCM 事件發布

env_log_scheduler
        |
        +--> MongoDB env.log
        +--> log_10min 預聚合
        +--> 完整性確認後清理舊 raw log
        +--> check_alive（跟隨目前 env_a/env_b 槽位）
```

主要原則：

- Nginx 是外部 HTTP/HTTPS 入口；API 的 Gunicorn 只綁定 loopback。
- `env_a` 與 `env_b` 是藍綠部署槽位，兩者目前都啟動，但實際外部流量由 `current_env.conf` 決定。
- Chat 訊息先寫入 PostgreSQL，再由 outbox worker 發布到 Centrifugo，避免只靠即時連線造成事件遺失。
- Redis 是 Centrifugo 的本機 engine/暫存服務，不是 Chat 訊息的主要持久資料庫。
- MQTT 仍有外部相容性用途；不要因 Chat 已使用 Centrifugo 就直接移除 Mosquitto。

## 3. 服務清單

### 3.1 應用程式與資料服務

| 類別 | systemd unit / process | 執行帳號 | 目錄或設定 | Port | 用途與目前狀態 |
|---|---|---|---|---|---|
| Web / reverse proxy | `nginx.service` | master root；worker 由 Nginx 設定為 `www-data` | `/etc/nginx` | `0.0.0.0:80`, `0.0.0.0:443` | 對外 HTTP、HTTPS、反向代理與靜態網站；active |
| API A 槽 | `env_a.service` | `azureuser` | `/home/azureuser/webroot/env_a` | `127.0.0.1:5000` | Gunicorn 3 workers；API 備用/藍綠槽位；health/live 盤點時回 200 |
| API B 槽 | `env_b.service` | `azureuser` | `/home/azureuser/webroot/env_b` | `127.0.0.1:5002` | Gunicorn 3 workers；目前 Nginx active 槽位；health/live 盤點時回 200 |
| Chat outbox | `chat_outbox_worker.service` | `azureuser` | `/home/azureuser/webroot/env_log_scheduler/chat_outbox_worker_main.py` | 無 listen port | 以 PostgreSQL advisory lock 確保單一 worker；輪詢 `chat_outbox_events`，每批最多 50 筆，送往 Centrifugo/FCM；active |
| Log scheduler | `env_log_scheduler.service` | `azureuser` | `/home/azureuser/webroot/env_log_scheduler/main.py` | 無 listen port | 每日建立 `log_10min`、確認後清理舊 raw log，並執行 `check_alive`；active |
| Realtime | `centrifugo.service` | `www-data` | `/usr/local/bin/centrifugo`、`/etc/centrifugo/config.json` | `127.0.0.1:8001` | WebSocket 與 HTTP publish endpoint；由 Nginx `/chat/...` 轉發；依賴 Redis；active |
| Redis | `redis-server.service` | `redis` | `/etc/redis/redis.conf`、`/var/lib/redis` | `127.0.0.1:6379` | Centrifugo engine；盤點時 `PING` 回 `PONG`；active |
| PostgreSQL | `postgresql@10-main.service` | 實際程序為 `postgres` | `/etc/postgresql/10/main`、`/var/lib/postgresql/10/main` | `0.0.0.0:5432` | PostgreSQL 10；Life Chat 的 `life_chat` 連線在盤點時存在；active |
| MongoDB | `mongod.service` | `mongodb` | `/etc/mongod.conf`、`/mnt/mongodb` | `0.0.0.0:27017` | Life/Env 資料與 scheduler log；實際 `dbPath` 為 `/mnt/mongodb`；盤點時 ping 結果為 1；active |
| MQTT | `mosquitto.service` | `mosquitto` | `/etc/mosquitto/mosquitto.conf` | `0.0.0.0:1883`、`*:8081` | Detector / 舊客戶端相容性與 MQTT WebSocket；active |

### 3.2 作業系統、排程與監控服務

| 類別 | service | 用途與目前狀態 |
|---|---|---|
| 延遲工作 | `atd.service` | 執行 `at` 排程；active。spool 目錄目前為 `daemon:daemon`、`0700`；查看 queue 通常需要 root。 |
| TLS 憑證 | `certbot.timer` | 定期執行憑證 renewal；timer active。憑證與 renewal 設定在 `/etc/letsencrypt`。 |
| VM watchdog | `env-watchdog.timer` | 每分鐘檢查 API、readiness、資源與 systemd 相關狀態；timer active，`env-watchdog.service` 為被 timer 觸發的 static unit。 |
| Azure VM Agent | `walinuxagent.service` | Azure VM provisioning、extension 與平台整合；active。 |
| Azure monitoring | `omsagent-cb2fd482-a346-4119-bc09-03fae8e76ab8.service`、`omid.service` | Log Analytics / OMI 監控資料收集；OMS agent 與 OMI 均在運作。 |
| Dependency Agent | `microsoft-dependency-agent` 相關程序 | `microsoft-dependency-agent-manager` 與 child process 均可見；legacy generated unit 顯示為 inactive 時，不要只依 unit 名稱判斷，需同時查看程序與 Azure Monitor 狀態。 |
| 基礎服務 | `ssh`, `cron`, `systemd-resolved`, `systemd-timesyncd`, `rsyslog` 等 | VM 登入、系統排程、DNS、時間同步與系統日誌；目前正常運作。 |

## 4. Nginx 網域與路由

目前 `/etc/nginx/sites-enabled` 可見的主要設定：

| 網域 | 目前路徑 | 備註 |
|---|---|---|
| `env.airyzone.com` | `/etc/nginx/conf.d/current_env.conf` → `127.0.0.1:5002` | 目前 active 為 `env_b`；`/chat/connection/websocket` 與 `/chat/health` 轉至 `127.0.0.1:8001` |
| `envsys.airyzone.com` | `/home/azureuser/webroot/envsys` | 靜態網站 |
| `cemesys.airyzone.com` | `/home/azureuser/webroot/cemesys` | 靜態網站 |
| `cosafetysys.airyzone.com` | `/home/azureuser/webroot/cosafetysys` | 靜態網站 |
| `test.airyzone.com` | `/home/azureuser/webroot/test` | 測試靜態網站 |
| `pet.airyzone.com` | `127.0.0.1:5001` | 設定仍存在，但本次盤點沒有 5001 listener；外部請求回 502。這是目前待確認項目，不可列為正常 production service。 |

### Active slot 的判斷

目前 symlink 為：

```text
/etc/nginx/conf.d/current_env.conf
  -> /etc/nginx/conf.d/env_target_b.map

內容：map $host $env_upstream { default 127.0.0.1:5002; }
```

`env_log_scheduler` 的 `env_core_resolver.py` 也會跟隨這個 symlink，正式模式只接受 `env_a` 或 `env_b`，不會自動退回 `pet`。手動測試 `pet` 必須明確使用 `ENV_CORE_DIR`。

切換或修改前，先做：

```bash
readlink -f /etc/nginx/conf.d/current_env.conf
cat /etc/nginx/conf.d/current_env.conf
sudo nginx -t
curl -fsS http://127.0.0.1:5000/health/live
curl -fsS http://127.0.0.1:5002/health/live
```

不要直接刪除另一個槽位；它是回滾與零/低停機切換的一部分。

## 5. 目錄結構設計

### 5.1 使用者與應用程式區

```text
/home/azureuser/
├── webroot/
│   ├── env/                    # 後端共同/舊部署工作區；目前 systemd 主要執行 env_a/env_b
│   ├── env_a/                  # API 藍綠 A 槽，Gunicorn :5000
│   ├── env_b/                  # API 藍綠 B 槽，Gunicorn :5002，目前 active
│   ├── env_log_scheduler/      # log 預聚合、raw log 維護、check_alive、Chat outbox worker
│   ├── pet/                    # 手動/開發用 Pet app 與部署切換腳本
│   ├── envsys/                 # EnvSys 靜態網站
│   ├── cemesys/                # CemeSys 靜態網站
│   ├── cosafetysys/             # CosafetySys 靜態網站
│   └── test/                   # 測試靜態網站
└── monitoring.env              # watchdog/通知用私密設定；目前權限為 0600，不應同步回 Git
```

應用程式樹的 owner 基準是 `azureuser:azureuser`。本次完整掃描 `/home/azureuser/webroot` 沒有發現 root-owned 檔案；整個 `/home/azureuser` 的 root-owned 殘留 `.rnd` 也已修正為 `azureuser:azureuser`、`0600`。

### 5.2 系統設定區

```text
/etc/
├── systemd/system/
│   ├── env_a.service
│   ├── env_a.service.d/hardening.conf
│   ├── env_b.service
│   ├── env_b.service.d/hardening.conf
│   ├── env_log_scheduler.service
│   ├── chat_outbox_worker.service
│   ├── centrifugo.service
│   ├── env-watchdog.service
│   ├── env-watchdog.timer
│   └── redis-server.service.d/override.conf
├── nginx/
│   ├── sites-enabled/          # domain routing
│   └── conf.d/current_env.conf # active A/B slot symlink
├── redis/redis.conf
├── postgresql/10/main/         # PostgreSQL cluster configuration
├── mongod.conf
├── mosquitto/mosquitto.conf
├── centrifugo/config.json      # 值含 secrets，文件本身不可貼出
├── letsencrypt/                # live 憑證、renewal 設定、私鑰
└── opt/microsoft/omsagent/     # OMS agent 設定
```

### 5.3 資料、執行期與日誌區

| 路徑 | 預期 owner | 用途 |
|---|---|---|
| `/var/lib/redis` | `redis:redis` | Redis 持久化資料 |
| `/var/lib/postgresql/10/main` | `postgres:postgres` | PostgreSQL 10 cluster data |
| `/mnt/mongodb` | `mongodb:mongodb` | MongoDB WiredTiger data；由額外資料磁碟掛載 |
| `/var/opt/microsoft/omsagent/cb2fd482-a346-4119-bc09-03fae8e76ab8` | `omsagent:omiusers` | OMS agent 的 log、state、run |
| `/var/spool/cron/atjobs`、`/var/spool/cron/atspool` | `daemon:daemon` | `atd` 工作佇列 |
| `/home/azureuser/webroot/env_log_scheduler/logs` | `azureuser:azureuser` | scheduler 的 rotating log；systemd journal 另存 service stdout/stderr |
| `/home/azureuser/webroot/pet/gunicorn.log` | `azureuser:azureuser` | Pet 手動啟動程序的歷史 log；目前不能用歷史 log 取代現行 listener 檢查 |

### 5.4 MongoDB 資料磁碟掛載

MongoDB 原本使用根磁碟，因空間不足後已移至額外資料磁碟。現在 `/etc/mongod.conf` 的 `dbPath` 為 `/mnt/mongodb`，`/etc/fstab` 使用穩定 UUID 掛載：

```text
UUID=93ee6d16-c80e-44c5-ba64-653132ca7dbb  /mnt/mongodb  ext4  defaults,nofail  0  2
```

最近一次重啟後的實際對應為 `/dev/sdc1`，但 Azure 可能在不同重啟中重新排列 `/dev/sdX` 名稱；接手或排障時應以 UUID 與 `findmnt -no SOURCE /mnt/mongodb` 為準，不要把 `/dev/sdc1` 寫死在維運腳本中。`mongod.service` 已有 drop-in：

```text
/etc/systemd/system/mongod.service.d/mongodb-mount.conf
RequiresMountsFor=/mnt/mongodb
After=mnt-mongodb.mount
ConditionPathIsMountPoint=/mnt/mongodb
```

## 6. Port 與暴露面

以下是本次 `ss -ltn` 盤點結果的重點：

| Bind | Port | 對應 | 交接注意事項 |
|---|---:|---|---|
| `0.0.0.0` / `[::]` | 22 | SSH | 管理入口；確認 Azure NSG 與 SSH key policy |
| `0.0.0.0` / `[::]` | 80, 443 | Nginx | 公開 Web/HTTPS 入口 |
| `127.0.0.1` | 5000 | env_a | 不應直接對外開放 |
| `127.0.0.1` | 5002 | env_b | 不應直接對外開放；目前 active |
| `127.0.0.1` | 6379 | Redis | 正確保持 loopback；不要改成公開 listen |
| `127.0.0.1` | 8001 | Centrifugo | 正確由 Nginx 內部轉發；不要直接公開 |
| `0.0.0.0` / `[::]` | 5432 | PostgreSQL | 目前對所有介面 listen；確認 Azure NSG、UFW、`pg_hba.conf` 與外部依賴後才可收斂 |
| `0.0.0.0` / `[::]` | 27017 | MongoDB | 目前對所有介面 listen；確認 API、scheduler、外部用戶端與認證後才可收斂 |
| `0.0.0.0` / `[::]` | 1883 | Mosquitto MQTT | 外部 detector/舊客戶端可能依賴；不要直接移除 |
| `*` | 8081 | Mosquitto MQTT WebSocket | 由 `mosquitto.conf` 的 `listener 8081` / `protocol websockets` 提供 |
| `0.0.0.0` | 25324 | `omsagent`（OMS monitoring agent；PID 會隨重啟變更） | 已用 root `ss -ltnp 'sport = :25324'` 確認；修改網路設定前仍應先確認當前 PID |
| — | 5001 | Pet route 目標 | 本次沒有 listener；`pet.airyzone.com` 因此回 502 |

PostgreSQL、MongoDB、MQTT 的 all-interface listen 是目前設定事實，不等於已確認它們可被公網存取；實際風險還要對照 Azure NSG、VM firewall、服務認證與 `pg_hba.conf`/Mongo/MQTT ACL。

目前 UFW 為 inactive；`/lib/ufw` 已修正為 `root:root`、`0755`。因此不能把 UFW 當成目前有效的 VM 入站防護，外部暴露面仍需以 Azure NSG、服務自身 ACL 與必要的網路測試確認。

## 7. 特殊設定與不可誤刪項目

### Redis systemd override

目前 `/etc/systemd/system/redis-server.service.d/override.conf` 是：

```ini
[Service]
Type=simple
ExecStart=
ExecStart=/usr/bin/redis-server /etc/redis/redis.conf --daemonize no
```

這是為了讓 Redis 在 systemd 管理下以前景模式執行。不要只刪掉 override 或恢復 daemonize 行為而不重新驗證 `MainPID`、`ActiveState` 與 `redis-cli PING`。

### API service hardening

`env_a.service` 與 `env_b.service` 都有 `hardening.conf`，包含：

- 5 分鐘內最多 5 次啟動限制
- `Restart=on-failure`、`RestartSec=10`
- `TasksMax=256`
- `TimeoutStopSec=30`
- `KillMode=control-group`

### Scheduler 排程解讀

- 每日聚合時間由 `SCHEDULER_HOUR` / `SCHEDULER_MINUTE` 決定，預設為 03:00。
- `check_alive` 的實際 APScheduler trigger 是每 5 分鐘：`CronTrigger(minute='*/5')`。
- `main.py` 的啟動 log 仍寫「每 15 分鐘」，這是過時訊息；維運判斷應以實際程式碼與 journal 執行紀錄為準。
- raw log 清理只有在 `log_10min` 聚合成功後才執行，且保留天數不得低於 30 天。
- `phone_log` 壓縮功能受環境變數保護；不要在未確認 dry-run、覆蓋率與資料備份前開啟 execute。

### 憑證與已停用 renewal

- `certbot.timer` active；目前 renewal 檔案包括 `env.airyzone.com`、`envsys.airyzone.com`、`mqtt.airyzone.com`、`pet.airyzone.com`、`test.airyzone.com`。
- `envaz.airyzone.com.conf` 已改名為 `envaz.airyzone.com.conf.disabled-20260819200637`，目前不是 active renewal 設定。不要因看到檔案就重新啟用；先確認 DNS、Nginx 與實際使用者。
- Nginx 目前多個站點引用 `/etc/letsencrypt/live/envsys.airyzone.com/` 憑證路徑；renewal/憑證變更後要驗證所有相關 domain。

### AppArmor 與 DHCP

`/sbin/dhclient` 使用 AppArmor `Enforce` profile。原本啟動時曾出現執行 `/bin/true` 被拒絕；檔案 owner 修復為 `root:root` 後仍存在，確認不是一般 Unix 權限問題，而是 profile 缺少執行規則。

目前以 local override 修復：

```text
/etc/apparmor.d/local/sbin.dhclient
/bin/true ixr,
```

已重新載入 `/sbin/dhclient` profile，`aa_exec_test=pass`，修復後沒有新的 dhclient AppArmor denial。不要為了解決此問題而停用整個 AppArmor；若修改 profile，先備份並使用 `apparmor_parser -r` 重新載入。

## 8. 常用只讀檢查

```bash
# 身分與整體 systemd
hostname
sudo systemctl is-system-running
sudo systemctl --failed --no-pager

# A/B active slot
readlink -f /etc/nginx/conf.d/current_env.conf
cat /etc/nginx/conf.d/current_env.conf
sudo nginx -t

# API / realtime
curl -fsS http://127.0.0.1:5000/health/live
curl -fsS http://127.0.0.1:5002/health/live
curl -fsS http://127.0.0.1:8001/health

# 資料服務
redis-cli -h 127.0.0.1 -p 6379 PING
pg_isready -h 127.0.0.1 -p 5432
mongo --quiet --host 127.0.0.1:27017 --eval 'db.adminCommand({ping:1}).ok'

# 服務 journal
sudo journalctl -u env_a.service -u env_b.service -n 100 --no-pager
sudo journalctl -u env_log_scheduler.service -u chat_outbox_worker.service -n 100 --no-pager
sudo journalctl -u redis-server.service -u centrifugo.service -n 100 --no-pager

# scheduler 只讀狀態（會連線 MongoDB）
cd /home/azureuser/webroot/env_log_scheduler
.venv/bin/python build_log_10min.py --status
```

### 需要 root 才能完成的 owner 稽核

不要用廣泛的 `chown -R` 或 `chmod -R` 修復。應針對預期 owner 的單一資料樹列出異常，例如：

```bash
sudo find /var/lib/redis -xdev \( ! -user redis -o ! -group redis \) -printf '%u:%g %m %p\n'
sudo find /var/lib/postgresql/10/main -xdev \( ! -user postgres -o ! -group postgres \) -printf '%u:%g %m %p\n'
sudo find /mnt/mongodb -xdev \( ! -user mongodb -o ! -group mongodb \) -printf '%u:%g %m %p\n'
sudo find /var/opt/microsoft/omsagent/cb2fd482-a346-4119-bc09-03fae8e76ab8/log -xdev \( ! -user omsagent -o ! -group omiusers \) -printf '%u:%g %m %p\n'
```

輸出為空才表示該樹沒有 owner/group 異常；不要把「服務 active」當成「所有資料檔 owner 都正確」。

## 9. 目前健康快照與待辦

### 2026-08-19 22:28（重啟後）

以下是本次重啟後的最新驗證結果：

- `hostname`: `az02`；uptime 約 11 分鐘；load average `0.07, 0.08, 0.07`。
- `systemd`: `running`；failed units 0；`dpkg --audit` 無輸出。
- `/`: 29 GB 中使用 41%；`/mnt`: 使用 32%；`/mnt/mongodb`: 32 GB 中使用 66%；inode 使用率均低。
- `/mnt/mongodb` 實際掛載來源為 `/dev/sdc1`，對應 UUID `93ee6d16-c80e-44c5-ba64-653132ca7dbb`。
- MongoDB ping 為 `1`；Redis 回傳 `PONG`；PostgreSQL 顯示 `accepting connections`。
- Nginx、Redis、PostgreSQL、MongoDB、Mosquitto、Centrifugo、`env_a`、`env_b`、Chat outbox、scheduler、`atd` 與 OMS agent 均為 `active`。
- AppArmor module 已載入，`/sbin/dhclient` profile 正常；修復後沒有新的 denial。
- 曾短暫出現 `[dpkg-query] <defunct>` zombie，parent 為 Microsoft Dependency Agent；等待 10 秒後已消失，未發現持續性 zombie。
- 核心系統路徑的非 root group 檔案只有標準 setgid 程式：`unix_chkpwd`、`pam_extrausers_chkpwd`、`ssh-agent`、`crontab`、`chage`、`expiry`；這些是預期的 `shadow`、`ssh`、`crontab` 群組權限，不是 owner 損壞。

### 已驗證

- `systemd`: `running`，failed units 0。
- `dpkg --audit`: clean；Redis、Redis server、Redis tools 均為 `install ok installed`。
- Redis: `PONG`。
- PostgreSQL: `127.0.0.1:5432 - accepting connections`。
- MongoDB: ping 結果 1。
- `https://env.airyzone.com/health/live`: HTTP 200。
- `https://env.airyzone.com/health/ready`: HTTP 200。
- `https://env.airyzone.com/chat/health`: HTTP 200。
- `/home/azureuser/webroot` 遞迴 owner 檢查沒有 root-owned 檔案。
- 本次重啟後完整健康檢查再次確認 systemd、dpkg、資料庫、服務與 MongoDB 資料磁碟均正常。

### 待處理或需接手人確認

1. `pet.airyzone.com` 的 Nginx 路由存在，但 5001 沒有 listener，外部回 502。確認 Pet 是否仍需使用；若需要，應恢復其明確的啟動/監控方式，而不是只重啟 Nginx。
2. PostgreSQL、MongoDB、MQTT 目前對 all interfaces listen；UFW inactive。確認 Azure NSG、服務認證、ACL 與外部設備依賴後，再評估是否收斂 listen address。
3. Ubuntu 18.04.6 已過時；大版本升級仍未執行，應另訂維護窗口，不要在一般故障處理中順手執行。
4. 本文件的應用程式 owner 與核心系統路徑已檢查；Redis/PostgreSQL/MongoDB/OMS 深層資料樹的完整 root 遞迴稽核仍應由 root terminal 另行執行。

## 10. 近期已完成的復原事項

以下變更在本文件建立前已完成，接手人應保留其結果：

- 結束卡住的 apt/dpkg 程序並完成 `dpkg --configure --pending`；Redis 套件已完成設定。
- 建立 Redis systemd foreground override，Redis 現在由 systemd 管理且 `PONG` 正常。
- 修復 `atd` spool 目錄 owner/mode，`atd.service` 已 active。
- 修復 OMS agent log/state 檔案的 `omsagent:omiusers` 權限，OMS service 已 active。
- 停用不再使用的 `envaz.airyzone.com` Certbot renewal 檔案，保留 disabled 備份。
- 修復 `/home/azureuser/.rnd` 為 `azureuser:azureuser`、`0600`。
- 修復系統檔案 owner/metadata 異常：以已安裝套件版本重裝可取得的核心套件，完成 dpkg 設定，並針對 `/lib`、alternative links、MongoDB tools 與 `/etc/mongod.conf` 做 targeted repair；沒有使用全域 `chown -R`。
- 修復 `/sbin/dhclient` AppArmor 規則，備份位於 `/root/apparmor-repair-20260819222423`。
- 修復後已完成一次 VM reboot；重啟後 MongoDB 資料磁碟以 UUID 正確掛載，所有主要服務與資料庫健康檢查通過。

所有上述變更都應視為既有 production 狀態；若需要重做，先備份目前設定並逐項驗證，不要以全域 owner/permission 命令取代 targeted repair。

## 11. 變更安全規則

- 任何 root 指令先確認 `hostname` 為 `az02`。
- 服務設定變更前先備份原檔；變更後依序執行 `systemctl daemon-reload`（需要時）、`systemctl is-active`、journal、health endpoint。
- 不要直接執行 `chown -R`、`chmod -R`、`apt-get upgrade`、`do-release-upgrade` 或 `reboot`，除非已確認目標、備份、維護窗口與 rollback。
- 不要只切換 Nginx 而不確認對應 API health、MongoDB 連線與 scheduler 的 active slot。
- 不要直接修改 Chat PostgreSQL 資料；任何 migration 或 SQL mutation 都要先確認精確 SQL、備份與回滾方案。
- 不要把 `.env`、`monitoring.env`、Centrifugo config 的 secret 值貼到交接文件；文件只記錄路徑、用途與 owner/mode。
