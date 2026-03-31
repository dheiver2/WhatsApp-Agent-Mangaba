#!/usr/bin/env python3
"""Seed script - loads knowledge base documents into the local index.

Usage:
    python scripts/seed_knowledge.py
    python scripts/seed_knowledge.py --reset
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.rag.vectorstore import get_vectorstore, load_knowledge_base


def main() -> None:
    reset = "--reset" in sys.argv

    settings = get_settings()
    print(f"[Seed] Knowledge dir: {settings.knowledge_dir}")
    print(f"[Seed] Local index dir: {settings.chroma_persist_dir}")

    vectorstore = get_vectorstore()
    if reset:
        print("[Seed] Resetting local index...")
        vectorstore.clear()

    print("[Seed] Loading knowledge base...")
    load_knowledge_base()
    print("[Seed] Done!")

    existing = vectorstore.get()
    count = len(existing["ids"]) if existing and existing.get("ids") else 0
    print(f"[Seed] Total chunks in store: {count}")

    if count > 0:
        print("\n[Seed] Test query: 'como tratar objeção de cancelamento'")
        results = vectorstore.similarity_search("como tratar objeção de cancelamento", k=2)
        for index, doc in enumerate(results, start=1):
            print(f"\n  Result {index} [{doc.metadata.get('source')}]:")
            print(f"  {doc.page_content[:150]}...")


if __name__ == "__main__":
    main()
