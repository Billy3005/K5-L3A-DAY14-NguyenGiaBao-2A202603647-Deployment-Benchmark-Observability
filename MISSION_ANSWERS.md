# Day 14 Lab — Mission Answers

> **Nguồn bằng chứng.** Số liệu và output trong file này lấy từ các lệnh đã chạy trong workspace (phiên Codex) và được ghi lại ở `reports/local-http.txt`, `reports/production-readiness.txt`, `06-lab-complete/benchmark-observability/develop/reports/eval_v2.json`. Số liệu benchmark và observability (CP7, CP8) nằm trong [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md). Mục **AI log** ghi cách tôi dùng Codex và Claude Code trong quá trình làm bài. Phần giải thích khái niệm được suy ra từ việc đọc code và đề lab.

---

## CP0 — Setup

- Chạy trong **WSL2**: Python **3.11.18**, `python -c "import os; print(os.name)"` in `posix`. Đây là điều kiện để checker gửi được SIGTERM (trên Python Windows, tiêu chí Graceful shutdown không kiểm tra được).
- Docker Compose **v5.1.4**; Docker Engine **29.5.3** (số này in ra trong output của checker).
- `docker run --rm hello-world` chạy thành công.

---

## Part 1 — Localhost vs Production (CP1)

### Exercise 1.1 — Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret** (dòng 17-18): `OPENAI_API_KEY`, `DATABASE_URL` chứa mật khẩu. Push lên GitHub là lộ.
2. **Log ra secret** (dòng 34): `print(... OPENAI_API_KEY)`. Log thường được gửi sang hệ thống khác nên key lộ theo.
3. **`print()` thay vì logging có cấu trúc** (dòng 33, 34, 38): không có level, không có timestamp, không parse được.
4. **Không có health check** (dòng 42-43): platform không biết app đã chết để restart.
5. **Port cố định 8000** (dòng 52): Railway/Render cấp port qua biến `PORT`.
6. **`host="localhost"`** (dòng 51): trong container, request từ bên ngoài không vào được; cần `0.0.0.0`.
7. **`reload=True` và `DEBUG = True`** (dòng 21, 53): chế độ debug/auto-reload không dành cho production.
8. **Không xử lý shutdown**: request đang chạy bị cắt khi tắt.

### Exercise 1.2 — Chạy thực tế

Bản mẫu chạy bằng `uvicorn app:app` trên **cổng 18214** trong WSL (cổng khác 8000 để tránh đụng các bản dùng chung cổng). Bản develop nhận `question` qua query string.

Kết quả gọi `POST /ask?question=...` (HTTP 200, thân phản hồi ghi trong `reports/local-http.txt`):

