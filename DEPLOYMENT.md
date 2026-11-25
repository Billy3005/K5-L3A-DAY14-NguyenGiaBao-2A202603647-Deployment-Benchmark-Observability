# Deployment Information

## Public URL

https://agent-production-f6303733.up.railway.app

## Platform

Railway. Project `k5-day14-deployment-bao`, environment `production`, service `agent` và Redis (cả hai Online). Deploy ID `1b17a3a9-e159-4582-bdf3-67f02c204094` (Active), deploy path `06-lab-complete` (build bằng `Dockerfile`, cấu hình `06-lab-complete/railway.toml`).

Workspace: gói Railway **Hobby** đang có sẵn, do học viên chọn. Tài liệu này không ghi nhận Lab Coach đã phê duyệt hay xác nhận lựa chọn đó.

## Deploy

Lệnh deploy, chạy từ **gốc repo**:

```bash
railway up ./06-lab-complete --path-as-root --service agent
```

Service Redis nằm cùng project; `agent` trỏ tới Redis bằng reference variable `REDIS_URL`. Railway cấp `PORT`.

## Environment Variables Set

Chỉ ghi tên và giá trị không bí mật. Giá trị bí mật đặt trực tiếp trên Railway, không nằm trong repo.

| Biến | Giá trị / loại |
|---|---|
| `AGENT_API_KEY` | secret, chuỗi ngẫu nhiên (không ghi trong repo) |
| `REDIS_URL` | reference variable tới service Redis |
| `ENVIRONMENT` | đã đặt |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | do Railway cấp, không đặt thủ công |

## Test Commands

Bốn lệnh kiểm tra (`AGENT_API_KEY` lấy từ biến môi trường của shell, không ghi vào file):

```bash
BASE=https://agent-production-f6303733.up.railway.app
: "${AGENT_API_KEY:?đặt AGENT_API_KEY là key đã đặt trên Railway}"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # mong đợi 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # mong đợi 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # mong đợi 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # mong đợi 200
```

Kết quả ghi trong [reports/public-http.json](reports/public-http.json) (`tested_at` `2026-11-25T09:32:30.4553284+00:00`):

| Lệnh | Mong đợi | Kết quả |
|---|---|---|
| `GET /health` | 200 | **200** |
| `GET /ready` | 200 | **200** |
| `POST /ask` không key | 401 | **401** |
| `POST /ask` có key | 200 | **200** |

Checker của lab đã chạy với URL public trong WSL2. Kết quả **PASS 12/12, 42/42 checks passed**. [Output đầy đủ](reports/production-readiness-cloud.txt)

## Screenshots

| File | Nội dung |
|---|---|
| [screenshots/dashboard.png](screenshots/dashboard.png) | Dashboard Railway: project `k5-day14-deployment-bao`, service `agent` và Redis đều Online |
| [screenshots/running.png](screenshots/running.png) | Deploy `1b17a3a9` ở trạng thái Active, Deploy Logs có `GET /ready` 200, `GET /health` 200, `POST /ask` 401 rồi 200 |
| [screenshots/test.png](screenshots/test.png) | Ảnh file JSON kết quả 4 lệnh `curl` (`reports/public-http.json`), không phải terminal |

Trong ba ảnh không thấy giá trị `AGENT_API_KEY`.
