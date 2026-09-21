"""Always-on voice loop — wake → listen → think → speak, with barge-in.

Transport-agnostic: feed() takes raw 16kHz mono PCM16 bytes and returns a list
of ("json", dict) / ("bytes", bytes) events; the WebSocket route delivers them.
transcribe/answer/speak/wake_score are injected so tests drive the whole loop
with stubs and synthetic audio — no mic, model, or socket required.

States: sleeping → listening → thinking → speaking → listening (follow-up
window) → sleeping. Barge-in is wake-word-only during speaking (no acoustic
echo cancellation, so energy is ignored while AURA talks — documented, honest).
"""
from __future__ import annotations

import io
import struct
import time
import wave
from typing import Any, Callable

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2  # 640
WAKE_SAMPLES = 1280  # 80ms @ 16kHz


def rms_energy(pcm: bytes) -> float:
    """RMS of PCM16 bytes. Silence ≈ <100, conversational speech ≈ 500–4000."""
    if len(pcm) < 2:
        return 0.0
    n = len(pcm) // 2
    fmt = "<" + "h" * n
    try:
        samples = struct.unpack(fmt, pcm[:n * 2])
    except struct.error:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / n) ** 0.5


def pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def default_transcribe(pcm: bytes) -> str:
    from . import voice as voicemod
    try:
        out = voicemod.transcribe_bytes(pcm_to_wav(pcm))
    except RuntimeError:
        return ""
    return (out.get("text") or "").strip()


def default_answer(text: str) -> str:
    from .orchestrator import run_turn
    final = ""
    for chunk in run_turn(text):
        lines = chunk.split("\n")
        ev = ""
        for ln in lines:
            if ln.startswith("event:"):
                ev = ln[6:].strip()
            elif ln.startswith("data:") and ev == "result":
                import json
                try:
                    final = json.loads(ln[5:].strip()).get("text", "") or ""
                except ValueError:
                    pass
    return final.strip() or "I didn't catch that."


def default_speak(text: str) -> tuple[bytes, str]:
    from . import prefs, voice as voicemod
    selected = prefs.get("voice_engine") or "browser"
    if selected != "browser":
        return voicemod.speak(text, engine=selected)
    engines = ("piper", "edge") if prefs.get("privacy") in ("hybrid", "cloud") else ("piper",)
    last: Exception | None = None
    for engine in engines:
        try:
            audio, media = voicemod.speak(text, engine=engine)
            if audio:
                return audio, media
        except Exception as e:  # noqa: BLE001 — try next engine, report last
            last = e
    raise RuntimeError(str(last) if last else "no server TTS engine available")


def default_wake_score(pcm80ms: bytes) -> float:
    from . import wake
    try:
        return wake.score_pcm16(wake.get_model(), pcm80ms)
    except RuntimeError:
        return 0.0


