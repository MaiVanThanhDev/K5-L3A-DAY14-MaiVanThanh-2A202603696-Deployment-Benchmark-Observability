# Day 14 Lab - Mission Answers

> **Học viên:** Mai Văn Thành · **MSSV:** 2A202603696 · **Lớp:** K5-L3A

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Đọc `01-localhost-vs-production/develop/app.py`, tìm được 9 vấn đề:

| # | Anti-pattern | Dòng | Vì sao nguy hiểm |
|---|---|---|---|
| 1 | **Hardcode secret**: `OPENAI_API_KEY = "sk-..."`, `DATABASE_URL = "postgresql://admin:password123@..."` | 17–18 | Push lên GitHub là lộ key và mật khẩu DB ngay. Muốn đổi key thì phải sửa code và deploy lại |
| 2 | **Log ra secret**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Secret xuất hiện trong log của nền tảng, ai đọc được log là có key. Đã thấy thật khi chạy (xem Exercise 1.2) |
| 3 | **Config cứng trong code**: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Không đổi được giữa dev, staging và prod nếu không sửa code. Vi phạm 12-Factor (Config in env) |
| 4 | **Dùng `print()` thay cho logging** | 33, 34, 38 | Không có level, không có timestamp, không có cấu trúc JSON, nên log aggregator không parse được. Trên Windows, `print()` câu tiếng Việt còn làm crash request (xem Exercise 1.2) |
| 5 | **Không có health check** (`/health`, `/ready`) | — | Agent treo thì nền tảng không biết để restart, load balancer vẫn gửi traffic vào instance chết |
| 6 | **Bind `host="localhost"`** | 51 | Trong container, `localhost` chỉ nhận kết nối từ chính container, bên ngoài không gọi vào được. Phải dùng `0.0.0.0` |
| 7 | **Port cứng `port=8000`** | 52 | Railway, Render và Cloud Run cấp port qua biến môi trường `PORT`. Port cứng thì app không nhận traffic |
| 8 | **`reload=True` luôn bật** | 53 | Chế độ dev: tốn CPU để theo dõi file và sinh thêm tiến trình con. Khi tắt cha mà con chưa chết thì cổng vẫn bị giữ (gặp thật khi làm lab) |
| 9 | **Không xử lý SIGTERM / graceful shutdown** | — | Khi nền tảng deploy bản mới hoặc scale down, request đang xử lý bị cắt ngang và người dùng nhận lỗi |

Ngoài ra: không validate input (chỉ lấy `question` qua query string) và không có cấu hình CORS.

### Exercise 1.2: Chạy bản develop

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
```

**Lần chạy đầu (Windows, stdout chuyển hướng ra file):**

```text
$ curl -X POST "http://localhost:8000/ask?question=Hello"
Internal Server Error

# log server:
  File ".../develop/app.py", line 38, in ask_agent
    print(f"[DEBUG] Response: {response}")
UnicodeEncodeError: 'charmap' codec can't encode character 'Đ' in position 18
```

App crash vì `print()` ghi câu trả lời tiếng Việt ra stdout dùng mã cp1252 của Windows. Đây là ví dụ thật của "It works on my machine": cùng một code nhưng chạy trên máy hoặc terminal khác thì hỏng. Chạy lại với `PYTHONIOENCODING=utf-8`:

```text
$ curl http://localhost:8000/
{"message":"Hello! Agent is running on my machine :)"}

$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
HTTP 200

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found            # không có health check

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
HTTP 422                          # bản develop chỉ nhận query, không nhận JSON
```

**Log server, secret bị in ra:**

```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). ...
```

**Nhận xét:** app chạy được nhưng chưa sẵn sàng cho production: lộ secret trong log, không có `/health`, chỉ nghe trên `localhost:8000`, và crash theo encoding của môi trường.

### Exercise 1.3: Chạy bản production và bảng so sánh

```bash
cd ../production
cp .env.example .env
pip install -r requirements.txt
python app.py
```

```text
$ curl http://localhost:8000/
{"app":"AI Agent","version":"1.0.0","environment":"development","status":"running"}

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:22:49.977278+00:00"}

$ curl http://localhost:8000/ready
{"ready":true}

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{}'
{"detail":"question field is required"}  HTTP 422

# log server:
WARNING:root:OPENAI_API_KEY not set — using mock LLM
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

Bản production nghe trên `0.0.0.0`, có `/health` và `/ready`, trả lỗi 422 rõ ràng khi thiếu input và không log secret.

