import os
import time

from config import BATCH_SIZE, SLEEP_TIME
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from retriever import _vector_store
from settings import Docs_Dir


def batch_add_documents(vector_store, documents):
    """Adds documents to vector store in batches to respect API rate limits."""
    total_docs = len(documents)

    for i in range(0, total_docs, BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total_docs + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} chunks)...")

        try:
            vector_store.add_documents(batch)
            print(f"  - Success. Sleeping for {SLEEP_TIME}s...")
            time.sleep(SLEEP_TIME)
        except Exception as e:
            print(f"  - Error in batch {batch_num}: {e}")
            # Optional: Add a longer sleep here if you want to retry automatically
            # time.sleep(60)


def ingest():
    """Ingests documents from the directory into the vector store."""
    existing = _vector_store.get(include=[])
    if len(existing["ids"]) > 0:
        print("Documents already exist in the vector store.")
        return

    documents = []
    print(f"Loading documents from {Docs_Dir}...")
    for filename in os.listdir(Docs_Dir):
        if filename.endswith(".md"):
            try:
                loader = TextLoader(os.path.join(Docs_Dir, filename), encoding="utf-8")
                documents.extend(loader.load())
            except Exception as e:
                print(f"Error loading {filename}: {e}")

    if not documents:
        raise RuntimeError("No documents found in the directory.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = splitter.split_documents(documents)

    print(f"Total chunks created: {len(docs)}")
    print("Starting batched ingestion...")

    # Use the new batching function instead of adding all at once
    batch_add_documents(_vector_store, docs)

    print("Ingestion complete.")


if __name__ == "__main__":
    ingest()
