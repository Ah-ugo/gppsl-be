"""Text chunking + embeddings. Gemini embeddings when GOOGLE_API_KEY is set, otherwise a local deterministic
hashing embedding (clearly a fallback: good for keyword-ish similarity, not semantic). Cosine similarity runs in Python,
which is fine at this size; swap in Atlas Vector Search later without changing callers."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Optional

LOCAL_DIM = 256
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were", "be", "by", "with", "at", "as", "it", "this", "that"}


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):  # prefer to break at a sentence or space
            cut = max(text.rfind(". ", start, end), text.rfind(" ", start, end))
            if cut > start + size // 2:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def local_embed(text: str) -> list[float]:
    vec = [0.0] * LOCAL_DIM
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]
    for w in words:
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        vec[h % LOCAL_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


async def embed(text: str, api_key: str = "", model: str = "models/text-embedding-004") -> tuple[list[float], str]:
    """Returns (vector, provider). Falls back to local on any failure so uploads never break."""
    if api_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/{model}:embedContent", params={"key": api_key},
                                 json={"content": {"parts": [{"text": text[:8000]}]}})
                r.raise_for_status()
            return r.json()["embedding"]["values"], "gemini"
        except Exception:  # noqa: BLE001
            pass
    return local_embed(text), "local"
