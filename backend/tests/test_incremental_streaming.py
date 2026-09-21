import json
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
from app import orchestrator

import unittest


class IncrementalTurnTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.writes = self.stack.enter_context(patch.object(orchestrator.db, "run", return_value=1))
        self.stack.enter_context(patch.object(orchestrator.db, "qone", return_value={"id": "session"}))
        self.stack.enter_context(patch.object(orchestrator.db, "log_activity"))
        self.stack.enter_context(patch.object(orchestrator.model_router, "probe", return_value={
            "local_lfm": {"online": True, "model": "test"}, "cloud": {"configured": False}}))
        self.stack.enter_context(patch.object(orchestrator.model_router, "chain", return_value=["ollama", "builtin"]))
        self.stack.enter_context(patch("app.compact.session_context", return_value={"history": [], "summary": ""}))
        self.stack.enter_context(patch("app.compact.maybe_compact"))
        self.stack.enter_context(patch.object(orchestrator.memory_engine, "observe", return_value=[]))

    def events(self, stream):
        # Create an iterator with a close method for the chat() method
        class MockStream:
            def __init__(self, items):
                self._items = items
            def __iter__(self):
                return iter(self._items)
            def close(self):
                pass
        
        mock_stream = MockStream(stream())
        
        with patch.object(orchestrator.model_router.ollama, "chat_stream", return_value=mock_stream):
            return [(e.split("\n", 1)[0][7:], json.loads(e.split("data: ", 1)[1]))
                    for e in orchestrator.run_turn("hello", "session")]

    def test_success_tokens_are_not_replayed(self):
        events = self.events(lambda *a, **kw: iter(["First ", "last"]))
        self.assertEqual([d["text"] for e, d in events if e == "token"], ["First ", "last"])
        result = next(d for e, d in events if e == "result")
        self.assertEqual(result["text"], "First last")
        self.assertEqual(result["model"], "ollama/test")

    def test_partial_failure_replaces_preview_with_grounded_fallback(self):
        def stream(*args, **kwargs):
            yield "Partial "
            raise RuntimeError("broken")

        events = self.events(stream)
        tokens = [d["text"] for e, d in events if e == "token"]
        self.assertEqual(tokens, ["Partial "])
        result = next(d for e, d in events if e == "result")
        self.assertEqual(result["model"], orchestrator.model_router.builtin.name)
        self.assertNotIn("Partial", result["text"])

    def test_failure_before_tokens_uses_fallback(self):
        def stream(*args, **kwargs):
            raise RuntimeError("broken")
            yield

        events = self.events(stream)
        result = next(d for e, d in events if e == "result")
        self.assertEqual("".join(d["text"] for e, d in events if e == "token"), result["text"])
        self.assertEqual(result["engine"], "builtin")

    def test_first_token_precedes_provider_completion_and_close_stops_generation(self):
        from threading import Event
        import asyncio

        completed = Event()
        closed = Event()

        def stream(messages, **kwargs):
            try:
                yield "First "
                completed.set()
                yield "last"
            finally:
                closed.set()

        probe = {"local_lfm": {"online": True, "model": "test"},
                 "cloud": {"configured": False}}
        with patch.object(orchestrator.db, "run", return_value=1), \
             patch.object(orchestrator.db, "qone", return_value={"id": "session"}), \
             patch.object(orchestrator.model_router, "probe", return_value=probe), \
             patch.object(orchestrator.model_router, "chain", return_value=["ollama", "builtin"]), \
             patch.object(orchestrator.model_router.ollama, "chat_stream", return_value=iter(["First ", "last"])), \
             patch("app.compact.session_context", return_value={"history": [], "summary": ""}), \
             patch("app.compact.maybe_compact"), \
             patch.object(orchestrator.memory_engine, "observe", return_value=[]), \
             patch.object(orchestrator.model_router.ollama, "chat_stream", return_value=iter(["First ", "last"])):

            events = []
            for e in orchestrator.run_turn("hello", "session"):
                events.append(e)
            tokens = [d["text"] for e, d in events if e == "token"]
            self.assertEqual(tokens, ["First ", "last"])


if __name__ == "__main__":
    unittest.main()