import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .listing_parser import size_class_for
from .models import NATURES, SIZE_CLASSES, STATUSES, TX_TYPES, Complex, PriceRecord, ReviewItem, utcnow

FINGERPRINT_FIELDS = (
    "complex_id",
    "size_class",
    "exclusive_m2",
    "supply_m2",
    "tx_type",
    "nature",
    "price_krw",
    "deposit_krw",
    "monthly_rent_krw",
    "floor",
    "contract_date",
    "report_date",
    "source_name",
    "source_url",
    "source_record_id",
    "source_version",
    "status",
    "is_estimate",
)

PARTIAL_DETAIL_FIELDS = ("amounts", "floor", "contract_date", "exclusive_m2", "source_url")

DEFAULT_FRESHNESS_DAYS = {"ACTUAL": 45, "ASKING": 14}


class RecordValidationError(ValueError):
    pass


@dataclass
class Candidate:
    complex_id: int
    size_class: str
    tx_type: str
    nature: str
    source_name: str
    price_krw: int | None = None
    deposit_krw: int | None = None
    monthly_rent_krw: int | None = None
    exclusive_m2: float | None = None
    supply_m2: float | None = None
    floor: str = ""
    contract_date: date | None = None
    report_date: date | None = None
    source_url: str = ""
    source_record_id: str | None = None
    source_version: str | None = None
    raw_snippet: str = ""
    status: str = "ACTIVE"
    is_estimate: bool = False
    estimate_note: str = ""
    captured_at: datetime | None = None

    def to_json(self) -> dict:
        out = {}
        for k, v in self.__dict__.items():
            out[k] = v.isoformat() if isinstance(v, (date, datetime)) else v
        return out

    @classmethod
    def from_json(cls, data: dict) -> "Candidate":
        d = dict(data)
        for k in ("contract_date", "report_date"):
            if d.get(k):
                d[k] = date.fromisoformat(d[k])
        if d.get("captured_at"):
            d["captured_at"] = datetime.fromisoformat(d["captured_at"])
        return cls(**d)


@dataclass
class IngestResult:
    outcome: str
    record: PriceRecord | None = None
    review: ReviewItem | None = None
    reasons: list[str] = field(default_factory=list)


def _norm_float(v: float | None) -> str:
    return "" if v is None else f"{float(v):.4f}"


def _norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return _norm_float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v).strip()


