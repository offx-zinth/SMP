from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

import chromadb
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ProductVision(BaseModel):
    id: str
    project_name: str
    problem_statement: str
    target_users: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SystemArchitecture(BaseModel):
    id: str
    vision_id: str
    title: str
    overview: str
    api_schemas: dict[str, Any] = Field(default_factory=dict)
    data_models: dict[str, Any] = Field(default_factory=dict)
    database_schema: dict[str, Any] = Field(default_factory=dict)
    integration_points: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Epic(BaseModel):
    id: str
    vision_id: str
    title: str
    summary: str
    priority: int = 100
    status: str = "proposed"
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Ticket(BaseModel):
    id: str
    epic_id: str
    title: str
    description: str
    role: str
    status: str = "todo"
    priority: int = 100
    dependencies: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    assignee: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PullRequest(BaseModel):
    id: str
    ticket_id: str
    title: str
    description: str
    branch: str
    status: str = "open"
    files_changed: list[str] = Field(default_factory=list)
    checks: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(slots=True)
class StoredArtifact(Generic[ModelT]):
    table: str
    payload: ModelT


class CorporateMemory:
    """Virtual Jira/Confluence backed by SQLite + ChromaDB for long-lived context."""

    _TABLE_MODELS: dict[str, type[BaseModel]] = {
        "product_visions": ProductVision,
        "system_architectures": SystemArchitecture,
        "epics": Epic,
        "tickets": Ticket,
        "pull_requests": PullRequest,
    }

    def __init__(self, *, sqlite_path: str | Path, chroma_path: str | Path, collection: str = "corporate_memory") -> None:
        self._sqlite_path = Path(sqlite_path)
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._sqlite_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        self._chroma_client = chromadb.PersistentClient(path=str(Path(chroma_path)))
        self._collection = self._chroma_client.get_or_create_collection(name=collection)

        self._initialize_schema()

    def close(self) -> None:
        self._conn.close()

    def _initialize_schema(self) -> None:
        for table in self._TABLE_MODELS:
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        self._conn.commit()

    def upsert(self, artifact: BaseModel, *, table: str | None = None) -> None:
        target_table = table or self._resolve_table(type(artifact))
        payload = artifact.model_dump_json()
        timestamp = datetime.now(UTC).isoformat()

        self._conn.execute(
            f"""
            INSERT INTO {target_table}(id, payload, created_at)
            VALUES(?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at
            """,
            (str(getattr(artifact, "id")), payload, timestamp),
        )
        self._conn.commit()

        self._collection.upsert(
            ids=[f"{target_table}:{getattr(artifact, 'id')!s}"],
            documents=[payload],
            metadatas=[{"table": target_table, "id": str(getattr(artifact, "id")), "ts": timestamp}],
        )

    def get(self, table: str, artifact_id: str) -> BaseModel | None:
        model = self._TABLE_MODELS[table]
        row = self._conn.execute(f"SELECT payload FROM {table} WHERE id=?", (artifact_id,)).fetchone()
        if row is None:
            return None
        return model.model_validate_json(str(row["payload"]))

    def list(self, table: str, *, limit: int = 100) -> list[BaseModel]:
        model = self._TABLE_MODELS[table]
        rows = self._conn.execute(
            f"SELECT payload FROM {table} ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [model.model_validate_json(str(row["payload"])) for row in rows]

    def search_semantic(self, query: str, *, table: str | None = None, limit: int = 5) -> list[StoredArtifact[BaseModel]]:
        where = {"table": table} if table else None
        results = self._collection.query(query_texts=[query], n_results=limit, where=where)

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        artifacts: list[StoredArtifact[BaseModel]] = []
        for identifier, document, metadata in zip(ids, documents, metadatas, strict=False):
            table_name = str(metadata.get("table", ""))
            model = self._TABLE_MODELS.get(table_name)
            if model is None:
                logger.warning("Unknown table metadata in semantic search: %s", identifier)
                continue
            try:
                payload = model.model_validate(json.loads(str(document)))
            except Exception:  # noqa: BLE001
                logger.exception("Failed to parse semantic search document for %s", identifier)
                continue
            artifacts.append(StoredArtifact(table=table_name, payload=payload))
        return artifacts

    def _resolve_table(self, model_type: type[BaseModel]) -> str:
        for table, klass in self._TABLE_MODELS.items():
            if model_type is klass:
                return table
        raise KeyError(f"No table mapping for model type {model_type.__name__}")
