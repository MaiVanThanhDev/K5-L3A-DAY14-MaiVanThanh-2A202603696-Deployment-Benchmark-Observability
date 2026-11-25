# Benchmark & Observability Report — Day 14

**Họ tên:** Mai Văn Thành (2A202603696, K5-L3A)
**Ngày chạy:** 2026-11-25 (giờ ghi trong báo cáo là UTC)
**Môi trường:** Windows 10 Pro, Intel Core i5-13400F (16 threads), RAM 16 GB. Docker Desktop 29.9.2 trên WSL2 (16 CPU, 7,7 GB RAM cấp cho Docker). Bước 1 chạy Python 3.14 trong Ubuntu WSL2. Agent, load test và Locust cùng chạy trên một máy.

**File bằng chứng:**
- `reports/`: `load_v2_c{1,10,50,100}.json`, `load_v2_slow_{0,0.03,0.1}.json`, `eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`, `chaos_results.json` (thời gian alert của thí nghiệm 4.2), `prometheus_snapshot_0840.json` (số liệu Exercise 7.4)
- `benchmark-results/`: `scale_1_stats.csv`, `scale_3_stats.csv` (+ history/failures)
- `screenshots/`: `grafana-dashboard.png`, `jaeger-slow-trace.png`, `jaeger-error-trace.png`, `prometheus-alert-firing.png`

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < **500 ms** | LLM mock mất khoảng 150–230 ms/request (p50 ≈ 190 ms). 500 ms cho dư khoảng 2 lần cho hàng đợi và mạng mà người dùng vẫn cảm thấy "tức thì". Đặt theo p95 vì average che mất tail latency (mục 2.2). Alert dùng ngưỡng lỏng hơn (p95 > 1 s trong 2 phút) để tránh báo động vì spike ngắn |
| Error rate `/ask` | < **2 %** | Upstream LLM mock có khoảng 1% lỗi nền (`MOCK_ERROR_RATE=0.01`), nên SLO 2% chừa error budget cho lỗi nền mà vẫn bắt được sự cố thật. Alert: > 5% trong 1 phút |
| Accuracy trên golden dataset | ≥ **95 %** và **0 regression** | Golden set có 23 câu, 95% nghĩa là sai tối đa 1 câu. Trong CI dùng gate chặt hơn: `--min-accuracy 1.0 --baseline <bản đang chạy>`, vì đây là bộ câu đã biết đáp án nên không có lý do để sai |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (agent v2, 1 process uvicorn, mặc định `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`).

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.85 | 195.3 | 229.3 | 1704.0 | 2.00 % (6 × 503) | ✅ PASS |
| 10 | 41.87 | 187.0 | 221.8 | 1692.7 | 2.33 % (7 × 503) | ❌ FAIL (error rate) |
| 50 | 106.64 | 196.9 | 298.3 | 1694.1 | 2.00 % (6 × 503) | ✅ PASS |
| 100 | 56.87 | 519.8 | 3141.9 | 3399.7 | 0.67 % (2 × 503) | ❌ FAIL (p95) |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency.

- **c = 1 → 10:** RPS tăng gần tuyến tính (3,85 → 41,87, khoảng 10,9 lần) và p50 gần như không đổi (≈ 190 ms). Lý do: gần như toàn bộ thời gian của một request là **chờ I/O** (mock LLM `await asyncio.sleep`), nên event loop phục vụ nhiều request song song mà không tốn thêm CPU. Throughput ≈ concurrency / latency (định luật Little: 10 / 0,239 s ≈ 42 req/s, khớp với đo đạc).
- **c = 50:** RPS chỉ tăng thêm khoảng 2,5 lần (106,6) thay vì 5 lần. p90 và p95 bắt đầu tăng (272,6 / 298,3 ms): bắt đầu **bão hoà**.
- **c = 100:** RPS **giảm** còn 56,87 và p50 nhảy lên 519,8 ms, p95 lên 3141,9 ms, vi phạm SLO. Agent chỉ có **một process uvicorn**, tức một event loop chạy trên một core. Phần việc dùng CPU của mỗi request (parse JSON, Pydantic, ghi log JSON, cập nhật Prometheus metrics) cộng dồn lại, nên request phải **xếp hàng chờ CPU** chứ không còn chỉ chờ I/O. Thêm vào đó, load generator (`httpx`, 100 kết nối) chạy cùng máy cũng tranh CPU. Chỉ có 300 request ở c = 100 (3 "đợt") nên giai đoạn khởi động chiếm phần lớn thời gian đo. Muốn tăng tiếp thì phải scale ra nhiều process hoặc instance, không thể chỉ tăng concurrency.
- **Error rate 2–2,33 %** là nhiễu thống kê của lỗi nền 1% với mẫu chỉ 300 request (7 lỗi so với kỳ vọng 3). Lần c = 10 vượt SLO 2% chỉ vì 1 request lỗi thêm. Muốn kết luận error rate cần mẫu lớn hơn nhiều, hoặc đo theo cửa sổ thời gian dài.
- **p99 ≈ 1,7 s ở mọi mức tải** đến từ khoảng 3% request "slow" của mock (+1500 ms), không phụ thuộc tải (xem 2.2).