```json
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Kết quả `GET /health` của bản production mẫu (khớp cấu trúc của `01-localhost-vs-production/production/app.py`, gồm `uptime_seconds`, `version`, `environment`, `timestamp`):

```json
{"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:27:35.637711+00:00"}
```

Lưu ý quan trọng về graceful shutdown ở app mẫu: `01-localhost-vs-production/production/app.py` đăng ký `signal.signal(SIGTERM, handle_sigterm)` mà hàm này **chỉ ghi log**, không gọi lại handler cũ của uvicorn. Nếu handler tự đăng ký thay thế handler của uvicorn thì process có thể không tự thoát khi nhận SIGTERM. Đây là rủi ro đã được cảnh báo trong đề (CODE_LAB, Step 7), chưa được kiểm chứng riêng trên app mẫu. Ở **CP5 thì khác**: app Part 6 không đăng ký signal handler nào, và checker đã xác nhận process thoát với exit code 0 (xem Part 6).

### Exercise 1.3 — So sánh develop / production

| Feature | Develop | Production | Tại sao quan trọng |
|---|---|---|---|
| Config | Hardcode trong code | Đọc từ env qua `config.py` | Đổi môi trường không phải sửa code; secret không nằm trong git |
| Health check | Không có | `/health` (liveness) và `/ready` (readiness) | Platform tự restart app chết; load balancer không gửi traffic vào instance chưa sẵn sàng |
| Logging | `print()`, in cả secret | JSON, không log secret | Hệ thống log (Loki, Datadog) lọc và truy vấn được |
| Shutdown | Đột ngột | `lifespan` + xử lý SIGTERM | Deploy hay scale-down không làm hỏng request đang chạy |
| Host / Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên cloud |

Anti-pattern develop đã được production sửa: secret hardcode ở `develop/app.py` dòng 17-18 được thay bằng `os.getenv` trong `production/config.py`.

---

## Part 2 — Docker (CP2)

### Exercise 2.1 — Dockerfile develop

1. **Base image:** `python:3.11` (bản đầy đủ, không phải `slim`).
2. **Working directory:** `/app`.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo layer. Chỉ sửa code thì layer `pip install` được dùng lại; nếu `COPY . .` đứng trước thì mỗi lần sửa code đều cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh mặc định và bị thay thế khi gõ `docker run image <lệnh khác>`. `ENTRYPOINT` là phần cố định; tham số của `docker run` được nối vào sau nó.

### Exercise 2.2 / 2.3 — Build, chạy, kích thước

Build từ **gốc repo** (Dockerfile `COPY` theo đường dẫn tính từ gốc):

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent
```

Kích thước đo được:

| Image | Disk usage (`docker images`) | Content size (`docker image inspect`) |
|---|---|---|
| `my-agent:develop` | 1.67 GB | 426 319 869 byte |
| `my-agent:advanced` | 240 MB | 57 408 917 byte |
| Giảm | ≈ **85.6%** (hệ thập phân) | ≈ **86.5%** (= (426319869 − 57408917) / 426319869) |

Hai cột đo hai thứ khác nhau: *disk usage* gồm cả các layer chia sẻ và dữ liệu lưu trên đĩa, *content size* là tổng kích thước nén/nội dung của image. Vì vậy hai tỷ lệ giảm hơi lệch nhau; bài dùng số `docker images` (85.6%) làm số chính.

Container develop chạy ở **cổng 18215**, `POST /ask?question=...` trả **HTTP 200**:

```json
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Multi-stage giảm dung lượng ở đâu:

- **Stage 1 (builder):** cài gcc, libpq-dev và chạy `pip install --user`. Stage này chỉ để build.
- **Stage 2 (runtime):** bắt đầu lại từ `python:3.11-slim`, chỉ copy thư mục package đã cài và source. Công cụ build, apt cache không vào image cuối.
- Image nhỏ hơn nhờ base `slim` và vì runtime không chứa phần build. Chạy bằng user non-root là lợi ích bảo mật.

### Exercise 2.4 — Stack Docker Compose

Sơ đồ (đọc từ `02-docker/production/docker-compose.yml`):

```text
Client -> Nginx :80 -> agent :8000 -> Redis  (session / rate limit)
                                   -> Qdrant (vector DB)
