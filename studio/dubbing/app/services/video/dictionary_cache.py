import logging
import os
from cachetools import TTLCache, cached
from convex import ConvexClient
import re

logger = logging.getLogger(__name__)

CONVEX_URL = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
_client: ConvexClient | None = None


def _get_client() -> ConvexClient:
    global _client
    if _client is None:
        _client = ConvexClient(CONVEX_URL)
    return _client


dict_cache = TTLCache(maxsize=128, ttl=300)


@cached(cache=dict_cache)
def fetch_dictionary_category(category_id: str) -> dict:
    """
    Fetches the global configuration document from Convex
    `dubbingDictionaries` for a specific category_id (e.g. 'automotive').
    Returns the JSON payload stored in the `data` column.
    """
    if not category_id:
        return {}

    try:
        client = _get_client()
        result = client.query(
            "dictionaries:getByCategoryInternal",
            {
                "categoryId": category_id,
                "__internalApiKey": INTERNAL_API_KEY,
            },
        )
        return result or {}
    except Exception as e:
        logger.error(f"[DICTIONARY] Failed to fetch dictionary category {category_id} from Convex: {e}")
        return {}


def build_dictionary_prompt(category_id: str, entity: str) -> str:
    """Builds the system prompt block for the category + entity."""
    block = ""

    if category_id:
        data = fetch_dictionary_category(category_id)
        if data:
            anti_priming = data.get("anti_priming", "")
            if anti_priming:
                block += f"ANTI_PRIMING RULE: {anti_priming}\n\n"

            dictionary = data.get("dictionary", [])
            if dictionary:
                block += f"--- {str(category_id).upper()} DICTIONARY ---\n"
                for item in dictionary:
                    term = item.get("term", "")
                    output = item.get("output", "")
                    rule = item.get("rule", "TRANSLITERATE")
                    if term and output:
                        block += f"- Hear: '{term}' -> Write: '{output}' (Rule: {rule})\n"
                block += "\n"

    if entity and entity.strip():
        entity = entity.strip()
        block += (
            f"ZERO-SHOT OVERRIDE: The user has explicitly identified the core subject of this video as '{entity}'. "
            f"If this is an alphanumeric tech product, brand name, or car model (e.g. F-150, iPhone 16), retain it exactly as '{entity}' in Latin text. "
            f"Otherwise, translate '{entity}' to Sorani accurately."
        )

    return block.strip()


def inject_lrm(text: str, category_id: str) -> str:
    """
    Injects Left-to-Right Mark (U+200E) around canonical Latin entity strings
    mapped in the dictionary.
    """
    if not text or not category_id:
        return text

    data = fetch_dictionary_category(category_id)
    if data:
        dictionary = data.get("dictionary", [])
        for item in dictionary:
            if item.get("rule") == "LATIN_CANONICAL":
                target = item.get("output", "")
                if target:
                    pattern = re.compile(re.escape(target), re.IGNORECASE)
                    text = pattern.sub(f"‎{target}‎", text)

    return text