### 2.2 Tail latency

Lệnh: khởi động lại v2 với `MOCK_SLOW_RATE=<x>`, rồi `--requests 300 --concurrency 20 --out reports/load_v2_slow_<x>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 191.0 | 218.9 | 236.9 |
| 0.03 (mặc định) | 252.3 | 242.8 | 1694.8 |
| 0.1 | 302.9 | 1674.8 | 1709.4 |

**Nhận xét:**
- **p99 nhạy nhất:** chỉ 3% request chậm đã đẩy p99 từ 236,9 lên 1694,8 ms (**gấp khoảng 7 lần**), trong khi avg chỉ tăng 32% (191,0 → 252,3 ms) và p95 gần như không đổi (+24 ms). Khi tỉ lệ chậm lên 10% (vượt 5%), **p95 cũng nhảy vọt** (218,9 → 1674,8 ms, gấp 7,6 lần), còn avg vẫn chỉ tăng 59%.
- Percentile "bật" theo **ngưỡng**: p95 giữ nguyên chừng nào dưới 5% request chậm, rồi nhảy hẳn sang mức latency của nhóm chậm. Average thì tăng từ từ theo tỉ lệ, nên trông "ổn".
- **Vì sao SLO không nên đặt theo average:** avg 252 ms trông tốt, nhưng cứ 100 người thì 3 người phải chờ khoảng 1,7 giây. Average trộn số đông nhanh với số ít rất chậm, nên che mất trải nghiệm tệ nhất, trong khi chính nhóm đó mới rời bỏ sản phẩm. SLO theo p95/p99 cam kết trực tiếp "95% (99%) người dùng nhanh hơn X". Throughput cũng giảm (102 → 70 → 53 req/s) vì các slot concurrency bị request chậm chiếm giữ lâu.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Lệnh:
```bash
python eval/run_eval.py --url http://localhost:8001 --out reports/eval_v1.json
python eval/run_eval.py --url http://localhost:8002 --out reports/eval_v2.json --baseline reports/eval_v1.json
# sửa KNOWLEDGE_BASE, tắt/bật lại v2
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
```

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | **100.0 % (23/23)** |
| Avg tokens / câu | 57.5 | 109.1 | 118.8 |
| Tổng cost (USD) | 0.00041 | 0.000762 | 0.000835 |
| Cost / câu đúng (USD) | 0.00040995 | 0.00003627 | 0.00003629 |
| Latency p50 / p95 (ms) | 151.2 / 187.4 | 175.1 / 214.5 | 191.2 / 210.6 |
| Quality gate | ❌ FAIL (min 0.8) | ✅ PASS (min 0.8, 0 regression so với v1) | ✅ PASS (min **1.0**, 0 regression so với v2) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Retrieval không tìm được tài liệu nào (KB không có keyword `jwt`), nên v2 trả lời chung chung "Câu hỏi hay! Điều này phụ thuộc…". Thêm entry KB với keywords `["jwt", "api key", "json web token"]`: *"API key là chuỗi bí mật cố định… JWT là **token** tự chứa thông tin (sub, role, exp) được ký bằng **chữ ký** số… token tự **hết hạn** theo exp."* |
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Tương tự, không có tài liệu về HPA. Thêm entry keywords `["hpa", "horizontal pod autoscaler", "kubernetes", "autoscal"]`: *"Kubernetes HPA… dựa trên **CPU** utilization, **memory** usage, hoặc **custom metrics** (request/s, queue, p95 từ Prometheus)…"* |

Keyword của entry mới được chọn cụ thể (`jwt`, `hpa`) để không "cướp" retrieval của câu khác. Kết quả: 2 câu được cải thiện, 0 regression. Đã chép phần sửa sang `production/utils/mock_llm.py` để stack Docker cũng đạt 100%.

**Quality gate trong CI:** `run_eval.py` trả **exit code 1** khi accuracy < `--min-accuracy` hoặc có câu regression so với `--baseline`. Kiểm chứng: chạy v1 với `--baseline reports/eval_v2.json` cho ra 20 câu regression, `Quality gate ❌ FAIL`, **exit code 1**. Bước GitHub Actions chặn merge:

```yaml
# .github/workflows/eval.yml
name: eval-quality-gate
on: pull_request
jobs:
  eval:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: 06-lab-complete/benchmark-observability/develop } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - name: Start agent (PR version)
        run: |
          AGENT_VERSION=v2 PORT=8002 python app.py &
          for i in $(seq 1 30); do curl -sf localhost:8002/health && break; sleep 1; done
      - name: Quality gate — fail job (exit 1) nếu accuracy < 100% hoặc có regression
        run: python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2_fixed.json --out eval_pr.json
