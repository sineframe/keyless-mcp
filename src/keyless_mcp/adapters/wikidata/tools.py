"""Wikidata tools: entity search and entity lookup through the Wikibase Action API."""

import re
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import Field

from keyless_mcp.core import AdapterHttp, InvalidInput, ToolRegistry, UpstreamError, truncate

API_URL = "https://www.wikidata.org/w/api.php"
ENTITY_URL = "https://www.wikidata.org/wiki/"
MAX_LIMIT = 50  # wbsearchentities rejects more than 50 for anonymous clients
TEXT_CHARS = 300

# Wikidata language codes are plain lowercase codes: "en", "de", "zh-hans", "mul".
LANG_RE = re.compile(r"^[a-z]{2,12}(-[a-z]{2,12})*$")
# "q42" is accepted for "Q42". Other input is sent unchanged so the API judges it.
ID_RE = re.compile(r"^[pqlPQL]\d+$")
# Error codes caused by the caller's arguments; any other code is reported as an upstream fault.
INPUT_ERROR_CODES = {"no-such-entity", "invalid-entity-id", "badvalue"}


def check_language(language: str) -> str:
    code = language.strip().lower()
    if not LANG_RE.match(code):
        raise InvalidInput(
            f"language {language!r} is not a Wikidata language code. Use codes such as 'en', "
            "'de', 'fr', 'es', 'ja' or 'zh-hans'."
        )
    return code


def entity_url(entity_id: str) -> str:
    return f"{ENTITY_URL}{quote(entity_id, safe='')}"


def raise_for_api_error(data: Any) -> None:
    """Wikidata reports many failures as HTTP 200 with ``{"error": {"code", "info"}}``."""
    if not isinstance(data, dict):
        raise UpstreamError("wikidata: unexpected response shape from the Wikidata API")
    error = data.get("error")
    if error is None:
        return
    code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
    info = error.get("info", "no details given") if isinstance(error, dict) else str(error)
    if code in INPUT_ERROR_CODES:
        raise InvalidInput(f"Wikidata rejected the request ({code}): {info}")
    raise UpstreamError(f"wikidata: the Wikidata API answered with error {code}: {info}")


def pick_text(values: dict[str, Any], language: str) -> tuple[str | None, str | None]:
    """The best (text, language) from a labels/descriptions map, or (None, None).

    With ``languagefallback=1`` the API files the fallback text under the requested language
    key and says which language it really is in ``language`` (Q42's label is "mul"). If the key
    is missing, try "mul" and "en", then anything at all.
    """
    for key in (language, "mul", "en", *values):
        entry = values.get(key)
        if isinstance(entry, dict) and entry.get("value"):
            return truncate(entry["value"], TEXT_CHARS), entry.get("language", key)
    return None, None


def sitelink_key(language: str) -> str:
    """Wikidata names a language edition ``<code>wiki`` with ``_`` for ``-``: zh_yuewiki."""
    return f"{language.replace('-', '_')}wiki"


def wikipedia_link(sitelinks: dict[str, Any], language: str) -> dict[str, str] | None:
    """The Wikipedia article in the requested language, else the English one, else None."""
    for code in (language, "en"):
        link = sitelinks.get(sitelink_key(code))
        if isinstance(link, dict) and link.get("title"):
            title = link["title"]
            slug = quote(title.replace(" ", "_"), safe="()_,:")
            return {
                "language": code,
                "title": title,
                "url": f"https://{code}.wikipedia.org/wiki/{slug}",
            }
    return None


