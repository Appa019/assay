from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _now_utc() -> datetime:
    return datetime.now(UTC)


class PushSubscription(SQLModel, table=True):
    """One browser/device subscribed to Web Push (the PWA on the phone).

    The endpoint URL is the identity: re-subscribing the same device replaces
    the row, and a push service answering 404/410 gets the row deleted.
    """

    __tablename__ = "push_subscription"

    endpoint: str = Field(primary_key=True, max_length=1024)
    p256dh: str = Field(max_length=256)  # client public key (payload encryption)
    auth: str = Field(max_length=64)  # client auth secret
    created_at: datetime = Field(default_factory=_now_utc)
