"""Server-side voice — faster-whisper STT + Piper TTS (both optional).

Deps live in requirements-voice.txt. Models download on first use into
DATA_DIR/models (~75MB whisper tiny + ~60MB piper voice) and are cached
in memory afterwards. Every entry point degrades to a clear 503-style
RuntimeError when deps/models are missing.
"""
from __future__ import annotations

import io
import subprocess
import sys
import threading
import wave
from pathlib import Path

from . import config, db, prefs

_LOCK = threading.RLock()
_WHISPER = None
_PIPER = None
_PIPER_VOICE = ""

MISSING = ("server voice needs requirements-voice.txt "
           "(pip install -r backend/requirements-voice.txt)")


def model_dir() -> Path:
    d = Path(config.DATA_DIR) / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def whisper_model():
    global _WHISPER
    with _LOCK:
        if _WHISPER is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise RuntimeError(MISSING)
            _WHISPER = WhisperModel(
                getattr(config, "WHISPER_MODEL", "tiny"),
                device="cpu", compute_type="int8",
                download_root=str(model_dir() / "whisper"))
        return _WHISPER


def transcribe_bytes(data: bytes) -> dict:
    """Transcribe audio bytes (wav/mp3/m4a/webm...). Returns {text, language, duration}."""
    model = whisper_model()
    try:
        segments, info = model.transcribe(io.BytesIO(data), beam_size=1)
    except Exception as e:
        raise ValueError(f"could not decode audio: {str(e)[:150]}")
    text = "".join(s.text for s in segments).strip()
    return {"text": text, "language": getattr(info, "language", "") or "",
            "duration": round(getattr(info, "duration", 0) or 0, 1)}


def _ensure_piper_download(voice: str) -> Path:
    dest = model_dir() / "piper"
    dest.mkdir(parents=True, exist_ok=True)
    if list(dest.glob(f"{voice}*.onnx")) or list(dest.glob(f"**/{voice}*.onnx")):
        return dest
    r = subprocess.run([sys.executable, "-m", "piper.download_voices",
                        "--download-dir", str(dest), voice],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"piper voice download failed: {(r.stderr or r.stdout)[-300:]}")
    return dest


PIPER_VOICES = [
    {"id": "en_US-lessac-medium", "label": "Lessac · US English, masculine"},
    {"id": "en_US-amy-medium", "label": "Amy · US English, feminine"},
    {"id": "en_US-ryan-high", "label": "Ryan · US English, masculine, high quality"},
    {"id": "en_US-kristin-medium", "label": "Kristin · US English, feminine"},
    {"id": "en_GB-alan-medium", "label": "Alan · British English, masculine"},
]
PIPER_IDS = {v["id"] for v in PIPER_VOICES}


def piper_voice(voice: str | None = None):
    global _PIPER, _PIPER_VOICE
    want = voice or prefs.get("voice_piper_id") or getattr(config, "PIPER_VOICE", "en_US-lessac-medium")
    with _LOCK:
        if _PIPER is None or _PIPER_VOICE != want:
            try:
                from piper import PiperVoice
            except ImportError:
                raise RuntimeError(MISSING)
            dest = _ensure_piper_download(want)
            found = list(dest.glob(f"{want}*.onnx")) or list(dest.glob(f"**/{want}*.onnx"))
            if not found:
                raise RuntimeError(f"piper voice '{want}' not found after download")
            _PIPER = PiperVoice.load(str(found[0]))
            _PIPER_VOICE = want
        return _PIPER


