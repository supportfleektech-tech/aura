import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import urllib.request


ASSETS = {
    "kokoro-v1.0.int8.onnx": (114119327, "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c"),
    "voices-v1.0.bin": (28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}
BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"


def download_asset(path: Path, url: str, size: int, digest: str) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Refusing symlink asset: {path.name}")
    if path.exists():
        with path.open("rb") as src:
            valid = path.stat().st_size == size and hashlib.file_digest(src, "sha256").hexdigest() == digest
        if not valid:
            raise RuntimeError(f"Invalid existing {path.name}; move it aside explicitly before retrying")
        print(f"Verified existing {path.name}: {size} bytes")
        return
    if not url.startswith(BASE_URL):
        raise RuntimeError("Only the kokoro-onnx official release URL is allowed")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".kokoro-", delete=False) as out:
            tmp = Path(out.name)
            sha = hashlib.sha256()
            count = 0
            with urllib.request.urlopen(url, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > size:
                        raise RuntimeError("Downloaded asset exceeds expected size")
                    sha.update(chunk)
                    out.write(chunk)
            if count != size or sha.hexdigest() != digest:
                raise RuntimeError("Downloaded asset size/checksum mismatch")
        os.link(tmp, path)
        print(f"Downloaded {path.name}: {size} bytes, SHA256 {digest}")
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit one-time Kokoro CPU model download (Apache-2.0 weights; MIT runtime). No runtime downloads.")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("AURA_DATA_DIR", Path(__file__).resolve().parents[1] / "data")))
    args = parser.parse_args()
    root = args.data_dir.resolve()
    dest = root / "models" / "kokoro"
    try:
        if dest.resolve() != dest:
            raise RuntimeError("Model path must not contain symlinks")
        dest.mkdir(parents=True, exist_ok=True)
        print("Kokoro v1.0 INT8 + voices: 142333725 bytes; model license Apache-2.0, kokoro-onnx MIT.")
        for name, (size, digest) in ASSETS.items():
            download_asset(dest / name, BASE_URL + name, size, digest)
    except Exception as exc:
        print(f"Kokoro setup failed: {exc}. No runtime network fallback is enabled.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