**Bảng so sánh:**

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| **Config** | Hardcode trong `app.py` (`DEBUG = True`, `MAX_TOKENS = 500`) | Đọc từ biến môi trường qua `config.py` (dataclass `Settings`, `os.getenv`) | Cùng một image chạy được ở dev, staging và prod, chỉ đổi env. Không phải sửa code để đổi cấu hình |
| **Secrets** | `OPENAI_API_KEY`, mật khẩu DB nằm trong code | Lấy từ env (`OPENAI_API_KEY`, `AGENT_API_KEY`), `.env` nằm trong `.gitignore`, chỉ commit `.env.example` | Không lộ secret trên Git. Đổi hoặc thu hồi key mà không phải deploy lại code |
| **Validate config** | Không có | `validate()`: thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` thì `raise ValueError` | Fail fast: lỗi cấu hình lộ ra ngay lúc khởi động, không đợi tới lúc có request thật |
| **Health check** | Không có (`/health` trả 404) | `/health` (liveness: uptime, version) và `/ready` (readiness: 503 khi chưa sẵn sàng) | Nền tảng dùng `/health` để biết khi nào restart container, load balancer dùng `/ready` để quyết định có gửi traffic vào không |
| **Logging** | `print()`, in cả secret, crash vì encoding | `logging` với format JSON (`event`, `question_length`, `client_ip`), không log nội dung nhạy cảm | Log aggregator (Loki, Datadog) parse và tìm kiếm được, có level, và không lộ secret |
| **Host / Port** | `localhost:8000` cứng | `HOST` (mặc định `0.0.0.0`) và `PORT` từ env | Container nhận được kết nối từ bên ngoài, nền tảng cloud cấp port động |
| **Debug / Reload** | `reload=True` luôn bật | `reload=settings.debug`, chỉ bật khi `DEBUG=true` | Production không tốn tài nguyên cho file watcher và không sinh tiến trình thừa |
| **Shutdown** | Tắt đột ngột | `lifespan` đặt `is_ready = False`, chờ request đang chạy rồi đóng; có handler `SIGTERM` | Deploy hoặc scale down không cắt ngang request, `/ready` báo 503 để load balancer ngừng gửi traffic trước |
| **Input** | `question` qua query string, không kiểm tra | Nhận JSON body, thiếu `question` thì trả 422 kèm thông báo rõ | Client nhận lỗi dễ hiểu, không lộ stack trace |
| **CORS** | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ frontend được phép mới gọi được API từ trình duyệt |
| **Metrics** | Không có | `/metrics` (uptime, version, env) | Prometheus scrape được để theo dõi và cảnh báo |

**Hai điểm phát hiện thêm trong bản production (để rút kinh nghiệm cho Part 6):**

1. `python-dotenv` có trong `requirements.txt` nhưng `config.py` không gọi `load_dotenv()`, nên file `.env` thực ra **không được đọc**. App vẫn chạy chỉ vì mọi biến đều có giá trị mặc định. Muốn dùng `.env` khi chạy local thì phải `export` biến, hoặc thêm `load_dotenv()`.
2. `config.py` gọi `logging.warning(...)` lúc import, trước `logging.basicConfig(...)` trong `app.py`. Lời gọi này tự cấu hình root logger ở mức WARNING, nên `basicConfig` phía sau không còn tác dụng. Kết quả là các dòng log JSON mức INFO (`agent_request`, `agent_response`) không hiện ra, đúng như log ở trên. Cách sửa: `logging.basicConfig(..., force=True)` hoặc cấu hình logging trước khi import `config`.

### Checkpoint 1

- [x] Hiểu tại sao hardcode secret là nguy hiểm: lộ trên Git và trong log, muốn đổi key thì phải deploy lại.
- [x] Biết cách dùng biến môi trường: `os.getenv()` gom trong `config.py`, kèm `.env.example`.
- [x] Hiểu vai trò của health check: liveness (`/health`) để restart, readiness (`/ready`) để định tuyến traffic.
- [x] Biết graceful shutdown là gì: nhận SIGTERM, ngừng nhận request mới, xử lý xong request đang chạy rồi mới thoát.

---

## Part 2: Docker

> Tất cả image build từ gốc repo, Docker 29.9.2 (Docker Desktop + WSL2).

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản Python đầy đủ dựa trên Debian, có sẵn gcc và các build tool (dòng 8). Đây là lý do image develop nặng.
2. **Working directory:** `/app` (`WORKDIR /app`, dòng 11). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều chạy tương đối từ thư mục này.
3. **Tại sao COPY `requirements.txt` trước:** để tận dụng **layer cache** của Docker. Mỗi lệnh là một layer, và Docker chỉ build lại từ layer đầu tiên có thay đổi trở đi. `requirements.txt` hiếm khi đổi còn code đổi liên tục. Copy requirements rồi `pip install` (dòng 14–17) trước khi `COPY app.py` (dòng 20) nên khi chỉ sửa code, layer `pip install` (53,3 MB, đo bằng `docker history`) được lấy từ cache, build lại chỉ mất vài giây. Nếu `COPY . .` trước thì mỗi lần sửa code đều phải cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:**
   - `CMD ["python", "app.py"]` là **lệnh mặc định**, bị ghi đè hoàn toàn khi truyền lệnh khác: `docker run my-agent:develop whoami` chạy `whoami` thay vì app. Mình đã dùng đúng cách này để kiểm tra user trong container.
   - `ENTRYPOINT` là **lệnh cố định** của container. Tham số của `docker run` (hoặc `CMD`) được **nối vào sau** nó. Muốn đổi phải dùng `--entrypoint`.
   - Thường dùng kết hợp: `ENTRYPOINT` là chương trình chính, `CMD` là tham số mặc định.

### Exercise 2.2: Build và run (develop)

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name p2-dev -p 8000:8000 my-agent:develop
```

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.9,"container":true}

$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ docker ps
NAMES     IMAGE              STATUS        PORTS
p2-dev    my-agent:develop   Up 1 second   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp

$ docker logs p2-dev
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:33180 - "POST /ask?question=What%20is%20Docker HTTP/1.1" 200 OK
```

**Nhận xét:** ở Part 1, chạy trực tiếp trên Windows thì `print()` câu tiếng Việt bị crash (cp1252). Trong container, cùng loại code chạy bình thường vì môi trường Linux UTF-8 được đóng gói sẵn. Đây đúng là vấn đề "works on my machine" mà Docker giải quyết.

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (`builder`, `python:3.11-slim`):** cài build tool (`gcc`, `libpq-dev`) bằng apt, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này chỉ dùng để build, **không được deploy**.
- **Stage 2 (`runtime`, `python:3.11-slim` mới):** tạo user không phải root `appuser`, chỉ `COPY --from=builder /root/.local` (các package đã cài) cùng `main.py` và `utils/`, `chown` cho `appuser`, `USER appuser`, thêm `HEALTHCHECK` gọi `/health`, rồi chạy `uvicorn` với 2 worker.
- **Tại sao image nhỏ hơn:**
  1. Base `python:3.11-slim` thay cho `python:3.11` đầy đủ. Bản đầy đủ có sẵn gcc, header và nhiều thư viện hệ thống.
  2. Build tool (gcc, libpq-dev) và cache apt nằm lại ở stage builder. Image cuối chỉ chứa kết quả đã cài.
  3. `--no-cache-dir` không lưu cache pip.

**Kiểm chứng:**

```text
$ docker run --rm my-agent:advanced whoami
appuser                     # chạy non-root
$ docker run --rm my-agent:advanced sh -c "which gcc"
gcc: not found              # không mang build tool vào runtime
$ docker run --rm my-agent:develop sh -c "whoami; which gcc"
root
/usr/bin/gcc
```

### Exercise 2.3: Image size comparison

```text
$ docker image ls my-agent --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}"
REPOSITORY:TAG      SIZE
my-agent:advanced   240MB
my-agent:develop    1.67GB

