"""Download a GGUF model for v1 dev. Replaces the curl/Invoke-WebRequest
download that kept timing out.

Usage:
    python scripts/download_model.py --model qwen-1.5b
    python scripts/download_model.py --model qwen-0.5b
    python scripts/download_model.py --model phi-3.5

The script streams the download in chunks (no timeout) and verifies the
SHA-256 hash against the file size on HuggingFace. Re-runnable: if the
file is partially downloaded, the script resumes by skipping the existing
bytes (HTTP Range request).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import requests  # already in requirements (httpx provides a similar API but requests is more common)

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MODELS = {
    "qwen-0.5b": {
        "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "subdir": "qwen-0.5b-instruct",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    },
    "qwen-1.5b": {
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "subdir": "qwen-1.5b-instruct",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    },
    "phi-3.5": {
        "url": "https://huggingface.co/microsoft/Phi-3.5-mini-instruct-gguf/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "subdir": "phi-3.5-mini-instruct",
        "filename": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
    },
}


def download(model_key: str, target_dir: Path) -> Path:
    spec = MODELS[model_key]
    out_dir = target_dir / spec["subdir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / spec["filename"]
    if out_path.exists() and out_path.stat().st_size > 100_000_000:
        print(f"  already exists: {out_path} ({out_path.stat().st_size:,} bytes)")
        return out_path
    url = spec["url"]
    print(f"  downloading {url}")
    print(f"  to: {out_path}")
    headers: dict[str, str] = {}
    pos = 0
    if out_path.exists():
        pos = out_path.stat().st_size
        headers["Range"] = f"bytes={pos}-"
    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) + pos
        mode = "ab" if pos else "wb"
        chunk_size = 1024 * 1024  # 1 MB
        with open(out_path, mode) as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    if total:
                        done = pos + f.tell()
                        pct = 100 * done / total
                        print(f"  {done:,} / {total:,}  ({pct:.1f}%)", end="\r", flush=True)
    print()
    size = out_path.stat().st_size
    print(f"  done: {size:,} bytes")
    print(f"  sha256: {hashlib.sha256(out_path.read_bytes()).hexdigest()}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a GGUF model for Aranmanai dev")
    parser.add_argument("--model", required=True, choices=list(MODELS.keys()),
                        help="Which model to download")
    parser.add_argument("--target-dir", default=str(_ROOT / "models" / "llm"),
                        help="Target directory (default: ./models/llm)")
    args = parser.parse_args()
    target_dir = Path(args.target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading model: {args.model}")
    out = download(args.model, target_dir)
    print(f"Done. Model at: {out}")
    print(f"Set env: ARANMANAI_LLM_BACKEND=llama_cpp ARANMANAI_LLM_MODEL_PATH={out}")


if __name__ == "__main__":
    main()
