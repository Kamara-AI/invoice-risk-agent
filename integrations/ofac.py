"""OFAC sanctions screening integration.

Calls the OFAC API (v4) to screen vendor names against the Specially
Designated Nationals (SDN) list and other sanctions lists.

A positive match (score above the API's threshold) is treated as a hard block.
The result is also written back to vendor_ledger.ofac_status to avoid
redundant API calls for repeat invoices from the same vendor.
"""

from __future__ import annotations

import httpx

from config import settings


class OFACClient:
    """HTTP client for the OFAC sanctions screening API.

    Uses httpx for synchronous HTTP calls. All methods raise on
    non-2xx responses — callers should catch httpx.HTTPStatusError.
    """

    def __init__(self) -> None:
        """Initialise the OFAC HTTP client with base URL and API key from settings."""
        self._base_url = settings.ofac_api_base_url
        self._api_key = settings.ofac_api_key
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=10.0,
        )

    def check_vendor(
        self,
        vendor_name: str,
        vendor_country: str | None = None,
    ) -> dict:
        """Screen a vendor name against the OFAC sanctions list.

        Sends a synchronous POST to the OFAC API screening endpoint.
        The response includes a match score and a list of matched entities.
        A match score >= 85 is treated as a positive hit by gate_ofac.

        Args:
            vendor_name: Legal name of the vendor as it appears on the invoice.
            vendor_country: Optional ISO 3166-1 alpha-2 country code. Providing
                            this narrows the search and reduces false positives.

        Returns:
            Raw API response dict containing at minimum:
            - 'match': bool — True if any entity exceeded the threshold.
            - 'score': float — Highest match score across all entities.
            - 'matches': list[dict] — Details of matched entities (may be empty).

        Raises:
            httpx.HTTPStatusError: On non-2xx API responses.
            httpx.RequestError: On network-level failures.
        """
        # Build the case entry — optionally include country to narrow results.
        case: dict = {"name": vendor_name}
        if vendor_country:
            case["address"] = {"country": vendor_country}

        payload = {
            "apiKey": self._api_key,
            "minScore": 75,   # Capture soft-flag range (75-89) AND hard-block range (>=90)
            "sources": ["SDN"],
            "cases": [case],
        }

        response = self._client.post("/screen", json=payload)
        response.raise_for_status()

        raw = response.json()

        # Normalise to the canonical return contract expected by gate_ofac.
        # The OFAC v4 API returns: {"results": [{"matches": [...]}]}
        results = raw.get("results", [])
        all_matches: list[dict] = []
        highest_score: float = 0.0

        for result in results:
            matches = result.get("matches", [])
            all_matches.extend(matches)
            for match in matches:
                score = match.get("score", 0.0)
                if score > highest_score:
                    highest_score = score

        matched = len(all_matches) > 0

        return {
            "match": matched,
            "score": highest_score,
            "matches": all_matches,
            "raw": raw,  # Preserve full payload for gate_results.details
        }
