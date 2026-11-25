# Deployment Information

> Agent được deploy là agent Part 6 trong `06-lab-complete/` (đạt `PASS 12/12`).

## Public URL

TODO: https://<your-agent>.up.railway.app

## Platform

TODO: Railway (cấu hình: `06-lab-complete/railway.toml`) — hoặc Render (`06-lab-complete/render.yaml`)

- Service agent: build từ `06-lab-complete/Dockerfile` (multi-stage, `python:3.11-slim`, non-root, 273 MB)
- Service Redis: Redis của nền tảng (rate limit + cost guard)
- Health check của nền tảng: `GET /health`

## Test Commands

Đặt biến trước khi chạy (không ghi key thật vào file này):

```bash
BASE=https://<your-agent>.up.railway.app
AGENT_API_KEY=<key đã đặt trên nền tảng>
```

### 4 lệnh tự kiểm (CP6) — chỉ in mã HTTP

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả:

```text
TODO: dán output (4 dòng: 200 / 200 / 401 / 200)
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
