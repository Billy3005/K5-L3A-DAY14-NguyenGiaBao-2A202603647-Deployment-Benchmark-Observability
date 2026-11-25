# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Gia Bảo
**Ngày chạy:** 25/11/2026
**Môi trường:** Ubuntu trên WSL2, Python 3.11.18; Docker Desktop (16 CPU, 3.68 GiB RAM), Docker Engine 29.5.3, Docker Compose v5.1.4. Mọi thành phần chạy trên cùng một máy, kể cả công cụ tạo tải.

## Quy ước đọc báo cáo

- Mọi con số lấy nguyên từ file bằng chứng trong repo. Link dưới đây là đường dẫn tương đối, mở được trực tiếp trên GitHub. Số tôi tự tính từ các file đó (tỉ lệ %, hiệu số, thời gian span) được ghi rõ là "tính từ".
- Load test và Locust dùng cấu hình mặc định của mock: `MOCK_ERROR_RATE=0.01` (1% lỗi) và `MOCK_SLOW_RATE=0.03`, trừ mục 2.2 đổi `MOCK_SLOW_RATE`. Eval chạy với `MOCK_ERROR_RATE=0` để tránh một câu fail ngẫu nhiên. Cả ba lần eval dùng cùng bộ 23 câu `golden_dataset.jsonl`, không chỉnh sửa.
- Phần nào chưa đo hoặc chưa chạy được nói rõ là "chưa đo" hoặc "không chạy". Giả thuyết được ghi là giả thuyết, không ghi như kết luận.

| Bằng chứng | Đường dẫn |
|---|---|
| Load test, 4 mức concurrency | [c1](reports/load_v2_c1.json), [c10](reports/load_v2_c10.json), [c50](reports/load_v2_c50.json), [c100](reports/load_v2_c100.json) |
| Load test, so sánh `MOCK_SLOW_RATE` | [0](reports/load_v2_slow_0.json), [0.03](reports/load_v2_slow_0.03.json), [0.1](reports/load_v2_slow_0.1.json) |
| Eval | [v1](reports/eval_v1.json), [v2](reports/eval_v2.json), [v2 sau khi sửa KB](reports/eval_v2_fixed.json) |
| Locust (thống kê) | [scale_1_stats.csv](benchmark-results/scale_1_stats.csv), [scale_3_stats.csv](benchmark-results/scale_3_stats.csv) |
| Locust (chi tiết lỗi) | [scale_1_failures.csv](06-lab-complete/benchmark-observability/production/benchmark-results/scale_1_failures.csv), [scale_3_failures.csv](06-lab-complete/benchmark-observability/production/benchmark-results/scale_3_failures.csv) |
| Alert | [alerts.json](reports/alerts.json) |
| Trace và log | [trace-evidence.json](reports/trace-evidence.json) |
| Truy vấn PromQL | [grafana-metrics.json](reports/grafana-metrics.json) |
| Ảnh | [grafana-dashboard.png](screenshots/grafana-dashboard.png), [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png), [jaeger-error-trace.png](screenshots/jaeger-error-trace.png), [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png) |

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Là ngưỡng mặc định của `load_test.py` (`slo.p95_ms = 500`). Ở concurrency 1 và 10, p95 đo được là 218.2 ms và 218.9 ms, nên ngưỡng còn dư khoảng 2.3 lần. |
| Error rate `/ask` | < 2% | Là ngưỡng mặc định của `load_test.py` (`slo.error_rate = 0.02`). Mock chủ động gây khoảng 1% lỗi, nên ngưỡng gấp đôi mức lỗi nền. |
| Accuracy trên golden dataset | ≥ 85% | Ngưỡng của job CI (xem mục 3.3). Các report eval ghi `min_accuracy` 0.8 (v1, v2) và 1.0 (v2 sau khi sửa), là ngưỡng cho từng lần chạy thủ công. |