```

Các service chung network `internal` và gọi nhau bằng tên service (Docker DNS). Chỉ Nginx mở cổng ra ngoài. `agent` chờ Redis và Qdrant `service_healthy` rồi mới khởi động.

Kết quả test qua Nginx cổng **80**: `GET /health` trả 200 (response có `version` **2.0.0**) và `POST /ask` với body JSON trả 200.

---

## Part 3 — Cloud Deployment (CP6)

### Trạng thái

**Đã deploy.** Agent Part 6 chạy trên Railway với URL public **https://agent-production-f6303733.up.railway.app**.

| Mục | Giá trị |
|---|---|
| Project / environment | `k5-day14-deployment-bao` / `production` |
| Service | `agent` (Online) và Redis (Online, có `redis-volume`) |
| Deploy ID | `1b17a3a9-e159-4582-bdf3-67f02c204094` (Active) |
| Deploy path | `06-lab-complete` |
| Workspace | Gói Railway **Hobby** đang có sẵn, do học viên chọn. Báo cáo này không ghi nhận Lab Coach đã phê duyệt hay xác nhận lựa chọn đó |

Kết quả 4 lệnh tự kiểm, ghi trong [reports/public-http.json](reports/public-http.json) (`tested_at` `2026-11-25T09:32:30.4553284+00:00`):

| Lệnh | Mong đợi | Kết quả |
|---|---|---|
| `GET /health` | 200 | **200** |
| `GET /ready` | 200 | **200** |
| `POST /ask` không key | 401 | **401** |
| `POST /ask` có key | 200 | **200** |

Ảnh: [dashboard.png](screenshots/dashboard.png) (project, service `agent` và Redis Online), [running.png](screenshots/running.png) (deploy `1b17a3a9` Active, log request), [test.png](screenshots/test.png) (ảnh JSON kết quả `curl` ở `reports/public-http.json`, không phải terminal). Lệnh deploy và biến môi trường (chỉ tên, không có giá trị bí mật) nằm trong [DEPLOYMENT.md](DEPLOYMENT.md).

Cấu hình sẵn sàng: `06-lab-complete/railway.toml` đặt `builder = "DOCKERFILE"` và `healthcheckPath = "/health"`; `CMD` của Dockerfile đọc `${PORT:-8000}`. Checker tiêu chí 12 đã ✅ ở mức cấu hình.

### So sánh `railway.toml` và `render.yaml`

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng | TOML | YAML (Blueprint) |
| Phạm vi | Cấu hình build/deploy của **một** service | Khai báo **nhiều** service trong một file (web + redis) |
| Biến môi trường | Đặt qua dashboard hoặc `railway variables set` | Khai báo trong `envVars`; secret dùng `sync: false` hoặc `generateValue: true` |
| Redis | Tạo riêng bằng add-on rồi trỏ `REDIS_URL` | Khai báo `type: redis` ngay trong file |
| Cập nhật | `railway up` | Tự sync khi push GitHub (`autoDeploy`) |

Khác nhau vì Railway coi file là cấu hình của một service trong project, còn Render coi file là Infrastructure-as-Code của cả hệ thống.

### Exercise 3.3 — Pipeline Cloud Run

`cloudbuild.yaml` chạy bốn bước nối tiếp (`waitFor`): chạy test (pytest) → build image gắn tag `$COMMIT_SHA` và `latest` (dùng `--cache-from`) → push lên Container Registry → `gcloud run deploy` (min 1 / max 10 instance, 512Mi, secret lấy từ Secret Manager). `service.yaml` khai báo cùng service dưới dạng IaC: liveness `/health`, startup probe `/ready`, mỗi instance xử lý tối đa 80 request đồng thời. Phần này chỉ đọc cấu hình, không deploy.

---

## Part 4 — API Security (CP3)

### Exercise 4.1 — API key (`04-api-gateway/develop/app.py`)

- **Key được check ở đâu:** hàm `verify_api_key` (dòng 39-54), gắn vào `/ask` bằng `Depends`.
- **Sai key thì sao:** bản develop trả **403** (thiếu key mới trả 401). Bản Part 6 đã thống nhất cả hai trường hợp trả 401.
- **Rotate key:** key đọc từ biến `AGENT_API_KEY`, nên đổi giá trị rồi restart; muốn không downtime thì tạm chấp nhận cả key cũ lẫn key mới.

Output `curl -i` thực tế (trích nguyên văn từ `reports/local-http.txt`).

Không có key → **401**:

```text
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 08:36:42 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

Có key → **200**:

