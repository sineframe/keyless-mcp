"""Tools for Frankfurter's dated currency reference rates."""

import datetime
import re
from typing import Annotated, Any
from urllib.parse import urlencode

from pydantic import Field

from keyless_mcp.core import AdapterHttp, InvalidInput, ToolRegistry, UpstreamError

BASE_URL = "https://api.frankfurter.dev/v1"
MAX_DAYS = 31


def _currency(code: str) -> str:
    if re.fullmatch(r"[A-Z]{3}", code) is None:
        raise InvalidInput("Currency codes must be three uppercase letters, e.g. EUR or USD.")
    return code


def _params(base: str, symbols: str | None) -> dict[str, str]:
    params = {"base": _currency(base)}
    if symbols is not None:
        codes = [_currency(code.strip()) for code in symbols.split(",")]
        params["symbols"] = ",".join(dict.fromkeys(codes))
    return params


def _date(value: str) -> datetime.date:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise InvalidInput("Dates must use YYYY-MM-DD, e.g. 2024-01-02.")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise InvalidInput("Dates must be a valid calendar date, e.g. 2024-01-02.") from None


async def _rates(http: AdapterHttp, path: str, params: dict[str, str]) -> dict[str, Any]:
    data = await http.get_json(f"{BASE_URL}/{path}", params)
    if not isinstance(data, dict) or not isinstance(data.get("rates"), dict):
        raise UpstreamError("frankfurter: expected an object containing currency rates.")
    return {**data, "source_url": f"{BASE_URL}/{path}?{urlencode(params)}"}


def register(tools: ToolRegistry, http: AdapterHttp) -> None:
    @tools.tool(title="Get dated currency reference rates")
    async def frankfurter_get_rates(
        base: Annotated[
            str, Field(description="Base currency as three uppercase letters, e.g. 'EUR'.")
        ] = "EUR",
        symbols: Annotated[
            str | None,
            Field(description="Target codes, e.g. 'USD,GBP'; omit for all supported currencies."),
        ] = None,
        date: Annotated[
            str,
            Field(description="Calendar date as YYYY-MM-DD, e.g. '2024-01-06', or 'latest'."),
        ] = "latest",
    ) -> dict[str, Any]:
        """Get amount, base, observation date, rates and source URL for currency reference rates.

        Rates are per unit of base currency. 'latest' means the latest working day's reference
        rates, not live trading prices. Weekends and holidays can return an earlier date.
        """
        params = _params(base, symbols)
        if date != "latest":
            _date(date)
        return await _rates(http, date, params)

    @tools.tool(title="Get a short currency reference-rate time series")
    async def frankfurter_get_time_series(
        start_date: Annotated[
            str, Field(description="First calendar date as YYYY-MM-DD, e.g. '2024-01-02'.")
        ],
        end_date: Annotated[
            str,
            Field(
                description=("End date, e.g. '2024-01-04' (YYYY-MM-DD); at most 31 days inclusive.")
            ),
        ],
        base: Annotated[
            str, Field(description="Base currency as three uppercase letters, e.g. 'EUR'.")
        ] = "EUR",
        symbols: Annotated[
            str | None,
            Field(description="Target codes, e.g. 'USD,GBP'; omit for all supported currencies."),
        ] = None,
    ) -> dict[str, Any]:
        """Get amount, base, date bounds, daily rates keyed by observation date and source URL.

        Limit requests to 31 calendar days including both bounds. Rates are per unit of base
        currency and are published on working days, so dates may differ from the requested bounds.
        """
        params = _params(base, symbols)
        start, end = _date(start_date), _date(end_date)
        if start > end:
            raise InvalidInput("start_date must not be after end_date.")
        if (end - start).days >= MAX_DAYS:
            raise InvalidInput("Range must span at most 31 calendar days, including both bounds.")
        return await _rates(http, f"{start_date}..{end_date}", params)

    @tools.tool(title="List supported currency codes")
    async def frankfurter_list_currencies() -> dict[str, Any]:
        """List supported currency codes and their full names, with a count and source URL."""
        data = await http.get_json(f"{BASE_URL}/currencies")
        if not isinstance(data, dict):
            raise UpstreamError("frankfurter: expected an object of currency codes and names.")
        return {"currencies": data, "count": len(data), "source_url": f"{BASE_URL}/currencies"}
