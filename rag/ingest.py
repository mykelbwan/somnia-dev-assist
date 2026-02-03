import os

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from retriever import _vector_store
from settings import Docs_Dir


def ingest():
    """Ingests documents from the directory into the vector store."""
    existing = _vector_store.get(include=[])
    if len(existing["ids"]) > 0:
        print("Documents already exist in the vector store.")
        return

    documents = []
    for filename in os.listdir(Docs_Dir):
        if filename.endswith(".md"):
            loader = TextLoader(os.path.join(Docs_Dir, filename), encoding="utf-8")
            documents.extend(loader.load())

    if not documents:
        raise RuntimeError("No documents found in the directory.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = splitter.split_documents(documents)
    _vector_store.add_documents(docs)

    print(f"Ingesting {len(docs)} chunks successful.")


if __name__ == "__main__":
    ingest()