```text
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 08:36:42 GMT
server: uvicorn
content-length: 145
content-type: application/json

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 / 4.3 — JWT và rate limit (`04-api-gateway/production`)

Luồng JWT: đổi `student` / `demo123` ở `POST /auth/token` lấy token ký HS256 chứa `sub`, `role`, `exp`; server chỉ verify chữ ký, không tra database. Token không được ghi trong báo cáo.

Vòng lặp gọi liên tục: **10 request đầu trả 200, các request sau trả 429** (đúng giới hạn 10 req/phút của user):

```text
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 200 OK
HTTP/1.1 429 Too Many Requests
HTTP/1.1 429 Too Many Requests
date: Wed, 25 Nov 2026 08:36:44 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795595865
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Trả lời câu hỏi của đề:

- **Thuật toán:** sliding window (mỗi user một `deque` timestamp, loại các timestamp quá 60 giây).
- **Limit:** user 10 request/phút, admin 100 request/phút.
- **Admin:** role `admin` (tài khoản `teacher`) dùng `rate_limiter_admin` với ngưỡng cao hơn; đây là ngưỡng khác chứ không phải bỏ qua hoàn toàn rate limit.

### Exercise 4.4 — Cost guard

Kiểm tra budget **trước** khi gọi LLM (vượt thì trả 402) và ghi chi phí theo token **sau** khi gọi. Bản mẫu lưu trong RAM nên mất khi restart và không chia sẻ giữa các worker; bản Part 6 chuyển sang Redis (xem Part 6).

Rate limit bảo vệ **tốc độ** (chống spam). Cost guard bảo vệ **tiền**: vài request rất dài vẫn có thể đốt hết budget mà không vượt rate limit. Cần cả hai.

---

## Part 5 — Scaling & Reliability (CP4)

### Exercise 5.1 / 5.2 — Health, readiness, shutdown (`05-scaling-reliability/develop`)

- **Liveness `/health`:** process còn sống không. Fail → platform **restart** container.
- **Readiness `/ready`:** có nhận traffic được không. Fail → load balancer **ngừng gửi traffic** nhưng không restart.

Output thực tế (`reports/local-http.txt`):

```text
{"status":"ok","uptime_seconds":0.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:36:46.298612+00:00","checks":{"memory":{"status":"ok","used_percent":23.3}}}
{"ready":true,"in_flight_requests":1}
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

`in_flight_requests` bằng 1 vì chính request `/ready` đang được middleware đếm.

**Graceful shutdown ở app mẫu develop (quan sát khi thử):** `05-scaling-reliability/develop/app.py` tự đăng ký `signal.signal(SIGTERM, handle_sigterm)` và `SIGINT`, handler này chỉ ghi log. Khi thử gửi SIGTERM lúc chạy dưới `uvicorn app:app`, request đang xử lý vẫn trả **200**, nhưng handler tự đăng ký chỉ ghi log và không gọi lại handler của uvicorn nên **process vẫn sống** và phải được dọn (tắt) thủ công sau thử nghiệm. Điều này khác với CP5: ở Part 6, checker gửi SIGTERM lúc đang có request, request vẫn trả 200 và process **tự thoát với exit code 0**, `docker stop` xong trong 0.9 giây, vì code Part 6 không đăng ký signal handler. Hai kết quả không mâu thuẫn; chỉ app mẫu thiếu bước gọi lại handler cũ.

### Exercise 5.3 — Stateless

State trong RAM của instance 1 không thấy được từ instance 2. Khi scale ra nhiều instance, request tiếp theo của cùng một user có thể rơi vào instance khác và mất state. Giải pháp là đưa state vào Redis để mọi instance đọc chung.

### Exercise 5.4 / 5.5 — Load balancing và stateless

Chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` rồi `python test_stateless.py`. Kết quả:

- Session `5b4a5d4b-61ce-47e1-886d-1ab71fe67523`.
- 5 request liên tiếp được phục vụ lần lượt bởi: `instance-95ee44`, `instance-19f5fa`, `instance-76b1be`, `instance-95ee44`, `instance-19f5fa`.
- Lịch sử hội thoại có đủ **10 message** (5 câu hỏi + 5 câu trả lời).

