import random
import uuid

from locust import HttpUser, between, task


class SMPUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        # In a real scenario, we might authenticate here.
        # For these tests, we assume SMP_OPEN_MODE=1 or use a dev key.
        self.headers = {"Content-Type": "application/json"}

    def call_rpc(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": str(uuid.uuid4())}
        return self.client.post("/rpc", json=payload, headers=self.headers)

    @task(5)
    def test_navigate(self):
        # P-001: Navigate latency/throughput
        self.call_rpc("smp/navigate", {"query": "class User", "include_relationships": True})

    @task(3)
    def test_search(self):
        # P-002: Search latency/throughput
        self.call_rpc("smp/search", {"query": "auth", "match": "any", "top_k": 10})

    @task(3)
    def test_context(self):
        # P-003: Context latency/throughput
        # Assuming we have some files in the graph
        self.call_rpc("smp/context", {"file_path": "src/main.py", "scope": "function", "depth": 2})

    @task(2)
    def test_trace(self):
        # P-004: Trace latency/throughput
        self.call_rpc("smp/trace", {"start": "node_1", "relationship": "calls", "depth": 3, "direction": "out"})

    @task(2)
    def test_update(self):
        # P-005: Update latency/throughput
        self.call_rpc("smp/update", {"file_path": "src/main.py"})

    @task(2)
    def test_vector_search(self):
        # P-006: Vector search latency/throughput
        embedding = [random.uniform(-1, 1) for _ in range(1536)]
        self.call_rpc("smp/vector/search", {"embedding": embedding, "top_k": 5})

    @task(1)
    def test_vector_upsert(self):
        # P-007: Vector upsert latency/throughput
        embedding = [random.uniform(-1, 1) for _ in range(1536)]
        self.call_rpc(
            "smp/vector/upsert",
            {
                "ids": [str(uuid.uuid4())],
                "embeddings": [embedding],
                "metadatas": [{"type": "code_chunk"}],
                "documents": ["some code snippet"],
            },
        )

    @task(1)
    def test_batch_update(self):
        # P-008: Batch update latency/throughput
        self.call_rpc("smp/batch_update", {"changes": [{"file_path": "src/main.py"}, {"file_path": "src/utils.py"}]})
