import os

from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY is not None:
    GEMINI_API_KEY = SecretStr(GEMINI_API_KEY)
else:
    GEMINI_API_KEY = None
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set")

Docs_Dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"
)
if not os.path.exists(Docs_Dir):
    raise RuntimeError(f"Docs directory {Docs_Dir} does not exist.")

DB_Dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
if not os.path.exists(DB_Dir):
    os.makedirs(DB_Dir)

Collection_Name = "somnia_dev_assist"
