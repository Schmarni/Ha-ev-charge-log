"""Pure statistics logic for EV Charge Log (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SOURCE_EVCC = "evcc"
SOURCE_MANUAL = "manual"


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_evcc_session(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an evcc /api/sessions record into our session format."""
    energy = _f(raw.get("chargedEnergy"))
    created = raw.get("created")
    if not energy or energy <= 0 or not created:
        return None
    finished = raw.get("finished")
    if finished and finished.startswith("0001-"):
        finished = None
    duration_ns = _f(raw.get("chargeDuration"))
    price = _f(raw.get("price"))
    return {
        "id": f"evcc_{raw.get('id')}",
        "source": SOURCE_EVCC,
        "start": created,
        "end": finished,
        "location": raw.get("loadpoint") or "evcc",
        "vehicle": raw.get("vehicle"),
        "energy": round(energy, 3),
        "cost": round(price, 4) if price is not None else None,
        "odometer": _f(raw.get("odometer")),
        "duration": round(duration_ns / 60e9) if duration_ns else None,
        "waiting_time": None,
        "charge_type": "AC",
        "solar_percentage": _f(raw.get("solarPercentage")),
        "note": None,
    }


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        # evcc uses nanosecond precision; trim to microseconds
        try:
            head, _, tail = ts.partition(".")
            digits = "".join(c for c in tail if c.isdigit())
            rest = tail[len(digits):]
            return datetime.fromisoformat(f"{head}.{digits[:6]}{rest}".replace("Z", "+00:00"))
        except ValueError:
            return None


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


@dataclass
class Bucket:
    """Aggregated values for a group of sessions."""

    sessions: int = 0
    energy: float = 0.0
    cost: float = 0.0
    priced_energy: float = 0.0
    priced_cost: float = 0.0
    unpriced_energy: float = 0.0
    duration: float = 0.0
    waiting: float = 0.0
    solar_energy: float = 0.0
    solar_known_energy: float = 0.0

    def add(self, s: dict[str, Any]) -> None:
        energy = s.get("energy") or 0.0
        self.sessions += 1
        self.energy += energy
        if s.get("cost") is not None:
            self.cost += s["cost"]
            self.priced_energy += energy
            self.priced_cost += s["cost"]
        else:
            self.unpriced_energy += energy
        self.duration += s.get("duration") or 0
        self.waiting += s.get("waiting_time") or 0
        if s.get("solar_percentage") is not None:
            self.solar_known_energy += energy
            self.solar_energy += energy * s["solar_percentage"] / 100

    @property
    def avg_price(self) -> float | None:
        return _div(self.priced_cost, self.priced_energy)


@dataclass
class Stats:
    """Result of a statistics calculation."""

    total: Bucket = field(default_factory=Bucket)
    home: Bucket = field(default_factory=Bucket)
    external: Bucket = field(default_factory=Bucket)
    month: Bucket = field(default_factory=Bucket)
    year: Bucket = field(default_factory=Bucket)
    odometer: float | None = None
    distance: float | None = None
    distance_month: float | None = None
    distance_year: float | None = None
    fuel_consumption: float = 0.0
    fuel_price: float = 0.0
    monthly: list[dict[str, Any]] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)

    # cost including an estimate for sessions without price
    def cost_of(self, b: Bucket, fallback_price: float | None = None) -> float:
        price = fallback_price if fallback_price is not None else b.avg_price
        return b.cost + (b.unpriced_energy * price if price else 0.0)

    @property
    def total_cost(self) -> float:
        return self.cost_of(self.home) + self.cost_of(self.external)

    @property
    def home_cost(self) -> float:
        return self.cost_of(self.home)

    @property
    def external_cost(self) -> float:
        return self.cost_of(self.external)

    def fuel_cost_for(self, km: float | None) -> float | None:
        if km is None:
            return None
        return km / 100 * self.fuel_consumption * self.fuel_price

    @property
    def fuel_cost(self) -> float | None:
        return self.fuel_cost_for(self.distance)

    @property
    def savings(self) -> float | None:
        fuel = self.fuel_cost
        return None if fuel is None else fuel - self.total_cost

    @property
    def consumption(self) -> float | None:
        if not self.distance:
            return None
        return self.total.energy / self.distance * 100

    @property
    def cost_per_100km(self) -> float | None:
        if not self.distance:
            return None
        return self.total_cost / self.distance * 100

    @property
    def fuel_cost_per_100km(self) -> float:
        return self.fuel_consumption * self.fuel_price

    @property
    def solar_share_home(self) -> float | None:
        b = self.home
        v = _div(b.solar_energy, b.solar_known_energy)
        return None if v is None else v * 100

    @property
    def month_cost(self) -> float:
        return self.cost_of(self.month, self.total.avg_price)

    @property
    def month_savings(self) -> float | None:
        fuel = self.fuel_cost_for(self.distance_month)
        return None if fuel is None else fuel - self.month_cost

    @property
    def year_cost(self) -> float:
        return self.cost_of(self.year, self.total.avg_price)

    @property
    def year_savings(self) -> float | None:
        fuel = self.fuel_cost_for(self.distance_year)
        return None if fuel is None else fuel - self.year_cost


