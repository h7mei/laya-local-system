# Laya Local System One

Local HTTP service for [Laya](https://pypi.org/project/laya/) (`choice` / `score` / `noul` decisions) with a web UI at `/` and the Jev-compatible `POST /v1/systemone` API.

Guide: [Laya Local System One](https://laplusda.com/en/posts/laya-local-system-one-model-guide/)

## Requirements

- Python 3.10+ (this machine has 3.12)
- Disk space for checkpoints under `.cache/huggingface` (english + multilingual)
- Optional NVIDIA GPU: CUDA-capable driver + CUDA PyTorch wheel (see GPU setup below)

## Setup

### Windows (PowerShell)

```powershell
cd C:\Users\User\Documents\AAXX\code\laya-local-system
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\setup-gpu.ps1   # installs CUDA torch; skip on CPU-only machines
.\.venv\Scripts\python.exe -I -c "import laya, torch; print(laya.__version__, torch.cuda.is_available())"
Copy-Item .env.example .env
```

### Linux / macOS

```bash
cd /path/to/laya-local-system
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# NVIDIA GPU (Linux):
.venv/bin/python -m pip uninstall -y torch
.venv/bin/python -m pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv/bin/python -I -c "import laya, torch; print(laya.__version__, torch.cuda.is_available())"
cp .env.example .env
chmod +x scripts/serve.sh
```

`.env` defaults to `LAYA_DEVICE=auto` (CUDA when available) and `LAYA_PRELOAD=1`. Set `LAYA_DEVICE=cpu` to force CPU. Optional: set `HF_TOKEN` for higher Hub rate limits. After a successful download you can set `HF_HUB_OFFLINE=1` to block network fetches at runtime.

### GPU setup (NVIDIA)

Plain `pip install torch` from PyPI is **CPU-only**. This repo ships `scripts/setup-gpu.ps1` which installs `torch==2.11.0+cu128` (works with driver CUDA 12.x, including RTX 50-series). Confirm with:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a')"
```

Expect `True` and your GPU name (e.g. `NVIDIA GeForce RTX 5060 Ti`). Then restart the server — startup logs should show `device=cuda, gpu=...`.

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

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the request builder UI, [http://127.0.0.1:8000/api](http://127.0.0.1:8000/api) for API integration docs / key + ngrok controls, or [http://127.0.0.1:8000/monitor](http://127.0.0.1:8000/monitor) for usage stats (SQLite-backed request log).

Defaults (override in `.env`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `LAYA_HOST` | `127.0.0.1` | Bind address |
| `LAYA_PORT` | `8000` | Port |
| `LAYA_DEVICE` | `auto` | `auto` → CUDA if available, else CPU; or set `cuda` / `cpu` |
| `LAYA_PRELOAD` | `1` | Load checkpoints at startup (recommended on GPU) |
| `LAYA_MODELS` | `english,multilingual` | Checkpoints checked (and downloaded if missing) before serve |
| `HF_HOME` | `.cache/huggingface` | Local model cache |
| `LAYA_API_KEY` | _(unset)_ | If set, require `Authorization: Bearer` on predict |
| `NGROK_AUTHTOKEN` | _(unset)_ | ngrok token for public tunnels |
| `LAYA_NGROK` | `0` | Set `1` to auto-start ngrok when the server boots |
| `LAYA_USAGE_DB` | `data/usage.sqlite` | SQLite file for `/monitor` usage stats |

## Public URL (ngrok)

1. Open [http://127.0.0.1:8000/api](http://127.0.0.1:8000/api) → **Keys (SQLite)**.
2. Click **Generate** for an API key (recommended before tunneling).
3. Paste your ngrok authtoken from the [ngrok dashboard](https://dashboard.ngrok.com/get-started/your-authtoken) and **Save token**.
4. Click **Start ngrok**, or set `LAYA_NGROK=1` in `.env` and restart the server.

Keys are stored in `data/usage.sqlite` (same DB as usage stats). `.env` values for `LAYA_API_KEY` / `NGROK_AUTHTOKEN` are imported once if the DB rows are empty.
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
- `GET /api` — API integration guide + keys + ngrok controls
- `GET /monitor` — usage monitor (totals, by day/model, recent requests)
- `GET /health` — process status and loaded checkpoints
- `GET /v1/integration` — local/public base URL and tunnel status
- `GET /v1/keys` — masked API key / ngrok token status
- `POST /v1/keys/api-key/generate` — generate API key into SQLite
- `PUT /v1/keys/api-key` — set API key
- `DELETE /v1/keys/api-key` — clear API key
- `PUT /v1/keys/ngrok-token` — set ngrok authtoken
- `DELETE /v1/keys/ngrok-token` — clear ngrok authtoken
- `GET /v1/usage` — SQLite usage aggregates + recent rows
- `POST /v1/usage/clear` — wipe usage log (uses API key when set)
- `POST /v1/tunnel/start` — open ngrok tunnel
- `POST /v1/tunnel/stop` — close ngrok tunnel
- `POST /v1/systemone` — decide over `state` + typed `questions`
