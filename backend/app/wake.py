"""Wake-word detection — openWakeWord, 'hey jarvis' model bundled with the pip package.

The model file ships inside site-packages (no separate download). 16kHz mono
PCM16 input in 80ms frames (1280 samples). Everything degrades to a clear
RuntimeError when the optional dep is missing — the voice loop then runs in
tap-to-talk mode instead of pretending to hear a wake word.
"""
from __future__ import annotations

import os
import threading

MODEL_KEY = "hey_jarvis_v0.1"
FRAME_SAMPLES = 1280  # 80ms @ 16kHz
MISSING = ("wake word needs requirements-voice.txt "
           "(pip install -r backend/requirements-voice.txt)")

_LOCK = threading.RLock()
_MODEL = None


def available() -> bool:
    try:
        import openwakeword  # noqa: F401
        return _bundled_path() is not None
    except ImportError:
        return False


def _bundled_path() -> str | None:
    try:
        import openwakeword
    except ImportError:
        return None
    p = os.path.join(os.path.dirname(openwakeword.__file__),
                     "resources", "models", MODEL_KEY + ".onnx")
    return p if os.path.exists(p) else None


def get_model():
    """Lazy singleton openWakeWord Model. Raises RuntimeError when unavailable."""
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            path = _bundled_path()
            if path is None:
                raise RuntimeError(MISSING)
            from openwakeword.model import Model
            _MODEL = Model(wakeword_model_paths=[path])
        return _MODEL


def score_pcm16(model, pcm: bytes) -> float:
    """Score one 80ms frame. Returns 0.0..1.0 (caller buffers to 1280 samples)."""
    import numpy as np
    frame = np.frombuffer(pcm, dtype=np.int16)
    if len(frame) < FRAME_SAMPLES:
        frame = np.pad(frame, (0, FRAME_SAMPLES - len(frame)))
    else:
        frame = frame[:FRAME_SAMPLES]
    out = model.predict(frame)
    try:
        return float(out.get(MODEL_KEY, 0.0) or 0.0)
    except (AttributeError, TypeError):
        return 0.0


def reset(model) -> None:
    try:
        model.reset()
    except Exception:
        pass