def fingerprint(c: Candidate | PriceRecord) -> str:
    payload = {f: _norm(getattr(c, f)) for f in FINGERPRINT_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def validate(c: Candidate, db: Session) -> None:
    if c.tx_type not in TX_TYPES:
        raise RecordValidationError("거래유형은 매매/전세/월세 중 하나여야 합니다.")
    if c.nature not in NATURES:
        raise RecordValidationError("자료 성격은 실거래/호가 중 하나여야 합니다.")
    if c.size_class not in SIZE_CLASSES:
        raise RecordValidationError("평형 구분은 전용 59㎡ 또는 84㎡여야 합니다.")
    if c.status not in STATUSES:
        raise RecordValidationError("상태 값이 올바르지 않습니다.")
    if not c.source_name.strip():
        raise RecordValidationError("출처 이름이 필요합니다.")
    if db.get(Complex, c.complex_id) is None:
        raise RecordValidationError("존재하지 않는 단지입니다.")
    for name in ("price_krw", "deposit_krw", "monthly_rent_krw"):
        v = getattr(c, name)
        if v is None:
            continue
        if type(v) is not int or v < 0 or (v == 0 and not (name == "deposit_krw" and c.tx_type == "WOLSE")):
            raise RecordValidationError("금액은 0보다 큰 원 단위 정수여야 합니다 (월세 보증금만 0 허용).")
    if c.tx_type == "SALE":
        if c.price_krw is None or c.deposit_krw is not None or c.monthly_rent_krw is not None:
            raise RecordValidationError("매매 기록에는 매매가만 입력합니다 (보증금/월세 불가).")
    elif c.tx_type == "JEONSE":
        if c.deposit_krw is None or c.price_krw is not None or c.monthly_rent_krw is not None:
            raise RecordValidationError("전세 기록에는 전세 보증금만 입력합니다 (매매가/월세 불가).")
    else:
        if c.deposit_krw is None or c.monthly_rent_krw is None or c.price_krw is not None:
            raise RecordValidationError("월세 기록에는 보증금과 월세를 함께 입력해야 합니다 (매매가 불가).")
    if c.exclusive_m2 is not None:
        derived = size_class_for(c.exclusive_m2)
        if derived != c.size_class:
            raise RecordValidationError(
                f"전용면적 {c.exclusive_m2}㎡는 전용 {c.size_class}㎡ 시리즈에 속하지 않습니다. 공급면적을 전용면적 칸에 넣지 않았는지 확인하세요."
            )
    if c.supply_m2 is not None and c.exclusive_m2 is not None and c.supply_m2 < c.exclusive_m2:
        raise RecordValidationError("공급면적은 전용면적보다 작을 수 없습니다. 두 값이 바뀌었는지 확인하세요.")
    if c.contract_date and c.report_date and c.report_date < c.contract_date:
        raise RecordValidationError("신고/확인일이 계약일보다 앞설 수 없습니다.")


def _apply(rec: PriceRecord, c: Candidate) -> None:
    for k in (
        "complex_id", "size_class", "exclusive_m2", "supply_m2", "tx_type", "nature", "price_krw",
        "deposit_krw", "monthly_rent_krw", "contract_date", "report_date", "source_name", "source_url",
        "source_record_id", "source_version", "raw_snippet", "status", "is_estimate", "estimate_note",
    ):
        setattr(rec, k, getattr(c, k))
    rec.floor = c.floor or ""
    rec.captured_at = c.captured_at or utcnow()
    rec.fingerprint = fingerprint(c)


def _new_record(db: Session, c: Candidate, uid: str | None = None, version: int = 1, reason: str = "") -> PriceRecord:
    rec = PriceRecord(record_uid=uid or uuid.uuid4().hex, version=version, is_current=True, change_reason=reason)
    _apply(rec, c)
    db.add(rec)
    db.flush()
    return rec


def _supersede(db: Session, old: PriceRecord, c: Candidate, reason: str) -> PriceRecord:
    old.is_current = False
    db.flush()
    return _new_record(db, c, uid=old.record_uid, version=old.version + 1, reason=reason)


def _diff_fields(old: PriceRecord, c: Candidate) -> list[str]:
    return [f for f in FINGERPRINT_FIELDS if _norm(getattr(old, f)) != _norm(getattr(c, f))]


def _amounts(x) -> tuple:
    return (x.price_krw, x.deposit_krw, x.monthly_rent_krw)


def _partial_matches(db: Session, c: Candidate) -> list[tuple[PriceRecord, list[str]]]:
    q = select(PriceRecord).where(
        PriceRecord.is_current.is_(True),
        PriceRecord.complex_id == c.complex_id,
        PriceRecord.size_class == c.size_class,
        PriceRecord.tx_type == c.tx_type,
        PriceRecord.nature == c.nature,
    )
    out = []
    for rec in db.scalars(q):
        same = []
        if _amounts(rec) == _amounts(c):
            same.append("금액")
        if (rec.floor or "") == (c.floor or "") and c.floor:
            same.append("층")
        if rec.contract_date and rec.contract_date == c.contract_date:
            same.append("계약일")
        if rec.exclusive_m2 is not None and _norm_float(rec.exclusive_m2) == _norm_float(c.exclusive_m2):
            same.append("전용면적")
        if rec.source_url and rec.source_url == c.source_url:
            same.append("출처URL")
        if "출처URL" in same or len(same) >= 2:
            out.append((rec, same))
    return out


def ingest(db: Session, c: Candidate) -> IngestResult:
    validate(c, db)
    fp = fingerprint(c)
    if c.source_record_id:
        existing = db.scalars(
            select(PriceRecord)
            .where(
                PriceRecord.source_name == c.source_name,
                PriceRecord.source_record_id == c.source_record_id,
                PriceRecord.is_current.is_(True),
            )
            .order_by(PriceRecord.version.desc())
        ).first()
        if existing is None:
            return IngestResult("created", record=_new_record(db, c))
        if existing.fingerprint == fp:
            return IngestResult("duplicate", record=existing)
        seen = db.scalars(
            select(PriceRecord).where(
                PriceRecord.record_uid == existing.record_uid,
                PriceRecord.fingerprint == fp,
            )
        ).first()
        if seen is not None:
            review = ReviewItem(
                candidate=c.to_json(),
                matched_record_id=existing.id,
                reasons=f"이 출처 ID의 과거 버전(v{seen.version})과 같은 데이터가 다시 들어왔습니다. 최신 버전(v{existing.version})을 되돌릴지 확인하세요.",
            )
            db.add(review)
            db.flush()
            return IngestResult("ambiguous", review=review, reasons=[review.reasons])
        if (existing.complex_id, existing.tx_type, existing.size_class) != (c.complex_id, c.tx_type, c.size_class):
            review = ReviewItem(
                candidate=c.to_json(),
                matched_record_id=existing.id,
                reasons="같은 출처 ID인데 단지/거래유형/평형이 다릅니다: " + ", ".join(_diff_fields(existing, c)),
            )
            db.add(review)
            db.flush()
            return IngestResult("ambiguous", review=review, reasons=[review.reasons])
        reason = "출처 데이터 변경: " + ", ".join(_diff_fields(existing, c))
        return IngestResult("new_version", record=_supersede(db, existing, c, reason))
    dup = db.scalars(select(PriceRecord).where(PriceRecord.fingerprint == fp, PriceRecord.is_current.is_(True))).first()
    if dup is not None:
        return IngestResult("duplicate", record=dup)
    partial = _partial_matches(db, c)
    if partial:
        rec, same = partial[0]
        reasons = [
            f"기록 #{rec.id}와 일부 일치 (일치: {', '.join(same)}; 다름: {', '.join(_diff_fields(rec, c)) or '-'})"
            for rec, same in partial
        ]
        review = ReviewItem(candidate=c.to_json(), matched_record_id=rec.id, reasons="\n".join(reasons))
        db.add(review)
        db.flush()
        return IngestResult("ambiguous", review=review, reasons=reasons)
    return IngestResult("created", record=_new_record(db, c))


def resolve_review(db: Session, review: ReviewItem, action: str) -> PriceRecord | None:
    if review.status != "PENDING":
        raise RecordValidationError("이미 처리된 검토 항목입니다.")
    c = Candidate.from_json(review.candidate)
    rec = None
    if action == "separate":
        validate(c, db)
        rec = _new_record(db, c, reason="검토 후 별개 거래로 저장")
    elif action == "new_version":
        if review.matched_record is None:
            raise RecordValidationError("비교 대상 기록이 없습니다.")
        validate(c, db)
        target = review.matched_record
        if not target.is_current:
            target = db.scalars(
                select(PriceRecord).where(PriceRecord.record_uid == target.record_uid, PriceRecord.is_current.is_(True))
            ).first()
        if target is None or (target.complex_id, target.tx_type, target.size_class) != (c.complex_id, c.tx_type, c.size_class):
            raise RecordValidationError("단지/거래유형/평형이 다른 기록의 새 버전으로 저장할 수 없습니다.")
        if target.source_record_id and c.source_record_id and (
            target.source_name != c.source_name or target.source_record_id != c.source_record_id
        ):
            raise RecordValidationError("출처 ID가 서로 다른 기록은 같은 기록의 버전으로 묶을 수 없습니다. 별개 거래로 저장하세요.")
        rec = _supersede(db, target, c, "검토 후 기존 기록의 새 버전: " + ", ".join(_diff_fields(target, c)))
    elif action != "discard":
        raise RecordValidationError("알 수 없는 처리 방법입니다.")
    review.status = {"separate": "SEPARATE", "new_version": "NEW_VERSION", "discard": "DISCARDED"}[action]
    review.resolution_record_id = rec.id if rec else None
    review.resolved_at = utcnow()
    db.flush()
    return rec


def series_points(
    db: Session, complex_id: int, tx_type: str, size_classes: list[str], natures: list[str]
) -> list[PriceRecord]:
    if tx_type not in TX_TYPES:
        raise RecordValidationError("거래유형이 올바르지 않습니다.")
    q = (
        select(PriceRecord)
        .where(
            PriceRecord.complex_id == complex_id,
            PriceRecord.tx_type == tx_type,
            PriceRecord.size_class.in_([s for s in size_classes if s in SIZE_CLASSES]),
            PriceRecord.nature.in_([n for n in natures if n in NATURES]),
            PriceRecord.is_current.is_(True),
        )
        .order_by(PriceRecord.contract_date, PriceRecord.captured_at)
    )
    return list(db.scalars(q))


@dataclass
class Freshness:
    last_updated: datetime | None
    expected_days: int
    stale: bool
    count: int


def series_freshness(
    db: Session, complex_id: int, tx_type: str, size_class: str, nature: str, intervals: dict, now: datetime | None = None
) -> Freshness:
    now = now or utcnow()
    days = int(intervals.get(nature, DEFAULT_FRESHNESS_DAYS[nature]))
    recs = list(
        db.scalars(
            select(PriceRecord).where(
                PriceRecord.complex_id == complex_id,
                PriceRecord.tx_type == tx_type,
                PriceRecord.size_class == size_class,
                PriceRecord.nature == nature,
            )
        )
    )
    if not recs:
        return Freshness(None, days, False, 0)
    last = max(r.captured_at for r in recs)
    current = sum(1 for r in recs if r.is_current)
    return Freshness(last, days, now - last > timedelta(days=days), current)


def latest_current(db: Session, complex_id: int, tx_type: str, size_class: str, nature: str) -> PriceRecord | None:
    return db.scalars(
        select(PriceRecord)
        .where(
            PriceRecord.complex_id == complex_id,
            PriceRecord.tx_type == tx_type,
            PriceRecord.size_class == size_class,
            PriceRecord.nature == nature,
            PriceRecord.is_current.is_(True),
            PriceRecord.status != "CANCELLED",
        )
        .order_by(PriceRecord.contract_date.desc(), PriceRecord.captured_at.desc())
    ).first()
