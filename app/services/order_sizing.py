"""Turn a BRL order into what the broker's ticket actually asks for.

The committee sizes in reais ("R$ 1.600 em PETR3"), but the broker's ticket wants
a TICKER, a QUANTITY and a PRICE. Doing that division by hand at the moment of
buying is where mistakes happen, so the conversion lives here — deterministic,
from the live mark-to-market price, never from a number the model remembered.

B3 has two order books and the ticket is not interchangeable between them:
lots of 100 trade in the regular book under the plain ticker, anything from 1
to 99 trades in the odd-lot book under ``TICKER + "F"``. An order for 30 shares
typed as PETR3 simply will not fill, so the split is part of the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from app.models.asset import AssetClass

# B3 regular-lot size. Below it the order has to go to the odd-lot book.
BOARD_LOT = 100
_CRYPTO_STEP = Decimal("0.00000001")  # 8 dp, the satoshi-grade floor


@dataclass(frozen=True)
class TicketLine:
    """One line to type into the broker ticket, verbatim."""

    ticker: str
    quantity: Decimal
    price: Decimal
    book: str  # "padrão" | "fracionário" | "aplicação"

    @property
    def total_brl(self) -> Decimal:
        return (self.quantity * self.price).quantize(Decimal("0.01"))


def size_order(
    *,
    amount_brl: Decimal,
    price: Decimal | None,
    asset_class: AssetClass,
) -> Decimal | None:
    """How many units ``amount_brl`` buys at ``price``.

    Always rounds DOWN: overshooting the committee's sizing costs real money,
    undershooting only leaves a few reais unallocated. Returns None when the
    class has no unit (CDB is an application, not a quantity), when there is no
    price, or when the amount does not buy a single unit.
    """
    if asset_class == AssetClass.FIXED_INCOME:
        return None
    if price is None or price <= 0 or amount_brl <= 0:
        return None

    raw = Decimal(amount_brl) / Decimal(price)
    if asset_class == AssetClass.CRYPTO:
        quantity = raw.quantize(_CRYPTO_STEP, rounding=ROUND_DOWN)
    else:
        quantity = raw.quantize(Decimal("1"), rounding=ROUND_DOWN)
    return quantity if quantity > 0 else None


def ticket_lines(
    *,
    ticker: str,
    asset_class: AssetClass,
    amount_brl: Decimal,
    quantity: Decimal | None,
    price: Decimal | None,
) -> list[TicketLine]:
    """Split an order into the ticket lines it really needs.

    A CDB is one "aplicação" line carrying the BRL amount. Crypto is one line.
    A B3 stock becomes one line per book: the round-lot part under the plain
    ticker and the 1-99 remainder under ``TICKER + "F"``.
    """
    if asset_class == AssetClass.FIXED_INCOME:
        return [
            TicketLine(
                ticker=ticker,
                quantity=Decimal(1),
                price=Decimal(amount_brl),
                book="aplicação",
            )
        ]
    if quantity is None or price is None or quantity <= 0:
        return []
    if asset_class == AssetClass.CRYPTO:
        return [TicketLine(ticker=ticker, quantity=quantity, price=price, book="fracionário")]

    whole = int(quantity)
    lots, odd = divmod(whole, BOARD_LOT)
    lines: list[TicketLine] = []
    if lots:
        lines.append(
            TicketLine(
                ticker=ticker,
                quantity=Decimal(lots * BOARD_LOT),
                price=price,
                book="padrão",
            )
        )
    if odd:
        lines.append(
            TicketLine(
                ticker=f"{ticker}F",
                quantity=Decimal(odd),
                price=price,
                book="fracionário",
            )
        )
    return lines


def _fmt_qty(quantity: Decimal) -> str:
    """Integers without a tail, crypto without trailing zero noise."""
    if quantity == quantity.to_integral_value():
        return str(int(quantity))
    return format(quantity.normalize(), "f")


def _fmt_brl(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"R$ {text}"


def ticket_summary(lines: list[TicketLine]) -> str:
    """One-line, copy-ready rendering of the ticket. Empty when unsized."""
    if not lines:
        return ""
    if lines[0].book == "aplicação":
        return f"{lines[0].ticker} · aplicar {_fmt_brl(lines[0].price)}"
    return "  +  ".join(
        f"{line.ticker} · {_fmt_qty(line.quantity)} un · {_fmt_brl(line.price)}" for line in lines
    )
