import json
from dataclasses import asdict
from pathlib import Path

from app.config import get_settings
from app.rag.embeddings import (
    build_idf_map,
    build_weighted_vector,
    cosine_similarity,
    normalize_text,
    overlap_ratio,
    tokenize_text,
    vector_norm,
)
from app.rag.types import Document, StoredChunk

_vectorstore = None


def _split_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
    separators: tuple[str, ...] = ("\n\n", "\n", ". ", " "),
) -> list[str]:
    content = text.strip()
    if not content:
        return []

    del chunk_overlap

    def split_large_piece(piece: str) -> list[str]:
        remaining = piece.strip()
        result: list[str] = []
        while len(remaining) > chunk_size:
            split_at = -1
            for separator in separators[1:]:
                candidate = remaining.rfind(separator, 0, chunk_size)
                if candidate > chunk_size // 2:
                    split_at = candidate + len(separator)
                    break
            if split_at == -1:
                split_at = chunk_size
            result.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            result.append(remaining)
        return result

    units: list[str] = []
    for paragraph in (part.strip() for part in content.split("\n\n")):
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
        else:
            units.extend(split_large_piece(paragraph))

    chunks: list[str] = []
    current_parts: list[str] = []
    current_size = 0

    for unit in units:
        separator_size = 2 if current_parts else 0
        candidate_size = current_size + separator_size + len(unit)
        if current_parts and candidate_size > chunk_size:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = [unit]
            current_size = len(unit)
            continue

        current_parts.append(unit)
        current_size = candidate_size

    if current_parts:
        chunks.append("\n\n".join(current_parts).strip())

    return chunks


