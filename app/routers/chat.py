from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.models.chat import ChatChannel
from app.schemas.chat import ChatMessageRead, ChatSend, ChatState
from app.services import chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _state(limit: int = 60) -> ChatState:
    return ChatState(
        busy=chat_service.is_busy(),
        messages=[
            ChatMessageRead.model_validate(m, from_attributes=True)
            for m in chat_service.history(limit)
        ],
    )


@router.get("", response_model=ChatState)
async def read_chat(limit: int = 60) -> ChatState:
    """Conversation so far plus whether a turn is in flight."""
    return _state(limit)


@router.post("", response_model=ChatState, status_code=status.HTTP_202_ACCEPTED)
async def send_message(payload: ChatSend) -> ChatState:
    """Queue a turn and return immediately.

    A consultant turn can run for minutes, so the reply is never awaited here.
    The client polls this same resource and watches the pending assistant
    message flip from ``running`` to ``done`` or ``failed``.
    """
    if chat_service.is_busy():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ainda estou terminando a resposta anterior.",
        )
    try:
        chat_service.start_turn(payload.text, ChatChannel.WEB)
    except chat_service.ChatUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _state()


@router.post("/upload", response_model=ChatState, status_code=status.HTTP_202_ACCEPTED)
async def upload_attachment(
    file: UploadFile = File(...),
    caption: str = Form(""),
) -> ChatState:
    """Send a photo or document to the consultant.

    Lands in the same inbox the Telegram bot writes to, so a receipt photo
    becomes a registered expense exactly the same way from either door.
    """
    if chat_service.is_busy():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ainda estou terminando a resposta anterior.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
    try:
        path = chat_service.save_attachment(file.filename or "arquivo.bin", data)
    except chat_service.ChatUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    chat_service.start_attachment_turn(path, caption.strip(), ChatChannel.WEB)
    return _state()


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_chat() -> None:
    """Drop the chained Claude session. The transcript and MEMORY.md survive."""
    if chat_service.is_busy():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não dá para reiniciar no meio de uma resposta.",
        )
    chat_service.reset_session()