$ docker image inspect my-agent:develop  --format '{{.Size}}'   → 1667784010 bytes
$ docker image inspect my-agent:advanced --format '{{.Size}}'   → 239815330 bytes
```

- **Develop:** 1667,8 MB (≈ 1,67 GB)
- **Production (advanced, multi-stage):** 239,8 MB
- **Difference:** giảm 1428,0 MB, tức **≈ 85,6%** (= (1667,8 − 239,8) / 1667,8). Image production nhỏ hơn khoảng 7 lần và đạt yêu cầu < 500 MB.

(Dung lượng nén khi push lên registry, cột CONTENT SIZE: develop 426 MB, advanced 57,4 MB, giảm ≈ 86,5%.)

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

```bash
cd 02-docker/production
touch .env.local                 # compose cần file này (nằm trong .gitignore)
docker compose -p k5-day14-docker up -d --build
```

**Architecture diagram:**

```text
                     Host (máy của bạn)
                           │  :80 (và :443)
                           ▼
              ┌──────────────────────────┐
              │  nginx (nginx:alpine)     │  reverse proxy, load balancer,
              │  rate limit 10 r/s/IP     │  security headers
              └────────────┬─────────────┘
                           │ proxy_pass http://agent:8000
   ┌───────────────────────┼─────────── network "internal" (bridge) ──┐
   │                       ▼                                          │
   │        ┌──────────────────────────┐                              │
   │        │ agent (FastAPI, :8000)    │  build từ Dockerfile,        │
   │        │ target: runtime, non-root │  healthcheck /health          │
   │        └──────┬──────────────┬────┘                              │
   │   redis://redis:6379/0   http://qdrant:6333                      │
   │               ▼              ▼                                   │
   │   ┌──────────────────┐  ┌────────────────────┐                   │
   │   │ redis:7-alpine    │  │ qdrant:v1.9.0       │                  │
   │   │ cache, rate limit │  │ vector DB (RAG)     │                  │
   │   │ volume redis_data │  │ volume qdrant_data  │                  │
   │   └──────────────────┘  └────────────────────┘                   │
   └──────────────────────────────────────────────────────────────────┘
```

**Services được start (4):**

```text
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 11 seconds (healthy)   8000/tcp
nginx     nginx:alpine            Up 10 seconds             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 21 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 21 seconds (healthy)   6379/tcp
```

**Chúng giao tiếp thế nào:**
- Cả 4 service cùng nằm trong network `internal` (bridge). Docker có DNS nội bộ nên gọi nhau bằng **tên service**: agent kết nối `redis:6379` và `qdrant:6333`, nginx `proxy_pass` tới `agent:8000`. Kiểm tra bằng `docker compose exec agent python -c "socket.gethostbyname(...)"` ra `redis 172.20.0.3`, `qdrant 172.20.0.2`.
- **Chỉ nginx mở cổng ra host** (80/443). Agent, Redis và Qdrant không có `ports:`, nên `curl http://localhost:8000/health` bị **connection refused**. Người ngoài chỉ vào được qua nginx.
- `depends_on` + `condition: service_healthy`: agent chỉ start khi Redis và Qdrant đã healthy (log: `qdrant-1 Healthy`, `redis-1 Healthy`, sau đó mới tới `agent-1 Started`), và nginx start sau agent.

**Test qua Nginx:**

```text
$ curl http://localhost/health
{"status":"ok","uptime_seconds":10.0,"version":"2.0.0","timestamp":"2026-11-25T07:58:36.855800"}

$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -i http://localhost/ready
HTTP/1.1 200 OK
Server: nginx                       # server_tokens off: ẩn version
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
{"ready":true}

# Bắn 40 request song song vào / để thử rate limit của nginx (10 r/s, burst 20):
     26 200
     14 429
```

**Debug container:**

```text
$ docker compose -p k5-day14-docker logs agent
agent-1  | {"time":"2026-11-25 07:58:36,891","level":"INFO","msg":"{"event": "request", "q_len": 21}"}
agent-1  | INFO:     172.20.0.5:33244 - "POST /ask HTTP/1.1" 200 OK      # 172.20.0.5 = nginx
$ docker compose -p k5-day14-docker exec agent ...                      # chạy lệnh bên trong container
$ docker compose -p k5-day14-docker down
```

### Checkpoint 2

- [x] Hiểu cấu trúc Dockerfile: `FROM`, `WORKDIR`, `COPY`, `RUN`, `EXPOSE`, `CMD`; thứ tự layer quyết định cache.
- [x] Biết lợi ích của multi-stage build: image 1,67 GB → 240 MB (−85,6%), không có gcc, chạy non-root.
- [x] Hiểu Docker Compose orchestration: 4 service, network nội bộ, DNS theo tên service, `depends_on` + healthcheck.
- [x] Biết cách debug container: `docker logs`, `docker compose logs <service>`, `docker exec`, `docker ps`, `docker history`.

---

## Part 3: Cloud Deployment

> Lớp K5 deploy chính agent Part 6 (`06-lab-complete/`) sau khi đạt `PASS 12/12`.

### Exercise 3.1 / 3.2: Deploy agent Part 6

