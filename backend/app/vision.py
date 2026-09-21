"""Image understanding (v1.6.0 WS6, roadmap §19.2).

`analyze_image` follows the privacy-ordered chain: local Ollama vision model
first, cloud vision (any OpenAI-compatible `image_url` endpoint) second, and
an honest off-state when neither is reachable — never a fabricated
description. Derived text lands in `vision_results`, separate from the
original file row.
"""
from __future__ import annotations
import base64
import time

from . import db, prefs

IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}
MAX_BYTES = 3 * 1024 * 1024
MAX_SIDE = 1568

VISION_PROMPT = ("Describe this image factually: what it shows, any visible text transcribed "
                 "verbatim, and notable details. Do not invent anything not visible.")

OFF_ERROR = ("vision unavailable: no reachable vision model "
             "(Ollama vision model or configured cloud key required)")


def _fit(data: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale oversized images so they fit vision context windows. Never raises."""
    try:
        if len(data) <= MAX_BYTES:
            return data, mime
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        w, h = img.size
        scale = min(1.0, MAX_SIDE / max(w, h))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, mime


def analyze_image(data: bytes, mime: str = "image/png", question: str = "") -> dict:
    """Returns {ok, description?, model?, ms?, error?}. Never raises."""
    if db.DRY_RUN:
        db.blocked("vision: analysis skipped")
        return {"ok": True, "description": "[dry-run: vision withheld]", "model": "dry-run", "ms": 0}
    try:
        if not prefs.get("vision_enabled"):
            return {"ok": False, "error": "vision is disabled (Settings → Intelligence → Image understanding)"}
    except Exception:
        pass
    data, mime = _fit(data, mime)
    url = f"data:{mime or 'image/png'};base64," + base64.b64encode(data).decode()
    prompt = (question or "").strip() or VISION_PROMPT
    msgs = [{"role": "user", "content": prompt}]

    from .inference import OllamaClient, get_cloud_client, router
    try:
        pr = router.probe()
        chain = router.chain()
    except Exception:
        pr, chain = {}, []
    if "ollama" in chain and (pr.get("local_lfm") or {}).get("online"):
        try:
            vm = prefs.get("ollama_vision_model") or "llava"
            t0 = time.time()
            text = (OllamaClient().chat(msgs, model=vm, images=[url], purpose="vision") or "").strip()
            if text:
                return {"ok": True, "description": text, "model": f"ollama/{vm}",
                        "ms": int((time.time() - t0) * 1000)}
        except Exception:
            pass
    if "cloud" in chain and (pr.get("cloud") or {}).get("configured"):
        try:
            client = get_cloud_client()
        except Exception:
            client = None
        if client is not None and client.configured():
            try:
                t0 = time.time()
                text = (client.chat(msgs, images=[url], purpose="vision", timeout=120.0) or "").strip()
                if text:
                    return {"ok": True, "description": text, "model": f"cloud/{client.model}",
                            "ms": int((time.time() - t0) * 1000)}
            except Exception as e:
                from . import costs as _costs
                if isinstance(e, _costs.BudgetExceeded):
                    return {"ok": False, "error": str(e)}
    return {"ok": False, "error": OFF_ERROR}


def analyze_file(file_id: int, question: str = "") -> dict:
    """Analyze an uploaded image; persists to `vision_results`. Returns the stored row shape."""
    row = db.qone("SELECT * FROM files WHERE id=?", (file_id,))
    if not row:
        return {"ok": False, "status": 404, "error": "unknown file"}
    mime = (row.get("mime") or "").split(";")[0].strip().lower()
    if mime not in IMAGE_MIMES:
        return {"ok": False, "status": 400, "error": f"not an image (mime: {mime or 'unknown'})"}
    try:
        with open(row["path"], "rb") as f:
            data = f.read(MAX_BYTES * 4 + 1)
    except OSError:
        return {"ok": False, "status": 410, "error": "original file missing from disk"}
    res = analyze_image(data, mime, question)
    if not res.get("ok"):
        return res
    vid = db.run("INSERT INTO vision_results (file_id, question, description, model, ms)"
                 " VALUES (?,?,?,?,?)",
                 (file_id, (question or "")[:500], res["description"], res["model"], res["ms"]))
    return {"ok": True, "id": vid, "file_id": file_id, "question": question or "",
            "description": res["description"], "model": res["model"], "ms": res["ms"]}