Giải thích: Nginx chia request theo round-robin sang 3 instance, nhưng history vẫn liền mạch vì session được đọc/ghi qua kho dùng chung (Redis) thay vì RAM của từng instance.

---

## Part 6 — Final Project (CP5)

### Thiết kế

| Tiêu chí | File | Thiết kế và lý do |
|---|---|---|
| Config | `app/config.py`, `.env.example` | Mọi giá trị đọc bằng `os.getenv` lúc tạo `Settings`. `AGENT_API_KEY` mặc định rỗng nên không có secret trong code. |
| `/health` | `app/main.py` | Luôn trả 200, không đụng Redis. Redis chết không có nghĩa process hỏng; nếu `/health` fail, platform restart liên tục mà không sửa được gì. |
| `/ready` | `app/main.py`, `app/redis_client.py` | Ping Redis; lỗi → 503. Client có `socket_connect_timeout=2` để trả lời nhanh thay vì treo. App không ping Redis lúc import nên khởi động được khi chưa có Redis. |
| API key | `app/auth.py` | `APIKeyHeader(auto_error=False)` để tự trả 401 (không phải 422/403). So sánh bằng `secrets.compare_digest` trên **bytes** (`encode()`), để key chứa ký tự không phải ASCII vẫn ra 401 thay vì lỗi 500. Chưa đặt key thì từ chối tất cả (fail closed). |
| Rate limit | `app/rate_limiter.py` | Sliding window 60 giây bằng Redis sorted set. State trong Redis nên dùng chung giữa 2 worker và sống sót qua restart. Thêm request vào cửa sổ rồi đếm trong một MULTI để hai request đồng thời không cùng lọt qua; request bị từ chối thì được gỡ ra. Key được băm, không lưu API key thô. Có header `Retry-After`. |
| Cost guard | `app/cost_guard.py`, `app/main.py` | Xem phần riêng bên dưới. |
| Log JSON | `app/main.py` | `JsonFormatter` + logger riêng ghi ra stdout; middleware log mỗi request; không log secret. |
| Xử lý lỗi | `app/main.py` | Pydantic trả 422 cho input sai; handler riêng trả 503 khi Redis lỗi và 500 chung chung cho lỗi khác, không lộ stack trace. |
| Graceful shutdown | `app/main.py`, `Dockerfile` | Không tự đăng ký handler SIGTERM, để uvicorn xử lý. `CMD` dùng `exec` để uvicorn là PID 1 và nhận SIGTERM khi `docker stop`. |
| Dockerfile | `Dockerfile` | Multi-stage, base `slim`, venv ở builder, user non-root, `HEALTHCHECK` bằng Python (slim không có curl), port theo `${PORT:-8000}`. |
| Compose | `docker-compose.yml` | Service `agent` (build) + `redis:7-alpine` có healthcheck; `REDIS_URL=redis://redis:6379/0`; `depends_on` điều kiện `service_healthy`; `.env` là `required: false`; cổng map theo `${PORT:-8000}` ở cả hai vế. |
| `.dockerignore` | `.dockerignore` | Loại `.env*` (giữ `.env.example`), cache, venv, `.git`, Part 7. |
| Deploy config | `railway.toml` | `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`. `render.yaml` giữ nguyên chỉ có comment vì chỉ cần một trong hai. |

### Cost guard sau review: reserve / settle

Lỗi ban đầu là race condition: kiểu "kiểm tra budget rồi mới cộng chi phí" cho phép nhiều request đồng thời cùng thấy còn budget và cùng vượt. Thiết kế sau review:

