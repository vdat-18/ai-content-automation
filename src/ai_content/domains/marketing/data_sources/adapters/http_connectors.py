"""Bounded read-only HTTP connectors for sandbox vendor resources."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from ..domain.models import DataSourceDefinition, NormalizedRecord
from ..ports.interfaces import SourceReadError

_MAX_PAGES = 20
_SHOPIFY_MAX_PAGES = 100
_SHOPIFY_API_VERSION = "2026-07"
_SHOPIFY_METAFIELD_BATCH_SIZE = 50
_SHOPIFY_METAFIELD_KEYS = (
    "des_group_dimensions.depth",
    "des_group_dimensions.height",
    "des_group_dimensions.length",
    "des_group_dimensions.width",
    "des_group_specifications.color",
    "des_group_specifications.shape",
    "des_group_specifications.style",
    "shopify.decoration-material",
    "shopify.furniture-fixture-material",
    "custom.installation_required",
    "custom.ready_to_ship",
    "custom.weight",
)
_SHOPIFY_CREATIVE_PRODUCT_QUERY = """
query CreativeProduct($id: ID!, $metafieldKeys: [String!]!) {
  product(id: $id) {
    id
    title
    handle
    descriptionHtml
    vendor
    productType
    status
    tags
    createdAt
    updatedAt
    publishedAt
    options { id name position optionValues { name } }
    variants(first: 2048) {
      nodes {
        id
        title
        sku
        position
        price
        compareAtPrice
        selectedOptions { name value }
        image { id }
        createdAt
        updatedAt
      }
    }
    images(first: 250) {
      nodes { id url altText width height }
      pageInfo { hasNextPage }
    }
    metafields(first: 50, keys: $metafieldKeys) {
      nodes {
        namespace
        key
        type
        value
        updatedAt
        reference {
          ... on Metaobject { id type handle fields { key type value } }
        }
        references(first: 20) {
          nodes {
            ... on Metaobject { id type handle fields { key type value } }
          }
        }
      }
    }
  }
}
"""
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _error_for_response(response: httpx.Response) -> SourceReadError:
    if response.status_code in {401, 403}:
        return SourceReadError("AUTH_FAILED", "Source credentials or resource access are invalid")
    if response.status_code == 429:
        return SourceReadError("RATE_LIMITED", "Source API rate limit was reached")
    if response.status_code == 404:
        return SourceReadError("RESOURCE_NOT_FOUND", "An allowlisted source resource was not found")
    return SourceReadError("SOURCE_HTTP_ERROR", f"Source API returned HTTP {response.status_code}")


async def _json(response: httpx.Response) -> dict[str, Any]:
    if not response.is_success:
        raise _error_for_response(response)
    try:
        payload = response.json()
    except ValueError as error:
        raise SourceReadError("MALFORMED_RESPONSE", "Source API returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise SourceReadError("MALFORMED_RESPONSE", "Source API response must be an object")
    if isinstance(payload.get("code"), int) and payload["code"] != 0:
        raise SourceReadError("SOURCE_API_ERROR", f"Source API returned code {payload['code']}")
    return payload


class ShopifyConnector:
    def __init__(
        self,
        access_token: str | None,
        timeout_seconds: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = access_token
        self._timeout = timeout_seconds
        self._transport = transport

    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        if any(resource.get("kind") != "products" for resource in definition.resources):
            raise SourceReadError("INVALID_CONFIGURATION", "Shopify only supports products")
        token = self._require_token()
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as client:
            return await self._fetch_products(client, definition, token)

    async def fetch_product(
        self,
        definition: DataSourceDefinition,
        product_id: str,
    ) -> tuple[NormalizedRecord, dict[str, Any]]:
        """Read current truth for one product immediately before Creative compilation."""
        if any(resource.get("kind") != "products" for resource in definition.resources):
            raise SourceReadError("INVALID_CONFIGURATION", "Shopify only supports products")
        token = self._require_token()
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as client:
            return await self._fetch_product(client, definition, token, product_id)

    async def _fetch_product(
        self,
        client: httpx.AsyncClient,
        definition: DataSourceDefinition,
        token: str,
        product_id: str,
    ) -> tuple[NormalizedRecord, dict[str, Any]]:
        response = await client.post(
            f"{definition.base_url}/admin/api/{_SHOPIFY_API_VERSION}/graphql.json",
            headers={
                "X-Shopify-Access-Token": token,
                "Content-Type": "application/json",
            },
            json={
                "query": _SHOPIFY_CREATIVE_PRODUCT_QUERY,
                "variables": {
                    "id": _shopify_gid("Product", product_id),
                    "metafieldKeys": list(_SHOPIFY_METAFIELD_KEYS),
                },
            },
        )
        payload = await _json(response)
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            raise SourceReadError(
                "SOURCE_API_ERROR", "Shopify GraphQL rejected the Creative product query"
            )
        data = payload.get("data")
        product = data.get("product") if isinstance(data, dict) else None
        if product is None:
            raise SourceReadError("RESOURCE_NOT_FOUND", "Shopify product no longer exists")
        if not isinstance(product, dict):
            raise SourceReadError("MALFORMED_RESPONSE", "Shopify product is invalid")
        raw_product, metafields = _shopify_graphql_product(product)
        currency = str(definition.metadata.get("currency", "USD")).upper()
        brand = str(definition.metadata.get("brand") or definition.name)
        store_id = urlparse(definition.base_url).hostname or definition.source_id
        record = _shopify_product(
            raw_product,
            currency,
            brand=brand,
            store_id=store_id,
            metafields=metafields,
        )
        return record, {"product": product}

    async def _fetch_products(
        self,
        client: httpx.AsyncClient,
        definition: DataSourceDefinition,
        token: str,
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        products: list[dict[str, Any]] = []
        url = f"{definition.base_url}/admin/api/{_SHOPIFY_API_VERSION}/products.json"
        params: dict[str, str] | None = {"limit": "250"}
        headers = {"X-Shopify-Access-Token": token}
        for _ in range(_SHOPIFY_MAX_PAGES):
            response = await client.get(url, params=params, headers=headers)
            payload = await _json(response)
            page = payload.get("products")
            if not isinstance(page, list):
                raise SourceReadError("MALFORMED_RESPONSE", "Shopify products are missing")
            products.extend(item for item in page if isinstance(item, dict))
            next_url = _next_link(response.headers.get("link"))
            if next_url is None:
                break
            url, params = next_url, None
        else:
            raise SourceReadError("PAGE_LIMIT_EXCEEDED", "Shopify pagination exceeded limit")
        metafields = await self._fetch_metafields(
            client,
            definition.base_url,
            headers,
            tuple(str(item.get("id")) for item in products if item.get("id") is not None),
        )
        currency = str(definition.metadata.get("currency", "USD")).upper()
        brand = str(definition.metadata.get("brand") or definition.name)
        store_id = urlparse(definition.base_url).hostname or definition.source_id
        records = tuple(
            _shopify_product(
                item,
                currency,
                brand=brand,
                store_id=store_id,
                metafields=metafields.get(str(item.get("id")), ()),
            )
            for item in products
        )
        return records, {"products": products, "metafields": metafields}

    def _require_token(self) -> str:
        if not self._token:
            raise SourceReadError("NOT_CONFIGURED", "Shopify access token is not configured")
        return self._token

    async def _fetch_metafields(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        headers: dict[str, str],
        product_ids: tuple[str, ...],
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        endpoint = f"{base_url}/admin/api/{_SHOPIFY_API_VERSION}/graphql.json"
        query = """
        query ProductCreativeMetafields($ids: [ID!]!, $keys: [String!]!) {
          nodes(ids: $ids) {
            ... on Product {
              id
              metafields(first: 50, keys: $keys) {
                nodes {
                  namespace
                  key
                  type
                  value
                  updatedAt
                  reference {
                    ... on Metaobject { id type handle fields { key type value } }
                  }
                  references(first: 20) {
                    nodes {
                      ... on Metaobject { id type handle fields { key type value } }
                    }
                  }
                }
              }
            }
          }
        }
        """
        output: dict[str, tuple[dict[str, Any], ...]] = {}
        graphql_headers = {**headers, "Content-Type": "application/json"}
        for offset in range(0, len(product_ids), _SHOPIFY_METAFIELD_BATCH_SIZE):
            batch = product_ids[offset : offset + _SHOPIFY_METAFIELD_BATCH_SIZE]
            response = await client.post(
                endpoint,
                headers=graphql_headers,
                json={
                    "query": query,
                    "variables": {
                        "ids": [_shopify_gid("Product", item) for item in batch],
                        "keys": list(_SHOPIFY_METAFIELD_KEYS),
                    },
                },
            )
            payload = await _json(response)
            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                raise SourceReadError(
                    "SOURCE_API_ERROR", "Shopify GraphQL rejected the product metafield query"
                )
            data = payload.get("data")
            nodes = data.get("nodes") if isinstance(data, dict) else None
            if not isinstance(nodes, list):
                # Metafields enrich Product truth but are optional. Preserve the core
                # read_products snapshot when a store returns no GraphQL data.
                continue
            for node in nodes:
                if not isinstance(node, dict) or not node.get("id"):
                    continue
                product_id = str(node["id"]).rsplit("/", 1)[-1]
                connection = node.get("metafields")
                raw_nodes = connection.get("nodes") if isinstance(connection, dict) else []
                output[product_id] = tuple(
                    _shopify_metafield(item) for item in raw_nodes if isinstance(item, dict)
                )
        return output


def _next_link(value: str | None) -> str | None:
    if not value:
        return None
    for item in value.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', item)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


def _shopify_gid(resource: str, value: str) -> str:
    return value if value.startswith("gid://shopify/") else f"gid://shopify/{resource}/{value}"


def _shopify_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).rsplit("/", 1)[-1]


def _shopify_graphql_product(
    product: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    images_connection = product.get("images")
    if not isinstance(images_connection, dict):
        raise SourceReadError("MALFORMED_RESPONSE", "Shopify product images are missing")
    page_info = images_connection.get("pageInfo")
    if isinstance(page_info, dict) and page_info.get("hasNextPage") is True:
        raise SourceReadError("PAGE_LIMIT_EXCEEDED", "Shopify product has more than 250 images")
    image_nodes = images_connection.get("nodes")
    if not isinstance(image_nodes, list):
        raise SourceReadError("MALFORMED_RESPONSE", "Shopify product images are invalid")

    variants_connection = product.get("variants")
    variant_nodes = (
        variants_connection.get("nodes") if isinstance(variants_connection, dict) else None
    )
    if not isinstance(variant_nodes, list):
        raise SourceReadError("MALFORMED_RESPONSE", "Shopify product variants are missing")

    image_variant_ids: dict[str, list[str]] = {}
    variants = []
    for index, item in enumerate(variant_nodes, 1):
        if not isinstance(item, dict):
            continue
        variant_id = _shopify_id(item.get("id"))
        if variant_id is None:
            continue
        image = item.get("image")
        image_id = _shopify_id(image.get("id")) if isinstance(image, dict) else None
        if image_id is not None:
            image_variant_ids.setdefault(image_id, []).append(variant_id)
        selected_options = [
            option for option in item.get("selectedOptions", ()) if isinstance(option, dict)
        ]
        variants.append(
            {
                "id": variant_id,
                "title": item.get("title"),
                "sku": item.get("sku"),
                "position": item.get("position") or index,
                "price": item.get("price"),
                "compare_at_price": item.get("compareAtPrice"),
                "image_id": image_id,
                "created_at": item.get("createdAt"),
                "updated_at": item.get("updatedAt"),
                **{
                    f"option{position}": option.get("value")
                    for position, option in enumerate(selected_options, 1)
                    if position <= 3
                },
            }
        )

    options = []
    for index, item in enumerate(product.get("options", ()), 1):
        if not isinstance(item, dict):
            continue
        values = [
            str(option["name"])
            for option in item.get("optionValues", ())
            if isinstance(option, dict) and option.get("name") is not None
        ]
        options.append(
            {
                "id": _shopify_id(item.get("id")),
                "name": item.get("name"),
                "position": item.get("position") or index,
                "values": values,
            }
        )

    images = []
    for index, item in enumerate(image_nodes, 1):
        if not isinstance(item, dict):
            continue
        image_id = _shopify_id(item.get("id"))
        if image_id is None:
            continue
        images.append(
            {
                "id": image_id,
                "src": item.get("url"),
                "position": index,
                "alt": item.get("altText"),
                "width": item.get("width"),
                "height": item.get("height"),
                "variant_ids": image_variant_ids.get(image_id, ()),
            }
        )

    metafields_connection = product.get("metafields")
    metafield_nodes = (
        metafields_connection.get("nodes") if isinstance(metafields_connection, dict) else ()
    )
    metafields = tuple(
        _shopify_metafield(item) for item in metafield_nodes if isinstance(item, dict)
    )
    return (
        {
            "id": _shopify_id(product.get("id")),
            "title": product.get("title"),
            "handle": product.get("handle"),
            "body_html": product.get("descriptionHtml"),
            "vendor": product.get("vendor"),
            "product_type": product.get("productType"),
            "status": (
                str(product["status"]).casefold() if product.get("status") is not None else None
            ),
            "tags": ", ".join(str(tag) for tag in product.get("tags", ()) if tag),
            "created_at": product.get("createdAt"),
            "updated_at": product.get("updatedAt"),
            "published_at": product.get("publishedAt"),
            "options": options,
            "variants": variants,
            "images": images,
        },
        metafields,
    )


def _shopify_metafield(item: Mapping[str, Any]) -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    reference = item.get("reference")
    if isinstance(reference, dict):
        references.append(reference)
    connection = item.get("references")
    if isinstance(connection, dict) and isinstance(connection.get("nodes"), list):
        references.extend(node for node in connection["nodes"] if isinstance(node, dict))
    canonical = []
    for node in references:
        fields = node.get("fields")
        label = next(
            (
                field.get("value")
                for field in fields or ()
                if isinstance(field, dict)
                and field.get("key") in {"label", "name", "display_name", "value"}
                and field.get("value")
            ),
            None,
        )
        canonical.append(str(label or node.get("handle") or node.get("id")))
    return {
        "namespace": item.get("namespace"),
        "key": item.get("key"),
        "type": item.get("type"),
        "value": item.get("value"),
        "canonical_value": ", ".join(canonical) if canonical else item.get("value"),
        "updated_at": item.get("updatedAt"),
        "references": references,
    }


def _shopify_product(
    product: Mapping[str, Any],
    currency: str,
    *,
    brand: str,
    store_id: str,
    metafields: tuple[dict[str, Any], ...],
) -> NormalizedRecord:
    variants = [item for item in product.get("variants", []) if isinstance(item, dict)]
    images = [item for item in product.get("images", []) if isinstance(item, dict)]
    options = [item for item in product.get("options", []) if isinstance(item, dict)]
    skus = tuple(
        dict.fromkeys(str(item.get("sku", "")).strip() for item in variants if item.get("sku"))
    )
    prices = [str(item.get("price")) for item in variants if item.get("price") is not None]
    product_id = str(product.get("id", ""))
    if not product_id:
        raise SourceReadError("MALFORMED_RESPONSE", "Shopify product has no ID")
    option_names = {
        int(item.get("position") or index): str(item.get("name") or "Option")
        for index, item in enumerate(options, 1)
    }
    normalized_variants = []
    for index, item in enumerate(variants, 1):
        variant_id = item.get("id")
        if variant_id is None:
            continue
        selected_options = [
            {"name": option_names[position], "value": str(value)}
            for position in (1, 2, 3)
            if (value := item.get(f"option{position}")) is not None and position in option_names
        ]
        image_id = str(item["image_id"]) if item.get("image_id") is not None else None
        normalized_variants.append(
            {
                "id": str(variant_id),
                "product_id": product_id,
                "title": str(item.get("title") or item.get("sku") or f"Variant {index}"),
                "sku": str(item["sku"]).strip() if item.get("sku") else None,
                "position": int(item.get("position") or index),
                "price": item.get("price"),
                "compare_at_price": item.get("compare_at_price"),
                "selected_options": selected_options,
                "image_id": image_id,
                "media_ids": (image_id,) if image_id else (),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )
    normalized_media = [
        {
            "id": str(item.get("id")),
            "url": item.get("src"),
            "position": int(item.get("position") or index),
            "alt": item.get("alt"),
            "width": item.get("width"),
            "height": item.get("height"),
            "variant_ids": tuple(str(value) for value in item.get("variant_ids", ()) if value),
        }
        for index, item in enumerate(images, 1)
        if item.get("id") is not None and item.get("src")
    ]
    family_key = skus[0] if len(skus) == 1 else str(product.get("handle") or product_id)
    return NormalizedRecord(
        kind="product",
        provider_id=product_id,
        data={
            "brand": brand,
            "store_id": store_id,
            "product_id": product_id,
            "family_key": family_key,
            "handle": product.get("handle") or product_id,
            "sku": skus[0] if len(skus) == 1 else None,
            "variant_skus": skus,
            "variants": normalized_variants,
            "options": [
                {
                    "id": str(item.get("id") or f"{product_id}:option:{index}"),
                    "product_id": product_id,
                    "name": str(item.get("name") or "Option"),
                    "position": int(item.get("position") or index),
                    "values": tuple(str(value) for value in item.get("values", ()) if value),
                }
                for index, item in enumerate(options, 1)
            ],
            "media": normalized_media,
            "metafields": metafields,
            "title": product.get("title"),
            "description_html": product.get("body_html"),
            "price": prices[0] if prices else None,
            "currency": currency,
            "status": product.get("status"),
            "tags": product.get("tags", ""),
            "product_type": product.get("product_type"),
            "vendor": product.get("vendor"),
            "image_urls": [item["url"] for item in normalized_media],
            "created_at": product.get("created_at"),
            "updated_at": product.get("updated_at"),
            "published_at": product.get("published_at"),
        },
    )


class LarkConnector:
    def __init__(
        self,
        tenant_token: str | None,
        app_id: str | None,
        app_secret: str | None,
        timeout_seconds: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._tenant_token = tenant_token
        self._app_id = app_id
        self._app_secret = app_secret
        self._timeout = timeout_seconds
        self._transport = transport

    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        raw: dict[str, Any] = {"resources": []}
        records: list[NormalizedRecord] = []
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as client:
            token = self._tenant_token or await self._exchange_token(client, definition.base_url)
            headers = {"Authorization": f"Bearer {token}"}
            for resource in definition.resources:
                kind = resource.get("kind")
                if kind == "base":
                    resource_records, payload = await self._fetch_base(
                        client, definition.base_url, headers, resource
                    )
                elif kind == "sheet":
                    resource_records, payload = await self._fetch_sheet(
                        client, definition.base_url, headers, resource
                    )
                elif kind == "doc":
                    resource_records, payload = await self._fetch_doc(
                        client, definition.base_url, headers, resource
                    )
                else:
                    raise SourceReadError("INVALID_CONFIGURATION", "Unsupported Lark resource")
                records.extend(resource_records)
                raw["resources"].append(payload)
        return tuple(records), raw

    async def _exchange_token(self, client: httpx.AsyncClient, base_url: str) -> str:
        if not self._app_id or not self._app_secret:
            raise SourceReadError("NOT_CONFIGURED", "Lark credentials are not configured")
        response = await client.post(
            f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        payload = await _json(response)
        token = payload.get("tenant_access_token")
        if not token:
            raise SourceReadError("AUTH_FAILED", "Lark did not return a tenant token")
        return str(token)

    async def _fetch_base(self, client, base_url, headers, resource):
        app_token = _required(resource, "app_token")
        table_id = _required(resource, "table_id")
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(_MAX_PAGES):
            params = {"page_size": "500"}
            if page_token:
                params["page_token"] = page_token
            response = await client.get(
                f"{base_url}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                params=params,
                headers=headers,
            )
            payload = await _json(response)
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise SourceReadError("MALFORMED_RESPONSE", "Lark Base records are missing")
            items.extend(item for item in data["items"] if isinstance(item, dict))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                raise SourceReadError("MALFORMED_RESPONSE", "Lark Base page token is missing")
        else:
            raise SourceReadError("PAGE_LIMIT_EXCEEDED", "Lark pagination exceeded limit")
        records = tuple(
            NormalizedRecord("creative_brief", str(item.get("record_id")), item.get("fields", {}))
            for item in items
            if item.get("record_id")
        )
        return records, {
            "kind": "base",
            "app_token": app_token,
            "table_id": table_id,
            "items": items,
        }

    async def _fetch_sheet(self, client, base_url, headers, resource):
        token = _required(resource, "spreadsheet_token")
        value_range = _required(resource, "range")
        response = await client.get(
            f"{base_url}/open-apis/sheets/v2/spreadsheets/{token}/values/{quote(value_range, safe='!:$')}",
            headers=headers,
        )
        payload = await _json(response)
        values = payload.get("data", {}).get("valueRange", {}).get("values")
        if not isinstance(values, list):
            raise SourceReadError("MALFORMED_RESPONSE", "Lark Sheet values are missing")
        records = _tabular_records("creative_strategy", token, values)
        return records, {
            "kind": "sheet",
            "spreadsheet_token": token,
            "range": value_range,
            "values": values,
        }

    async def _fetch_doc(self, client, base_url, headers, resource):
        document_id = _required(resource, "document_id")
        response = await client.get(
            f"{base_url}/open-apis/docx/v1/documents/{document_id}/raw_content", headers=headers
        )
        payload = await _json(response)
        content = payload.get("data", {}).get("content")
        if not isinstance(content, str):
            raise SourceReadError("MALFORMED_RESPONSE", "Lark document content is missing")
        return (NormalizedRecord("brand_guideline", document_id, {"content": content}),), {
            "kind": "doc",
            "document_id": document_id,
            "content": content,
        }


class GoogleConnector:
    def __init__(
        self,
        access_token: str | None,
        timeout_seconds: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = access_token
        self._timeout = timeout_seconds
        self._transport = transport

    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        if not self._token:
            raise SourceReadError("NOT_CONFIGURED", "Google access token is not configured")
        headers = {"Authorization": f"Bearer {self._token}"}
        records: list[NormalizedRecord] = []
        raw: dict[str, Any] = {"resources": []}
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as client:
            for resource in definition.resources:
                kind = resource.get("kind")
                if kind == "doc":
                    file_id = _required(resource, "file_id")
                    response = await client.get(
                        f"{definition.base_url}/drive/v3/files/{file_id}/export",
                        params={"mimeType": "text/plain"},
                        headers=headers,
                    )
                    if not response.is_success:
                        raise _error_for_response(response)
                    content = response.text
                    records.append(
                        NormalizedRecord("supporting_context", file_id, {"content": content})
                    )
                    raw["resources"].append({"kind": "doc", "file_id": file_id, "content": content})
                elif kind == "sheet":
                    spreadsheet_id = _required(resource, "spreadsheet_id")
                    value_range = _required(resource, "range")
                    sheets_base_url = str(
                        definition.metadata.get("sheets_base_url", "https://sheets.googleapis.com")
                    ).rstrip("/")
                    response = await client.get(
                        f"{sheets_base_url}/v4/spreadsheets/{spreadsheet_id}/values/{quote(value_range, safe='!:$')}",
                        headers=headers,
                    )
                    payload = await _json(response)
                    values = payload.get("values")
                    if not isinstance(values, list):
                        raise SourceReadError(
                            "MALFORMED_RESPONSE", "Google Sheet values are missing"
                        )
                    records.extend(_tabular_records("supporting_context", spreadsheet_id, values))
                    raw["resources"].append(
                        {
                            "kind": "sheet",
                            "spreadsheet_id": spreadsheet_id,
                            "range": value_range,
                            "values": values,
                        }
                    )
                elif kind == "folder":
                    folder_id = _required(resource, "folder_id")
                    files: list[dict[str, Any]] = []
                    page_token: str | None = None
                    for _ in range(_MAX_PAGES):
                        params = {
                            "q": f"'{folder_id}' in parents and trashed = false",
                            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,thumbnailLink)",
                            "pageSize": "1000",
                        }
                        if page_token:
                            params["pageToken"] = page_token
                        response = await client.get(
                            f"{definition.base_url}/drive/v3/files", params=params, headers=headers
                        )
                        payload = await _json(response)
                        page = payload.get("files")
                        if not isinstance(page, list):
                            raise SourceReadError(
                                "MALFORMED_RESPONSE", "Google Drive files are missing"
                            )
                        files.extend(item for item in page if isinstance(item, dict))
                        page_token = payload.get("nextPageToken")
                        if not page_token:
                            break
                    else:
                        raise SourceReadError(
                            "PAGE_LIMIT_EXCEEDED", "Google pagination exceeded limit"
                        )
                    records.extend(
                        NormalizedRecord("reference_asset", str(item["id"]), item)
                        for item in files
                        if isinstance(item, dict) and item.get("id")
                    )
                    raw["resources"].append(
                        {"kind": "folder", "folder_id": folder_id, "files": files}
                    )
                else:
                    raise SourceReadError("INVALID_CONFIGURATION", "Unsupported Google resource")
        return tuple(records), raw


class GoogleMerchantConnector:
    def __init__(
        self,
        access_token: str | None,
        timeout_seconds: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = access_token
        self._timeout = timeout_seconds
        self._transport = transport

    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        if not self._token:
            raise SourceReadError(
                "NOT_CONFIGURED", "Google Merchant access token is not configured"
            )
        headers = {"Authorization": f"Bearer {self._token}"}
        records: list[NormalizedRecord] = []
        raw: dict[str, Any] = {"resources": []}
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as client:
            for resource in definition.resources:
                if resource.get("kind") != "products":
                    raise SourceReadError(
                        "INVALID_CONFIGURATION", "Google Merchant only supports products"
                    )
                account_id = _digits(_required(resource, "account_id"), "Merchant account ID")
                items: list[dict[str, Any]] = []
                page_token: str | None = None
                for _ in range(_MAX_PAGES):
                    params = {"pageSize": "250"}
                    if page_token:
                        params["pageToken"] = page_token
                    response = await client.get(
                        f"{definition.base_url}/products/v1/accounts/{account_id}/products",
                        params=params,
                        headers=headers,
                    )
                    payload = await _json(response)
                    page = payload.get("products", [])
                    if not isinstance(page, list):
                        raise SourceReadError(
                            "MALFORMED_RESPONSE", "Google Merchant products are missing"
                        )
                    items.extend(item for item in page if isinstance(item, dict))
                    page_token = payload.get("nextPageToken")
                    if not page_token:
                        break
                else:
                    raise SourceReadError(
                        "PAGE_LIMIT_EXCEEDED", "Google Merchant pagination exceeded limit"
                    )
                records.extend(_merchant_product(item) for item in items)
                raw["resources"].append(
                    {"kind": "products", "account_id": account_id, "items": items}
                )
        return tuple(records), raw


class KlaviyoConnector:
    def __init__(
        self,
        api_key: str | None,
        timeout_seconds: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport

    async def fetch(
        self, definition: DataSourceDefinition
    ) -> tuple[tuple[NormalizedRecord, ...], dict[str, Any]]:
        if not self._api_key:
            raise SourceReadError("NOT_CONFIGURED", "Klaviyo API key is not configured")
        headers = {
            "Authorization": f"Klaviyo-API-Key {self._api_key}",
            "accept": "application/vnd.api+json",
            "revision": str(definition.metadata.get("revision", "2025-07-15")),
        }
        records: list[NormalizedRecord] = []
        raw: dict[str, Any] = {"resources": []}
        supported = {
            "campaigns": "email_campaign",
            "flows": "email_flow",
            "metrics": "email_metric",
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as client:
            for resource in definition.resources:
                kind = resource.get("kind")
                record_kind = supported.get(kind)
                if record_kind is None:
                    raise SourceReadError("INVALID_CONFIGURATION", "Unsupported Klaviyo resource")
                params: dict[str, str] | None = {"page[size]": "50"}
                if resource.get("filter"):
                    params["filter"] = str(resource["filter"])
                url = f"{definition.base_url}/{kind}"
                items: list[dict[str, Any]] = []
                for _ in range(_MAX_PAGES):
                    response = await client.get(url, params=params, headers=headers)
                    payload = await _json(response)
                    page = payload.get("data")
                    if not isinstance(page, list):
                        raise SourceReadError("MALFORMED_RESPONSE", "Klaviyo data is missing")
                    items.extend(item for item in page if isinstance(item, dict))
                    links = payload.get("links", {})
                    next_url = links.get("next") if isinstance(links, dict) else None
                    if not next_url:
                        break
                    url = _same_origin_url(definition.base_url, next_url)
                    params = None
                else:
                    raise SourceReadError(
                        "PAGE_LIMIT_EXCEEDED", "Klaviyo pagination exceeded limit"
                    )
                records.extend(_klaviyo_record(record_kind, item) for item in items)
                raw["resources"].append({"kind": kind, "items": items})
        return tuple(records), raw


def _merchant_product(item: Mapping[str, Any]) -> NormalizedRecord:
    attributes = item.get("productAttributes", {})
    if not isinstance(attributes, dict):
        raise SourceReadError("MALFORMED_RESPONSE", "Merchant product attributes are invalid")
    offer_id = str(item.get("offerId") or attributes.get("offerId") or "")
    provider_id = str(item.get("name") or offer_id)
    if not provider_id:
        raise SourceReadError("MALFORMED_RESPONSE", "Merchant product has no ID")
    return NormalizedRecord(
        "merchant_product",
        provider_id,
        {
            "sku": offer_id or None,
            "title": attributes.get("title"),
            "channel": item.get("channel"),
            "content_language": item.get("contentLanguage"),
            "feed_label": item.get("feedLabel"),
            "availability": attributes.get("availability"),
            "link": attributes.get("link"),
            "image_url": attributes.get("imageLink"),
            "price": attributes.get("price"),
            "product_status": item.get("productStatus"),
        },
    )


def _klaviyo_record(kind: str, item: Mapping[str, Any]) -> NormalizedRecord:
    provider_id = str(item.get("id") or "")
    attributes = item.get("attributes", {})
    if not provider_id or not isinstance(attributes, dict):
        raise SourceReadError("MALFORMED_RESPONSE", "Klaviyo item is missing ID or attributes")
    return NormalizedRecord(
        kind,
        provider_id,
        {**attributes, "relationships": item.get("relationships", {})},
    )


async def _json_list(response: httpx.Response, label: str) -> list[dict[str, Any]]:
    if not response.is_success:
        raise _error_for_response(response)
    try:
        payload = response.json()
    except ValueError as error:
        raise SourceReadError("MALFORMED_RESPONSE", "Source API returned invalid JSON") from error
    if not isinstance(payload, list):
        raise SourceReadError("MALFORMED_RESPONSE", f"{label} must be a list")
    return [item for item in payload if isinstance(item, dict)]

def _digits(value: str, label: str) -> str:
    normalized = value.replace("-", "")
    if not normalized.isdigit():
        raise SourceReadError("INVALID_CONFIGURATION", f"{label} must contain only digits")
    return normalized

def _same_origin_url(base_url: str, next_url: Any) -> str:
    if not isinstance(next_url, str):
        raise SourceReadError("MALFORMED_RESPONSE", "Pagination URL is invalid")
    base = urlparse(base_url)
    candidate = urlparse(next_url)
    if (candidate.scheme, candidate.netloc) != (base.scheme, base.netloc):
        raise SourceReadError("MALFORMED_RESPONSE", "Pagination URL changed source origin")
    return next_url


def _required(resource: Mapping[str, Any], name: str) -> str:
    value = resource.get(name)
    if not isinstance(value, str) or not value:
        raise SourceReadError("INVALID_CONFIGURATION", f"Resource field {name} is required")
    return value


def _tabular_records(kind: str, parent_id: str, values: list[Any]) -> tuple[NormalizedRecord, ...]:
    if not values:
        return ()
    headers = [str(item) for item in values[0]] if isinstance(values[0], list) else []
    records = []
    for index, row in enumerate(values[1:], start=2):
        if not isinstance(row, list):
            continue
        data = {
            header: row[column] if column < len(row) else None
            for column, header in enumerate(headers)
        }
        records.append(NormalizedRecord(kind, f"{parent_id}:row:{index}", data))
    return tuple(records)


__all__ = [
    "GoogleConnector",
    "GoogleMerchantConnector",
    "KlaviyoConnector",
    "LarkConnector",
    "ShopifyConnector",
    "SourceReadError",
]
