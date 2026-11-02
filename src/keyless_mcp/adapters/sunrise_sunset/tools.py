"""Tools for retrieving UTC solar times from Sunrise-Sunset.org."""

from typing import Annotated, Any

from pydantic import Field

from keyless_mcp.core import AdapterHttp, InvalidInput, ToolRegistry, UpstreamError

API_URL = "https://api.sunrise-sunset.org/json"
SOURCE_URL = "https://sunrise-sunset.org"


def _coordinate(value: float, name: str, lower: float, upper: float) -> float:
    if not lower <= value <= upper:
        raise InvalidInput(f"{name} must be between {lower:g} and {upper:g}.")
    return value


def register(tools: ToolRegistry, http: AdapterHttp) -> None:
    @tools.tool(title="Get UTC sunrise and sunset times")
    async def sunrise_sunset_get_times(
        latitude: Annotated[
            float,
            Field(description="Latitude in decimal degrees, e.g. 36.72016. Must be -90 to 90."),
        ],
        longitude: Annotated[
            float,
            Field(description="Longitude in decimal degrees, e.g. -4.42034. Must be -180 to 180."),
        ],
        date: Annotated[
            str,
            Field(
                description="UTC calendar date as YYYY-MM-DD, e.g. '2020-01-15'. Default 'today'."
            ),
        ] = "today",
    ) -> dict[str, Any]:
        """Get UTC sunrise, sunset, solar noon and twilight times for a location and date.

        Results include the Sunrise-Sunset.org source URL for required attribution.
        """
        lat = _coordinate(latitude, "latitude", -90, 90)
        lng = _coordinate(longitude, "longitude", -180, 180)
        data = await http.get_json(
            API_URL,
            {"lat": lat, "lng": lng, "date": date, "formatted": 0},
        )
        if not isinstance(data, dict) or data.get("status") != "OK":
            status = data.get("status") if isinstance(data, dict) else "invalid response"
            raise UpstreamError(f"sunrise_sunset: API returned {status!r}.")
        results = data.get("results")
        if not isinstance(results, dict):
            raise UpstreamError("sunrise_sunset: API response did not include results.")
        return {
            "status": data["status"],
            "tzid": data.get("tzid", "UTC"),
            "results": results,
            "source_url": SOURCE_URL,
        }