Ngưỡng alert của Prometheus lỏng hơn SLO để tránh báo động giả: `AgentHighErrorRate` khi error rate > 5% kéo dài 1 phút, `AgentHighLatencyP95` khi p95 > 1 giây kéo dài 2 phút ([alert_rules.yml](06-lab-complete/benchmark-observability/production/prometheus/alert_rules.yml)).

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Mỗi lần chạy gửi 300 request tới agent v2 (cổng 8002). Mức lỗi 1% là lỗi 503 do mock chủ động tạo; theo mã `develop/app.py`, endpoint `/ask` chỉ trả 503 khi `LLMError` xảy ra.

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.41 | 188.1 | 218.2 | 1697.9 | 0.67% (2/300) | PASS |
| 10 | 38.25 | 190.1 | 218.9 | 1697.9 | 1.67% (5/300) | PASS |
| 50 | 86.07 | 264.4 | 575.2 | 1719.8 | 1.33% (4/300) | **FAIL**: p95 575.2 ms > 500 ms |
| 100 | 54.27 | 861.5 | 4029.8 | 4236.6 | 2.33% (7/300) | **FAIL**: p95 4029.8 ms > 500 ms và error rate 2.33% > 2% |

Số liệu phụ (cùng file JSON): thời gian chạy lần lượt 68.09 s, 7.84 s, 3.49 s, 5.53 s; latency trung bình 227.7, 234.6, 335.8, 1344.3 ms; latency lớn nhất 1715.5, 1711.7, 1853.6, 4303.5 ms.

**Nhận xét:**

- **RPS không tăng tuyến tính.** Từ concurrency 1 lên 10, RPS tăng 8.67 lần (4.41 → 38.25). Từ 10 lên 50, RPS chỉ tăng 2.25 lần (38.25 → 86.07). Từ 50 lên 100, RPS **giảm** 36.9% (86.07 → 54.27). Số RPS thấp ở concurrency 1 phù hợp với việc chỉ có một request được xử lý mỗi lúc: 1 / 0.2277 s ≈ 4.39 req/s, gần với 4.41 đo được.
- **Vị trí bắt đầu vi phạm SLO.** Ở concurrency 10, p95 vẫn 218.9 ms. Ở concurrency 50, p50 tăng từ 190.1 lên 264.4 ms và p95 vượt 500 ms. Ở concurrency 100, trung bình 1344.3 ms. Theo dữ liệu này, mức tải tối đa còn đạt SLO nằm trong khoảng từ 10 đến dưới 50 concurrent request, và chưa chạy mức trung gian để xác định chính xác hơn.
- **Nguyên nhân chưa đo.** Dữ liệu cho thấy latency tăng khi concurrency tăng, nhưng không cho biết điểm nghẽn nằm ở agent, ở máy tạo tải chạy chung máy, hay ở hệ điều hành. Không có số CPU hoặc bộ nhớ nào được ghi trong các lần chạy này.
- **Độ tin cậy.** Mỗi lần chạy chỉ có 300 request và kéo dài 3.5–7.8 s (trừ concurrency 1), nên p99 chính là vài request chậm nhất (3 request trong 300). Mỗi mức chỉ chạy một lần, không có lặp lại.
- **Error rate ở concurrency 100.** 7 lỗi trên 300 request cao hơn mức 1% kỳ vọng (khoảng 3 request), nhưng vì mọi lỗi 503 đều do mock chủ động tạo, một lần chạy này không đủ để kết luận tải làm tăng lỗi. Cần chạy lặp để biết.

### 2.2 Tail latency (concurrency 20, 300 request)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|
| 0 | 213.2 | 274.8 | 308.0 | 1.00% (3/300) | PASS |
| 0.03 (mặc định) | 219.8 | 218.9 | 1694.4 | 1.33% (4/300) | PASS |
| 0.1 | 348.4 | 1685.5 | 1711.1 | 1.00% (3/300) | **FAIL**: p95 1685.5 ms > 500 ms |

**Nhận xét:**