```

Đặt job này là **required status check** trong branch protection của `main`: exit code khác 0 làm job đỏ, và PR không merge được.

**Trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- v2 (RAG) tốn **gấp khoảng 1,9 lần token** mỗi câu (109,1 so với 57,5) vì prompt chứa thêm context, tổng cost gấp 1,86 lần, và p50 chậm hơn 24 ms (bước retrieval khoảng 20 ms + prompt dài hơn).
- Đổi lại, accuracy tăng từ 4,3% lên 91,3%, nên **cost / câu đúng rẻ hơn khoảng 11,3 lần** (0,00040995 so với 0,00003627 USD). Câu trả lời sai thì "rẻ" cũng vô giá trị, nên phải so sánh theo cost / câu đúng chứ không theo cost / câu.
- Sửa KB làm avg tokens tăng thêm 9,7 (tài liệu mới dài hơn), nhưng cost / câu đúng gần như giữ nguyên (0,00003629).

---

## 4. Observability stack (production)

Stack: `docker compose -p k5-day14-observability up -d --build` (agent ×2 + nginx + prometheus + grafana + jaeger + locust). `promtool test rules alert_rules_test.yml` cho ra `SUCCESS`.

**Lỗi trong code mẫu đã sửa:** container agent restart liên tục với `ModuleNotFoundError: No module named 'uvicorn'`. Trong `production/Dockerfile`, user `agent` được tạo với `-d /app` nên `HOME=/app`, Python tìm user site ở `/app/.local`, trong khi package được copy vào `/home/agent/.local`. Đã thêm `ENV PYTHONUSERBASE=/home/agent/.local` (cách bản Part 5 đã làm).

### Exercise 7.4: Đọc dashboard (số liệu Prometheus lúc 08:40:50 UTC, 2 instance, cấu hình mặc định, Locust 10 user; xem `reports/prometheus_snapshot_0840.json`)

1. **p95 và avg:** p95 = **291 ms**, avg = **228 ms** (p50 = 171 ms, p99 = **1812 ms**). p95 và avg khá gần nhau nhưng p99 gấp khoảng 8 lần avg. Khoảng cách avg ↔ p99 chính là **tail latency**: đa số request khoảng 170–290 ms, nhưng khoảng 3% request chậm thêm khoảng 1,5 s (mock `MOCK_SLOW_RATE=0.03`). Avg bị nhóm chậm kéo lên trên p50 (228 > 171), cho thấy phân bố lệch phải.
2. **Requests/s theo instance:** `172.20.0.7` = 3,091 req/s, `172.20.0.8` = 3,073 req/s, **chênh 0,6%**, nên Nginx chia **đều** (round-robin qua `server agent:8000 resolve`).
3. **Input tokens/s (492,5) > output tokens/s (265,5):** input = system prompt + **context retrieval** (RAG chèn nguyên tài liệu vào prompt) + câu hỏi, còn output chỉ là câu trả lời ngắn. RAG làm input phình ra. Đây cũng là lý do giá input/1K token thường thấp hơn output.
4. **`curl http://localhost:8080/metrics`** trả `HTTP/1.1 404 Not Found` (trang lỗi của nginx). `nginx.conf` **chặn `/metrics` từ bên ngoài**: metrics lộ thông tin nội bộ (route, số request, cost, version) và có thể bị dùng để dò hệ thống. Prometheus scrape trực tiếp từng container `agent:8000/metrics` qua network nội bộ `obs_net`, không đi qua nginx.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger: [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (event `exception`): [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với **2 alert cùng firing** (`AgentHighErrorRate` + `AgentHighLatencyP95`): [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

