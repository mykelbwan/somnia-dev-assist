from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from api.routes.chat import router as chat_router
from api.exceptions import APIError

app = FastAPI(
    title="Somnia RAG API",
    description="An API for interacting with the Somnia RAG agent.",
    version="0.1.0",
)

@app.exception_handler(APIError)
async def api_exception_handler(request: Request, exc: APIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )

app.include_router(chat_router, prefix="/api", tags=["chat"])
