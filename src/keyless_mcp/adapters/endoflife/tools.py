"""Compact release-cycle and product discovery tools for endoflife.date's v1 API."""

import datetime
import re
from typing import Annotated, Any

from pydantic import Field

from keyless_mcp.core import AdapterHttp, InvalidInput, ToolRegistry, UpstreamError

BASE_URL = "https://endoflife.date/api/v1"
MAX_CYCLES = 25


def _cycle(release: dict[str, Any], today: datetime.date) -> dict[str, Any]:
    """Preserve lifecycle dates and booleans, leaving missing statuses unknown."""
    if not isinstance(release, dict) or not isinstance(release.get("name"), str):
        raise UpstreamError("endoflife: response contains an invalid release cycle.")
    eol = release.get("eolFrom")
    if eol is None:
        flag = release.get("isEol")
        eol = flag if isinstance(flag, bool) else None
    if isinstance(eol, str):
        try:
            eol_passed = datetime.date.fromisoformat(eol) <= today
        except ValueError:
            raise UpstreamError("endoflife: response contains an invalid EOL date.") from None
    elif isinstance(eol, bool) or eol is None:
        eol_passed = eol
    else:
        raise UpstreamError("endoflife: response contains an invalid EOL date or status.")

    support = release.get("eoasFrom")
    if support is None and isinstance(release.get("isEoas"), bool):
        support = not release["isEoas"]
    lts = release.get("ltsFrom")
    if lts is None and isinstance(release.get("isLts"), bool):
        lts = release["isLts"]
    latest = release.get("latest")
    if latest is not None and (
        not isinstance(latest, dict)
        or any(
            value is not None and not isinstance(value, str)
            for value in (latest.get("name"), latest.get("date"))
        )
    ):
        raise UpstreamError("endoflife: response contains an invalid latest version.")
    latest = latest or {}
    return {
        "cycle": release["name"],
        "release_date": release.get("releaseDate"),
        "eol": eol,
        "eol_passed": eol_passed,
        "latest": latest.get("name"),
        "latest_release_date": latest.get("date"),
        "lts": lts,
        "support": support,
    }


def register(tools: ToolRegistry, http: AdapterHttp) -> None:
    @tools.tool(title="Get software release cycles and end-of-life dates")
    async def endoflife_get_product(
        product: Annotated[
            str,
            Field(description="Lowercase slug, e.g. 'python'; use letters, digits and hyphens."),
        ],
        limit: Annotated[
            int,
            Field(
                strict=True,
                description="Maximum release cycles as an integer, 1 to 25, e.g. 5. Default 10.",
            ),
        ] = 10,
    ) -> dict[str, Any]:
        """Get a product's release cycles, versions, release, EOL, LTS and support dates.

        eol_passed uses the current UTC date (true on and after the EOL date), or the API's
        boolean status when no date is known; null means unknown. eol, lts and support preserve
        dates or boolean statuses. support refers to active support, not every support phase;
        false eol_passed alone does not imply active support. Includes counts, as_of and source URL.
        """
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", product) is None:
            raise InvalidInput("product must be a lowercase slug, e.g. 'python' or 'ubuntu'.")
        if not 1 <= limit <= MAX_CYCLES:
            raise InvalidInput("limit must be between 1 and 25.")
        url = f"{BASE_URL}/products/{product}/"
        data = await http.get_json(url)
        result = data.get("result") if isinstance(data, dict) else None
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("name"), str)
            or not isinstance(result.get("releases"), list)
        ):
            raise UpstreamError("endoflife: expected a product response containing release cycles.")
        releases = result["releases"]
        today = datetime.datetime.now(datetime.UTC).date()
        return {
            "product": result["name"],
            "as_of": today.isoformat(),
            "total": len(releases),
            "returned": min(limit, len(releases)),
            "cycles": [_cycle(release, today) for release in releases[:limit]],
            "source_url": url,
        }

    @tools.tool(title="List product slugs tracked by endoflife.date")
    async def endoflife_list_products() -> dict[str, Any]:
        """List all canonical product slugs, their count and source URL to discover lookup names.

        Returns only slugs, omitting the index's aliases, tags and other product metadata.
        Use one of these names as the product argument to endoflife_get_product.
        """
        url = f"{BASE_URL}/products/"
        data = await http.get_json(url)
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            raise UpstreamError("endoflife: expected a product index response.")
        if any(
            not isinstance(product, dict) or not isinstance(product.get("name"), str)
            for product in data["result"]
        ):
            raise UpstreamError("endoflife: response contains an invalid product index entry.")
        products = [product["name"] for product in data["result"]]
        return {"products": products, "count": len(products), "source_url": url}
