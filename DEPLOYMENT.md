# Deployment Information

> Agent được deploy là agent Part 6 trong `06-lab-complete/` (đạt `PASS 12/12`).

## Public URL

https://k5-l3a-day14-maivanthanh-2a202603696-deployment-production.up.railway.app

## Platform

**Railway**, deploy từ GitHub repo (nhánh `main`):

- Service agent: Root Directory = `06-lab-complete`, Config file = `/06-lab-complete/railway.toml` (builder `DOCKERFILE`, `healthcheckPath = "/health"`); build từ `06-lab-complete/Dockerfile` (multi-stage, `python:3.11-slim`, non-root)
- Service Redis: Railway Redis (state của rate limit + cost guard); agent nối qua `REDIS_URL=${{Redis.REDIS_URL}}`
- Health check của nền tảng: `GET /health`

**Lỗi gặp khi deploy và cách sửa:** lần build đầu fail sau khoảng 16 giây vì Railway build ở gốc repo, nơi có một `Dockerfile` mẫu dành cho app Go của đề (`go build` không tìm thấy code). Đã sửa bằng cách đặt Root Directory = `06-lab-complete` và đường dẫn config `/06-lab-complete/railway.toml`. File config của Railway tính đường dẫn từ gốc repo, không theo Root Directory.

## Test Commands

Đặt biến trước khi chạy (không ghi key thật vào file này):

```bash
BASE=https://k5-l3a-day14-maivanthanh-2a202603696-deployment-production.up.railway.app
AGENT_API_KEY=<key đã đặt trên Railway>
```

### 4 lệnh tự kiểm (CP6) — chỉ in mã HTTP

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả (2026-11-25):

```text
200
200
401
200
```

(Dòng 4 dùng key thật đặt trong biến môi trường `$env:AGENT_API_KEY` của terminal, key không hiện ra. Ảnh: [screenshots/test.png](screenshots/test.png).)

Chi tiết từng endpoint:

```text
$ curl $BASE/health
{"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":142.2,"timestamp":"2026-11-25T08:56:22.137261+00:00"}  -> HTTP 200

$ curl $BASE/ready
{"ready":true,"redis":"ok"}  -> HTTP 200                       # Redis trên Railway đã kết nối

$ curl -X POST $BASE/ask -H 'Content-Type: application/json' -d '{"question":"Hello"}'
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}  -> HTTP 401

$ curl -X POST $BASE/ask -H 'X-API-Key: wrong-key' -H 'Content-Type: application/json' -d '{"question":"Hello"}'
{"detail":"Invalid API key."}  -> HTTP 401
```

Script chấm:

```text
$ python check_production_ready.py --static-only --public-url https://k5-l3a-day14-maivanthanh-2a202603696-deployment-production.up.railway.app
✅ 12. Public URL ready (Railway / Render config)
     ✅ Public URL: GET https://k5-l3a-day14-maivanthanh-2a202603696-deployment-production.up.railway.app/health → 200
```

### Health Check

```bash
curl "$BASE/health"
# {"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":...,"timestamp":"..."}
```

### API Test (with authentication)

```bash
curl -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# 200 {"question":"What is deployment?","answer":"Deployment là quá trình ...","usage":{...}}
```

### Rate limit (10 req/phút)

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" \
    -H "X-API-Key: $AGENT_API_KEY" -H 'Content-Type: application/json' -d '{"question":"test"}'
done; echo
# 200 ×10 rồi 429
```

### Kiểm tra bằng script chấm

```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

## Environment Variables Set

Đặt trên nền tảng (Variables / Environment), **không** ghi trong code hay Git:

| Biến | Giá trị |
|---|---|
| `PORT` | do nền tảng tự cấp |
| `ENVIRONMENT` | `production` |
| `AGENT_API_KEY` | secret ngẫu nhiên (`openssl rand -hex 32`, hoặc Render `generateValue`) |
| `REDIS_URL` | tham chiếu tới Redis của nền tảng (Railway: `${{Redis.REDIS_URL}}`) |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `MONTHLY_BUDGET_USD` | `10` |
| `DAILY_BUDGET_USD` | `0` (không giới hạn theo ngày) |
| `LOG_LEVEL` | `INFO` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