1. **Budget theo ngày UTC**, lưu ở key `cost:YYYY-MM-DD` trong Redis, có TTL 2 ngày. Đây là budget toàn cục của dịch vụ, không theo từng user.
2. **Giữ chỗ trước khi gọi LLM (`reserve`)** bằng một **script Lua** chạy nguyên tử trong Redis: đọc số đã tiêu, nếu `đã tiêu + phí giữ chỗ > budget` thì trả 0 (API trả **402**), ngược lại `INCRBYFLOAT` luôn. Vì đọc–so sánh–cộng nằm trong một script nên hai request đồng thời không thể cùng vượt.
3. **Phí giữ chỗ** = chi phí token đầu vào (số từ × 2, tối thiểu 1) + chi phí **upper bound đầu ra của mock** (`MAX_OUTPUT_TOKENS` tính từ câu trả lời dài nhất trong `MOCK_RESPONSES`). Nhờ vậy phí giữ chỗ không bao giờ nhỏ hơn phí thật.
4. **Đối soát (`settle`)** sau khi LLM xong: tính phí thật rồi chỉ cộng phần chênh `thật − đã giữ` (thường âm, tức hoàn lại phần giữ dư).
5. **Trả lại (`release`)** toàn bộ phần đã giữ khi mock/LLM ném lỗi.
6. **Kỳ UTC được lưu cùng reservation:** key được chốt lúc giữ chỗ và nằm trong `Reservation`, nên đối soát/hoàn trả luôn vào đúng ngày dù request kéo qua nửa đêm UTC.

Giới hạn còn lại: nếu process bị kill giữa `reserve` và `settle`, phần giữ chỗ không được hoàn và tồn tại đến hết TTL.

Với budget kiểm thử rất nhỏ của checker (`0.000001`), phí giữ chỗ của ngay request đầu đã lớn hơn budget nên checker nhận **402 ở request thứ 1**.

### Kết quả checker (bản đầy đủ, WSL2 + Docker)

Chạy `python check_production_ready.py` trong `06-lab-complete/` (lưu ở `reports/production-readiness.txt`). Kết quả: **12/12 tiêu chí đạt, 41/41 checks passed**. Một số số liệu trong output: image `prod-check` nặng **63 MB**, 429 xuất hiện sau 5 request thành công (`RATE_LIMIT_PER_MINUTE=5`), 402 ở request thứ 1, **17 dòng log JSON** hợp lệ, `docker stop` thoát **exit code 0 trong 0.9 giây**.

Phần "📋 Checklist Deliverable" nguyên văn:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 41/41 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

### Giải thích các câu hỏi cốt lõi

1. **Vì sao `/health` 200 khi Redis chết còn `/ready` 503?** Redis chết không làm process hỏng. Nếu `/health` fail, platform restart container liên tục mà không giải quyết được gì. Việc đúng là `/ready` trả 503 để load balancer tạm ngừng gửi traffic vào instance đó, đến khi Redis trở lại.
2. **Vì sao rate limit không lưu trong dict của process?** Dockerfile chạy 2 worker (mỗi worker một bộ nhớ riêng), và checker restart agent rồi mong state còn. State phải ở Redis.
3. **Vì sao `CMD` cần `exec`?** Không có `exec`, shell là PID 1 và nhận SIGTERM thay uvicorn; hết thời gian chờ thì Docker gửi SIGKILL (exit code 137). Có `exec`, uvicorn là PID 1 nên tắt êm.
4. **Vì sao member của sorted set phải duy nhất (timestamp + uuid)?** Hai request cùng timestamp sẽ ghi đè nhau và bị đếm thành một.
5. **Vì sao thêm rồi mới đếm?** Đếm rồi mới thêm cho phép hai request đồng thời cùng thấy "còn chỗ"; thêm trước rồi đếm trong một MULTI thì chỉ request nằm trong giới hạn mới qua.

---

## Part 7 — Benchmark & Observability (CP7)

### Exercise 7.1 — Đọc metrics

Ví dụ cho mỗi loại metric trong `develop/app.py`:

- **Counter** (chỉ tăng, dùng với `rate()`): `http_requests_total`, `llm_tokens_total`, `llm_cost_usd_total`.
- **Gauge** (lên xuống): `agent_in_flight_requests` (số request đang xử lý), `agent_info`.
- **Histogram** (chia giá trị vào bucket, tính percentile bằng `histogram_quantile`): `http_request_duration_seconds` (các dòng `_bucket`, `_sum`, `_count`), `llm_request_duration_seconds`.

