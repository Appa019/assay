"""The BRL → ticket conversion the client retypes into the broker."""

from decimal import Decimal

from app.models.asset import AssetClass
from app.services import order_sizing


def test_stock_quantity_rounds_down_to_whole_shares() -> None:
    """R$ 1.600 at 52,01 is 30,76 shares — buying 31 would overshoot the
    committee's sizing with real money, so the remainder stays unallocated."""
    qty = order_sizing.size_order(
        amount_brl=Decimal("1600"), price=Decimal("52.01"), asset_class=AssetClass.STOCKS
    )
    assert qty == Decimal("30")


def test_crypto_keeps_eight_decimals_and_never_overshoots() -> None:
    """8 dp, floored: 0.0048273099… becomes 0.00482730, and the resulting
    spend stays under the budgeted amount rather than a cent over it."""
    price = Decimal("331447.54")
    qty = order_sizing.size_order(
        amount_brl=Decimal("1600"), price=price, asset_class=AssetClass.CRYPTO
    )
    assert qty == Decimal("0.00482730")
    assert qty * price <= Decimal("1600")


def test_cdb_has_no_quantity() -> None:
    """A CDB is an amount applied, not a number of units."""
    assert (
        order_sizing.size_order(
            amount_brl=Decimal("9057.75"),
            price=Decimal("1"),
            asset_class=AssetClass.FIXED_INCOME,
        )
        is None
    )


def test_amount_below_one_share_yields_no_quantity() -> None:
    assert (
        order_sizing.size_order(
            amount_brl=Decimal("20"), price=Decimal("52.01"), asset_class=AssetClass.STOCKS
        )
        is None
    )


def test_missing_price_yields_no_quantity() -> None:
    assert (
        order_sizing.size_order(
            amount_brl=Decimal("1600"), price=None, asset_class=AssetClass.STOCKS
        )
        is None
    )


def test_odd_lot_goes_to_the_fractional_book() -> None:
    """30 shares typed as PETR3 never fills: 1-99 trades only as PETR3F."""
    lines = order_sizing.ticket_lines(
        ticker="PETR3",
        asset_class=AssetClass.STOCKS,
        amount_brl=Decimal("1600"),
        quantity=Decimal("30"),
        price=Decimal("52.01"),
    )
    assert len(lines) == 1
    assert lines[0].ticker == "PETR3F"
    assert lines[0].quantity == Decimal("30")
    assert lines[0].book == "fracionário"
    assert lines[0].total_brl == Decimal("1560.30")


def test_round_lot_stays_on_the_plain_ticker() -> None:
    lines = order_sizing.ticket_lines(
        ticker="VALE3",
        asset_class=AssetClass.STOCKS,
        amount_brl=Decimal("15724"),
        quantity=Decimal("200"),
        price=Decimal("78.62"),
    )
    assert len(lines) == 1
    assert (lines[0].ticker, lines[0].quantity, lines[0].book) == (
        "VALE3",
        Decimal("200"),
        "padrão",
    )


def test_mixed_quantity_splits_across_both_books() -> None:
    """130 shares is two tickets: 100 as ITUB4 and 30 as ITUB4F."""
    lines = order_sizing.ticket_lines(
        ticker="ITUB4",
        asset_class=AssetClass.STOCKS,
        amount_brl=Decimal("5449.60"),
        quantity=Decimal("130"),
        price=Decimal("41.92"),
    )
    assert [(x.ticker, x.quantity) for x in lines] == [
        ("ITUB4", Decimal("100")),
        ("ITUB4F", Decimal("30")),
    ]


def test_cdb_ticket_is_an_application_in_brl() -> None:
    lines = order_sizing.ticket_lines(
        ticker="CDB BRADESCO 100%CDI",
        asset_class=AssetClass.FIXED_INCOME,
        amount_brl=Decimal("9057.75"),
        quantity=None,
        price=None,
    )
    assert len(lines) == 1
    assert lines[0].book == "aplicação"
    assert lines[0].price == Decimal("9057.75")


def test_unpriced_order_produces_no_ticket() -> None:
    """Better an empty ticket than a made-up quantity."""
    assert (
        order_sizing.ticket_lines(
            ticker="PETR3",
            asset_class=AssetClass.STOCKS,
            amount_brl=Decimal("1600"),
            quantity=None,
            price=None,
        )
        == []
    )