- **Chỉ số nhạy nhất.** Khi `MOCK_SLOW_RATE` tăng từ 0 lên 0.03, trung bình chỉ tăng 6.6 ms (+3.1%) trong khi p99 tăng từ 308.0 lên 1694.4 ms (khoảng 5.5 lần). Khi lên 0.1, trung bình tăng 63.4% so với mức 0 (213.2 → 348.4 ms) và p95 tăng từ 274.8 lên 1685.5 ms.
- **Giải thích.** Khoảng 3% request chậm nằm ngoài top 5% nên chưa chạm p95, nhưng đã chạm p99. Ở 10% request chậm, p95 cũng bị kéo lên. Mock cộng thêm 1500 ms cho request chậm (`MOCK_SLOW_MS`), khớp với p99 xấp xỉ 1700 ms.
- **p95 ở mức 0.03 thấp hơn mức 0** (218.9 so với 274.8 ms). Đây là dao động giữa hai lần chạy 300 request, không phải do request chậm giảm tải; không rút kết luận từ chênh lệch này.
- **Vì sao SLO không nên đặt theo trung bình.** Ở mức 0.03, trung bình 219.8 ms trông không khác mức 0 (213.2 ms), trong khi một phần nhỏ người dùng phải chờ gần 1.7 giây. Trung bình che mất nhóm này. p95/p99 phản ánh trải nghiệm của nhóm chậm nhất.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Cùng 23 câu hỏi, `MOCK_ERROR_RATE=0`, không có lỗi (`errors: 0` ở cả ba report).

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | **100% (23/23)** |
| Avg tokens / câu | 57.7 | 108.7 | 113.7 |
| Tổng cost (USD) | 0.000412 | 0.000756 | 0.00079 |
| Cost / câu đúng (USD) | 0.00041235 | 3.599e-05 | 3.436e-05 |
| Quality gate | **FAIL** (ngưỡng 0.8) | PASS (ngưỡng 0.8, không regression) | PASS (ngưỡng 1.0, không regression) |

Nguồn: [eval_v1.json](reports/eval_v1.json), [eval_v2.json](reports/eval_v2.json), [eval_v2_fixed.json](reports/eval_v2_fixed.json). Trường `regressions` là rỗng ở cả v2 và v2 sau khi sửa. v1 chỉ trả lời đúng câu `basic-01`.

### 3.1 Những câu v2 trả lời sai ban đầu và cách sửa

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm vào `KNOWLEDGE_BASE` một tài liệu kích hoạt bằng từ khoá `jwt`, nói rằng API key là chuỗi cố định không tự hết hạn, còn JWT là token có chữ ký số và thời điểm hết hạn. |
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm tài liệu kích hoạt bằng `hpa`, `kubernetes`, `autoscal`, nêu HPA scale theo CPU, memory hoặc custom metrics. |

Chỉ sửa `KNOWLEDGE_BASE` trong `utils/mock_llm.py` của `develop` và đồng bộ sang `production`; không sửa golden dataset. Các từ khoá mới chỉ xuất hiện trong hai câu hỏi trên của dataset, nên các câu đã đúng giữ nguyên tài liệu truy xuất. Kết quả: 23/23, `regressions` rỗng.

### 3.2 Trade-off chất lượng / chi phí / latency giữa v1 và v2

- **Chất lượng.** v2 (có retrieval) đúng 21/23 so với 1/23 của v1; sau khi sửa KB, v2 đúng 23/23.
- **Chi phí.** v2 tốn nhiều token hơn: 108.7 so với 57.7 token trung bình mỗi câu (khoảng 1.88 lần) vì prompt có thêm tài liệu truy xuất. Tổng cost của v2 trước khi sửa là 0.000756 USD so với 0.000412 USD của v1 (khoảng 1.83 lần, tính từ hai số này).
- **Cost / câu đúng** là chỉ số so sánh có ích hơn: 3.599e-05 USD của v2 so với 0.00041235 USD của v1, tức rẻ hơn khoảng 11.5 lần; sau khi sửa KB là 3.436e-05 USD, rẻ hơn khoảng 12.0 lần (cả hai tỉ lệ tính từ các số trong báo cáo).
- **Latency.** Báo cáo eval có ghi p50/p95 (v1 p95 1496.7 ms, v2 p95 216.4 ms, v2 sau khi sửa p95 219.0 ms), nhưng với 23 mẫu chỉ cần một request chậm là p95 nhảy mạnh, nên **không dùng số này để so latency hai phiên bản**. Latency phải đo bằng load test (mục 2).

### 3.3 Quality gate trong CI với ngưỡng 85%

`run_eval.py` thoát với exit code 1 khi accuracy dưới `--min-accuracy` hoặc có regression so với `--baseline`. Job CI chạy agent v2 với `MOCK_ERROR_RATE=0`, rồi gọi:

