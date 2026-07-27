from app.services import telegram_service as tg


def test_table_renders_as_stanzas() -> None:
    md = (
        "| Ativo | Classe | R$ |\n"
        "|---|---|---|\n"
        "| PETR4 | acoes_b3 | 1000 |\n"
        "| BTC | crypto | 2000 |\n"
    )
    out = tg.format_for_telegram(md)
    assert "<b>PETR4</b>" in out
    assert "• Classe: acoes_b3" in out
    assert "|" not in out  # no raw pipes survive


def test_format_survives_html_metacharacters() -> None:
    out = tg.format_for_telegram("lucro < 10% & preço > R$ 5")
    assert "&lt;" in out and "&amp;" in out and "&gt;" in out


def test_chunk_prefers_line_boundaries() -> None:
    text = "\n".join(f"linha {i}" for i in range(1000))
    chunks = tg.chunk_text(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    # No mid-line splits: rejoining must reproduce the original text.
    assert "".join(chunks) == text
    assert all(c.endswith("\n") or c is chunks[-1] for c in chunks)


def test_long_table_formats_before_chunking() -> None:
    """A table longer than one Telegram message must be HTML-formatted as a
    WHOLE and only then chunked — chunk-then-format used to mangle it."""
    rows = "\n".join(f"| ATIVO{i} | classe | {i} | racional longo {'x' * 60} |" for i in range(80))
    md = "| Ativo | Classe | R$ | Racional |\n|---|---|---|---|\n" + rows
    html = tg.format_for_telegram(md)
    chunks = tg.chunk_text(html)
    assert len(chunks) > 1
    # Every chunk is already-rendered stanza text, never a raw table fragment.
    assert all("|" not in c for c in chunks)


def test_strip_html_roundtrip() -> None:
    assert tg._strip_html("<b>oi</b> &amp; <code>x&lt;1</code>") == "oi & x<1"
