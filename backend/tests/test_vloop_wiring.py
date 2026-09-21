import unittest
from unittest.mock import patch

from app import prefs, voice, vloop


class LoopVoiceSelectionTest(unittest.TestCase):
    def test_selected_server_engine_is_used_without_substitution(self):
        for engine in ("kokoro", "piper", "edge"):
            with self.subTest(engine=engine):
                with patch.object(prefs, "get", side_effect=lambda key: {"voice_engine": engine, "privacy": "hybrid"}.get(key)), patch.object(voice, "speak", return_value=(b"selected", "audio/wav")) as speak:
                    self.assertEqual(vloop.default_speak("Hello"), (b"selected", "audio/wav"))
                    speak.assert_called_once_with("Hello", engine=engine)

    def test_missing_kokoro_does_not_silently_use_cloud(self):
        with patch.object(prefs, "get", side_effect=lambda key: {"voice_engine": "kokoro", "privacy": "hybrid"}.get(key)), patch.object(voice, "speak", side_effect=RuntimeError("Kokoro assets missing")) as speak:
            with self.assertRaisesRegex(RuntimeError, "Kokoro assets missing"):
                vloop.default_speak("Hello")
            speak.assert_called_once_with("Hello", engine="kokoro")

    def test_local_first_never_attempts_edge_fallback(self):
        with patch.object(prefs, "get", side_effect=lambda key: {"voice_engine": "browser", "privacy": "local-first"}.get(key)), patch.object(voice, "speak", side_effect=RuntimeError("Piper unavailable")) as speak:
            with self.assertRaisesRegex(RuntimeError, "Piper unavailable"):
                vloop.default_speak("Hello")
            speak.assert_called_once_with("Hello", engine="piper")

    def test_permitted_browser_fallback_retains_piper_then_edge(self):
        with patch.object(prefs, "get", side_effect=lambda key: {"voice_engine": "browser", "privacy": "hybrid"}.get(key)), patch.object(voice, "speak", side_effect=[RuntimeError("Piper unavailable"), (b"edge", "audio/mpeg")]) as speak:
            self.assertEqual(vloop.default_speak("Hello"), (b"edge", "audio/mpeg"))
            self.assertEqual([call.kwargs["engine"] for call in speak.call_args_list], ["piper", "edge"])