```bash
python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85
```

- **Ý nghĩa của 85% trên 23 câu.** 85% của 23 là 19.55, nên cần đúng ít nhất 20 câu (20/23 = 86.96%) và cho phép tối đa 3 câu sai. 19/23 (82.6%) sẽ fail. Mỗi câu chiếm khoảng 4.35 điểm phần trăm, nên ngưỡng này thô; đây là hạn chế của bộ dữ liệu nhỏ. Kết quả thực tế đều phân biệt rõ: v2 ban đầu 91.3% qua, v1 4.35% rớt.
- **Để chặn merge cần hai điều kiện.** (1) Bước eval fail vì exit code 1. (2) Job đó phải được đặt làm **required status check** trong branch protection của nhánh `main` ("Require status checks to pass before merging"). Nếu không đặt required, PR vẫn merge được dù job đỏ.
- Báo cáo này mô tả cách làm; không khẳng định file workflow đã nằm trong repo.

---

## 4. Observability stack (production)

Stack chạy bằng `docker compose -p k5-day14-observability` với 3 instance agent phía sau Nginx.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với alert đang **firing**: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Ảnh Grafana** hiển thị các Golden Signals: **43.8 req/s**, error rate **1.06%**, latency p95 **471.65 ms**, **28** request in-flight, **3** instance up. (Ảnh còn thể hiện LLM cost 1 giờ $0.3459.) Ảnh được chụp lúc không có fault, trước khi bật thí nghiệm ở mục 4.2.

**Ảnh Prometheus Alerts** cho thấy `AgentHighErrorRate` và `AgentHighLatencyP95` cùng **FIRING**, `AgentInstanceDown` **INACTIVE**. Ảnh còn có `LLMCostBurnRateHigh` ở trạng thái **FIRING** (nhóm `agent-cost`). Alert này không thuộc thí nghiệm nào được lên kế hoạch (thí nghiệm C không chạy) và thời điểm firing của nó không được ghi lại, nên không có số đo thời gian cho nó. Panel "Cost burn rate (USD/giờ)" trong ảnh Grafana cho thấy đường chi phí vượt đường ngưỡng $2/giờ trong lúc chạy tải, phù hợp với việc alert này firing, nhưng báo cáo không xác định chính xác nguyên nhân.

**Ghi nhận khác** (không có file output đi kèm trong repo nên báo cáo này không kiểm tra lại được): `GET /metrics` qua Nginx trả 404 (cấu hình `location = /metrics { return 404; }` trong `nginx.conf`), và lệnh `promtool test rules` cho `alert_rules_test.yml` báo SUCCESS.

### 4.2 Thí nghiệm "phá hệ thống"

Hai thí nghiệm **A và B được thực hiện cùng một lúc**: `MOCK_ERROR_RATE=0.2` và `MOCK_SLOW_RATE=0.3` đặt đồng thời. Thời điểm bắt đầu thay đổi là `2026-11-25T08:43:44.527Z`. Thời gian tới lúc firing là thời điểm script lần đầu quan sát thấy alert ở trạng thái firing trên Prometheus ([alerts.json](reports/alerts.json)).

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (đặt cùng B) | `AgentHighErrorRate` | **95.9 giây** (first observed 08:45:20.40) | Chưa có ảnh Grafana lúc fault; theo thiết kế dashboard là panel "Error rate". Chưa quan sát/chụp. |
| B | `MOCK_SLOW_RATE=0.3` (đặt cùng A) | `AgentHighLatencyP95` | **147.4 giây** (first observed 08:46:11.91) | Chưa có ảnh Grafana lúc fault; theo thiết kế dashboard là panel "Latency p95". Chưa quan sát/chụp. |
| C | `LLM_MODEL=mock-llm-large` | Không chạy | Không chạy | Không chạy |
| D | `docker pause` 1 instance | Không chạy | Không chạy | Không chạy |
| E | `AGENT_VERSION=v1` | Không chạy | Không chạy | Không chạy |

**Diễn giải thời gian (tính từ `alerts.json`):**