class LoopSession:
    """One full-duplex conversation. All audio plumbing in, events out."""

    def __init__(self, *,
                 transcribe: Callable[[bytes], str] | None = None,
                 answer: Callable[[str], str] | None = None,
                 speak: Callable[[str], tuple[bytes, str]] | None = None,
                 wake_score: Callable[[bytes], float] | None = None,
                 cfg: dict | None = None):
        c = cfg or {}
        self.transcribe = transcribe or default_transcribe
        self.answer = answer or default_answer
        self.speak = speak or default_speak
        self.wake_score = wake_score or default_wake_score
        self.wake_threshold = float(c.get("wake_threshold", 0.5))
        self.energy_thr = float(c.get("vad_energy", 500.0))
        self.end_silence_ms = int(c.get("end_silence_ms", 900))
        self.min_utt_ms = int(c.get("min_utterance_ms", 400))
        self.max_utt_ms = int(c.get("max_utterance_ms", 15000))
        self.followup_ms = int(c.get("followup_ms", 6000))
        self.barge_in = bool(c.get("barge_in", True))
        self.wake_enabled = bool(c.get("wake_enabled", True))
        self.state = "sleeping"
        self._utt = bytearray()       # current utterance PCM
        self._wakebuf = bytearray()   # 80ms wake windows
        self._preroll = bytearray()   # last ~0.5s kept for wake cut-in
        self._silence_ms = 0
        self._speech_seen = False
        self._deadline_ms: float | None = None
        self._speaking_aborted = False

    # ------------------------------------------------------------- input --
    def feed(self, pcm: bytes, now_ms: float | None = None) -> list[tuple[str, Any]]:
        """Feed PCM16 bytes (any length). Returns deliverable events."""
        now = time.monotonic() * 1000 if now_ms is None else now_ms
        evs: list[tuple[str, Any]] = []
        if self.state == "thinking":
            return evs  # thinking is synchronous; no re-entry
        # follow-up window expiry
        if (self.state == "listening" and self._deadline_ms is not None
                and not self._utt and now >= self._deadline_ms):
            return self._to_sleep(evs, now)
        if self.state == "speaking":
            return self._feed_speaking(pcm, evs, now)
        if self.state == "sleeping" and self.wake_enabled:
            self._feed_wake(pcm, evs, now)
            if self.state == "sleeping":
                return evs
            pcm = bytes(self._preroll) + pcm  # don't clip the first word
        if self.state == "listening":
            self._feed_listen(pcm, evs, now)
        return evs

    def tap_to_talk(self) -> list[tuple[str, Any]]:
        """Skip the wake gate (fallback when wake-word dep is missing)."""
        evs: list[tuple[str, Any]] = []
        self._begin_listen(evs, followup=False)
        return evs

    # ------------------------------------------------------------ states --
    def _emit(self, evs: list, kind: str, payload: Any) -> None:
        evs.append((kind, payload))

    def _to_sleep(self, evs: list, now: float) -> list[tuple[str, Any]]:
        self.state = "sleeping"
        self._utt.clear()
        self._wakebuf.clear()
        self._deadline_ms = None
        self._speech_seen = False
        self._emit(evs, "json", {"t": "state", "state": "sleeping"})
        return evs

    def _begin_listen(self, evs: list, followup: bool) -> None:
        self.state = "listening"
        self._utt.clear()
        self._silence_ms = 0
        self._speech_seen = False
        self._deadline_ms = None if not followup else -1  # armed after speak
        self._emit(evs, "json", {"t": "state", "state": "listening",
                                 "followup": followup})

    def _feed_wake(self, pcm: bytes, evs: list, now: float) -> None:
        self._preroll += pcm
        self._preroll = self._preroll[-(SAMPLE_RATE // 2 * 2):]  # ~0.5s
        self._wakebuf += pcm
        win = WAKE_SAMPLES * 2
        while len(self._wakebuf) >= win:
            frame = bytes(self._wakebuf[:win])
            del self._wakebuf[:win]
            try:
                score = float(self.wake_score(frame))
            except Exception:
                score = 0.0
            if score >= self.wake_threshold:
                self._emit(evs, "json", {"t": "wake", "score": round(score, 3)})
                self._begin_listen(evs, followup=False)
                return

    def _feed_listen(self, pcm: bytes, evs: list, now: float) -> None:
        off = 0
        while off < len(pcm):
            frame = pcm[off:off + FRAME_BYTES]
            off += FRAME_BYTES
            if len(frame) < FRAME_BYTES:
                break  # ragged tail dropped; next feed continues
            loud = rms_energy(frame) >= self.energy_thr
            self._utt += frame
            utt_ms = len(self._utt) // 2 // (SAMPLE_RATE // 1000)
            if loud:
                self._speech_seen = True
                self._silence_ms = 0
            else:
                self._silence_ms += FRAME_MS
            if utt_ms >= self.max_utt_ms and self._speech_seen:
                self._endpoint(evs, now)
                return
            if (self._speech_seen and self._silence_ms >= self.end_silence_ms
                    and utt_ms >= self.min_utt_ms):
                self._endpoint(evs, now)
                return
        # follow-up window with no speech at all
        if (not self._speech_seen and self._deadline_ms is not None
                and self._deadline_ms > 0 and now >= self._deadline_ms
                and not self._utt):
            self._to_sleep(evs, now)

    def _feed_speaking(self, pcm: bytes, evs: list, now: float) -> list[tuple[str, Any]]:
        if not (self.barge_in and self.wake_enabled):
            return evs
        self._wakebuf += pcm
        win = WAKE_SAMPLES * 2
        while len(self._wakebuf) >= win:
            frame = bytes(self._wakebuf[:win])
            del self._wakebuf[:win]
            try:
                score = float(self.wake_score(frame))
            except Exception:
                score = 0.0
            if score >= self.wake_threshold:
                self._speaking_aborted = True
                self._emit(evs, "json", {"t": "barge", "score": round(score, 3)})
                self._begin_listen(evs, followup=False)
                return evs
        return evs

    def _endpoint(self, evs: list, now: float) -> None:
        utt = bytes(self._utt)
        self._utt.clear()
        utt_ms = len(utt) // 2 // (SAMPLE_RATE // 1000)
        self._emit(evs, "json", {"t": "utterance", "ms": utt_ms})
        self.state = "thinking"
        self._emit(evs, "json", {"t": "state", "state": "thinking"})
        try:
            text = (self.transcribe(utt) or "").strip()
        except Exception as e:  # noqa: BLE001 — STT failure is data
            text = ""
            self._emit(evs, "json", {"t": "error", "stage": "transcribe",
                                     "detail": str(e)[:160]})
        self._emit(evs, "json", {"t": "transcript", "text": text})
        if not text:
            self._begin_listen(evs, followup=True)
            self._deadline_ms = now + self.followup_ms
            return
        try:
            reply = (self.answer(text) or "").strip()
        except Exception as e:  # noqa: BLE001 — brain failure is data
            reply = ""
            self._emit(evs, "json", {"t": "error", "stage": "answer",
                                     "detail": str(e)[:160]})
        if not reply:
            reply = "I didn't catch that."
        self._emit(evs, "json", {"t": "answer", "text": reply})
        try:
            audio, media = self.speak(reply)
        except Exception as e:  # noqa: BLE001 — client falls back to browser TTS
            audio, media = b"", ""
            self._emit(evs, "json", {"t": "error", "stage": "speak",
                                     "detail": str(e)[:160]})
        self.state = "speaking"
        self._speaking_aborted = False
        self._wakebuf.clear()
        self._emit(evs, "json", {"t": "state", "state": "speaking",
                                 "media": media, "bytes": len(audio)})
        if audio:
            self._emit(evs, "bytes", audio)
        # follow-up window starts when the client finishes playing; the route
        # calls spoke() on client "played" message, else we arm it now.
        self._deadline_ms = now + self.followup_ms + max(0, len(audio) // 32)

    def spoke(self, now_ms: float | None = None) -> list[tuple[str, Any]]:
        """Client finished playing the reply → open the follow-up window."""
        evs: list[tuple[str, Any]] = []
        if self.state != "speaking":
            return evs
        now = time.monotonic() * 1000 if now_ms is None else now_ms
        if self._speaking_aborted:
            return evs  # barge already moved us to listening
        self._begin_listen(evs, followup=True)
        self._deadline_ms = now + self.followup_ms
        return evs