**Route label và cardinality.** Middleware `observe_requests` dùng `route.path` (template, ví dụ `/ask`) và gán `unmatched` cho URL không khớp route nào. Nếu dùng URL thật (`request.url.path`), một bot quét hàng nghìn URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`...) sẽ tạo ra mỗi URL một giá trị label mới, tức mỗi URL một bộ time series (histogram còn nhân thêm theo số bucket). Số series tăng không giới hạn làm tốn RAM của app và Prometheus (cardinality explosion). Dùng template giữ số giá trị label ở mức nhỏ và cố định.

**Metric bổ sung** `agent_question_length_chars` là Histogram với bucket `20, 50, 100, 200, 500, 1000, 2000`, được ghi bằng `QUESTION_LENGTH.observe(len(body.question))` trong endpoint `/ask`. Dùng Histogram thay vì label `length=...` vì độ dài có vô số giá trị, nếu làm label sẽ bùng nổ cardinality.

### Exercise 7.3 — Eval và quality gate

Baseline agent v2 (đọc từ `develop/reports/eval_v2.json`): **21/23 đúng (91.3%)**, không có lỗi. Hai câu sai:

| ID | Keyword bị thiếu | Cách sửa |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm tài liệu kích hoạt bởi `jwt` vào `KNOWLEDGE_BASE`, nói rõ JWT là token có chữ ký số, có thời điểm hết hạn, còn API key không tự hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm tài liệu kích hoạt bởi `hpa` / `kubernetes` / `autoscal`, nêu HPA scale theo CPU, memory hoặc custom metrics. |

Chỉ sửa `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` và bản đồng bộ trong `production/utils/mock_llm.py`; không sửa golden dataset. Từ khoá kích hoạt mới chỉ trùng với hai câu hỏi trên nên không đổi tài liệu truy xuất của các câu đang đúng. Kết quả sau khi sửa và chạy lại eval: **23/23, không regression**.

**Quality gate trong CI.** `run_eval.py` thoát với **exit code 1** khi accuracy thấp hơn `--min-accuracy` hoặc có regression so với baseline. Ngưỡng CI là **0.85** (đề yêu cầu job fail nếu accuracy dưới 85%):

```yaml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Run agent + eval
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
          python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85