### 4.2 Thí nghiệm "phá hệ thống" (Exercise 7.6)

Tải nền: Locust headless 10 user (`-u 10 -r 5`) suốt các thí nghiệm. Mỗi lần đổi `.env` rồi `docker compose up -d --scale agent=2`, sau đó script poll `GET /api/v1/alerts` của Prometheus mỗi 2 giây. Thời gian tính từ lúc lệnh đổi cấu hình chạy xong tới khi alert chuyển `firing`. Hoàn tác và chờ mọi alert về `inactive` rồi mới làm thí nghiệm tiếp theo. Toàn bộ số liệu nằm trong `reports/chaos_results.json`.

| # | Thay đổi (giờ UTC) | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (08:27:24) | `AgentHighErrorRate` | **87 s** | **Error rate**: 0,87% → **21,7%** (đỏ); p95 gần như không đổi (0,289 → 0,298 s) |
| B | `MOCK_SLOW_RATE=0.3` (08:29:50) | `AgentHighLatencyP95` | **147 s** | **Latency p50/p95/p99**: p95 0,290 → **1,923 s**; RPS giảm 4,84 → 4,80 do user chờ lâu hơn |
| C | `LLM_MODEL=mock-llm-large` (08:33:20) | `LLMCostBurnRateHigh` | **177 s** | **Cost USD/giờ**: $0,62 → **$6,91**/giờ (gấp khoảng 11 lần sau 3 phút, vẫn đang tăng vì `rate[5m]` chưa phủ hết cửa sổ); LLM p95 0,289 → 0,672 s |
| D | `docker pause k5-day14-observability-agent-1` (08:41:01) | `AgentInstanceDown` (instance `172.20.0.7:8000`) | **42 s** | **Instances up**: 2 → **1**; req/s theo instance chỉ còn 1 đường. Error rate của agent vẫn xanh (0,43%) |
| E | `AGENT_VERSION=v1` (08:41:54) | **Không có** (theo dõi 150 s) | — | **Retrieval hit ratio** mất, **tokens/s** và **cost/giờ** giảm ($0,79 → $0,55/giờ), p95 còn **giảm** (0,293 → 0,198 s), bảng version đổi sang v1. Mọi metric hạ tầng đều "đẹp hơn" |

**Giải thích thời gian:** thời gian tới lúc firing ≈ thời gian để `rate(...[cửa sổ])` vượt ngưỡng + `for` + chu kỳ scrape/evaluate (5 s).
- A: `for: 1m` + cửa sổ 1 phút, ra 87 s.
- B: `for: 2m`, ra 147 s.
- C: `for: 2m` và `rate[5m]` cần đủ dữ liệu "đắt" để trung bình vượt $2/giờ, ra 177 s.
- D: `for: 30s`, ra 42 s, và khi `docker unpause` thì alert về inactive sau 10 s.

Ở D, log nginx ghi **9 request `POST /ask` trả 504** lúc 08:41:11–08:41:12 (`upstream timed out ... upstream: "http://172.20.0.7:8000/ask"`, đúng instance bị pause), nhưng error rate của agent vẫn chỉ 0,43%: request không bao giờ được agent xử lý xong nên metric của agent không đếm. Vì vậy cần giám sát thêm ở tầng load balancer hoặc synthetic check.

**Phát hiện thêm:** trong lúc chạy benchmark scaling 100 user (mục 5), `LLMCostBurnRateHigh` **đã tự firing**. Lúc 08:24:13 cost là **$5,85/giờ** (khoảng 60 req/s × khoảng $0,00004/request). Với ngưỡng $2/giờ, chỉ cần khoảng 14 req/s liên tục là alert cost bật. Đây không phải sự cố mà là **tải tăng hợp lệ**. Production nên đặt ngưỡng cost theo budget thật (ví dụ $10/tháng ≈ $0,014/giờ trung bình) và kèm theo cost / request để phân biệt "nhiều user hơn" với "mỗi request đắt hơn" (như thí nghiệm C).

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**