- **Nền tảng chính:** _(TODO: Railway hoặc Render)_
- **URL:** _(TODO: https://...)_. Chi tiết, lệnh test và ảnh xem trong [DEPLOYMENT.md](DEPLOYMENT.md).
- **Kết quả 4 lệnh tự kiểm (CP6):**

```text
(TODO: dán output 4 lệnh: /health 200, /ready 200, /ask không key 401, /ask có key 200)
```

### So sánh `railway.toml` và `render.yaml` (`06-lab-complete/`)

| Khía cạnh | `railway.toml` | `render.yaml` | Vì sao khác |
|---|---|---|---|
| Định dạng, phạm vi | TOML, cấu hình **một service** (build + deploy) | YAML Blueprint, mô tả **cả hạ tầng**: web service + Key Value (Redis) | Railway tạo Redis bằng UI/CLI (`railway add`) rồi tham chiếu biến; Render Blueprint là IaC, khai báo mọi resource trong một file |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath`, `dockerContext`, `rootDir: 06-lab-complete` | Render đọc Blueprint từ repo nên phải chỉ ra thư mục con; Railway chạy `railway up` ngay trong thư mục |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 100` | `healthCheckPath: /health` | Cùng ý tưởng: nền tảng chỉ chuyển traffic sang bản mới khi `/health` trả 200 (zero-downtime deploy) |
| Restart | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Render tự restart, không cấu hình trong file | Railway cho chỉnh chính sách restart |
| Secret | **Không có trong file**: đặt bằng `railway variables set AGENT_API_KEY=...` | `AGENT_API_KEY: generateValue: true` (Render tự sinh chuỗi ngẫu nhiên) | Cả hai đều không ghi secret vào Git; Render có thể tự sinh secret ngay trong Blueprint |
| Redis URL | Tham chiếu biến của service Redis: `REDIS_URL=${{Redis.REDIS_URL}}` | `fromService: {type: keyvalue, name: day14-redis, property: connectionString}` | Render nối service bằng khai báo; Railway dùng biến tham chiếu |
| Biến thường | Đặt qua CLI/UI | Ghi thẳng trong `envVars` (`RATE_LIMIT_PER_MINUTE`, `MONTHLY_BUDGET_USD`...) | Biến không nhạy cảm nên version hoá được trong Git |
| Port | Railway inject `PORT`, Dockerfile `CMD` dùng `${PORT:-8000}` | Render cũng inject `PORT` (mặc định 10000) | Vì vậy CMD bắt buộc đọc `PORT`, không cố định 8000 |
| Region, plan | Chọn trên UI | `region: singapore`, `plan: free` | Blueprint mô tả đầy đủ để tái tạo |

**Kết luận:** `railway.toml` chỉ là cấu hình build/deploy cho một service; secret và Redis quản lý ngoài file. `render.yaml` là Infrastructure-as-Code đầy đủ: một file dựng lại được cả agent lẫn Redis, secret được sinh tự động.

### Exercise 3.3: Pipeline CI/CD Cloud Run (`03-cloud-deployment/production-cloud-run/`)

`cloudbuild.yaml` định nghĩa pipeline Cloud Build chạy khi push lên `main`, gồm 4 bước nối tiếp nhau (`waitFor`):

1. **test:** trong image `python:3.11-slim`, cài `requirements.txt` + pytest rồi chạy `pytest tests/`. Test fail thì pipeline dừng, không build.
2. **build:** `docker build` image, gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tái dùng layer.
3. **push:** đẩy cả hai tag lên Container Registry.
4. **deploy:** `gcloud run deploy` dùng image **theo `$COMMIT_SHA`** (bất biến, rollback được) tại region `asia-southeast1`, đặt `min=1` (tránh cold start), `max=10` instance, 512 Mi RAM, 1 CPU, timeout 60 giây, `ENVIRONMENT=production`, và lấy `OPENAI_API_KEY` từ **Secret Manager** (`--set-secrets`), không hardcode.

`service.yaml` là cách khai báo (Knative) cùng service đó để `gcloud run services replace`: `containerConcurrency: 80` request/instance, autoscale 1–10, CPU/RAM requests–limits, secret lấy bằng `secretKeyRef`, **livenessProbe `/health`** (30 giây/lần) và **startupProbe `/ready`** (chỉ nhận traffic khi đã sẵn sàng).

---

## Part 4: API Security

> Chạy trong Ubuntu (WSL2), Python 3.14 venv. Token JWT trong output đã được che.

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **API key được check ở đâu?** Trong dependency `verify_api_key()` (dòng 39–54). Hàm này đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36) và được gắn vào endpoint bằng `Depends(verify_api_key)` (dòng 70). Endpoint nào cần bảo vệ thì thêm dependency này. `/` và `/health` để public vì nền tảng cần gọi health check.
- **Sai key thì sao?** Thiếu header thì trả **401 Unauthorized** (`Missing API key...`). Có header nhưng sai key thì trả **403 Forbidden** (`Invalid API key.`). Request bị chặn trước khi chạm tới LLM nên không tốn tiền.
- **Làm sao rotate key?** Key đọc từ biến môi trường `AGENT_API_KEY` (dòng 35), không nằm trong code. Để rotate: đặt giá trị mới trên nền tảng (Railway/Render Variables) rồi restart hoặc redeploy, không phải sửa code. Muốn rotate **không downtime** thì cho app chấp nhận đồng thời 2 key (ví dụ `AGENT_API_KEYS=old,new`), báo client chuyển sang key mới, sau đó gỡ key cũ.
- **Nhận xét:** dòng 91 `print(f"API Key: {API_KEY}")` in key ra log lúc khởi động, cùng anti-pattern với Part 1. Giá trị mặc định `"demo-key-change-in-production"` cũng là một dạng hardcode secret: quên đặt env thì app vẫn chạy với key ai cũng biết.

