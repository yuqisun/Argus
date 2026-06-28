"""Verify all Protocol interfaces can be implemented by concrete classes."""
from argus.interfaces.llm import LLMClient
from argus.interfaces.notifier import Notifier, Notification
from argus.interfaces.log_source import LogSource
from argus.interfaces.event_bus import EventBus
from argus.interfaces.code_search import CodeSearcher
from argus.interfaces.owner_resolver import OwnerResolver, OwnerResult
from argus.interfaces.fingerprinter import Fingerprinter, Fingerprint
from argus.models.event import AnomalyEvent, RawEvent


class TestProtocols:
    """Verify all Protocols can be implemented by concrete classes."""

    def test_llm_client_is_implementable(self):
        class FakeLLM(LLMClient):
            async def chat(self, messages, *, model=None, max_tokens=4096, temperature=0.1):
                return "response"
            async def chat_stream(self, messages, *, model=None, max_tokens=4096):
                yield "response"

        client = FakeLLM()
        assert isinstance(client, LLMClient)

    def test_notifier_is_implementable(self):
        class FakeNotifier(Notifier):
            @property
            def channel_name(self):
                return "fake"
            async def send(self, notification):
                return True

        notifier = FakeNotifier()
        assert isinstance(notifier, Notifier)

    def test_event_bus_is_implementable(self):
        class FakeBus(EventBus):
            async def publish(self, event, priority):
                return "msg-001"
            async def consume(self, priority):
                if False:
                    yield  # pragma: no cover
            async def dead_letter(self, event, reason):
                pass

        bus = FakeBus()
        assert isinstance(bus, EventBus)

    def test_code_searcher_is_implementable(self):
        class FakeSearcher(CodeSearcher):
            async def grep(self, repo, pattern, *, commit, glob=None):
                return []
            async def find_definition(self, repo, symbol, *, commit):
                return None
            async def get_call_graph(self, repo, function, *, commit, depth=2):
                return None
            async def blame(self, repo, file_path, line_number, *, commit):
                return ("dev@co.com", "abc123")

        searcher = FakeSearcher()
        assert isinstance(searcher, CodeSearcher)

    def test_owner_resolver_is_implementable(self):
        class FakeResolver(OwnerResolver):
            async def resolve(self, repo, file_path, line_number, *, commit):
                return [OwnerResult(name="Dev", email="dev@co.com", source="blame", confidence=0.8)]

        resolver = FakeResolver()
        assert isinstance(resolver, OwnerResolver)

    def test_fingerprinter_is_implementable(self):
        class FakeFP(Fingerprinter):
            def fingerprint(self, event):
                return Fingerprint(hash="abc", exception_type="ValueError", template_message="x", top_frames=["a"])
            def is_same_group(self, fp1, fp2):
                return fp1.hash == fp2.hash

        fp_impl = FakeFP()
        isinstance(fp_impl, Fingerprinter)

    def test_interfaces_import_models_not_redefine(self):
        """Verify RawEvent/AnomalyEvent come from models, not redefined in interfaces."""
        from argus.models.event import RawEvent as ModelRaw
        from argus.models.event import AnomalyEvent as ModelAnomaly
        from argus.interfaces.log_source import RawEvent as InterfaceRaw
        from argus.interfaces.event_bus import AnomalyEvent as InterfaceAnomaly
        # Both references should point to the same class
        assert ModelRaw is InterfaceRaw
        assert ModelAnomaly is InterfaceAnomaly