- Cả hai alert vào trạng thái pending khoảng 28–33 giây sau khi đổi cấu hình (`active_since` 08:44:12.40 cho latency và 08:44:17.40 cho error rate). Sau đó chờ đủ thời gian `for` trong rule: 1 phút cho error rate (63.0 giây từ pending đến lúc quan sát thấy firing) và 2 phút cho latency (119.5 giây). Con số 119.5 giây nhỏ hơn 120 giây một chút vì giờ ghi trong Prometheus và giờ ghi bởi script có thể lệch dưới 1 giây; không ảnh hưởng kết luận.
- Error rate firing trước latency, khớp với `for: 1m` so với `for: 2m`. Thời gian tới firing do độ dài cửa sổ `rate()` (1 phút) cộng với `for` của rule, không phải do hệ thống phản ứng chậm.
- Vì A và B đổi cùng lúc, hai alert này không tách riêng được tác động của từng thay đổi. Mỗi alert dựa trên metric riêng (error rate cho A, p95 cho B).
- Mức tải Locust trong lúc thí nghiệm không được ghi trong `alerts.json`; không khẳng định thêm về nó.

**Thí nghiệm E (không chạy): lỗi chất lượng được phát hiện bằng cách nào?** Khi `AGENT_VERSION=v1`, error rate và latency không đổi nên alert hạ tầng không firing. Cách phát hiện là chạy **eval trên golden dataset** làm quality gate: dữ liệu eval của chính bài này cho thấy v1 chỉ đạt 4.35% (1/23) và bị gate báo FAIL, trong khi v2 đạt 91.3%. Ngoài CI, nên chạy eval định kỳ trên mẫu traffic thật, thu phản hồi người dùng, dùng LLM làm giám khảo, và theo dõi metric "retrieval hit ratio". Thí nghiệm E thực tế không chạy trên stack nên đây là phân tích từ dữ liệu eval có sẵn.

### 4.3 Debug bằng trace

Thời lượng mỗi span **tính từ** `endTimeUnixNano − startTimeUnixNano` trong [trace-evidence.json](reports/trace-evidence.json). Cả hai trace xảy ra sau thời điểm đổi cấu hình ở mục 4.2 (08:44:03 và 08:44:16 UTC; Jaeger hiển thị 15:44:03 và 15:44:16 theo múi giờ trình duyệt). Báo cáo không xác định rằng hai request này chậm hoặc lỗi *vì* fault A+B, vì mock vẫn có 3% request chậm và 1% lỗi mặc định.

**Trace chậm** (ảnh: [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png))

- `trace_id`: `eab192f190ac17038f0e1ed850c6b157`
- Tổng thời gian (`POST /ask`): **1715.80 ms**
- Span chiếm nhiều thời gian nhất (không kể span cha): `chat mock-llm-small` = **1693.82 ms**, tức **98.72%** thời gian của `POST /ask`.

| Span | Thời lượng (ms) |
|---|---|
| `POST /ask` | 1715.80 |
| `agent.run` | 1713.52 |
| `agent.retrieve_context` | 19.31 |
| `chat mock-llm-small` | 1693.82 |

Phần `agent.run` ngoài hai span con chỉ còn khoảng 0.40 ms, và ngoài `agent.run` còn khoảng 2.28 ms thuộc `POST /ask`. Nghĩa là phần lớn thời gian nằm ở lời gọi LLM, không phải ở mã của agent.

Dòng log tương ứng (khớp `trace_id`, `span_id` trùng span gốc `POST /ask`):

```json
{"ts": "2026-11-25T08:44:04.965812+00:00", "level": "INFO", "service": "observable-agent", "instance": "164e95c044d3", "event": "llm_call", "trace_id": "eab192f190ac17038f0e1ed850c6b157", "span_id": "e52a10bb546c8957", "request_id": "6e07a1e4a12b", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1694.4}
```

Log ghi `llm_ms` 1694.4 ms, lệch 0.58 ms so với span (1693.82 ms) do hai chỗ đo khác nhau.

**Trace lỗi** (ảnh: [jaeger-error-trace.png](screenshots/jaeger-error-trace.png))

- `trace_id`: `1f4949c43df9084a557bc8209bfa9ae8`
- Tổng thời gian (`POST /ask`): **868.53 ms**, trạng thái HTTP 503, span `chat mock-llm-small` có `status.code = 2` (lỗi) và event `exception`.
- Span lâu nhất (không kể span cha): `chat mock-llm-small` = **845.48 ms**, tức **97.35%** của `POST /ask`.