class LocalVectorStore:
    def __init__(self, persist_directory: str):
        self.persist_directory = Path(persist_directory)
        self.index_path = self.persist_directory / "knowledge_index.json"
        self._chunks: list[StoredChunk] = []
        self._vectors: list[dict[str, float]] = []
        self._norms: list[float] = []
        self._tokens: list[list[str]] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        if self.index_path.exists():
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._chunks = [
                StoredChunk(
                    id=item["id"],
                    text=item["text"],
                    metadata=item.get("metadata", {}),
                )
                for item in payload.get("chunks", [])
            ]

        self._rebuild_cache()
        self._loaded = True

    def _rebuild_cache(self) -> None:
        token_lists = [tokenize_text(chunk.text) for chunk in self._chunks]
        idf_map = build_idf_map(token_lists)
        self._tokens = token_lists
        self._vectors = [build_weighted_vector(tokens, idf_map) for tokens in token_lists]
        self._norms = [vector_norm(vector) for vector in self._vectors]

    def _persist(self) -> None:
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        payload = {"chunks": [asdict(chunk) for chunk in self._chunks]}
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def clear(self) -> None:
        self._ensure_loaded()
        self._chunks = []
        self._rebuild_cache()
        self._persist()

    def get(self, include: list[str] | None = None) -> dict:
        self._ensure_loaded()
        include_set = set(include or ["documents", "metadatas"])
        data = {"ids": [chunk.id for chunk in self._chunks]}
        if "documents" in include_set:
            data["documents"] = [chunk.text for chunk in self._chunks]
        if "metadatas" in include_set:
            data["metadatas"] = [dict(chunk.metadata) for chunk in self._chunks]
        return data

    def add_documents(self, docs: list[Document]) -> None:
        self._ensure_loaded()
        known_ids = {chunk.id for chunk in self._chunks}

        for doc in docs:
            source = str(doc.metadata.get("source", "knowledge"))
            chunk_index = int(doc.metadata.get("chunk_index", 0))
            base_id = f"{source}:{chunk_index}"
            chunk_id = base_id
            suffix = 1
            while chunk_id in known_ids:
                chunk_id = f"{base_id}:{suffix}"
                suffix += 1
            known_ids.add(chunk_id)
            self._chunks.append(
                StoredChunk(
                    id=chunk_id,
                    text=doc.page_content,
                    metadata=dict(doc.metadata),
                )
            )

        self._rebuild_cache()
        self._persist()

    def delete(self, ids: list[str]) -> None:
        self._ensure_loaded()
        ids_set = set(ids)
        self._chunks = [chunk for chunk in self._chunks if chunk.id not in ids_set]
        self._rebuild_cache()
        self._persist()

    def all_chunks(self) -> list[StoredChunk]:
        self._ensure_loaded()
        return [StoredChunk(id=chunk.id, text=chunk.text, metadata=dict(chunk.metadata)) for chunk in self._chunks]

    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        return [doc for doc, _score in self.similarity_search_with_relevance_scores(query, k=k)]

    def similarity_search_with_relevance_scores(
        self,
        query: str,
        k: int = 4,
    ) -> list[tuple[Document, float]]:
        self._ensure_loaded()
        if not self._chunks:
            return []

        query_tokens = tokenize_text(query)
        idf_map = build_idf_map(self._tokens + [query_tokens])
        query_vector = build_weighted_vector(query_tokens, idf_map)
        query_norm = vector_norm(query_vector)
        normalized_query = normalize_text(query)

        scored_items: list[tuple[Document, float]] = []
        for index, chunk in enumerate(self._chunks):
            doc_vector = build_weighted_vector(self._tokens[index], idf_map)
            doc_norm = vector_norm(doc_vector)
            cosine = cosine_similarity(query_vector, doc_vector, query_norm, doc_norm)
            overlap = overlap_ratio(query_tokens, self._tokens[index])
            phrase_bonus = 0.08 if normalized_query and normalized_query in normalize_text(chunk.text) else 0.0
            score = min(1.0, cosine * 0.78 + overlap * 0.22 + phrase_bonus)
            scored_items.append((chunk.to_document(), score))

        scored_items.sort(key=lambda item: item[1], reverse=True)
        return scored_items[:k]

    def get_similarity_pairs(self, threshold: float = 0.0) -> list[tuple[StoredChunk, StoredChunk, float]]:
        self._ensure_loaded()
        pairs: list[tuple[StoredChunk, StoredChunk, float]] = []
        for left_index, left_chunk in enumerate(self._chunks):
            for right_index in range(left_index + 1, len(self._chunks)):
                right_chunk = self._chunks[right_index]
                similarity = cosine_similarity(
                    self._vectors[left_index],
                    self._vectors[right_index],
                    self._norms[left_index],
                    self._norms[right_index],
                )
                if similarity >= threshold:
                    pairs.append(
                        (
                            StoredChunk(id=left_chunk.id, text=left_chunk.text, metadata=dict(left_chunk.metadata)),
                            StoredChunk(id=right_chunk.id, text=right_chunk.text, metadata=dict(right_chunk.metadata)),
                            similarity,
                        )
                    )
        return pairs


def get_vectorstore() -> LocalVectorStore:
    global _vectorstore
    if _vectorstore is None:
        settings = get_settings()
        _vectorstore = LocalVectorStore(settings.chroma_persist_dir)
    return _vectorstore


def load_knowledge_base() -> None:
    """Load all .txt files from the knowledge directory into the local index."""
    settings = get_settings()
    knowledge_dir = Path(settings.knowledge_dir)
    vectorstore = get_vectorstore()

    existing = vectorstore.get()
    if existing.get("ids"):
        print(f"[RAG] Knowledge base already loaded ({len(existing['ids'])} chunks)")
        return

    all_docs: list[Document] = []
    for txt_file in sorted(knowledge_dir.glob("*.txt")):
        content = txt_file.read_text(encoding="utf-8")
        chunks = _split_text(content)
        for chunk_index, chunk in enumerate(chunks):
            all_docs.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "source": txt_file.name,
                        "chunk_index": chunk_index,
                    },
                )
            )

    if all_docs:
        vectorstore.add_documents(all_docs)
        print(
            f"[RAG] Loaded {len(all_docs)} chunks from "
            f"{len(list(knowledge_dir.glob('*.txt')))} files"
        )
    else:
        print("[RAG] No knowledge files found")
