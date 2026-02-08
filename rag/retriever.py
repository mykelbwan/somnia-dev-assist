from config import MAX_CONTEXT_CHARS, MAX_DOC_CHARS, MAX_RETRIEVED_DOCS
from langchain_chroma import Chroma
from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from settings import GEMINI_API_KEY, Collection_Name, DB_Dir

"""Commented out code cause the model is not available on my api key as i am not subscribed"""
# _embeddings = GoogleGenerativeAIEmbeddings(
#     model="models/text-embedding-004",
#     api_key=GEMINI_API_KEY,
#     task_type="retrieval_document",  # Helps the model understand this is for storage
#     request_options={"timeout": 60},  # increase timeout
# )

_embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001", api_key=GEMINI_API_KEY
)

_vector_store = Chroma(
    collection_name=Collection_Name,
    embedding_function=_embeddings,
    persist_directory=DB_Dir,
)

_retriever = _vector_store.as_retriever(
    search_type="mmr",
    search_kwargs={"k": 5, "fetch_k": 20},
)


@tool
def retriever(query: str) -> str:
    """
    Retrieves and formats relevant document snippets from the vector store based on the given query.

    This function performs a Maximum Marginal Relevance (MMR) search to identify the most
    pertinent documents. It iterates through the results, truncating individual page
    content and enforcing global character limits to ensure the final output fits within
    the context window constraints. Each snippet is formatted with its index and source
    metadata for attribution.

    Args:
                                    query (str): The search query used to find relevant information in the database.

    Returns:
                                    str: A formatted string of document results, or "DOCUMENTATION_SEARCH_RESULT: EMPTY"
                                                                    if no matches are found.
    """
    docs = _retriever.invoke(query)

    if not docs:
        return "DOCUMENTATION_SEARCH_RESULT: EMPTY"

    results = []
    total_chars = 0

    for i, doc in enumerate(docs[:MAX_RETRIEVED_DOCS]):
        content = doc.page_content[:MAX_DOC_CHARS]
        block = f"[{i + 1}] SOURCE: {doc.metadata.get('source', 'unknown')}\n{content}"

        if total_chars + len(block) > MAX_CONTEXT_CHARS:
            break

        results.append(block)
        total_chars += len(block)

    return "\n\n".join(results)