def compute(
    sessions: list[dict[str, Any]],
    *,
    now: datetime,
    current_odometer: float | None,
    start_odometer: float,
    fuel_consumption: float,
    fuel_price: float,
    recent_count: int = 25,
) -> Stats:
    """Compute all statistics."""
    st = Stats(fuel_consumption=fuel_consumption, fuel_price=fuel_price)

    dated: list[tuple[datetime, dict[str, Any]]] = []
    for s in sessions:
        dt = _parse(s.get("start"))
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        dated.append((dt.astimezone(now.tzinfo), s))
    dated.sort(key=lambda x: x[0])

    months: dict[str, Bucket] = {}
    month_odo_max: dict[str, float] = {}
    readings: list[tuple[datetime, float]] = []

    for dt, s in dated:
        st.total.add(s)
        (st.home if s.get("source") == SOURCE_EVCC else st.external).add(s)
        key = dt.strftime("%Y-%m")
        months.setdefault(key, Bucket()).add(s)
        if dt.year == now.year and dt.month == now.month:
            st.month.add(s)
        if dt.year == now.year:
            st.year.add(s)
        odo = s.get("odometer")
        if odo:
            readings.append((dt, odo))
            month_odo_max[key] = max(month_odo_max.get(key, 0), odo)

    max_reading = max((o for _, o in readings), default=None)
    odo_candidates = [o for o in (current_odometer, max_reading) if o]
    st.odometer = max(odo_candidates) if odo_candidates else None
    if st.odometer is not None:
        st.distance = max(st.odometer - start_odometer, 0)

    cur_key = now.strftime("%Y-%m")
    if st.odometer is not None:
        month_odo_max[cur_key] = max(month_odo_max.get(cur_key, 0), st.odometer)

    def odo_before(limit: datetime) -> float:
        prev = [o for d, o in readings if d < limit]
        return max(prev) if prev else start_odometer

    # distance per month = highest reading in month - highest reading before month
    all_keys = sorted(set(months) | ({cur_key} if st.odometer else set()))
    monthly = []
    for key in all_keys:
        y, m = (int(p) for p in key.split("-"))
        month_start = now.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)
        b = months.get(key, Bucket())
        km = None
        if key in month_odo_max:
            km = max(month_odo_max[key] - odo_before(month_start), 0)
        cost = st.cost_of(b, st.total.avg_price)
        fuel = st.fuel_cost_for(km)
        monthly.append(
            {
                "month": key,
                "sessions": b.sessions,
                "energy": round(b.energy, 1),
                "energy_external": None,
                "cost": round(cost, 2),
                "km": round(km) if km is not None else None,
                "fuel_cost": round(fuel, 2) if fuel is not None else None,
                "savings": round(fuel - cost, 2) if fuel is not None else None,
                "consumption": round(b.energy / km * 100, 1) if km else None,
            }
        )
        if key == cur_key:
            st.distance_month = km
    # external energy per month
    ext_by_month: dict[str, float] = {}
    for dt, s in dated:
        if s.get("source") != SOURCE_EVCC:
            k = dt.strftime("%Y-%m")
            ext_by_month[k] = ext_by_month.get(k, 0) + (s.get("energy") or 0)
    for row in monthly:
        row["energy_external"] = round(ext_by_month.get(row["month"], 0.0), 1)
    st.monthly = monthly

    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if st.odometer is not None:
        st.distance_year = max(st.odometer - odo_before(year_start), 0)

    recent = []
    for dt, s in reversed(dated[-recent_count:]):
        energy = s.get("energy") or 0
        cost = s.get("cost")
        recent.append(
            {
                "id": s.get("id"),
                "date": dt.isoformat(timespec="minutes"),
                "source": s.get("source"),
                "location": s.get("location"),
                "energy": round(energy, 2),
                "cost": round(cost, 2) if cost is not None else None,
                "price_per_kwh": round(cost / energy, 3) if cost is not None and energy else None,
                "odometer": s.get("odometer"),
                "duration": s.get("duration"),
                "waiting_time": s.get("waiting_time"),
                "charge_type": s.get("charge_type"),
                "solar_percentage": round(s["solar_percentage"], 1)
                if s.get("solar_percentage") is not None
                else None,
                "note": s.get("note"),
            }
        )
    st.recent = recent
    return st
