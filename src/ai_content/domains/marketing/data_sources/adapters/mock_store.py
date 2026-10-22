"""Deterministic mock Shopify customers and orders that reconcile with the mock catalog.

Customer totals are summed from the generated orders, so ``orders_count``,
``total_spent`` and ``last_order_id`` always agree with the order history. Buyer groups
only drive behavior (how often, how recently, which products); nothing is labeled with a
segment, so segments have to be derived from the order data like in a real store.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from ..domain.models import NormalizedRecord

_FIRST_NAMES = (
    "Olivia",
    "Liam",
    "Emma",
    "Noah",
    "Ava",
    "Ethan",
    "Sophia",
    "Mason",
    "Isabella",
    "Lucas",
    "Mia",
    "Logan",
    "Amelia",
    "James",
    "Harper",
    "Elijah",
    "Evelyn",
    "Henry",
    "Chloe",
    "Daniel",
    "Grace",
    "Jack",
    "Lily",
    "Owen",
)
_LAST_NAMES = (
    "Nguyen",
    "Smith",
    "Johnson",
    "Garcia",
    "Brown",
    "Davis",
    "Miller",
    "Wilson",
    "Moore",
    "Taylor",
    "Anderson",
    "Thomas",
    "Lee",
    "Martin",
    "Clark",
    "Lewis",
    "Walker",
    "Hall",
    "Young",
    "King",
)
_PLACES = (
    ("Seattle", "WA", "98101"),
    ("Portland", "OR", "97201"),
    ("San Francisco", "CA", "94105"),
    ("Los Angeles", "CA", "90012"),
    ("Austin", "TX", "78701"),
    ("Denver", "CO", "80202"),
    ("Chicago", "IL", "60601"),
    ("Brooklyn", "NY", "11201"),
    ("Boston", "MA", "02108"),
    ("Atlanta", "GA", "30303"),
)
_AGE_BANDS = ("18-24", "25-34", "35-44", "45-54", "55+")
_SALE_WINDOWS = (
    (date(2026, 7, 10), date(2026, 7, 13), "SUMMER15", Decimal("0.15")),
    (date(2026, 9, 5), date(2026, 9, 8), "LABORDAY15", Decimal("0.15")),
)


@dataclass(frozen=True)
class _Group:
    """A latent buyer group: its share of customers, order cadence and product affinity."""

    share: float
    orders: tuple[int, int]
    last_order_days: tuple[int, int]
    gap_days: tuple[int, int]
    discount_rate: float
    affinity: tuple[float, ...]


# Affinity is one weight per catalog item (same order as the brand's items).
_GROUPS: dict[str, tuple[_Group, ...]] = {
    "AuraSleep": (
        _Group(0.08, (4, 8), (3, 40), (35, 90), 0.1, (5, 2, 4, 1)),
        _Group(0.17, (2, 4), (10, 90), (40, 110), 0.25, (4, 3, 3, 2)),
        _Group(0.20, (1, 1), (1, 30), (0, 0), 0.5, (3, 3, 1, 3)),
        _Group(0.30, (1, 1), (60, 300), (0, 0), 0.6, (2, 4, 1, 4)),
        _Group(0.25, (2, 3), (150, 330), (30, 80), 0.4, (4, 3, 2, 1)),
    ),
    "OaklineHome": (
        _Group(0.08, (3, 5), (5, 45), (50, 120), 0.05, (5, 3, 2, 3)),
        _Group(0.17, (2, 3), (15, 100), (60, 130), 0.2, (3, 3, 3, 4)),
        _Group(0.20, (1, 1), (1, 30), (0, 0), 0.45, (3, 4, 1, 3)),
        _Group(0.30, (1, 1), (60, 300), (0, 0), 0.55, (2, 3, 2, 4)),
        _Group(0.25, (2, 2), (160, 330), (50, 110), 0.35, (4, 2, 3, 2)),
    ),
    "LumiSkin": (
        _Group(0.08, (6, 11), (2, 25), (25, 55), 0.1, (5, 3, 4, 4)),
        _Group(0.17, (3, 6), (7, 60), (28, 70), 0.25, (4, 3, 3, 3)),
        _Group(0.20, (1, 1), (1, 30), (0, 0), 0.5, (2, 5, 1, 2)),
        _Group(0.30, (1, 1), (45, 300), (0, 0), 0.6, (3, 4, 2, 1)),
        _Group(0.25, (2, 4), (120, 330), (30, 80), 0.4, (4, 2, 3, 2)),
    ),
}
# Share of the original weight kept for a product the customer already bought.
_REPEAT_WEIGHT = {"AuraSleep": 0.3, "OaklineHome": 0.1, "LumiSkin": 0.8}
_NEW_PRODUCT_INDEX = 2


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _moment(day: date, rng: random.Random) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(
        seconds=rng.randint(8 * 3600, 23 * 3600)
    )


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _order_days(group: _Group, end: date, rng: random.Random) -> list[date]:
    count = rng.randint(*group.orders)
    last = end - timedelta(days=rng.randint(*group.last_order_days))
    days = [last]
    for _ in range(count - 1):
        days.append(days[-1] - timedelta(days=rng.randint(*group.gap_days)))
    return [day for day in sorted(days) if (end - day).days < 365]


def _sale_for(day: date) -> tuple[str, Decimal] | None:
    for start, stop, code, rate in _SALE_WINDOWS:
        if start <= day <= stop:
            return code, rate
    return None


def _line_items(
    products: list[dict[str, Any]],
    group: _Group,
    day: date,
    rng: random.Random,
    launch_day: date,
    bought: set[int],
    repeat_weight: float,
) -> list[dict[str, Any]]:
    weights = [
        0.0
        if index == _NEW_PRODUCT_INDEX and day < launch_day
        else weight * (repeat_weight if index in bought else 1.0)
        for index, weight in enumerate(group.affinity)
    ]
    chosen = {rng.choices(range(len(products)), weights)[0]}
    if rng.random() < 0.3:
        chosen.add(rng.choices(range(len(products)), weights)[0])
    lines = []
    for index in sorted(chosen):
        product = products[index]
        variant = rng.choice(product["variants"])
        price = Decimal(variant["price"])
        quantity = 2 if price < 40 and rng.random() < 0.3 else 1
        lines.append(
            {
                "id": 0,
                "product_id": int(product["id"]),
                "variant_id": int(variant["id"]),
                "sku": variant["sku"],
                "title": product["title"],
                "variant_title": variant["title"],
                "quantity": quantity,
                "price": _money(price),
            }
        )
    return lines


def _order(
    *,
    order_id: int,
    customer: dict[str, Any],
    products: list[dict[str, Any]],
    campaigns: dict[int, str],
    group: _Group,
    day: date,
    first_order: bool,
    rng: random.Random,
    launch_day: date,
    bought: set[int],
    repeat_weight: float,
) -> dict[str, Any]:
    lines = _line_items(products, group, day, rng, launch_day, bought, repeat_weight)
    bought.update(
        index
        for index, product in enumerate(products)
        if int(product["id"]) in {line["product_id"] for line in lines}
    )
    for position, line in enumerate(lines, 1):
        line["id"] = order_id * 10 + position
    subtotal = sum(Decimal(line["price"]) * line["quantity"] for line in lines)
    discount_codes: list[dict[str, str]] = []
    discount = Decimal("0")
    sale = _sale_for(day)
    if sale is not None and rng.random() < 0.7:
        code, rate = sale
        discount = subtotal * rate
        discount_codes.append({"code": code, "amount": _money(discount), "type": "percentage"})
    elif first_order and rng.random() < group.discount_rate:
        discount = subtotal * Decimal("0.10")
        discount_codes.append(
            {"code": "WELCOME10", "amount": _money(discount), "type": "percentage"}
        )
    elif rng.random() < group.discount_rate * 0.3:
        discount = subtotal * Decimal("0.05")
        discount_codes.append(
            {"code": "THANKYOU5", "amount": _money(discount), "type": "percentage"}
        )
    shipping = Decimal("0") if subtotal >= 75 else Decimal("6.95")
    tax = (subtotal - discount) * Decimal("0.08")
    total = subtotal - discount + shipping + tax
    campaign = campaigns.get(lines[0]["product_id"])
    paid_social = campaign is not None and rng.random() < 0.45
    handle = lines[0]["title"].lower().replace(" ", "-")
    landing = f"/products/{handle}"
    if paid_social:
        landing += f"?utm_source=facebook&utm_medium=paid&utm_campaign={campaign}"
    created = _moment(day, rng)
    place = customer["default_address"]
    return {
        "id": order_id,
        "name": "",
        "created_at": _iso(created),
        "processed_at": _iso(created),
        "financial_status": "paid",
        "fulfillment_status": "fulfilled" if (date(2026, 9, 30) - day).days > 4 else None,
        "currency": "USD",
        "customer_id": customer["id"],
        "email": customer["email"],
        "subtotal_price": _money(subtotal),
        "total_discounts": _money(discount),
        "total_shipping_price": _money(shipping),
        "total_tax": _money(tax),
        "total_price": _money(total),
        "discount_codes": discount_codes,
        "line_items": lines,
        "source_name": "web",
        "landing_site": landing,
        "referring_site": "https://l.facebook.com/" if paid_social else "",
        "tags": "first-order" if first_order else "returning",
        "shipping_address": {
            "city": place["city"],
            "province_code": place["province_code"],
            "country_code": "US",
            "zip": place["zip"],
        },
        "cancelled_at": None,
    }


def _customer(index: int, rng: random.Random) -> dict[str, Any]:
    first, last = rng.choice(_FIRST_NAMES), rng.choice(_LAST_NAMES)
    city, province, zip_code = rng.choice(_PLACES)
    age = rng.choices(_AGE_BANDS, (2, 5, 4, 2, 1))[0]
    subscribed = rng.random() < 0.55
    return {
        "id": 7_000_000 + index,
        "email": f"{first}.{last}{index}@example.com".lower(),
        "first_name": first,
        "last_name": last,
        "state": "enabled",
        "verified_email": True,
        "email_marketing_consent": {
            "state": "subscribed" if subscribed else "not_subscribed",
            "opt_in_level": "single_opt_in",
        },
        "tags": f"age:{age}, region:{province}",
        "currency": "USD",
        "default_address": {
            "city": city,
            "province_code": province,
            "country_code": "US",
            "zip": zip_code,
        },
    }


def build_store(
    *,
    brand_key: str,
    products: list[dict[str, Any]],
    campaigns: dict[int, str],
    seed: int,
    end: date,
    customer_count: int,
) -> tuple[NormalizedRecord, ...]:
    """Return ``customer`` and ``order`` records, ordered by creation time."""
    groups = _GROUPS[brand_key]
    rng = random.Random(f"{seed}:{brand_key}:store")
    launch_day = end - timedelta(days=45)
    customers: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    pending = []
    for index in range(customer_count):
        group = rng.choices(groups, [item.share for item in groups])[0]
        customer = _customer(index, rng)
        for position, day in enumerate(_order_days(group, end, rng)):
            pending.append((day, customer, group, position == 0))
        customers.append(customer)
    pending.sort(key=lambda item: (item[0], item[1]["id"]))
    owned: dict[int, set[int]] = {}
    for number, (day, customer, group, first_order) in enumerate(pending):
        order = _order(
            order_id=5_000_000 + number,
            customer=customer,
            products=products,
            campaigns=campaigns,
            group=group,
            day=day,
            first_order=first_order,
            rng=rng,
            launch_day=launch_day,
            bought=owned.setdefault(customer["id"], set()),
            repeat_weight=_REPEAT_WEIGHT[brand_key],
        )
        order["name"] = f"#{1001 + number}"
        orders.append(order)
    spent: dict[int, Decimal] = {}
    history: dict[int, list[dict[str, Any]]] = {}
    for order in orders:
        history.setdefault(order["customer_id"], []).append(order)
        spent[order["customer_id"]] = spent.get(order["customer_id"], Decimal("0")) + Decimal(
            order["total_price"]
        )
    records = []
    for customer in customers:
        mine = history.get(customer["id"], [])
        if not mine:
            continue
        customer.update(
            {
                "created_at": mine[0]["created_at"],
                "updated_at": mine[-1]["created_at"],
                "orders_count": len(mine),
                "total_spent": _money(spent[customer["id"]]),
                "last_order_id": mine[-1]["id"],
                "last_order_name": mine[-1]["name"],
            }
        )
        records.append(NormalizedRecord("customer", str(customer["id"]), customer))
    records.extend(NormalizedRecord("order", str(order["id"]), order) for order in orders)
    return tuple(records)