**Test** (`AGENT_API_KEY=secret-key-123 python app.py`):

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/auth.py`)

**JWT flow:**
1. Client gửi `POST /auth/token` kèm `{"username","password"}`. `authenticate_user()` kiểm tra với `DEMO_USERS`; sai thì trả 401.
2. `create_token()` tạo JWT gồm `header.payload.signature`, payload là `{"sub": username, "role": role, "iat", "exp": now+60'}`, ký **HS256** bằng `JWT_SECRET` (lấy từ env).
3. Client gửi kèm mỗi request header `Authorization: Bearer <token>`.
4. `verify_token()` kiểm tra chữ ký và hạn bằng `jwt.decode(...)`, rồi lấy `username` và `role` ra luôn, **không cần tra DB** (stateless). Thiếu token trả 401, token hết hạn trả 401, token giả hoặc sai chữ ký trả 403.

Payload chỉ được **mã hoá base64, không bị mã hoá bí mật**: ai cũng đọc được nhưng không sửa được, vì sửa là sai chữ ký. Vì vậy không đặt thông tin nhạy cảm vào payload.

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"wrong"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token": "eyJhbGciOiJI...<đã che>", "token_type": "bearer", "expires_in_minutes": 60, "hint": "<đã che>"}
# decode phần payload của token:
{'sub': 'student', 'role': 'user', 'iat': 1795593676, 'exp': 1795597276}      # exp − iat = 3600 s = 60 phút

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": ""}'
HTTP/1.1 422 Unprocessable Content        # Pydantic: question min_length=1, max_length=1000
```

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** **Sliding Window Log**. Code gọi là "Sliding Window Counter" nhưng thực chất lưu từng timestamp. Mỗi user có một `deque` timestamp; mỗi request sẽ loại các timestamp cũ hơn `now − 60s`, rồi đếm số còn lại. Đạt `max_requests` thì trả 429 kèm `Retry-After` = thời điểm timestamp cũ nhất rời khỏi cửa sổ. Không phải token bucket: không có bucket nạp dần, và không cho burst vượt giới hạn.
- **Limit:** user thường (`role=user`, ví dụ `student`) được **10 request/60 giây**. Admin (`role=admin`, ví dụ `teacher`) được **100 request/60 giây** (dòng 86–87).
- **Bypass cho admin:** `app.py` dòng 141 chọn `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`. Role lấy từ JWT (đã ký nên client không tự sửa được), nên admin dùng limiter riêng với hạn mức cao hơn. Muốn bỏ hẳn giới hạn cho admin thì bỏ qua `limiter.check()` khi `role == "admin"`, nhưng vẫn nên giữ một giới hạn cao để phòng token admin bị lộ.
- **Hạn chế:** state nằm trong RAM (`defaultdict(deque)`), nên chạy nhiều instance thì mỗi instance đếm riêng (giới hạn thực tế thành 10 × N), restart là mất. Part 6 phải chuyển sang Redis.

**Test:** gọi liên tục 20 lần bằng token `student`. Lần gọi ở 4.2 đã dùng 1 request nên request thứ 10 của vòng lặp là request thứ 11 trong cửa sổ:

```text
Request 1: HTTP 200  {..."usage":{"requests_remaining":8,...}}
Request 2: HTTP 200  {..."usage":{"requests_remaining":7,...}}
...
Request 8: HTTP 200  {..."usage":{"requests_remaining":1,...}}
Request 9: HTTP 200  {..."usage":{"requests_remaining":0,...}}
Request 10: HTTP 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}  [retry-after: 59]
Request 11: HTTP 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}  [retry-after: 59]
...
Request 20: HTTP 429  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}  [retry-after: 59]

$ curl -i ... (headers khi bị 429)
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795593738
retry-after: 59

# 15 request liên tục bằng token teacher (admin, limit 100/phút):
200 200 200 200 200 200 200 200 200 200 200 200 200 200 200

$ curl http://localhost:8000/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":276,"cost_usd":0.000172,"budget_usd":1.0,"budget_remaining_usd":0.999828,"budget_used_pct":0.0}

$ curl -i http://localhost:8000/admin/stats -H "Authorization: Bearer $TOKEN"    # token student
HTTP/1.1 403 Forbidden
{"detail":"Admin only"}
```

Đủ 3 mã: **401** (không có hoặc sai credential), **200** (có token hợp lệ), **429** (vượt 10 request/phút). Request bị 429 không được tính vào cost (`/me/usage` chỉ ghi 10 request).

**Bug phát hiện:** response `/ask` có trường `"budget_remaining_usd"` nhưng thực chất trả về `usage.total_cost_usd`, tức số tiền **đã dùng** (tăng dần 1.6e-05 → 0.000172), không phải số còn lại. `/me/usage` mới tính đúng (`0.999828`).

### Exercise 4.4: Cost guard implementation

**Vấn đề của bản mẫu (`cost_guard.py`):** budget theo **ngày** ($1/ngày/user) và lưu trong **RAM** (`self._records`). Nhiều instance thì mỗi instance có sổ riêng, restart là mất, nên không bảo vệ được tiền thật.

**Cách làm:** $10/tháng/user, lưu trong Redis, reset đầu tháng.

```python
import os
from datetime import datetime, timezone
import redis

r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
MONTHLY_BUDGET_USD = 10.0
TTL_SECONDS = 32 * 24 * 3600

# Lua script: GET + so sánh + INCRBYFLOAT chạy NGUYÊN TỬ trên Redis
_CHECK_AND_ADD = r.register_script("""
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(ARGV[1])
local budget = tonumber(ARGV[2])
if current + cost > budget then
  return 0
end
redis.call('INCRBYFLOAT', KEYS[1], cost)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
""")

def _key(user_id: str) -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"budget:{user_id}:{month}"

def check_budget(user_id: str, estimated_cost: float) -> bool:
    """True nếu còn budget (và đã ghi nhận chi phí), False nếu vượt."""
    return bool(_CHECK_AND_ADD(keys=[_key(user_id)],
                               args=[estimated_cost, MONTHLY_BUDGET_USD, TTL_SECONDS]))
```

**Giải thích:**
1. **Key theo tháng** `budget:<user_id>:<YYYY-MM>`: sang tháng mới thì key khác, tự động bắt đầu từ $0, không cần cron reset. Dùng giờ **UTC** để mọi instance cùng hiểu "tháng" giống nhau.
2. **TTL 32 ngày:** key của tháng cũ tự xoá, Redis không phình mãi.
3. **Kiểm tra trước khi gọi LLM:** `current + estimated_cost > 10` thì trả `False`, endpoint trả **402 Payment Required**, không tốn tiền gọi LLM.
4. **Nguyên tử (Lua script):** lời giải mẫu trong CODE_LAB làm `GET` rồi mới `INCRBYFLOAT`, hai bước riêng. Nhiều instance cùng đọc `$9.5` rồi cùng cộng thì vượt budget (race condition). Lua script chạy trọn trên Redis, không bị chen ngang.
5. **Stateless:** state nằm ở Redis nên chạy 1 hay N instance, restart hay deploy lại thì số tiền vẫn đúng.
6. Thực tế nên ghi **chi phí ước tính trước** (giữ chỗ), sau khi LLM trả về thì điều chỉnh theo token thật (`INCRBYFLOAT` phần chênh lệch).

**Test với Redis thật** (`docker run -p 6390:6379 redis:7-alpine`):

```text
key = budget:student:2026-11
request 1: cost $3.00 -> ALLOW  spent=$3.00
request 2: cost $3.00 -> ALLOW  spent=$6.00
request 3: cost $3.00 -> ALLOW  spent=$9.00
request 4: cost $3.00 -> BLOCK (402)  spent=$9.00     # 9 + 3 > 10 → chặn, không cộng
request 5: cost $3.00 -> BLOCK (402)  spent=$9.00
TTL = 2764800 s (~32 ngày)
user khác không bị ảnh hưởng: True
race test: 50 request đồng thời x $1 -> allowed=10, spent=$10.00   # đúng 10, không vượt budget

