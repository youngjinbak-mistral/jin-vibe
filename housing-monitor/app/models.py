from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TX_TYPES = ("SALE", "JEONSE", "WOLSE")
NATURES = ("ACTUAL", "ASKING")
SIZE_CLASSES = ("59", "84")
STATUSES = ("ACTIVE", "CANCELLED", "AMENDED")

TX_LABELS = {"SALE": "매매", "JEONSE": "전세", "WOLSE": "월세"}
NATURE_LABELS = {"ACTUAL": "실거래", "ASKING": "호가"}
STATUS_LABELS = {"ACTIVE": "정상", "CANCELLED": "해제(취소)", "AMENDED": "정정"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Complex(Base):
    __tablename__ = "complexes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[str] = mapped_column(Text, default="")
    gu: Mapped[str] = mapped_column(String(50))
    dong: Mapped[str] = mapped_column(String(50), default="")
    nearest_station: Mapped[str] = mapped_column(String(100), default="")
    station_distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    station_walk_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    building_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    molit_lawd_cd: Mapped[str] = mapped_column(String(10), default="")
    molit_apt_name: Mapped[str] = mapped_column(String(200), default="")
    hill_note: Mapped[str] = mapped_column(Text, default="")
    daycare_anchor_distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daycare_anchor_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daycare_other_options: Mapped[str] = mapped_column(Text, default="")
    commute_1_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commute_2_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commute_3_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    parking_is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    unit_types: Mapped[list["UnitType"]] = relationship(
        back_populates="complex", cascade="all, delete-orphan", order_by="UnitType.size_class"
    )

    @property
    def alias_list(self) -> list[str]:
        return [a.strip() for a in (self.aliases or "").split(",") if a.strip()]

    @property
    def building_age(self) -> int | None:
        if not self.building_year:
            return None
        return date.today().year - self.building_year

    def unit(self, size_class: str) -> "UnitType | None":
        for u in self.unit_types:
            if u.size_class == size_class:
                return u
        return None


class UnitType(Base):
    __tablename__ = "unit_types"
    __table_args__ = (UniqueConstraint("complex_id", "size_class"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    complex_id: Mapped[int] = mapped_column(ForeignKey("complexes.id", ondelete="CASCADE"))
    size_class: Mapped[str] = mapped_column(String(4))
    exclusive_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    supply_m2: Mapped[float | None] = mapped_column(Float, nullable=True)

    complex: Mapped[Complex] = relationship(back_populates="unit_types")


class PriceRecord(Base):
    __tablename__ = "price_records"
    __table_args__ = (
        UniqueConstraint("record_uid", "version"),
        CheckConstraint("tx_type IN ('SALE','JEONSE','WOLSE')", name="ck_tx_type"),
        CheckConstraint("nature IN ('ACTUAL','ASKING')", name="ck_nature"),
        CheckConstraint("size_class IN ('59','84')", name="ck_size_class"),
        CheckConstraint(
            "(tx_type = 'SALE' AND price_krw IS NOT NULL AND deposit_krw IS NULL AND monthly_rent_krw IS NULL)"
            " OR (tx_type = 'JEONSE' AND price_krw IS NULL AND deposit_krw IS NOT NULL AND monthly_rent_krw IS NULL)"
            " OR (tx_type = 'WOLSE' AND price_krw IS NULL AND deposit_krw IS NOT NULL AND monthly_rent_krw IS NOT NULL)",
            name="ck_amounts_match_tx_type",
        ),
        Index("ix_series", "complex_id", "tx_type", "size_class", "nature", "is_current"),
        Index("ix_source_id", "source_name", "source_record_id"),
        Index("ix_fingerprint", "fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_uid: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    complex_id: Mapped[int] = mapped_column(ForeignKey("complexes.id"))
    size_class: Mapped[str] = mapped_column(String(4))
    exclusive_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    supply_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_type: Mapped[str] = mapped_column(String(10))
    nature: Mapped[str] = mapped_column(String(10))
    price_krw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deposit_krw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    monthly_rent_krw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    floor: Mapped[str] = mapped_column(String(20), default="")
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source_name: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_record_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_snippet: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE")
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    estimate_note: Mapped[str] = mapped_column(Text, default="")
    change_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    complex: Mapped[Complex] = relationship()

    @property
    def observed_date(self) -> date | None:
        return self.contract_date or self.report_date or (self.captured_at.date() if self.captured_at else None)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate: Mapped[dict] = mapped_column(JSON)
    matched_record_id: Mapped[int | None] = mapped_column(ForeignKey("price_records.id"), nullable=True)
    reasons: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    resolution_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    matched_record: Mapped[PriceRecord | None] = relationship()


class Secret(Base):
    __tablename__ = "secrets"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SheetConnection(Base):
    __tablename__ = "sheet_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(200))
    spreadsheet_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    account_email: Mapped[str] = mapped_column(String(320), default="")
    state: Mapped[str] = mapped_column(String(30), default="PENDING_CONFIRMATION")
    target_tab: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_sheet_gid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    header_row: Mapped[int] = mapped_column(Integer, default=1)
    existing_headers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    column_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tabs_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SheetAppend(Base):
    __tablename__ = "sheet_appends"
    __table_args__ = (UniqueConstraint("connection_id", "record_uid", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("sheet_connections.id"))
    record_id: Mapped[int] = mapped_column(ForeignKey("price_records.id"))
    record_uid: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    updated_range: Mapped[str] = mapped_column(Text, default="")
    appended_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
