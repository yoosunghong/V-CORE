from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = BASE_DIR / "seeds"
VECTOR_SIZE = 768


def deterministic_vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < VECTOR_SIZE:
        for byte in digest:
            values.append(round((byte / 255.0) * 2.0 - 1.0, 6))
            if len(values) == VECTOR_SIZE:
                break
        digest = hashlib.sha256(digest).digest()
    return values


def load_documents() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    with (SEED_DIR / "rag_documents.jsonl").open(encoding="utf-8") as file:
        for line in file:
            docs.append(json.loads(line))
    return docs


def build_points() -> dict[str, Any]:
    points = []
    for index, document in enumerate(load_documents(), start=1):
        text = document.pop("text")
        points.append(
            {
                "id": index,
                "vector": deterministic_vector(text),
                "payload": {**document, "text": text},
            }
        )
    return {"points": points}


def main() -> None:
    print(json.dumps(build_points(), ensure_ascii=False))


if __name__ == "__main__":
    main()