$ redis-cli KEYS 'budget:*'
budget:teacher:2026-11
budget:student:2026-11
budget:race:2026-11
```

**Rate limit và cost guard bổ sung cho nhau:**
- Rate limit bảo vệ **tốc độ**: chống spam hoặc DoS trong ngắn hạn (10 request/phút).
- Cost guard bảo vệ **tiền**: chống tổng chi phí cộng dồn dài hạn. Một user gọi đều 10 request/phút suốt cả tháng (khoảng 432.000 request) không bao giờ bị 429, nhưng vẫn có thể đốt rất nhiều tiền; ngược lại, một vài request với prompt cực dài cũng tốn tiền dù không vượt rate limit.

### Checkpoint 4

- [x] API key authentication: `X-API-Key`; thiếu thì 401, sai thì 403, key lấy từ env để rotate được.
- [x] Hiểu JWT flow: login, ký HS256, gửi Bearer, verify chữ ký và hạn, lấy role ra để phân quyền.
- [x] Rate limiting: sliding window 10 request/phút, đã quan sát 429 kèm `Retry-After`, admin 100 request/phút.
- [x] Cost guard với Redis: $10/tháng, key theo tháng kèm TTL, Lua nguyên tử, test race 50 luồng.

---

## Part 5: Scaling & Reliability

> 5.1–5.2 chạy trong Ubuntu (WSL2) để gửi được SIGTERM thật; 5.4–5.5 chạy bằng Docker Compose (`-p k5-day14-scaling`).

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

Hai endpoint đã có sẵn trong bản develop. Phân tích:

- **`/health`, liveness probe** ("process còn sống không?"): trả 200 kèm `status`, `uptime_seconds`, `version`, `checks.memory` (đo bằng psutil, dùng > 90% thì báo `degraded`). Endpoint này **không kiểm tra dependency bên ngoài**: Redis hoặc DB chết thì restart container cũng không chữa được, chỉ gây vòng restart vô ích.
- **`/ready`, readiness probe** ("có nên gửi traffic vào không?"): trả 503 khi `_is_ready = False`, tức đang khởi động, đang shutdown, hoặc (trong bản production) Redis không ping được. Load balancer dựa vào đây để tạm bỏ instance khỏi pool **mà không restart nó**.

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:04:19.792134+00:00","checks":{"memory":{"status":"ok","used_percent":18.8}}}

$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```

Bản production (`05-scaling-reliability/production/app.py`) thì `/ready` gọi `_redis.ping()`, lỗi thì 503 `"Redis not available"`. Còn `/health` vẫn trả 200 (status `degraded`) khi mất Redis. Part 6 cũng yêu cầu đúng hành vi này.

### Exercise 5.2: Graceful shutdown

Cơ chế trong bản develop:
1. `uvicorn` bắt SIGTERM và **ngừng nhận kết nối mới** (đóng listening socket).
2. Chờ request đang chạy xong (`timeout_graceful_shutdown=30`).
3. Chạy phần shutdown của `lifespan`: đặt `_is_ready = False` để `/ready` trả 503, chờ `_in_flight_requests == 0` (tối đa 30 giây), rồi đóng kết nối.
4. Thoát với exit code 0.

`handle_sigterm` của app chỉ để log. Khi uvicorn chạy, nó tự cài handler riêng và gọi lại handler cũ sau khi tắt xong, nên dòng `Received signal 15` xuất hiện **cuối cùng** trong log.

**Test** (gửi request mất khoảng 3 giây vì mock LLM có delay, 0,5 giây sau gửi `kill -TERM`):

```text
$ curl -X POST 'http://localhost:8000/ask?question=Long%20task' &
$ kill -TERM 2288      # 0.5s sau khi gửi request
[request] {"answer":"Đây là câu trả lời từ AI agent (mock). ..."} HTTP 200  (took 3.03s)
process exited with code 0 after 2.75s from SIGTERM
$ curl http://localhost:8000/health
connection refused

--- server log
INFO:     Shutting down                                         ← nhận SIGTERM
INFO:     127.0.0.1:40210 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK   ← request đang chạy VẪN hoàn thành
INFO:     Waiting for application shutdown.
2026-11-25 15:04:22,980 INFO 🔄 Graceful shutdown initiated...
2026-11-25 15:04:22,980 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [2288]
2026-11-25 15:04:22,980 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết luận:** request gửi trước SIGTERM **hoàn thành với 200**, không bị cắt ngang. Process đợi khoảng 2,75 giây (phần còn lại của request) rồi thoát với code 0. Nếu là SIGKILL (`kill -9`) thì không bắt được, request sẽ mất. Vì vậy các nền tảng gửi SIGTERM trước, chờ một khoảng (grace period) rồi mới SIGKILL.

**Nhận xét:** `ask()` của mock là hàm đồng bộ (`time.sleep`) nhưng được gọi trong endpoint `async def`, nên **chặn event loop** trong 3 giây: trong lúc đó instance không phục vụ được request nào khác. Code thật nên dùng client async hoặc khai báo endpoint là `def` để FastAPI chạy trong threadpool.

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

Bản production đã stateless: mọi conversation history lưu trong Redis key `session:<session_id>` (JSON, `SETEX` TTL 3600 giây, giữ tối đa 20 message). Instance nào cũng đọc và ghi được session của user. Mỗi instance có `INSTANCE_ID` riêng và trả về trong `served_by` để thấy rõ request đi đâu.

**Vì sao state trong RAM hỏng khi scale:** mỗi instance là một process riêng với bộ nhớ riêng. Turn 1 của user A vào instance 1 thì history nằm trong RAM của instance 1; turn 2 bị load balancer đưa sang instance 2 thì không thấy history, agent "mất trí nhớ". Thêm vào đó, restart hoặc deploy là mất toàn bộ state, và scale down thì mất state của instance bị xoá.

**Lưu ý:** code có fallback sang `_memory_store` khi không kết nối được Redis lúc **khởi động**. Fallback này che giấu lỗi: chạy nhiều instance mà Redis lỗi thì mỗi instance lặng lẽ dùng RAM riêng và state lại bị chia nhỏ. Production nên fail fast (`/ready` trả 503) thay vì fallback.

### Exercise 5.4: Load balancing (Nginx + 3 instance)

```bash
cd 05-scaling-reliability/production
touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