| Span | Thời lượng (ms) |
|---|---|
| `POST /ask` | 868.53 |
| `agent.run` | 866.23 |
| `agent.retrieve_context` | 20.45 |
| `chat mock-llm-small` | 845.48 |

Event `exception` ghi `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`.

Dòng log tương ứng:

```json
{"ts": "2026-11-25T08:44:16.936634+00:00", "level": "INFO", "service": "observable-agent", "instance": "74d3bee9cba1", "event": "llm_error", "trace_id": "1f4949c43df9084a557bc8209bfa9ae8", "span_id": "b5325e1637734cf6", "request_id": "a9c517fab6e3", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

Một lưu ý về trace lỗi: lời gọi LLM thất bại mà vẫn mất 845.48 ms. Theo mã `mock_llm.py`, lỗi được ném sau một nửa latency đã tính (`latency_ms / 2000` giây) và latency này có thể đã cộng thêm 1500 ms của nhánh "slow". Con số 845 ms phù hợp với trường hợp request vừa chậm vừa lỗi, nhưng đây là suy luận từ mã, chưa kiểm tra riêng.

### 4.4 Đọc số liệu dashboard và PromQL

Các truy vấn trong [grafana-metrics.json](reports/grafana-metrics.json) được lấy tại `unix_time` 1795596133.892, tương ứng khoảng 08:42:13.89 UTC (15:42:13 theo múi giờ hiển thị của Jaeger). **Thời điểm này khác thời điểm chụp ảnh dashboard** (trục thời gian trong ảnh kết thúc quanh 15:42, giờ chính xác lúc chụp không được ghi), nên số PromQL và số trong ảnh không trùng nhau là điều dự kiến; đây là hai lần đọc ở hai thời điểm khác nhau, không phải sai số. Cả hai nằm trong thời gian chạy scale_3 (lỗi 503 trong `scale_3_failures.csv` trải từ 08:41:20 đến 08:43:23).

| Chỉ số | Ảnh Grafana | Truy vấn PromQL (08:42:13.89 UTC) |
|---|---|---|
| Traffic `/ask` | 43.8 req/s | 47.01 req/s (tổng 3 instance, tính từ ba giá trị bên dưới) |
| p95 | 471.65 ms | 651.71 ms (`0.6517114750627048` giây) |
| Trung bình | không hiển thị | 279.71 ms (`0.27970865249079746` giây) |

**Trả lời câu hỏi Exercise 7.4:**

1. **p95 và avg, khoảng cách nói lên điều gì?** Ở thời điểm PromQL, p95 là 651.71 ms so với trung bình 279.71 ms, tức p95 gấp khoảng 2.33 lần trung bình. Khoảng cách này là dấu hiệu của tail latency: một phần request chậm hơn hẳn phần còn lại. Số trên ảnh (p95 471.65 ms) khác vì chụp ở thời điểm khác.
2. **Nginx có chia đều traffic cho các instance không?** Có, ở mức xấp xỉ. Req/s theo instance:

   | Instance | req/s | Tỉ trọng |
   |---|---|---|
   | `172.20.0.7:8000` | 16.43 | 34.95% |
   | `172.20.0.8:8000` | 15.32 | 32.59% |
   | `172.20.0.9:8000` | 15.26 | 32.46% |

   Instance cao nhất chỉ hơn thấp nhất khoảng 7.7%.
3. **Vì sao input tokens/s lớn hơn output tokens/s?** Đo được 3603.37 token/s đầu vào so với 1881.44 token/s đầu ra, tức đầu vào gấp khoảng 1.92 lần. Theo mã `mock_llm.py`, prompt gồm system prompt, tài liệu được truy xuất (agent v2) và câu hỏi, còn đầu ra chỉ là câu trả lời, nên đầu vào dài hơn. Token được ước lượng bằng `len(text) // 4`.
4. **`curl http://localhost:8080/metrics` trả gì và vì sao?** Trả 404, vì `nginx.conf` có `location = /metrics { return 404; }`: metric chỉ để Prometheus scrape trực tiếp trong mạng nội bộ, không công khai ra ngoài.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu lấy từ dòng **Aggregated** của [scale_1_stats.csv](benchmark-results/scale_1_stats.csv) và [scale_3_stats.csv](benchmark-results/scale_3_stats.csv). Aggregated gồm cả `POST /ask` và `GET /health` (Locust gọi `/health` thỉnh thoảng).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 60.59 | 190 | 480 | 1700 | 74 / 7673 (0.96%) |
| 3 | 44.14 | 210 | 3000 | 10000 | 574 / 5629 (10.20%) |