def register(tools: ToolRegistry, http: AdapterHttp) -> None:
    @tools.tool(title="Search Wikidata entities")
    async def wikidata_search_entities(
        query: Annotated[
            str,
            Field(
                description="Name or alias of the thing to find, e.g. 'Douglas Adams' or "
                "'Eiffel Tower'. Must not be empty."
            ),
        ],
        language: Annotated[
            str,
            Field(
                description="Language of the search and of the returned labels, e.g. 'en' "
                "(default), 'de', 'fr', 'es', 'ja'."
            ),
        ] = "en",
        limit: Annotated[
            int, Field(description=f"How many entities to return, 1 to {MAX_LIMIT}. Default 5.")
        ] = 5,
    ) -> dict[str, Any]:
        """Search Wikidata for entities (people, places, works, concepts) by name. Returns the
        best matches with entity ID (such as Q42), label, short description, Wikidata URL and
        what text matched. Use it to find the ID of a thing, then call wikidata_get_entity
        with that ID for its details and Wikipedia article."""
        text = query.strip()
        if not text:
            raise InvalidInput("query must not be empty.")
        if not 1 <= limit <= MAX_LIMIT:
            raise InvalidInput(f"limit must be between 1 and {MAX_LIMIT}.")
        code = check_language(language)
        data = await http.get_json(
            API_URL,
            {
                "action": "wbsearchentities",
                "search": text,
                "language": code,
                "limit": limit,
                "format": "json",
            },
        )
        raise_for_api_error(data)
        found = data.get("search")
        if not isinstance(found, list):
            raise UpstreamError("wikidata: the search response had no 'search' list")
        results = []
        for item in found:
            match = item.get("match") or {}
            results.append(
                {
                    "id": item["id"],
                    "label": truncate(item.get("label") or "", TEXT_CHARS) or None,
                    "description": truncate(item.get("description") or "", TEXT_CHARS) or None,
                    "url": entity_url(item["id"]),
                    "match": {"type": match.get("type"), "text": match.get("text")},
                }
            )
        return {"query": text, "language": code, "returned": len(results), "results": results}

    @tools.tool(title="Get Wikidata entity")
    async def wikidata_get_entity(
        entity_id: Annotated[
            str,
            Field(
                description="Wikidata entity ID, e.g. 'Q42' (Douglas Adams) or 'Q90' (Paris). "
                "One ID only. Use wikidata_search_entities to find it."
            ),
        ],
        language: Annotated[
            str,
            Field(
                description="Preferred language for the label and description, e.g. 'en' "
                "(default), 'de', 'fr'. Falls back to a related language when missing."
            ),
        ] = "en",
    ) -> dict[str, Any]:
        """Get one Wikidata entity by ID. Returns its label, short description (each with the
        language actually used, since fallbacks happen), Wikidata URL and its matching
        Wikipedia article title and URL when one exists. It does not return the entity's
        property statements."""
        wanted = entity_id.strip()
        if not wanted:
            raise InvalidInput("entity_id must not be empty.")
        if "|" in wanted:
            raise InvalidInput("entity_id must be a single ID such as 'Q42', not a list.")
        if ID_RE.match(wanted):
            wanted = wanted.upper()
        code = check_language(language)
        sites = "|".join(dict.fromkeys(sitelink_key(c) for c in (code, "en")))
        data = await http.get_json(
            API_URL,
            {
                "action": "wbgetentities",
                "ids": wanted,
                "props": "labels|descriptions|sitelinks",
                "languages": code,
                "languagefallback": 1,
                "sitefilter": sites,
                "format": "json",
            },
        )
        raise_for_api_error(data)
        entities = data.get("entities")
        entity = next(iter(entities.values()), None) if isinstance(entities, dict) else None
        if not isinstance(entity, dict):
            raise UpstreamError("wikidata: the response had no entity")
        if "missing" in entity:
            raise InvalidInput(
                f"No Wikidata entity {wanted!r}. Use wikidata_search_entities to find the ID."
            )
        label, label_language = pick_text(entity.get("labels") or {}, code)
        description, description_language = pick_text(entity.get("descriptions") or {}, code)
        entity_id_found = entity.get("id", wanted)
        return {
            "id": entity_id_found,
            "language": code,
            "label": label,
            "label_language": label_language,
            "description": description,
            "description_language": description_language,
            "url": entity_url(entity_id_found),
            "wikipedia": wikipedia_link(entity.get("sitelinks") or {}, code),
        }
