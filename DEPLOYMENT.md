# Deployment Information

> **Trạng thái: chưa deploy.** Railway CLI đã đăng nhập. Workspace hiện tại dùng gói HOBBY. Bài lab đang chờ quyết định về workspace triển khai. Hiện **chưa có URL public**, chưa có kết quả kiểm tra trên cloud và chưa có ảnh cloud. File này ghi lại lệnh sẽ chạy; mọi mục "Kết quả" giữ nguyên "Chưa chạy" cho tới khi chạy thật.

## Public URL

Chưa có. Chưa tạo domain public.

## Platform

Railway. Deploy agent Part 6 trong `06-lab-complete/` (build bằng `Dockerfile`, cấu hình `06-lab-complete/railway.toml`).

## Deploy

Chạy từ **gốc repo**:

```bash
railway login
railway up ./06-lab-complete --path-as-root --service agent
```

Trên Railway cần có sẵn: một project, một service Redis, một service tên `agent` (khớp `--service agent`), các biến môi trường bên dưới, và domain public của `agent` (Settings → Networking). `/ready` phải trả 200 trước khi chụp ảnh.

## Environment Variables Set

Chỉ ghi **tên** biến. Giá trị đặt trực tiếp trên Railway, không ghi vào repo.

| Biến | Loại | Ghi chú |
|---|---|---|
| `AGENT_API_KEY` | secret | Key ngẫu nhiên, tạo bằng `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `REDIS_URL` | reference | Dùng reference variable tới service Redis trong cùng project |
| `ENVIRONMENT` | config | Môi trường chạy |
| `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD` | config | Tùy chọn, app có giá trị mặc định |
| `PORT` | do Railway cấp | Không cần đặt |

Trạng thái: **chưa đặt** (chưa deploy).

## Test Commands

Chỉ chạy khi đã có URL public thật. Hai biến dưới đây phải là giá trị thật của bạn; lệnh sẽ dừng nếu chưa đặt:

```bash
: "${BASE:?đặt BASE là URL public của Railway, không có dấu / ở cuối}"
: "${AGENT_API_KEY:?đặt AGENT_API_KEY là key đã đặt trên Railway}"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # mong đợi 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # mong đợi 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # mong đợi 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # mong đợi 200
```

Sau khi 4 lệnh đúng, chạy thêm trong WSL2, từ `06-lab-complete/`: `python check_production_ready.py --public-url "$BASE"`.

| Lệnh | Mong đợi | Kết quả |
|---|---|---|
| `GET /health` | 200 | Chưa chạy |
| `GET /ready` | 200 | Chưa chạy |
| `POST /ask` không key | 401 | Chưa chạy |
| `POST /ask` có key | 200 | Chưa chạy |

## Screenshots

Chưa có ảnh cloud. Khi chụp, lưu đúng tên:

| File | Nội dung cần chụp |
|---|---|
| `screenshots/dashboard.png` | Dashboard Railway của project, thấy service `agent` và Redis đã deploy |
| `screenshots/running.png` | Service `agent` đang chạy: deployment thành công, healthcheck qua |
| `screenshots/test.png` | Terminal chạy 4 lệnh `curl`, thấy mã HTTP, không lộ key |

Che `AGENT_API_KEY` và mọi token trước khi chụp hoặc commit.