Riêng `POST /ask`: scale 1 có 6978 request, 74 lỗi (1.06%), p50 200 ms, p95 530 ms, p99 1700 ms, 55.11 req/s; scale 3 có 5111 request, 542 lỗi (10.60%), p50 210 ms, p95 3200 ms, p99 10000 ms, 40.08 req/s. Riêng `GET /health` ở scale 3: 32 lỗi trên 518 request.

**Chi tiết lỗi từ file `*_failures.csv`:**

| Lần chạy | Loại lỗi | Số lần | Khoảng thời gian (UTC) |
|---|---|---|---|
| scale 1 | `POST /ask` 503 | 74 | 08:38:55 → 08:40:51 |
| scale 3 | `POST /ask` 503 | 45 | 08:41:20 → 08:43:23 |
| scale 3 | `POST /ask` 502 Bad Gateway | 424 | 08:42:31 → 08:42:43 |
| scale 3 | `POST /ask` 504 Gateway Time-out | 73 | 08:42:30 → 08:42:41 |
| scale 3 | `GET /health` 502 Bad Gateway | 32 | 08:42:34 → 08:42:43 |

Tổng 574 lỗi ở scale 3 khớp với số `Failure Count` của dòng Aggregated (45 + 424 + 73 + 32 = 574).

**Giải thích kết quả (thận trọng):**

- **Lỗi 503 là lỗi mock mặc định, không phải do scale.** Cả hai lần chạy đều có lỗi 503 rải suốt thời gian chạy với tỉ lệ gần 1% (74/6978 ở scale 1 và 45/5111 ở scale 3), khớp với `MOCK_ERROR_RATE=0.01`.
- **Lỗi 502 và 504 là lỗi riêng của scale 3, tập trung trong khoảng 13 giây.** Toàn bộ 502/504 xuất hiện từ 08:42:30 đến 08:42:43. `nginx.conf` đặt `proxy_connect_timeout 2s` và `proxy_read_timeout 10s` ("agent treo quá 10s → 504"). Vì Nginx sinh các mã này khi không kết nối được hoặc chờ quá lâu một instance phía sau, và vì p99 của scale 3 là đúng 10000 ms, các lỗi 504 phù hợp với việc request chờ tới giới hạn đọc 10 giây. Latency lớn nhất 13.27 s (`/ask`) và 19.49 s (`/health`) vượt 10 s; `proxy_next_upstream error timeout` cho phép Nginx thử instance khác sau lỗi hoặc timeout, nên tổng thời gian có thể dài hơn 10 s (đây là suy luận từ cấu hình, chưa kiểm chứng).
- **Nguyên nhân gốc của đợt 502/504 chưa xác định được.** Dữ liệu chỉ cho biết lỗi xảy ra ở lớp Nginx trong một khoảng ngắn. Các giả thuyết cần kiểm chứng bằng `docker compose logs`, `docker stats` và `docker inspect` (số lần restart): một hoặc nhiều container agent không trả lời trong khoảng đó; giới hạn tài nguyên khai báo trong compose là 0.5 CPU và 256 MB mỗi replica; Docker Desktop chỉ có 3.68 GiB RAM cho cả stack. **Không có số đo CPU hay bộ nhớ nào của các container trong các lần chạy này, nên không khẳng định tài nguyên là nguyên nhân.**
- **Metric của agent không thấy các lỗi này.** 502/504 sinh ra ở Nginx, request chưa bao giờ được agent xử lý xong, nên không nằm trong `http_requests_total` của agent. Đây là lý do cần giám sát thêm ở tầng load balancer.
- **Không nên so trực tiếp với thí nghiệm fault.** Hai lần chạy scale dùng cấu hình lỗi mặc định (1% lỗi, 3% chậm), còn thí nghiệm ở mục 4.2 dùng 20% lỗi và 30% chậm, nên các số p95 và error rate của hai nhóm này không so sánh được.
- **Kết luận về scale.** Trong lần chạy này, 3 instance **không** cho kết quả tốt hơn 1 instance: RPS thấp hơn (44.14 so với 60.59), số request hoàn thành ít hơn khoảng 26.6% (5629 so với 7673), p95 và p99 cao hơn nhiều. Chỉ một lần chạy cho mỗi cấu hình nên chưa kết luận chắc chắn về 3 instance nói chung. Một điểm cần lưu ý khi đọc kết quả scale 1: p95 480 ms (gần ngưỡng 500) ở 100 user cho thấy một instance chưa bão hoà rõ rệt, và mỗi user Locust nghỉ 0.5–2 giây giữa các lần gọi, nên thông lượng chủ yếu bị giới hạn bởi số user và thời gian nghỉ (ước tính thô: 100 user / (khoảng 1.25 s nghỉ + 0.24 s phản hồi) ≈ 67 req/s, so với 60.59 đo được). Với kiểu tải này, thêm instance khó làm tăng RPS nhiều.
- **Về LLM latency.** Panel "LLM latency p95" trong ảnh Grafana nằm quanh 197–198 ms (đọc từ trục trong ảnh), thấp hơn nhiều so với p95 HTTP 471.65 ms trên cùng ảnh. Điều đó gợi ý thời gian chờ nằm ngoài lời gọi LLM, nhưng hai panel dùng cửa sổ tính khác nhau và chưa kiểm chứng thêm.

