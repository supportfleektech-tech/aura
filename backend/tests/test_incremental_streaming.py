import json
import time
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
from app import orchestrator

import unittest


class _StreamHarness(unittest.TestCase):
    """Drives `run_turn` with the router stubbed and returns parsed SSE events."""

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

    def batch_ms(self, ms):
        """Pin `sse_batch_ms` for this test.

        The batching assertions below used to depend on the machine's speed: three
        tokens had to land inside one 40ms window for them to coalesce, so a
        loaded box could turn a correct implementation into a red test (and a
        slow one into a green test). Pinning the interval makes the window a
        fact of the test rather than a race.
        """
        from app import prefs

        real_get = prefs.get

        def fake_get(key):
            return ms if key == "sse_batch_ms" else real_get(key)

        self.stack.enter_context(patch("app.prefs.get", side_effect=fake_get))

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


class IncrementalTurnTest(_StreamHarness):
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
        """The first token must reach the caller before the provider finishes, and
        abandoning the turn must close the upstream stream rather than leak it."""
        import gc

        class MockStream:
            def __init__(self, items):
                self._items = list(items)
                self.closed = False
            def __iter__(self):
                return iter(self._items)
            def close(self):
                self.closed = True

        stream = MockStream(["First ", "last"])
        with patch.object(orchestrator.model_router.ollama, "chat_stream",
                          return_value=stream):
            gen = orchestrator.run_turn("hello", "session")
            # Consume only up to and including the first token, then hang up.
            for chunk in gen:
                if chunk.startswith("event: token"):
                    self.assertIn("First ", chunk)
                    break
            else:
                self.fail("no token event was streamed")
            self.assertFalse(stream.closed, "stream closed before the turn finished")
            gen.close()  # client hung up mid-turn

        gc.collect()
        self.assertTrue(stream.closed,
                        "closing the turn must release the upstream LLM connection")


class TokenBatchingTest(unittest.TestCase):
    def test_the_first_token_flushes_immediately_then_the_interval_applies(self):
        """The first token must not wait out an interval: buffering it would put
        the first visible token behind the model's time-to-first-token."""
        from app.orchestrator import TokenBatcher
        b = TokenBatcher(min_interval_s=0.05)
        self.assertEqual(b.add("a"), "a", "the first token flushes at once")
        self.assertEqual(b.add("b"), "", "a token inside the interval waits")
        time.sleep(0.06)
        self.assertEqual(b.add("c"), "bc", "a token past the interval flushes the buffer plus itself")
        self.assertEqual(b.flush(), "", "buffer was already flushed")

    def test_flush_emits_the_remainder(self):
        from app.orchestrator import TokenBatcher
        b = TokenBatcher(min_interval_s=60.0)
        self.assertEqual(b.add("x"), "x", "the first token flushes at once")
        self.assertEqual(b.add("y"), "", "the second waits out a 60s interval")
        self.assertEqual(b.flush(), "y")
        self.assertEqual(b.flush(), "", "flush must be idempotent")

    def test_flush_on_empty_buffer_is_empty(self):
        from app.orchestrator import TokenBatcher
        self.assertEqual(TokenBatcher().flush(), "")

    def test_concatenated_batches_equal_the_original_text(self):
        from app.orchestrator import TokenBatcher
        b = TokenBatcher(min_interval_s=60.0)  # a real interval, not the 0.0 shortcut
        toks = ["Hello", ",", " ", "world", "!"]
        out = [b.add(t) for t in toks]
        out.append(b.flush())
        self.assertEqual("".join(p for p in out if p), "".join(toks))
        self.assertEqual(len([p for p in out if p]), 2,
                         "5 tokens inside one interval must coalesce — if this fails the "
                         "batcher is ignoring _min and the equality above proves nothing")

    def test_zero_interval_emits_one_payload_per_token(self):
        """sse_batch_ms=0 must restore the unbatched behaviour exactly."""
        from app.orchestrator import TokenBatcher
        b = TokenBatcher(min_interval_s=0.0)
        self.assertEqual([b.add(t) for t in ("a", "b")], ["a", "b"])
        # …and the same tokens under a real interval coalesce, so this pair shows
        # `_min` is read rather than ignored: a batcher that ignored it would pass
        # the first half of this test on its own.
        slow = TokenBatcher(min_interval_s=60.0)
        self.assertEqual([slow.add(t) for t in ("a", "b")], ["a", ""])
        self.assertEqual(slow.flush(), "b")


class StreamedTokensAreNeverDroppedTest(_StreamHarness):
    """Whatever the batcher is doing, the client must end up with every token the
    model produced — including when the stream dies mid-answer."""

    def test_a_stream_that_dies_mid_answer_still_flushes_its_partial_batch(self):
        self.batch_ms(5000)  # "bb" is guaranteed to still be buffered at the crash

        def stream(*args, **kwargs):
            yield "aa"
            yield "bb"  # these two sit inside the batch interval
            raise RuntimeError("broken")

        events = self.events(stream)
        streamed = "".join(d["text"] for e, d in events if e == "token")
        self.assertEqual(streamed, "aabb", "a token already received must never be dropped")

    def test_fast_stream_collapses_into_one_event(self):
        """The point of the feature: a burst of tokens inside one interval
        becomes one frame, and nothing is lost doing it."""
        self.batch_ms(5000)  # the whole burst is inside one window by construction

        def stream(*args, **kwargs):
            for tok in ("one ", "two ", "three"):
                yield tok

        events = self.events(stream)
        payloads = [d["text"] for e, d in events if e == "token"]
        self.assertEqual(payloads, ["one ", "two three"],
                         "3 tokens must become 2 frames, not 3")
        result = next(d for e, d in events if e == "result")
        self.assertEqual(result["text"], "one two three")

    def test_slow_stream_still_emits_each_token_as_it_arrives(self):
        """Batching must never delay a token that has already waited longer than
        the interval — that is what a typewriter effect needs to look continuous.

        The second half is the non-vacuity check: the same three tokens arriving
        instantly, under a long pinned interval, *do* collapse. Without it this
        test would also pass against a batcher that ignored `_min` and emitted
        every token on arrival.
        """
        self.batch_ms(5)  # pinned well under the 60ms gap below

        def stream(*args, **kwargs):
            for tok in ("one ", "two ", "three"):
                yield tok
                time.sleep(0.06)

        payloads = [d["text"] for e, d in self.events(stream) if e == "token"]
        self.assertEqual(payloads, ["one ", "two ", "three"])

        def burst(*args, **kwargs):
            for tok in ("one ", "two ", "three"):
                yield tok

        self.batch_ms(5000)
        collapsed = [d["text"] for e, d in self.events(burst) if e == "token"]
        self.assertEqual(collapsed, ["one ", "two three"],
                         "the interval was ignored — the test above proves nothing")


if __name__ == "__main__":
    unittest.main()
