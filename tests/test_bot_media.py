from pathlib import Path

import pytest

import scripts.telegram_bot as bot
from app.services import chat_service, telegram_service


@pytest.fixture(autouse=True)
def _drain_queue():
    yield
    while not bot._chat_queue.empty():
        bot._chat_queue.get_nowait()


def test_safe_filename_sanitizes_and_falls_back() -> None:
    assert bot._safe_filename("../../etc/passwd", "f.bin") == "passwd"
    assert bot._safe_filename("nota fiscal (julho).pdf", "f.bin") == "nota_fiscal__julho_.pdf"
    assert bot._safe_filename("", "f.bin") == "f.bin"
    assert bot._safe_filename("média até.pdf", "f.bin") == "m_dia_at_.pdf"
    assert len(bot._safe_filename("x" * 500 + ".pdf", "f.bin")) <= 80


def test_extract_media_prefers_document_and_largest_photo() -> None:
    doc_msg = {"document": {"file_id": "d1", "file_name": "extrato.pdf", "file_size": 100}}
    assert bot._extract_media(doc_msg) == ("arquivo", "d1", "extrato.pdf", 100)

    photo_msg = {
        "photo": [
            {"file_id": "small", "file_size": 10},
            {"file_id": "large", "file_size": 999},
        ]
    }
    assert bot._extract_media(photo_msg) == ("imagem", "large", "foto.jpg", 999)
    assert bot._extract_media({"text": "oi"}) is None


def test_handle_media_rejects_oversize_without_downloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("must not download oversize files")

    monkeypatch.setattr(telegram_service, "download_file", boom)
    msg = {"document": {"file_id": "d1", "file_name": "big.pdf", "file_size": 21 * 1024 * 1024}}
    assert "20 MB" in bot._handle_media(msg)


def test_handle_media_downloads_and_enqueues_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    saved = tmp_path / "inbox" / "20260728T000000_cupom.jpg"

    def fake_download(file_id: str, dest_dir: Path, *, preferred_name=None, **k) -> Path:
        assert file_id == "large"
        assert preferred_name.endswith("_foto.jpg")
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(b"jpg")
        return saved

    monkeypatch.setattr(telegram_service, "download_file", fake_download)
    monkeypatch.setattr(chat_service, "CHAT_WORKSPACE", tmp_path)
    msg = {
        "photo": [{"file_id": "large", "file_size": 999}],
        "caption": "cupom do mercado",
    }
    reply = bot._handle_media(msg)
    assert "Recebi a imagem" in reply
    turn = bot._chat_queue.get_nowait()
    assert str(saved) in turn
    assert "cupom do mercado" in turn


def test_handle_media_reports_download_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*a, **k):  # noqa: ANN002, ANN003
        raise telegram_service.TelegramError("getFile falhou")

    monkeypatch.setattr(telegram_service, "download_file", fail)
    monkeypatch.setattr(chat_service, "CHAT_WORKSPACE", tmp_path)
    msg = {"document": {"file_id": "d1", "file_name": "x.pdf", "file_size": 10}}
    assert "Não consegui baixar" in bot._handle_media(msg)
    assert bot._chat_queue.empty()


def test_unsupported_media_notice_and_silence() -> None:
    assert "não leio" in bot._unsupported_media({"voice": {"file_id": "v"}})
    # Service messages (no media, no text) must stay silent.
    assert bot._unsupported_media({"new_chat_members": []}) is None
