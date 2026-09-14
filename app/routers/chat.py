from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.models.chat import ChatChannel
from app.schemas.chat import ChatMessageRead, ChatSend, ChatState
from app.services import chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _state(limit: int = 60) -> ChatState:
    return ChatState(
        busy=chat_service.is_busy(),
        queued=chat_service.queued_count(),
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
    message walk ``queued`` → ``running`` → ``done`` (or ``failed``).

    Sending while he is still answering is allowed on purpose: the message
    goes to the back of the queue and is read in order. Refusing it with a 409
    only made the client hold the thought and retype it later.
    """
    try:
        chat_service.start_turn(payload.text, ChatChannel.WEB)
    except chat_service.ChatUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _state()


@router.post("/upload", response_model=ChatState, status_code=status.HTTP_202_ACCEPTED)
async def upload_attachments(
    files: list[UploadFile] = File(...),
    caption: str = Form(""),
) -> ChatState:
    """Send up to 3 photos/documents to the consultant in ONE message.

    They land in the same inbox the Telegram bot writes to and become a single
    turn — a receipt photographed front and back is one purchase, not two. Like
    a text message, it queues instead of being refused mid-turn.
    """
    if not 1 <= len(files) <= chat_service.MAX_ATTACHMENTS_PER_TURN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Envie de 1 a {chat_service.MAX_ATTACHMENTS_PER_TURN} arquivos.",
        )
    # Read (and size-check) everything BEFORE saving anything, so a too-big
    # third file doesn't leave half a message sitting in the inbox.
    contents: list[tuple[str, bytes]] = []
    for file in files:
        data = await file.read()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Arquivo vazio: {file.filename or 'sem nome'}.",
            )
        if len(data) > chat_service.MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Arquivo grande demais (limite de 20 MB): {file.filename}.",
            )
        contents.append((file.filename or "arquivo.bin", data))
    try:
        paths = [chat_service.save_attachment(name, data) for name, data in contents]
        chat_service.start_attachments_turn(paths, caption.strip(), ChatChannel.WEB)
    except chat_service.ChatUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    return _state()


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_chat() -> None:
    """Drop the chained Claude session and blank the visible history.

    Rows stay in chat_message (cost/tier stats); the GET only serves
    messages written after this moment. MEMORY.md survives untouched.
    """
    if chat_service.has_pending_turns():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tem mensagem em andamento ou na fila — espera ela terminar.",
        )
    chat_service.reset_session()
