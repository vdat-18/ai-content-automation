"""Derive RFM customer segments from Shopify customer and order records.

The output is plain numbers per segment (size, revenue share, what each segment buys), so
the persona step can reason from data instead of invented audiences.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean, median
from typing import Any

from ..domain.models import NormalizedRecord

SEGMENT_NAMES = (
    "Champions",
    "Loyal customers",
    "Recent customers",
    "Promising",
    "Needs attention",
    "At risk",
    "Inactive",
)


@dataclass(frozen=True)
class _Customer:
    customer_id: int
    recency_days: int
    frequency: int
    monetary: float
    tags: tuple[str, ...]
    product_revenue: dict[str, float]


def _parse_day(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _tercile_scores(values: list[float], *, higher_is_better: bool) -> tuple[float, float]:
    ordered = sorted(values)
    low, high = ordered[len(ordered) // 3], ordered[(2 * len(ordered)) // 3]
    return (low, high) if higher_is_better else (high, low)


def _score(value: float, cuts: tuple[float, float], *, higher_is_better: bool) -> int:
    first, second = cuts
    if higher_is_better:
        return 1 if value <= first else 2 if value <= second else 3
    return 3 if value <= second else 2 if value <= first else 1


def _segment(recency: int, frequency: int, monetary: int) -> str:
    if recency == 3 and frequency == 3:
        return "Champions"
    if frequency == 3 or (frequency == 2 and monetary == 3 and recency >= 2):
        return "Loyal customers"
    if recency == 3 and frequency == 1:
        return "Recent customers"
    if recency == 2 and frequency == 1:
        return "Promising"
    if recency == 2:
        return "Needs attention"
    if frequency >= 2:
        return "At risk"
    return "Inactive"


def _customers(
    customers: list[NormalizedRecord], orders: list[NormalizedRecord], as_of: datetime
) -> list[_Customer]:
    tags = {int(item.data["id"]): _split_tags(item.data.get("tags")) for item in customers}
    spent: dict[int, float] = defaultdict(float)
    count: Counter[int] = Counter()
    last: dict[int, datetime] = {}
    by_product: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for record in orders:
        data = record.data
        customer_id = int(data["customer_id"])
        placed = _parse_day(data["created_at"])
        spent[customer_id] += float(data["total_price"])
        count[customer_id] += 1
        last[customer_id] = max(last.get(customer_id, placed), placed)
        for line in data["line_items"]:
            by_product[customer_id][str(line["product_id"])] += float(line["price"]) * int(
                line["quantity"]
            )
    return [
        _Customer(
            customer_id=customer_id,
            recency_days=(as_of - last[customer_id]).days,
            frequency=count[customer_id],
            monetary=spent[customer_id],
            tags=tags.get(customer_id, ()),
            product_revenue=dict(by_product[customer_id]),
        )
        for customer_id in count
    ]


def _split_tags(value: Any) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def _top_tags(group: list[_Customer], prefix: str, limit: int = 2) -> list[str]:
    counts = Counter(
        tag.split(":", 1)[1] for item in group for tag in item.tags if tag.startswith(prefix)
    )
    return [
        f"{name} ({round(100 * value / len(group))}%)" for name, value in counts.most_common(limit)
    ]


def build_segment_report(
    customers: list[NormalizedRecord],
    orders: list[NormalizedRecord],
    *,
    product_id: str,
    product_titles: dict[str, str],
) -> dict[str, Any] | None:
    """Return RFM segment statistics for one product, or ``None`` without order history."""
    if not orders:
        return None
    as_of = max(_parse_day(item.data["created_at"]) for item in orders)
    people = _customers(customers, orders, as_of)
    repeat_counts = [item.frequency for item in people if item.frequency > 1]
    repeat_cut = median(repeat_counts) if repeat_counts else 2
    recency_cuts = _tercile_scores([item.recency_days for item in people], higher_is_better=False)
    money_cuts = _tercile_scores([item.monetary for item in people], higher_is_better=True)
    groups: dict[str, list[_Customer]] = defaultdict(list)
    for item in people:
        frequency = 1 if item.frequency == 1 else 2 if item.frequency <= repeat_cut else 3
        name = _segment(
            _score(item.recency_days, recency_cuts, higher_is_better=False),
            frequency,
            _score(item.monetary, money_cuts, higher_is_better=True),
        )
        groups[name].append(item)
    total_revenue = sum(item.monetary for item in people)
    product_revenue = sum(item.product_revenue.get(product_id, 0.0) for item in people)
    segments = []
    for name in SEGMENT_NAMES:
        group = groups.get(name)
        if not group:
            continue
        revenue = sum(item.monetary for item in group)
        buyers = [item for item in group if product_id in item.product_revenue]
        others: Counter[str] = Counter()
        for item in buyers:
            for other in item.product_revenue:
                if other != product_id:
                    others[other] += 1
        segments.append(
            {
                "segment": name,
                "customers": len(group),
                "customer_share_pct": round(100 * len(group) / len(people), 1),
                "store_revenue_share_pct": round(100 * revenue / total_revenue, 1),
                "avg_orders": round(mean(item.frequency for item in group), 1),
                "avg_total_spent": round(mean(item.monetary for item in group), 2),
                "days_since_last_order_median": int(median(item.recency_days for item in group)),
                "buyers_of_this_product": len(buyers),
                "product_penetration_pct": round(100 * len(buyers) / len(group), 1),
                "product_revenue_share_pct": round(
                    100
                    * sum(item.product_revenue[product_id] for item in buyers)
                    / (product_revenue or 1),
                    1,
                ),
                "often_also_buy": [
                    product_titles.get(key, key) for key, _ in others.most_common(2)
                ],
                "age_mix": _top_tags(group, "age:"),
                "region_mix": _top_tags(group, "region:"),
            }
        )
    return {
        "as_of": as_of.date().isoformat(),
        "customers": len(people),
        "orders": len(orders),
        "product_orders": sum(
            1
            for record in orders
            for line in record.data["line_items"]
            if str(line["product_id"]) == product_id
        ),
        "segments": segments,
    }


__all__ = ["SEGMENT_NAMES", "build_segment_report"]
