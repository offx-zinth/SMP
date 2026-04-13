"""Integration tests for SMP Protocol Handlers via the dispatcher."""

from __future__ import annotations

from smp.protocol.dispatcher import RpcDispatcher
from smp.protocol.handlers.annotation import (
    AnnotateBulkHandler,
    AnnotateHandler,
    TagHandler,
)
from smp.protocol.handlers.community import (
    CommunityBoundariesHandler,
    CommunityDetectHandler,
    CommunityGetHandler,
    CommunityListHandler,
)
from smp.protocol.handlers.enrichment import (
    EnrichBatchHandler,
    EnrichHandler,
    EnrichStaleHandler,
    EnrichStatusHandler,
)
from smp.protocol.handlers.handoff import (
    HandoffPRHandler,
    HandoffReviewHandler,
)
from smp.protocol.handlers.memory import (
    BatchUpdateHandler,
    ReindexHandler,
    UpdateHandler,
)
from smp.protocol.handlers.merkle import (
    IndexExportHandler,
    IndexImportHandler,
    MerkleTreeHandler,
    SyncHandler,
)
from smp.protocol.handlers.query import (
    ContextHandler,
    FlowHandler,
    ImpactHandler,
    LocateHandler,
    NavigateHandler,
    SearchHandler,
    TraceHandler,
)
from smp.protocol.handlers.safety import (
    AuditGetHandler,
    CheckpointHandler,
    DryRunHandler,
    GuardCheckHandler,
    IntegrityVerifyHandler,
    LockHandler,
    RollbackHandler,
    SessionCloseHandler,
    SessionOpenHandler,
    SessionRecoverHandler,
    UnlockHandler,
)
from smp.protocol.handlers.sandbox import (
    SandboxDestroyHandler,
    SandboxExecuteHandler,
    SandboxSpawnHandler,
)
from smp.protocol.handlers.telemetry import (
    TelemetryHandler,
    TelemetryHotHandler,
    TelemetryNodeHandler,
    TelemetryRecordHandler,
)


class TestHandlerRegistration:
    """Test that all registered handlers are reachable."""

    def test_all_registered_handlers_have_valid_method(self):
        """Each handler in dispatcher must have a valid non-empty method name."""
        dispatcher = RpcDispatcher()
        for method, handler in dispatcher._handlers.items():
            assert method, f"Handler {handler.__class__.__name__} has empty method"
            assert isinstance(method, str), f"Handler method must be str, got {type(method)}"
            assert handler.method == method, (
                f"Handler method mismatch: expected '{method}', "
                f"got '{handler.method}' from {handler.__class__.__name__}"
            )


class TestHandlerInstantiation:
    """Test each handler class can be instantiated without errors."""

    def test_safety_handlers(self):
        """Safety handlers can be instantiated."""
        handlers = [
            SessionOpenHandler,
            SessionCloseHandler,
            SessionRecoverHandler,
            GuardCheckHandler,
            DryRunHandler,
            CheckpointHandler,
            RollbackHandler,
            LockHandler,
            UnlockHandler,
            AuditGetHandler,
            IntegrityVerifyHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_query_handlers(self):
        """Query handlers can be instantiated."""
        handlers = [
            NavigateHandler,
            TraceHandler,
            ContextHandler,
            ImpactHandler,
            LocateHandler,
            SearchHandler,
            FlowHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_community_handlers(self):
        """Community handlers can be instantiated."""
        handlers = [
            CommunityDetectHandler,
            CommunityListHandler,
            CommunityGetHandler,
            CommunityBoundariesHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_merkle_handlers(self):
        """Merkle handlers can be instantiated."""
        handlers = [
            SyncHandler,
            MerkleTreeHandler,
            IndexExportHandler,
            IndexImportHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_handoff_handlers(self):
        """Handoff handlers can be instantiated."""
        handlers = [
            HandoffReviewHandler,
            HandoffPRHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_enrichment_handlers(self):
        """Enrichment handlers can be instantiated."""
        handlers = [
            EnrichHandler,
            EnrichBatchHandler,
            EnrichStaleHandler,
            EnrichStatusHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_annotation_handlers(self):
        """Annotation handlers can be instantiated."""
        handlers = [
            AnnotateHandler,
            AnnotateBulkHandler,
            TagHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_memory_handlers(self):
        """Memory handlers can be instantiated."""
        handlers = [
            UpdateHandler,
            BatchUpdateHandler,
            ReindexHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_sandbox_handlers(self):
        """Sandbox handlers can be instantiated."""
        handlers = [
            SandboxSpawnHandler,
            SandboxExecuteHandler,
            SandboxDestroyHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"

    def test_telemetry_handlers(self):
        """Telemetry handlers can be instantiated."""
        handlers = [
            TelemetryHandler,
            TelemetryHotHandler,
            TelemetryNodeHandler,
            TelemetryRecordHandler,
        ]
        for handler_cls in handlers:
            handler = handler_cls()
            assert handler.method.startswith("smp/"), f"{handler_cls.__name__} has invalid method: {handler.method}"


class TestDispatcherHandlerDiscovery:
    """Test that all expected handlers are registered in the dispatcher."""

    def test_safety_handlers_registered(self):
        """All safety handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/session/open",
            "smp/session/close",
            "smp/session/recover",
            "smp/guard/check",
            "smp/dryrun",
            "smp/checkpoint",
            "smp/rollback",
            "smp/lock",
            "smp/unlock",
            "smp/audit/get",
            "smp/verify/integrity",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_query_handlers_registered(self):
        """All query handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/navigate",
            "smp/trace",
            "smp/context",
            "smp/impact",
            "smp/locate",
            "smp/search",
            "smp/flow",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_community_handlers_registered(self):
        """All community handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/community/detect",
            "smp/community/list",
            "smp/community/get",
            "smp/community/boundaries",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_merkle_handlers_registered(self):
        """All merkle handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/sync",
            "smp/merkle/tree",
            "smp/index/export",
            "smp/index/import",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_handoff_handlers_registered(self):
        """All handoff handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/handoff/review",
            "smp/handoff/pr",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_enrichment_handlers_registered(self):
        """All enrichment handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/enrich",
            "smp/enrich/batch",
            "smp/enrich/stale",
            "smp/enrich/status",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_annotation_handlers_registered(self):
        """All annotation handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/annotate",
            "smp/annotate/bulk",
            "smp/tag",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_memory_handlers_registered(self):
        """All memory handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/update",
            "smp/batch_update",
            "smp/reindex",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_sandbox_handlers_registered(self):
        """All sandbox handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/sandbox/spawn",
            "smp/sandbox/execute",
            "smp/sandbox/destroy",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"

    def test_telemetry_handlers_registered(self):
        """All telemetry handlers are registered in dispatcher."""
        dispatcher = RpcDispatcher()
        expected_methods = [
            "smp/telemetry",
            "smp/telemetry/hot",
            "smp/telemetry/node",
            "smp/telemetry/record",
        ]
        for method in expected_methods:
            assert dispatcher.get_handler(method) is not None, f"Missing handler for {method}"
