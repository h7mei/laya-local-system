"""One entry point for Laya Local System One.

Loads `.env`, ensures checkpoints are cached (downloads only what is missing),
then starts the HTTP server. Works on Windows and Linux via the thin wrappers
``serve.ps1`` / ``serve.sh``, or directly:

    .venv/Scripts/python scripts/serve.py          # Windows
    .venv/bin/python scripts/serve.py              # Linux

Flags:
    --download-only   ensure models, then exit (no server)
    --check-only      verify cache only; exit 1 if anything is missing
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / ".cache" / "huggingface"
DEFAULT_MODELS = ("english", "multilingual")
REQUIRED = (
    "rl_agent_config.json",
    "model.safetensors",
)

DEFAULT_ENV = {
    "LAYA_HOST": "127.0.0.1",
    "LAYA_PORT": "8000",
    # auto = cuda when torch.cuda.is_available(), else cpu
    "LAYA_DEVICE": "auto",
    "LAYA_PRELOAD": "1",
    "LAYA_MODELS": ",".join(DEFAULT_MODELS),
}


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            os.environ[name] = value


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _resolve_device(raw: str | None) -> str:
    """Map LAYA_DEVICE to a concrete torch device string."""
    value = (raw or "auto").strip().lower() or "auto"
    if value in {"auto", "gpu"}:
        return "cuda" if _cuda_available() else "cpu"
    if value in {"cuda", "cuda:0"}:
        if not _cuda_available():
            print(
                "WARNING: LAYA_DEVICE=cuda but torch.cuda.is_available() is False "
                "(CPU-only torch wheel or missing NVIDIA driver). Falling back to cpu.\n"
                "Fix: run .\\scripts\\setup-gpu.ps1 (Windows) or install "
                "torch from https://download.pytorch.org/whl/cu128",
                file=sys.stderr,
            )
            return "cpu"
        return value
    return value


def _apply_defaults() -> None:
    for key, value in DEFAULT_ENV.items():
        os.environ.setdefault(key, value)

    os.environ["LAYA_DEVICE"] = _resolve_device(os.environ.get("LAYA_DEVICE"))

    hf_home = os.environ.get("HF_HOME") or str(DEFAULT_CACHE)
    hf_path = Path(hf_home)
    if not hf_path.is_absolute():
        hf_path = ROOT / hf_path
    hf_path.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_path)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def _patterns(subfolder: str | None) -> list[str]:
    prefix = f"{subfolder}/" if subfolder else ""
    return [
        prefix + name
        for name in (
            "rl_agent_config.json",
            "model.safetensors",
            "tokenizer/*",
            "encoder/*",
        )
    ]


def _checkpoint_ready(model_dir: Path) -> bool:
    if not all((model_dir / name).is_file() for name in REQUIRED):
        return False
    return (model_dir / "encoder" / "config.json").is_file() and (model_dir / "tokenizer").is_dir()


def _parse_models(raw: str | None) -> tuple[str, ...]:
    text = raw if raw is not None else os.environ.get("LAYA_MODELS", ",".join(DEFAULT_MODELS))
    names = tuple(n.strip() for n in text.split(",") if n.strip())
    if not names:
        raise SystemExit("No models specified.")
    return names


def verify(names: tuple[str, ...]) -> list[str]:
    """Return model keys missing from the Hub cache."""
    from huggingface_hub import snapshot_download
    from laya.router import DEFAULT_MODELS as LAYA_MODELS
    from laya.router import normalise_name

    missing: list[str] = []
    for name in names:
        key = normalise_name(name)
        repo, sub = LAYA_MODELS[key]
        try:
            root = Path(
                snapshot_download(
                    repo,
                    local_files_only=True,
                    allow_patterns=_patterns(sub),
                )
            )
        except Exception:
            missing.append(key)
            continue
        model_dir = root / sub if sub else root
        if not _checkpoint_ready(model_dir):
            missing.append(key)
    return missing


def download(names: tuple[str, ...]) -> None:
    from huggingface_hub import snapshot_download
    from laya.router import DEFAULT_MODELS as LAYA_MODELS
    from laya.router import normalise_name

    print("Downloading into cache:", ", ".join(names))
    print("HF_HOME =", os.environ["HF_HOME"])
    for name in names:
        key = normalise_name(name)
        repo, sub = LAYA_MODELS[key]
        print(f"\n==> {key} ({repo}" + (f"/{sub}" if sub else "") + ")")
        path = snapshot_download(repo, allow_patterns=_patterns(sub))
        model_dir = Path(path) / sub if sub else Path(path)
        if not _checkpoint_ready(model_dir):
            raise RuntimeError(f"Download finished but {key} is incomplete under {model_dir}")
        size_mb = (model_dir / "model.safetensors").stat().st_size / (1024 * 1024)
        print(f"OK {key}: {model_dir} ({size_mb:.0f} MB weights)")


def ensure_models(names: tuple[str, ...], *, check_only: bool = False) -> int:
    print(f"Checking local checkpoints ({', '.join(names)}) in {os.environ['HF_HOME']} ...")
    missing = verify(names)
    if not missing:
        print("Ready:", ", ".join(names))
        return 0
    if check_only:
        print("Missing checkpoints:", ", ".join(missing))
        return 1

    print("Need download:", ", ".join(missing))
    download(tuple(missing))
    missing = verify(names)
    if missing:
        print("Still missing after download:", ", ".join(missing), file=sys.stderr)
        return 1
    print("Ready:", ", ".join(names))
    return 0


def start_server() -> None:
    host = os.environ["LAYA_HOST"]
    port = os.environ["LAYA_PORT"]
    device = os.environ["LAYA_DEVICE"]
    preload = os.environ["LAYA_PRELOAD"]
    gpu_note = ""
    if device.startswith("cuda") and _cuda_available():
        try:
            import torch

            name = torch.cuda.get_device_name(0)
            gpu_note = f", gpu={name}"
        except Exception:
            gpu_note = ""
    print(
        f"Starting Laya UI on http://{host}:{port} "
        f"(device={device}{gpu_note}, preload={preload})"
    )
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.server import main as server_main

    server_main()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        default=None,
        help="Comma list: english,multilingual,typed-decisions (default: LAYA_MODELS / english,multilingual)",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Ensure models are cached, then exit without starting the server",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify cache; exit 1 if anything is missing",
    )
    args = parser.parse_args(argv)

    os.chdir(ROOT)
    _load_dotenv(ROOT / ".env")
    _apply_defaults()
    names = _parse_models(args.models)

    code = ensure_models(names, check_only=args.check_only)
    if code != 0 or args.check_only or args.download_only:
        return code

    start_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
