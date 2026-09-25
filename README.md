# Laya Local System One

Local HTTP service for [Laya](https://pypi.org/project/laya/) (`choice` / `score` / `noul` decisions) with a web UI at `/` and the Jev-compatible `POST /v1/systemone` API.

Guide: [Laya Local System One](https://laplusda.com/en/posts/laya-local-system-one-model-guide/)

## Requirements

- Python 3.10+ (this machine has 3.12)
- Disk space for checkpoints under `.cache/huggingface` (english + multilingual)

## Setup

### Windows (PowerShell)

```powershell
cd C:\Users\User\Documents\AAXX\code\laya-local-system
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -I -c "import laya; print(laya.__version__)"
Copy-Item .env.example .env
```

### Linux / macOS

```bash
cd /path/to/laya-local-system
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -I -c "import laya; print(laya.__version__)"
cp .env.example .env
chmod +x scripts/serve.sh
```

Optional: set `LAYA_DEVICE=cuda` in `.env` if you have an NVIDIA GPU. Optional: set `HF_TOKEN` for higher Hub rate limits during download. After a successful download you can set `HF_HUB_OFFLINE=1` in `.env` to block network fetches at runtime.

## Start the server

One script (`scripts/serve.py`) loads `.env`, checks the model cache, downloads anything missing, then starts the server. Use the thin wrapper for your OS:

**Windows**

```powershell
.\scripts\serve.ps1
```

**Linux / macOS**

```bash
./scripts/serve.sh
```

Optional flags (same on both):

```text
--download-only   ensure models are cached, then exit
--check-only      verify cache only; exit 1 if incomplete
--models english,multilingual
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the request builder UI, or [http://127.0.0.1:8000/api](http://127.0.0.1:8000/api) for API integration docs, copyable snippets, and ngrok controls.

Defaults (override in `.env`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `LAYA_HOST` | `127.0.0.1` | Bind address |
| `LAYA_PORT` | `8000` | Port |
| `LAYA_DEVICE` | `cpu` | Torch device |
| `LAYA_PRELOAD` | `0` | Lazy-load into RAM (files must already be cached) |
| `LAYA_MODELS` | `english,multilingual` | Checkpoints checked (and downloaded if missing) before serve |
| `HF_HOME` | `.cache/huggingface` | Local model cache |
| `LAYA_API_KEY` | _(unset)_ | If set, require `Authorization: Bearer` on predict |
| `NGROK_AUTHTOKEN` | _(unset)_ | ngrok token for public tunnels |
| `LAYA_NGROK` | `0` | Set `1` to auto-start ngrok when the server boots |

## Public URL (ngrok)

1. Get a token from [ngrok dashboard](https://dashboard.ngrok.com/get-started/your-authtoken).
2. Add to `.env`: `NGROK_AUTHTOKEN=...` and optionally `LAYA_NGROK=1`.
3. Restart the server, or open `/api` and click **Start ngrok**.

`GET /v1/integration` returns the local and public base URLs for clients.
## Health check

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

```bash
curl -s http://127.0.0.1:8000/health
```

Expect `status: ok`. With preload off, `loaded` is empty until the first predict (load from local cache only).

## Sample predict

**Windows (PowerShell)**

```powershell
$body = @{
  state = @{
    subject = "Duplicate charge"
    body = "I was charged twice and want a refund today."
  }
  questions = @{
    department = @{
      type = "choice"
      instructions = "Which team should handle this ticket?"
      criteria = @{
        billing = "Payments, invoices, and refunds"
        support = "Product help and bugs"
        sales = "New purchases and upgrades"
      }
    }
    refund_requested = @{
      type = "noul"
      instructions = "Does the customer explicitly request a refund?"
    }
  }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod http://127.0.0.1:8000/v1/systemone -Method Post -ContentType "application/json" -Body $body
```

**Linux / macOS**

```bash
curl -s http://127.0.0.1:8000/v1/systemone \
  -H 'Content-Type: application/json' \
  -d '{
    "state": {
      "subject": "Duplicate charge",
      "body": "I was charged twice and want a refund today."
    },
    "questions": {
      "department": {
        "type": "choice",
        "instructions": "Which team should handle this ticket?",
        "criteria": {
          "billing": "Payments, invoices, and refunds",
          "support": "Product help and bugs",
          "sales": "New purchases and upgrades"
        }
      },
      "refund_requested": {
        "type": "noul",
        "instructions": "Does the customer explicitly request a refund?"
      }
    }
  }'
```

## Endpoints

- `GET /` — playground UI
- `GET /api` — API integration guide + ngrok controls
- `GET /health` — process status and loaded checkpoints
- `GET /v1/integration` — local/public base URL and tunnel status
- `POST /v1/tunnel/start` — open ngrok tunnel
- `POST /v1/tunnel/stop` — close ngrok tunnel
- `POST /v1/systemone` — decide over `state` + typed `questions`