def speak_wav(text: str, voice: str | None = None, rate: float = 1.0) -> bytes:
    """Synthesize text to WAV bytes (16-bit PCM)."""
    text = clean_text(text)[:1500]
    if not text:
        raise ValueError("nothing to say")
    want = voice or prefs.get("voice_piper_id") or getattr(config, "PIPER_VOICE", "en_US-lessac-medium")
    if want not in PIPER_IDS:
        raise ValueError(f"unknown piper voice '{want}'")
    pv = piper_voice(want)
    cfg = None
    try:
        r = float(rate or 1.0)
        if r != 1.0:
            from piper.config import SynthesisConfig
            cfg = SynthesisConfig(length_scale=min(2.0, max(0.5, 1.0 / r)))
    except Exception:
        cfg = None
    chunks = list(pv.synthesize(text, cfg) if cfg else pv.synthesize(text))
    if not chunks:
        raise RuntimeError("piper produced no audio")
    rate = getattr(chunks[0], "sample_rate", 22050) or 22050
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for c in chunks:
            w.writeframes(c.audio_int16_bytes)
    return buf.getvalue()


KOKORO_VOICES = [
    {"id": "af_heart", "label": "Heart · US English, feminine"},
    {"id": "af_bella", "label": "Bella · US English, feminine"},
    {"id": "af_sarah", "label": "Sarah · US English, feminine"},
    {"id": "am_adam", "label": "Adam · US English, masculine"},
    {"id": "am_michael", "label": "Michael · US English, masculine"},
    {"id": "bf_emma", "label": "Emma · British English, feminine"},
    {"id": "bm_george", "label": "George · British English, masculine"},
]
KOKORO_IDS = {v["id"] for v in KOKORO_VOICES}
KOKORO_ASSETS = {
    "kokoro-v1.0.int8.onnx": (114119327, "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c"),
    "voices-v1.0.bin": (28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}
KOKORO_SETUP = "Kokoro offline assets missing or invalid; run venv/bin/python scripts/download_kokoro.py once with network access"
_KOKORO = None
_KOKORO_KEY = None


def kokoro_paths() -> tuple[Path, Path]:
    root = Path(config.DATA_DIR).resolve()
    dest = root / "models" / "kokoro"
    if dest.resolve() != dest:
        raise RuntimeError("Kokoro asset path must not contain symlinks")
    paths = tuple(dest / name for name in KOKORO_ASSETS)
    for path in paths:
        if path.is_symlink() or path.resolve() != path:
            raise RuntimeError("Kokoro asset path must not contain symlinks")
        if not path.is_file() or path.stat().st_size != KOKORO_ASSETS[path.name][0]:
            raise RuntimeError(KOKORO_SETUP)
    return paths


def kokoro_status() -> dict:
    import importlib.util
    installed = importlib.util.find_spec("kokoro_onnx") is not None
    try:
        paths = kokoro_paths()
        assets = True
        note = "Local CPU synthesis. No network access; English voices, rate control."
    except (OSError, RuntimeError) as exc:
        paths = None
        assets = False
        note = str(exc)
    if not installed:
        note = "Kokoro needs optional kokoro-onnx==0.6.1 in the project venv. " + note
    return {"installed": installed, "assets_ready": assets, "available": installed and assets,
            "loaded": paths is not None and _KOKORO is not None and _KOKORO_KEY == tuple(str(p) for p in paths),
            "note": note}


def kokoro_model():
    global _KOKORO, _KOKORO_KEY
    with _LOCK:
        paths = kokoro_paths()
        key = tuple(str(p) for p in paths)
        if _KOKORO is None or _KOKORO_KEY != key:
            import hashlib
            for path in paths:
                with path.open("rb") as asset:
                    digest = hashlib.file_digest(asset, "sha256").hexdigest()
                if digest != KOKORO_ASSETS[path.name][1]:
                    raise RuntimeError(KOKORO_SETUP)
            try:
                from kokoro_onnx import Kokoro
                import onnxruntime as ort
            except ImportError:
                raise RuntimeError("Kokoro needs optional kokoro-onnx==0.6.1 in the project venv")
            try:
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
                session = ort.InferenceSession(str(paths[0]), sess_options=options, providers=["CPUExecutionProvider"])
                model = Kokoro.from_session(session, str(paths[1]))
            except Exception as exc:
                raise RuntimeError("Kokoro could not load local assets or bundled eSpeak; verify optional dependencies and rerun setup") from exc
            _KOKORO, _KOKORO_KEY = model, key
        return _KOKORO


def speak_kokoro(text: str, voice_id: str | None = None, rate: float = 1.0) -> bytes:
    text = clean_text(text)[:1500]
    if not text:
        raise ValueError("nothing to say")
    want = voice_id or prefs.get("voice_kokoro_id")
    if want not in KOKORO_IDS:
        raise ValueError(f"unknown kokoro voice '{want}'")
    speed = prefs.validate("voice_rate", rate)
    with _LOCK:
        model = kokoro_model()
        try:
            samples, sample_rate = model.create(text, voice=want, speed=speed,
                                                lang="en-gb" if want.startswith("b") else "en-us")
        except Exception as exc:
            raise RuntimeError("Kokoro local synthesis failed; check the selected voice and local assets") from exc
    import array
    import math
    if not len(samples):
        raise RuntimeError("Kokoro produced no audio")
    if sample_rate != 24000 or any(not math.isfinite(float(s)) for s in samples):
        raise RuntimeError("Kokoro produced invalid audio")
    pcm = array.array("h", (int(max(-1, min(1, float(s))) * 32767) for s in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def status() -> dict:
    try:
        import faster_whisper  # noqa: F401
        stt = True
    except ImportError:
        stt = False
    try:
        import piper  # noqa: F401
        tts = True
    except ImportError:
        tts = False
    kokoro = kokoro_status()
    return {
        "kokoro_installed": kokoro["installed"], "kokoro_ready": kokoro["available"],
        "kokoro_loaded": kokoro["loaded"], "kokoro_note": kokoro["note"],
        "stt_installed": stt, "tts_installed": tts,
        "whisper_model": getattr(config, "WHISPER_MODEL", "tiny"),
        "whisper_ready": _WHISPER is not None,
        "piper_voice": getattr(config, "PIPER_VOICE", "en_US-lessac-medium"),
        "piper_ready": _PIPER is not None,
        "note": "" if (stt and tts) else MISSING,
    }


# ------------------------------------------------------- voice v2 (1.7.0) ---
import asyncio as _asyncio
import html as _html
import re as _re

EDGE_VOICES = [
    {"id": "en-KE-ChilembaNeural", "label": "Chilemba · Kenyan English, masculine"},
    {"id": "en-KE-AsiliaNeural", "label": "Asilia · Kenyan English, feminine"},
    {"id": "sw-KE-RafikiNeural", "label": "Rafiki · Kiswahili, masculine"},
    {"id": "sw-KE-ZuriNeural", "label": "Zuri · Kiswahili, feminine"},
    {"id": "en-US-AvaNeural", "label": "Ava · US English, feminine, full emotions"},
    {"id": "en-US-AndrewNeural", "label": "Andrew · US English, masculine, full emotions"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia · British English, feminine"},
    {"id": "en-GB-RyanNeural", "label": "Ryan · British English, masculine"},
]
EDGE_IDS = {v["id"] for v in EDGE_VOICES}
# Only these get mstts style tags; every other voice still gets the same
# prosody (rate/pitch/pauses) so emotions work everywhere, honestly labeled.
STYLE_VOICES = {"en-US-AvaNeural", "en-US-AndrewNeural"}

EMOTIONS = {
    "neutral":  {"label": "Neutral",  "style": "",         "rate": 1.00, "pitch_hz": 0,   "bpitch": 1.00, "pause": 1.00},
    "cheerful": {"label": "Cheerful", "style": "cheerful", "rate": 1.10, "pitch_hz": 30,  "bpitch": 1.15, "pause": 0.90},
    "calm":     {"label": "Calm",     "style": "",         "rate": 0.88, "pitch_hz": -10, "bpitch": 0.90, "pause": 1.30},
    "excited":  {"label": "Excited",  "style": "excited",  "rate": 1.15, "pitch_hz": 50,  "bpitch": 1.25, "pause": 0.85},
    "serious":  {"label": "Serious",  "style": "serious",  "rate": 0.95, "pitch_hz": -20, "bpitch": 0.85, "pause": 1.15},
    "sad":      {"label": "Sad",      "style": "sad",      "rate": 0.88, "pitch_hz": -15, "bpitch": 0.85, "pause": 1.25},
}


def clean_text(text: str) -> str:
    """Strip markdown/code so TTS reads words, not punctuation soup."""
    t = text or ""
    t = _re.sub(r"```.*?```", " ", t, flags=_re.S)
    t = _re.sub(r"`([^`]*)`", r"\1", t)
    t = _re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = _re.sub(r"[*_#>|~]+", "", t)
    t = _re.sub(r"[ \t]+", " ", t)
    return t.strip()


def humanize(text: str, emotion: str = "neutral", breaks: bool = True, use_style: bool = True) -> str:
    """Plain text -> SSML inner content: sentence/paragraph breaks + emotion style."""
    emo = EMOTIONS.get((emotion or "neutral").lower(), EMOTIONS["neutral"])
    paras = [p.strip() for p in _re.split(r"\n\s*\n", clean_text(text)) if p.strip()]
    if not paras:
        return ""
    p = emo["pause"]
    parts = []
    for para in paras:
        sents = [s.strip() for s in _re.split(r"(?<=[.!?…])\s+", para) if s.strip()]
        if breaks and len(sents) > 1:
            parts.append(f'<break time="{int(280 * p)}ms"/>'.join(_html.escape(s) for s in sents))
        else:
            parts.append(_html.escape(" ".join(sents)))
    body = (f'<break time="{int(600 * p)}ms"/>' if breaks else " ").join(parts)
    if use_style and emo["style"]:
        body = f'<mstts:express-as style="{emo["style"]}" styledegree="2">{body}</mstts:express-as>'
    return body


def speak_edge(text: str, voice_id: str | None = None, emotion: str | None = None,
               rate: float = 1.0, pitch: float = 1.0) -> bytes:
    """Neural cloud TTS (Microsoft Edge, free, no key). Returns MP3 bytes."""
    if (prefs.get("privacy") or "local-first").lower() not in ("hybrid", "cloud"):
        raise PermissionError("edge voices send text to Microsoft — switch privacy to Hybrid or Cloud to enable")
    if db.DRY_RUN:
        db.blocked("tts: edge speak skipped")
        raise RuntimeError("dry-run: cloud TTS withheld")
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge TTS needs: pip install edge-tts")
    v = voice_id or prefs.get("voice_edge_id") or "en-KE-ChilembaNeural"
    if v not in EDGE_IDS:
        raise ValueError(f"unknown edge voice '{v}'")
    emo_id = (emotion or prefs.get("voice_emotion") or "neutral").lower()
    emo = EMOTIONS.get(emo_id, EMOTIONS["neutral"])
    br = prefs.get("voice_breaks")
    if br is None:
        br = True
    r = round((emo["rate"] * float(rate or 1.0) - 1) * 100)
    hz = int(emo["pitch_hz"] + (float(pitch or 1.0) - 1) * 100)
    lang = "-".join(v.split("-")[:2])

    def _ssml(styled: bool) -> str:
        inner = humanize(text, emo_id, bool(br), use_style=styled and v in STYLE_VOICES)
        if not inner:
            raise ValueError("nothing to say")
        return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="{lang}"><voice name="{v}">'
                f'<prosody rate="{r:+d}%" pitch="{hz:+d}Hz">{inner}</prosody></voice></speak>')

    async def _run(ssml_text: str) -> bytes:
        out = []
        async for ch in edge_tts.Communicate(ssml_text, v).stream():
            if ch.get("type") == "audio":
                out.append(ch["data"])
        return b"".join(out)

    try:
        audio = _asyncio.run(_asyncio.wait_for(_run(_ssml(True)), 90))
    except ValueError:
        raise
    except Exception as e:
        try:
            import edge_tts as _et
            transient = isinstance(e, _et.exceptions.NoAudioReceived)
        except Exception:
            transient = False
        if transient and not (emo["style"] and v in STYLE_VOICES):
            import time as _t
            _t.sleep(1)
            try:
                audio = _asyncio.run(_asyncio.wait_for(_run(_ssml(True)), 90))
            except Exception as e2:
                raise RuntimeError(f"edge TTS failed: {str(e2)[:150]}")
            if audio:
                return audio
            raise RuntimeError("edge TTS produced no audio")
        if emo["style"] and v in STYLE_VOICES:
            try:  # voice may not support this style — retry prosody-only
                audio = _asyncio.run(_asyncio.wait_for(_run(_ssml(False)), 90))
            except Exception as e2:
                raise RuntimeError(f"edge TTS failed: {str(e2)[:150]}")
        else:
            raise RuntimeError(f"edge TTS failed: {str(e)[:150]}")
    if not audio:
        raise RuntimeError("edge TTS produced no audio")
    return audio


def speak(text: str, engine: str | None = None, voice: str | None = None,
          emotion: str | None = None, rate: float | None = None,
          pitch: float | None = None) -> tuple[bytes, str]:
    """Dispatcher for server TTS. Returns (audio_bytes, media_type)."""
    explicit = (engine or "").lower()
    eng = explicit or (prefs.get("voice_engine") or "browser").lower()
    if eng == "browser":
        if explicit:
            raise ValueError("browser engine renders in the page, not via /api/voice/speak")
        eng = "piper"  # legacy {text}-only callers keep getting piper wav
    if eng == "kokoro":
        return speak_kokoro(text, voice, rate if rate is not None else prefs.get("voice_rate")), "audio/wav"
    if eng == "edge":
        return speak_edge(text, voice, emotion, rate or float(prefs.get("voice_rate") or 1.0),
                          pitch if pitch is not None else float(prefs.get("voice_pitch") or 1.0)), "audio/mpeg"
    if eng == "piper":
        return speak_wav(text, voice, rate or float(prefs.get("voice_rate") or 1.0)), "audio/wav"
    raise ValueError(f"unknown engine '{eng}'")


def engines() -> dict:
    try:
        import edge_tts  # noqa: F401
        edge_ok = True
    except ImportError:
        edge_ok = False
    try:
        import piper  # noqa: F401
        piper_ok = True
    except ImportError:
        piper_ok = False
    cloud = (prefs.get("privacy") or "local-first").lower() in ("hybrid", "cloud")
    kokoro = kokoro_status()
    return {
        "engines": [
            {"id": "browser", "label": "Browser voices", "offline": True, "available": True,
             "features": ["voices", "rate", "pitch", "emotions", "breaks"],
             "note": "Instant, on-device. Quality depends on your system voices."},
            {"id": "piper", "label": "Piper (server, offline)", "offline": True,
             "available": piper_ok, "voices": PIPER_VOICES,
             "features": ["voices", "rate", "breaks"],
             "note": "Fast local synthesis. Voices download (~60MB) on first use."},
            {"id": "kokoro", "label": "Kokoro (server, offline CPU)", "offline": True,
             "available": kokoro["available"], "voices": KOKORO_VOICES,
             "features": ["voices", "rate"], "note": kokoro["note"]},
            {"id": "edge", "label": "Edge Neural (server, cloud)", "offline": False,
             "available": edge_ok and cloud, "voices": EDGE_VOICES,
             "features": ["voices", "rate", "pitch", "emotions", "breaks"],
             "note": "Most human. Free, no key — needs network + Hybrid/Cloud privacy."},
        ],
        "emotions": [{"id": k, "label": v["label"]} for k, v in EMOTIONS.items()],
        "current": {"engine": prefs.get("voice_engine"), "edge_voice": prefs.get("voice_edge_id"),
                    "piper_voice": prefs.get("voice_piper_id"), "kokoro_voice": prefs.get("voice_kokoro_id"),
                    "emotion": prefs.get("voice_emotion"),
                    "rate": prefs.get("voice_rate"), "pitch": prefs.get("voice_pitch"),
                    "breaks": prefs.get("voice_breaks")},
    }
