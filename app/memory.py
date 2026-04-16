from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _embed(text: str) -> Dict[str, float]:
    tokens = _tokenize(text)
    counts = Counter(tokens)
    total = max(sum(counts.values()), 1)
    return {token: value / total for token, value in counts.items()}


def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0.0) for k in a)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class MemoryMatch:
    source: str
    destination: str
    recommended_mode: str
    reason: str
    score: float
    created_at: str


class MemoryStore:
    """SQLite-backed long-term memory with simple vector similarity."""

    def __init__(self, db_path: str = "memory/route_memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trip_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                recommended_mode TEXT NOT NULL,
                reason TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def save_trip(self, source: str, destination: str, recommended_mode: str, reason: str) -> None:
        memory_text = f"{source} {destination} {recommended_mode} {reason}"
        embedding = _embed(memory_text)
        self.conn.execute(
            """
            INSERT INTO trip_memory (source, destination, recommended_mode, reason, embedding_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                destination,
                recommended_mode,
                reason,
                json.dumps(embedding),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def find_similar(self, source: str, destination: str, top_k: int = 3) -> List[MemoryMatch]:
        query_embedding = _embed(f"{source} {destination}")
        rows = self.conn.execute(
            """
            SELECT source, destination, recommended_mode, reason, embedding_json, created_at
            FROM trip_memory
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()

        scored: List[MemoryMatch] = []
        for row in rows:
            source_r, dest_r, mode_r, reason_r, emb_json, created_at = row
            memory_embedding = json.loads(emb_json)
            score = _cosine_similarity(query_embedding, memory_embedding)
            if score > 0.15:
                scored.append(
                    MemoryMatch(
                        source=source_r,
                        destination=dest_r,
                        recommended_mode=mode_r,
                        reason=reason_r,
                        score=score,
                        created_at=created_at,
                    )
                )
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]
