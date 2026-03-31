from app.rag.types import Document
from app.rag.vectorstore import get_vectorstore


def retrieve_context(query: str, top_k: int = 4) -> list[Document]:
    """Search the local knowledge base."""
    vectorstore = get_vectorstore()
    return vectorstore.similarity_search(query, k=top_k)


def retrieve_context_with_scores(query: str, top_k: int = 4) -> list[tuple[Document, float]]:
    """Search the local knowledge base returning relevance scores."""
    vectorstore = get_vectorstore()
    return vectorstore.similarity_search_with_relevance_scores(query, k=top_k)


def format_context(docs: list[Document]) -> str:
    """Format retrieved documents into a context string for the LLM."""
    parts = []
    for doc in docs:
        source = doc.metadata.get("source", "desconhecido")
        parts.append(f"[Fonte: {source}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)
