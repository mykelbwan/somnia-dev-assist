from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.exceptions import EmptyInputError
from api.streaming import stream_chat_responses

router = APIRouter()


class ChatRequest(BaseModel):
    query: str


class ChatResponse(BaseModel):
    answer: str
    exit_reason: str


@router.post("/chat/stream")
async def stream_chat(request: ChatRequest):
    """
    Handles a streaming chat request using Server-Sent Events.
    """
    if not request.query or not request.query.strip():
        # This check is done upfront for streaming to avoid starting a stream for empty input
        # A more robust implementation might yield a single error event in the stream.
        raise EmptyInputError()

    return StreamingResponse(
        stream_chat_responses(request.query),
        media_type="text/event-stream",
    )
