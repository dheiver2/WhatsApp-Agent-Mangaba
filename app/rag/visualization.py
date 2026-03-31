"""RAG Knowledge Base visualization data endpoints."""

from app.rag.vectorstore import get_vectorstore

COLOR_PALETTE = [
    "#3b82f6",
    "#ef4444",
    "#22c55e",
    "#f59e0b",
    "#8b5cf6",
    "#ec4899",
    "#06b6d4",
    "#f97316",
]


def get_all_chunks() -> list[dict]:
    """Get all chunks from the local knowledge base."""
    vectorstore = get_vectorstore()
    chunks = vectorstore.all_chunks()

    items = []
    for chunk in chunks:
        text = chunk.text
        items.append(
            {
                "id": chunk.id,
                "text": text,
                "source": chunk.metadata.get("source", ""),
                "chunk_index": chunk.metadata.get("chunk_index", 0),
                "text_preview": (text[:120] + "...") if len(text) > 120 else text,
                "char_count": len(text),
            }
        )

    return items


def get_graph_data(similarity_threshold: float = 0.55) -> dict:
    """Build a graph where nodes are chunks and edges are similarity connections."""
    vectorstore = get_vectorstore()
    chunks = vectorstore.all_chunks()

    if not chunks:
        return {"nodes": [], "edges": [], "stats": {}}

    sources = sorted({chunk.metadata.get("source", "") for chunk in chunks})
    source_colors = {
        source: COLOR_PALETTE[index % len(COLOR_PALETTE)]
        for index, source in enumerate(sources)
    }

    nodes = []
    for chunk in chunks:
        source = chunk.metadata.get("source", "")
        text = chunk.text
        nodes.append(
            {
                "id": chunk.id,
                "label": f"{source.replace('.txt', '')}#{chunk.metadata.get('chunk_index', 0)}",
                "source": source,
                "color": source_colors.get(source, "#6b7280"),
                "text_preview": (text[:100] + "...") if len(text) > 100 else text,
                "char_count": len(text),
                "group": sources.index(source) if source in sources else 0,
            }
        )

    edges = []
    for left, right, similarity in vectorstore.get_similarity_pairs(similarity_threshold):
        edges.append(
            {
                "source": left.id,
                "target": right.id,
                "similarity": round(float(similarity), 4),
                "same_source": left.metadata.get("source") == right.metadata.get("source"),
            }
        )

    stats = {
        "total_chunks": len(chunks),
        "total_edges": len(edges),
        "sources": [
            {
                "name": source,
                "color": source_colors[source],
                "count": sum(1 for chunk in chunks if chunk.metadata.get("source") == source),
            }
            for source in sources
        ],
        "avg_chunk_size": round(sum(len(chunk.text) for chunk in chunks) / max(len(chunks), 1)),
        "similarity_threshold": similarity_threshold,
    }

    return {"nodes": nodes, "edges": edges, "stats": stats}


def search_with_details(query: str, top_k: int = 5) -> dict:
    """Search the knowledge base and return detailed results with scores."""
    vectorstore = get_vectorstore()
    results = vectorstore.similarity_search_with_relevance_scores(query, k=top_k)

    items = []
    for doc, score in results:
        items.append(
            {
                "text": doc.page_content,
                "source": doc.metadata.get("source", ""),
                "chunk_index": doc.metadata.get("chunk_index", 0),
                "score": round(float(score), 4),
            }
        )

    return {"query": query, "results": items, "total": len(items)}