```text
$ docker compose -p k5-day14-scaling ps
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 8 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-2   Up 8 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-3   Up 8 seconds (healthy)    8000/tcp
k5-day14-scaling-nginx-1   Up 8 seconds              0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 19 seconds (healthy)   6379/tcp
```

**10 request** (`POST http://localhost:8080/chat`):

```text
Request 1 -> served_by instance-de1e61 | storage redis
Request 2 -> served_by instance-8becbc | storage redis
Request 3 -> served_by instance-77c151 | storage redis
Request 4 -> served_by instance-de1e61 | storage redis
Request 5 -> served_by instance-8becbc | storage redis
Request 6 -> served_by instance-77c151 | storage redis
Request 7 -> served_by instance-de1e61 | storage redis
Request 8 -> served_by instance-8becbc | storage redis
Request 9 -> served_by instance-77c151 | storage redis
Request 10 -> served_by instance-de1e61 | storage redis

# header X-Served-By (nginx thêm $upstream_addr):
X-Served-By: 172.20.0.3:8000
X-Served-By: 172.20.0.4:8000
X-Served-By: 172.20.0.5:8000
X-Served-By: 172.20.0.3:8000 ...

# docker compose logs agent | grep "POST /chat" (đếm theo container):
      3 agent-1
      4 agent-2
      3 agent-3
```

Nginx phân tải **round-robin** đều cho 3 instance. Docker DNS phân giải `agent` thành 3 IP, và upstream `agent_cluster` xoay vòng qua các IP đó.

**Một instance chết:** `docker stop k5-day14-scaling-agent-1` giữa một session đang chạy:

```text
$ docker stop k5-day14-scaling-agent-1
HTTP 200 served_by instance-8becbc turn 7
HTTP 200 served_by instance-de1e61 turn 8
HTTP 200 served_by instance-8becbc turn 9
HTTP 200 served_by instance-de1e61 turn 10
history count: 18
```

Traffic tự chuyển sang 2 instance còn lại, **không có request lỗi** (nhờ `proxy_next_upstream error timeout http_503` + `proxy_next_upstream_tries 3`: nginx thử lại sang upstream khác khi gặp lỗi kết nối hoặc 503). Session vẫn tiếp tục: 10 message cũ + 8 message mới = 18.

### Exercise 5.5: Test stateless (`python test_stateless.py`)

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: d8b18e36-97f2-4391-ace1-e0cb6ae62c36

Request 1: [instance-8becbc]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...
Request 2: [instance-77c151]
  Q: Why do we need containers?
Request 3: [instance-de1e61]
  Q: What is Kubernetes?
Request 4: [instance-8becbc]
  Q: How does load balancing work?
Request 5: [instance-77c151]
  Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-8becbc', 'instance-77c151', 'instance-de1e61'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ... (5 cặp user/assistant)
✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 câu hỏi trong **cùng một session** được xử lý bởi **cả 3 instance** khác nhau (xoay vòng), nhưng history đọc lại có đủ **10 message** (5 user + 5 assistant) theo đúng thứ tự. Không instance nào giữ history trong RAM: mỗi request đọc session từ Redis, thêm message, rồi ghi lại. Nếu lưu trong dict của process thì mỗi instance chỉ thấy khoảng 1/3 cuộc hội thoại. Script không tự tắt instance; phần kill instance mình làm thêm ở 5.4 cho thấy session vẫn tiếp tục khi một instance chết.

**Bug nhỏ phát hiện:** trường `turn` bị lệch +1. `append_to_history` đã thêm câu hỏi hiện tại vào history trước khi đếm, rồi code còn `+ 1`. Sau 5 turn thì request tiếp theo (turn 6) báo `turn 7`. Ngoài ra `append_to_history` làm **đọc, sửa, ghi** không nguyên tử: hai request cùng session tới hai instance cùng lúc có thể ghi đè nhau. Nên dùng `RPUSH` + `LTRIM` trên Redis list.

```bash
docker compose -p k5-day14-scaling down
```

### Checkpoint 5

- [x] Health và readiness: `/health` (liveness, không phụ thuộc Redis), `/ready` (503 khi chưa sẵn sàng hoặc mất Redis).
- [x] Graceful shutdown: SIGTERM giữa request mà request vẫn trả 200, process thoát với code 0.
- [x] Stateless: session trong Redis, hiểu vì sao state trong RAM hỏng khi scale.
- [x] Load balancing với Nginx: round-robin 3 instance, failover khi tắt 1 instance.
- [x] Test stateless: 5 request qua 3 instance, history đủ 10 message.

---

## Part 6: Final Project: Output `check_production_ready.py`

Chạy đầy đủ (có Docker) trong Ubuntu WSL2 (`os.name == "posix"`, gửi được SIGTERM), thư mục `06-lab-complete/`:

```text
$ python check_production_ready.py

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
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số dòng chi tiết từ cùng lần chạy:

```text
✅ Docker: image < 500 MB — 273 MB
✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)
✅ Khi chạy: hết budget → 402 — 402 ở request thứ 2
✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 15 dòng JSON
✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.6s
```

### Thiết kế

| File | Nội dung |
|---|---|
| `app/config.py` | Dataclass `Settings` đọc toàn bộ từ env (`PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`). `AGENT_API_KEY` **không có giá trị mặc định**; `validate()` fail fast nếu `ENVIRONMENT=production` mà thiếu key |
| `app/auth.py` | `APIKeyHeader("X-API-Key")`. Thiếu hoặc sai key trả **401**, so sánh bằng `secrets.compare_digest` (chống timing attack). Trả về `client_id` = 16 ký tự đầu SHA-256 của key, nên Redis và log **không bao giờ chứa key gốc** |
| `app/redis_client.py` | `redis.from_url(..., socket_connect_timeout=1)`, không ping lúc import, nên app khởi động được khi chưa có Redis. `redis_healthy()` dùng cho `/ready` |
| `app/rate_limiter.py` | Sliding window log trên **Redis sorted set**, chạy bằng **Lua script nguyên tử** (ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE). Vượt giới hạn trả **429** kèm `Retry-After`, `X-RateLimit-*`. Request bị chặn không được ghi vào window. Dùng chung giữa 2 worker và nhiều instance, còn nguyên sau restart |
| `app/cost_guard.py` | Chi phí tính theo token (giá gpt-4o-mini), lưu `INCRBYFLOAT` vào 2 key Redis theo client: `cost:<client>:day:<YYYY-MM-DD>` và `cost:<client>:month:<YYYY-MM>` (có TTL, sang kỳ mới thì tự reset). `check_budget()` trước khi gọi LLM, đã chi ≥ budget thì trả **402**. Mặc định $10/tháng |
| `app/main.py` | `JsonFormatter`: mỗi dòng log là 1 JSON (`ts`, `lvl`, `event`, các field). Middleware log mọi request (method, path, status, ms), không log nội dung câu hỏi. `/health` luôn 200; `/ready` trả 503 khi Redis chết hoặc đang shutdown. Thứ tự trong `/ask`: auth → rate limit → cost guard → LLM → `record_cost`. Exception handler: 422 gọn gàng, Redis lỗi trả 503, lỗi khác trả 500 `{"error": "Internal server error"}` (**không lộ stack trace**). `lifespan` lo shutdown: `ready=False`, chờ in-flight, đóng Redis |
| `Dockerfile` | 2 stage `python:3.11-slim`: builder tạo `/opt/venv`, runtime chỉ copy venv + `app/` + `utils/`. User `app` (non-root), có `HEALTHCHECK`, `CMD sh -c "exec uvicorn ... --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"`: `exec` để uvicorn là PID 1 và nhận SIGTERM. Image **273 MB** |
| `docker-compose.yml` | `agent` (build, port 8000, `env_file: .env` với `required: false`, `REDIS_URL=redis://redis:6379/0`, `depends_on: redis` healthy) + `redis:7-alpine` (AOF, volume, healthcheck) |
| `.dockerignore` | `.env`, `.env.*` (giữ `.env.example`), `__pycache__`, `venv`, `.git`, `*.md`, `benchmark-observability/`, `check_production_ready.py` |
| `railway.toml` / `render.yaml` | Xem so sánh ở Part 3 |

### Test thêm bằng `docker compose` (`-p k5-day14-final`)

```text
$ curl -i /health                 → 200 {"status":"ok","version":"1.0.0","environment":"staging",...}
$ curl -i /ready                  → 200 {"ready":true,"redis":"ok"}
$ /ask không key                  → 401 {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
$ /ask sai key                    → 401 {"detail":"Invalid API key."}
$ /ask đúng key                   → 200 {"question":"What is deployment?","answer":"Deployment là quá trình ...","usage":{"input_tokens":4,"output_tokens":19,"cost_usd":1.2e-05,"rate_limit_remaining":9}}
$ /ask body {}                    → 422 {"error":"Invalid request","details":[{"field":"question","msg":"Field required"}]}
$ /ask question 3000 ký tự        → 422 {"error":"Invalid request","details":[{"field":"question","msg":"String should have at most 2000 characters"}]}
# rate limit 10/phút:             200 200 200 200 200 200 200 200 200 429 429 429
#                                 429 + retry-after: 59
# Redis keys (không chứa API key gốc):
cost:818fa346bfb33313:month:2026-11
cost:818fa346bfb33313:day:2026-11-25
ratelimit:818fa346bfb33313
# docker compose stop redis:      /health 200 · /ready 503 {"ready":false,"reason":"redis unavailable"}
#                                 /ask 503 {"error":"Service temporarily unavailable (state store down)"}
# Redis lên lại:                  /ready 200
# docker compose stop agent:      dừng trong 0.83s, exit code 0
```

Log agent (mỗi dòng 1 JSON):

```json
{"ts": "2026-11-25T08:11:40.270+00:00", "lvl": "INFO", "logger": "agent", "event": "request", "method": "POST", "path": "/ask", "status": 429, "ms": 1.5}
{"ts": "2026-11-25T08:11:44.871+00:00", "lvl": "ERROR", "logger": "agent", "event": "redis_unavailable", "path": "/ask", "error": "ConnectionError"}
{"ts": "2026-11-25T08:11:48.755+00:00", "lvl": "INFO", "logger": "agent", "event": "shutdown_complete", "uptime_seconds": 10.0}
```

---

## AI Log

| Phần | Công cụ AI | Đã dùng để làm gì |
|---|---|---|
| Part 1 | Claude Code | Chạy bản develop và production, thu output curl, soạn bảng so sánh. Học viên đã đọc lại và kiểm tra |
| Part 2 | Claude Code | Build 2 image, đo dung lượng, chạy compose stack, thu output và soạn câu trả lời. Học viên đã đọc lại và kiểm tra |
| Part 4 | Claude Code | Viết script test 401/403/200/429, viết và test cost guard Redis (Lua), soạn câu trả lời. Học viên đã đọc lại và kiểm tra |
| Part 5 | Claude Code | Chạy test health/ready, graceful shutdown (SIGTERM trong WSL), stack 3 instance, failover, test_stateless; soạn câu trả lời. Học viên đã đọc lại và kiểm tra |
| Part 3 | Claude Code | Soạn bảng so sánh `railway.toml` / `render.yaml` và mô tả pipeline Cloud Run. Học viên deploy và kiểm tra URL |
| Part 6 | Claude Code | Viết code các TODO trong `06-lab-complete/` (config, auth, Redis, rate limiter Lua, cost guard, log JSON, graceful shutdown, Dockerfile, compose, railway/render), chạy `check_production_ready.py` tới PASS 12/12. Học viên đã đọc hiểu code |
| Part 7 | Claude Code | Chạy load test, eval, sửa `KNOWLEDGE_BASE`, sửa lỗi `PYTHONUSERBASE` trong Dockerfile stack observability, chạy Locust scale 1/3, script thí nghiệm A–E đo thời gian alert, truy vấn Jaeger API; soạn `BENCHMARK_REPORT.md`. Học viên chụp ảnh màn hình |