---

## 6. Kết luận

**3 điều học được về benchmark & observability:**

1. **Latency phải đo bằng percentile, không bằng trung bình.** Với 3% request chậm, trung bình chỉ tăng 3.1% (213.2 → 219.8 ms) trong khi p99 tăng từ 308.0 lên 1694.4 ms.
2. **Chạy một lần chưa đủ tin cậy.** Mỗi mức load test chỉ có 300 request và p99 chỉ là 3 request chậm nhất; chênh lệch p95 giữa mức 0 và 0.03 (274.8 so với 218.9 ms) cho thấy dao động giữa các lần chạy. Cần lặp và đo nhiều mẫu hơn trước khi kết luận.
3. **Metric của một service chỉ phản ánh điều nó nhìn thấy.** 502/504 sinh ra ở Nginx và 20 phút chạy fault cho thấy alert hạ tầng không phát hiện được suy giảm chất lượng (thí nghiệm E không firing theo thiết kế). Cần thêm giám sát ở tầng load balancer và đánh giá chất lượng bằng eval.

**Nếu đưa agent này lên production thật, tôi sẽ thêm các metric / alert sau** (chưa có trong stack hiện tại):

- **Metric ở tầng Nginx** (ví dụ nginx exporter hoặc log có `upstream_response_time`): đếm 502/504 và thời gian đáp ứng upstream. Alert khi tỉ lệ 5xx tại Nginx vượt ngưỡng, vì agent không đếm được các lỗi này.
- **Tài nguyên container**: CPU, bộ nhớ, số lần restart của từng replica (cAdvisor hoặc công cụ tương đương). Hiện chưa có số liệu để khẳng định hay loại trừ giả thuyết về tài nguyên ở mục 5.
- **Chất lượng đo online**: tỉ lệ đạt của eval chạy định kỳ trên mẫu traffic thật (hoặc LLM-as-judge), cộng với panel "retrieval hit ratio" có alert, để thí nghiệm kiểu E không còn "im lặng".
- **Alert p99 và burn rate theo nhiều cửa sổ**: alert hiện chỉ dựa trên p95 và error rate; p99 mới là chỉ số bị ảnh hưởng đầu tiên (mục 2.2).
- **Chi phí trên mỗi request / mỗi câu đúng**, cùng alert burn rate hiện có (`LLMCostBurnRateHigh`), vì alert này đã firing trong lúc chạy tải mà không có phân tích đi kèm.
- **Kiểm tra bên ngoài (synthetic probe)** gọi `/ask` từ ngoài mạng nội bộ, để phát hiện lỗi mà metric nội bộ của agent không thấy.
