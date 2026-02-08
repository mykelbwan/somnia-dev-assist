MAX_CONTEXT_CHARS = 12_000  # conservative for Gemini Flash
MAX_DOC_CHARS = 2_000
MAX_RETRIEVED_DOCS = 4
MAX_TURNS = 6
MAX_TOOL_CALL = 3

# Configuration for Free Tier Rate Limiting
# Limit is 100 requests per minute.
# Safe setting: 10 docs every 7 seconds = ~85 requests/minute (safe buffer)
BATCH_SIZE = 10
SLEEP_TIME = 7