```

Exit code 1 làm bước (và job) fail. Để thực sự **chặn merge**, job này phải được đặt làm **required status check** trong branch protection của nhánh `main` (Settings → Branches → "Require status checks to pass before merging"). Nếu không đặt required, PR vẫn có thể merge dù job đỏ. File workflow nêu trên là cách làm được mô tả trong bài; báo cáo này không khẳng định file đã nằm trong repo.

**Vì sao `cost / câu đúng` tốt hơn `cost / câu`:** v2 tốn nhiều token mỗi câu hơn v1 (prompt có thêm ngữ cảnh) nên đắt hơn theo từng câu, nhưng đúng nhiều hơn rất nhiều; chia chi phí cho số câu đúng mới phản ánh giá của một câu trả lời có ích.

### Phạm vi CP8 (xem BENCHMARK_REPORT.md)

Load test 4 mức concurrency, so sánh `MOCK_SLOW_RATE`, Locust scale 1 và 3 instance, thí nghiệm alert, trace và số liệu Grafana được trình bày trong [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md), kèm bốn ảnh trong `screenshots/`: [grafana-dashboard.png](screenshots/grafana-dashboard.png), [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png), [jaeger-error-trace.png](screenshots/jaeger-error-trace.png), [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png). Lệnh `promtool test rules` cho `alert_rules_test.yml` báo **SUCCESS** (ghi nhận từ lần chạy; không có file output riêng trong repo). Không lặp lại số đo ở đây để tránh lệch với báo cáo.

---

## AI log

Tôi là học viên và chủ dự án. Tôi dùng Codex làm việc trong workspace của mình để giao việc cho Claude Code, duyệt các bản sửa và chạy các phép kiểm tra. Claude Code viết phần triển khai và soạn bản nháp báo cáo. Các lần chạy ghi dưới đây được thực hiện qua Codex.

| Phần | Tôi yêu cầu gì và nhận được gì | Cách tôi dùng Codex để duyệt và kiểm tra |
|---|---|---|
| CP0–CP4 | Tôi yêu cầu giải thích các checkpoint và đối chiếu hướng dẫn K5 với code mẫu. Claude Code cũng rà lại yêu cầu và kiểm tra cấu hình repo. | Kiểm tra Python trong WSL2 và Docker, gọi API mẫu, đo kích thước hai image và chạy thử ba replica. Năm lượt gọi giữ đủ mười message trong cùng session. [Output HTTP local](reports/local-http.txt) |
| CP5 · Triển khai | Tôi giao Claude Code hoàn thiện agent FastAPI, Redis, Docker và cấu hình Railway. Claude trả bản sửa dưới dạng diff. | Duyệt và áp dụng diff, chạy checker nguyên bản. Khi Redis chưa sẵn sàng, tôi dùng Codex đọc lỗi và chạy lại với Redis thật. [Output checker](reports/production-readiness.txt) |
| CP5 · Sửa sau review | Tôi yêu cầu Claude xử lý trường hợp hai worker cùng kiểm tra ngân sách. Claude sửa để giữ trước chi phí bằng Lua trong Redis, đối soát sau khi mock trả lời và hoàn lại nếu mock lỗi. Claude cũng sửa cách so sánh API key và ánh xạ cổng theo `PORT`. | Kiểm tra thứ tự xử lý trong `/ask` rồi chạy lại checker với hai worker. Bản local đạt 12/12 tiêu chí, 41/41 phép kiểm. |
| CP7 | Tôi yêu cầu Claude thêm histogram độ dài câu hỏi và bổ sung kiến thức dựa trên hai câu sai trong eval v2. | Chạy load test ở bốn mức concurrency, đo ba mức `MOCK_SLOW_RATE`, rồi chạy lại eval trên cùng bộ 23 câu. V2 tăng từ 21/23 lên 23/23, không có regression. [Eval sau sửa](reports/eval_v2_fixed.json) |
| CP8 | Tôi gửi Claude lỗi `ModuleNotFoundError` của container. Claude xác định Python tìm sai thư mục thư viện của user và sửa `PYTHONUSERBASE` trong Dockerfile. | Build lại image, chạy Locust với một và ba replica, đối chiếu trace Jaeger với log cùng `trace_id` và đo thời gian đến khi hai alert cùng firing. Tôi thực hiện thí nghiệm A và B. [Báo cáo và bằng chứng CP8](BENCHMARK_REPORT.md) |
| CP6 | Tôi chọn workspace Railway Hobby đang dùng để deploy agent và Redis. Sau khi có URL public, tôi giao Claude cập nhật hồ sơ từ kết quả thực tế. | Deploy qua Codex và gọi bốn endpoint/trường hợp của đề, lần lượt nhận 200, 200, 401, 200. Checker chạy với URL public đạt 12/12 tiêu chí, 42/42 phép kiểm. [Kết quả HTTP](reports/public-http.json) · [Output checker với URL public](reports/production-readiness-cloud.txt) |
| Báo cáo | Tôi giao Claude soạn câu trả lời, báo cáo benchmark và hồ sơ deployment từ log, JSON, CSV và ảnh đã lưu. | Đối chiếu các bảng với file đo, kiểm tra hai bản sao CSV và mười bản sao JSON, rồi duyệt nội dung và ảnh trước khi lưu commit local. [Báo cáo benchmark](BENCHMARK_REPORT.md) · [Hồ sơ deployment](DEPLOYMENT.md) |