Lỗi chất lượng không làm hỏng hạ tầng: request vẫn 200, nhanh và rẻ hơn. Cần đo **chính chất lượng**:
1. **Eval làm quality gate trong CI/CD** (mục 3): chạy golden dataset với mọi thay đổi prompt, model, retrieval hoặc version; exit 1 thì chặn deploy. Bản v1 sẽ bị chặn ngay vì có 20 câu regression.
2. **Online eval / canary:** định kỳ (ví dụ mỗi 5 phút) gửi một mẫu câu golden tới production (synthetic probe), xuất metric `agent_eval_accuracy` và alert khi < 95%. Deploy canary và so sánh accuracy với bản cũ trước khi chuyển 100% traffic.
3. **Metric proxy cho chất lượng:** `retrieval_hit_ratio` (rơi về 0 ở E), số token output, tỉ lệ câu trả lời "fallback/chung chung", và alert khi chúng đổi đột ngột. Thêm vào đó là alert khi `agent_info{version}` đổi ngoài lịch deploy.
4. **Tín hiệu từ người dùng:** thumbs up/down, tỉ lệ hỏi lại, LLM-as-judge chấm mẫu ngẫu nhiên log production.

### 4.3 Debug bằng trace (Exercise 7.5)

Trace chậm nhất trong Jaeger (lọc `POST /ask`, min duration 1,5 s, có 437 trace khớp):

- `trace_id`: **`a986cba03cfd8013d3d8c20ecdeb5802`**
- Tổng thời gian: **1756.5 ms**
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1679.8 ms, 95,6%**). Gọi LLM upstream chậm, không phải code của agent: `agent.retrieve_context` chỉ 22,4 ms (1,3%), phần còn lại của `agent.run` không đáng kể. Attributes: `gen_ai.request.model=mock-llm-small`, `gen_ai.usage.input_tokens=74`, `gen_ai.usage.output_tokens=37`.

```text
POST /ask                      1756.5 ms (100.0%)
└── agent.run                  1702.3 ms ( 96.9%)
    ├── agent.retrieve_context   22.4 ms (  1.3%)   retrieval.documents=1
    └── chat mock-llm-small    1679.8 ms ( 95.6%)   ← span chậm nhất
```

- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep a986cba03cfd8013d3d8c20ecdeb5802`):

```json
{"ts": "2026-11-25T08:21:25.110248+00:00", "level": "INFO", "service": "observable-agent", "instance": "2ce746b1941a", "event": "llm_call", "trace_id": "a986cba03cfd8013d3d8c20ecdeb5802", "span_id": "79edafcf69cc12e9", "request_id": "1fa6e3bda2be", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1679.7}
{"ts": "2026-11-25T08:21:25.110543+00:00", "level": "INFO", "service": "observable-agent", "instance": "2ce746b1941a", "event": "http_request", "trace_id": "a986cba03cfd8013d3d8c20ecdeb5802", "span_id": "79edafcf69cc12e9", "request_id": "1fa6e3bda2be", "method": "POST", "route": "/ask", "status": 200, "ms": 1756.1}
```

`llm_ms` = 1679,7 trong log khớp với span 1679,8 ms; `ms` = 1756,1 khớp với root span 1756,5 ms.

**Trace lỗi:** `trace_id` **`c5fd9be0634894733feb069c7154a6f8`** (112,6 ms, HTTP 503). Span `chat mock-llm-small` có `status=ERROR`, `error.type=upstream_unavailable` và event **`exception`** (`exception.type=utils.mock_llm.LLMError`, `exception.message="Upstream LLM error: 503 Service Unavailable (mock)"`). Lỗi được lan lên `agent.run` và `POST /ask`. Log khớp:

```json
{"ts": "2026-11-25T08:24:28.802267+00:00", "level": "INFO", "service": "observable-agent", "instance": "f4304b0d8698", "event": "llm_error", "trace_id": "c5fd9be0634894733feb069c7154a6f8", "span_id": "c93738b8505b6fc4", "request_id": "e468a6367601", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T08:24:28.802571+00:00", "level": "INFO", "service": "observable-agent", "instance": "f4304b0d8698", "event": "http_request", "trace_id": "c5fd9be0634894733feb069c7154a6f8", "span_id": "c93738b8505b6fc4", "request_id": "e468a6367601", "method": "POST", "route": "/ask", "status": 503, "ms": 112.1}
```

Lỗi đến nhanh (112 ms) so với response thành công (khoảng 190 ms) vì mock trả lỗi sau một nửa latency, giống upstream thật thường fail sớm.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

```bash
docker compose -p k5-day14-observability up -d --build --scale agent=1
docker compose -p k5-day14-observability run --rm locust -f /mnt/locust/locustfile.py --host http://nginx \
  --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_1
docker compose -p k5-day14-observability up -d --scale agent=3      # Prometheus thấy 3 target "up" trước khi chạy
docker compose -p k5-day14-observability run --rm locust ... --csv /mnt/results/scale_3
```

Số liệu dòng `POST /ask` trong `benchmark-results/scale_*_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 60.12 | 190 | 230 | 1700 | 80 / 7194 (1.11 %), tất cả là 503 upstream |
| 3 | 60.13 | 190 | 230 | 1700 | 76 / 7191 (1.06 %), tất cả là 503 upstream |

(Tổng cộng cả `GET /health`: 66,16 so với 66,14 req/s. Avg `/ask`: 236,0 so với 234,4 ms.)

**Giải thích:** scale từ 1 lên 3 instance **không cải thiện gì**: RPS, p50, p95, p99 gần như giống hệt nhau.

1. **Agent chưa phải nút thắt.** Mock LLM là `await asyncio.sleep` (chờ I/O), nên một instance với 1 event loop xử lý 60 req/s mà p50 vẫn bằng latency của LLM (190 ms). In-flight trung bình chỉ khoảng 60 × 0,236 ≈ 14 request, quá ít để bão hoà một instance (giới hạn 0,5 CPU).
2. **Throughput bị Locust giới hạn (closed-loop).** Mỗi user chờ `between(0.5, 2)` giây (trung bình 1,25 s) rồi mới gửi request tiếp. Throughput tối đa ≈ users / (think time + latency) = 100 / (1,25 + 0,24) ≈ **67 req/s**, khớp với 66,15 req/s đo được. Thêm instance không làm user gửi nhanh hơn.
3. **Latency do LLM upstream quyết định.** Panel LLM latency cho thấy p50 khoảng 190 ms và p99 khoảng 1,7 s chính là latency của mock LLM (bao gồm 3% slow request). Scale ngang agent không làm LLM nhanh hơn: trace ở 4.3 cho thấy 95,6% thời gian nằm trong span gọi LLM.

Muốn thấy lợi ích của scaling thì phải tạo tải vượt khả năng một instance: nhiều user hơn hoặc `wait_time` ngắn hơn (open-loop), hoặc thêm phần việc dùng nhiều CPU. Lúc đó 3 instance mới giữ p95 thấp trong khi 1 instance bắt đầu xếp hàng (như mức c = 100 ở mục 2.1). Với agent LLM thật, nút thắt thường là **rate limit / quota và latency của nhà cung cấp LLM**, nên cần caching, batching, model nhỏ hơn hoặc streaming, chứ không chỉ thêm instance.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối, percentile nói thật.** Chỉ 3% request chậm làm p99 tăng khoảng 7 lần mà avg chỉ tăng 32%; ở 10% thì p95 cũng nhảy theo. SLO phải đặt theo p95/p99, và benchmark phải đủ mẫu (300 request đã cho error rate dao động 0,67–2,33%).
  2. **Hạ tầng xanh không có nghĩa là trả lời đúng.** Thí nghiệm E (v1) làm mọi metric đẹp hơn nhưng accuracy giảm từ 91% xuống 4%. Chỉ eval trên golden dataset (với exit code chặn CI) mới bắt được. So sánh phiên bản phải dùng **cost / câu đúng** chứ không dùng cost / câu.
  3. **Metrics → traces → logs liên kết với nhau.** Dashboard báo p99 cao, Jaeger cho thấy span LLM chiếm 95,6%, `trace_id` dẫn tới đúng 2 dòng log JSON có `llm_ms` khớp. Scale ngang không giúp được khi nút thắt nằm ở upstream hoặc ở phía tạo tải. Phải đo để biết, không đoán.
- Nếu đưa agent lên production thật, mình sẽ thêm:
  - **Metric:** `agent_eval_accuracy` (online synthetic eval), `retrieval_hit_ratio` theo thời gian, cost **/ request** và cost theo API key, `rate_limit_rejections_total` và `budget_rejections_total` (429/402 của Part 6), độ dài hàng đợi / event-loop lag, metric tầng nginx (4xx/5xx/504 và upstream response time).
  - **Alert:** accuracy online < 95%; retrieval hit ratio giảm > 50% so với hôm qua; burn rate SLO đa cửa sổ (5m/1h) thay cho ngưỡng cố định; cost theo budget tháng (dự báo vượt $10); nginx 5xx/504 > 1% (bắt được trường hợp D); synthetic check từ bên ngoài vào `/health` và `/ask`; `agent_info{version}` thay đổi ngoài khung deploy.
