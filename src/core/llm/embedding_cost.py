"""
Kosten fuer Embedding-Aufrufe.

Voyage liefert in der Antwort ``total_tokens``, aber keinen USD-Betrag. Der
Preis wird deshalb aus dem Listenpreis je Modell gerechnet (wie ocr_cost.py
fuer Mistral-OCR).

Quelle der Preise: offizielle Voyage-Preisseite
https://docs.voyageai.com/docs/pricing — Stand 10.11.2026.
ACHTUNG: Listenpreis. Voyage gewaehrt je Konto ein Freikontingent (laut
Preisseite 200 Mio. Tokens fuer voyage-3-large); die Rechnung kann darunter
liegen. Der Wert hier ist also eine Obergrenze dessen, was der Aufruf kostet.

Ein Modell ohne Eintrag hat KEINEN Preis: estimate_embedding_cost gibt dann
0.0 zurueck, und der Aufruf zaehlt in der Metrik als ``unpriced_requests``.
Kein Durchschnitts- oder Ersatzpreis.
"""

from typing import Dict

# USD je 1 Mio. Tokens (Listenpreis).
EMBEDDING_USD_PER_MILLION_TOKENS: Dict[str, float] = {
    "voyage-3-large": 0.18,
}


def has_embedding_price(model: str) -> bool:
    """True, wenn fuer das Modell ein Listenpreis hinterlegt ist."""
    return model in EMBEDDING_USD_PER_MILLION_TOKENS


def estimate_embedding_cost(model: str, tokens: int) -> float:
    """
    USD fuer einen Embedding-Aufruf nach Listenpreis.

    Returns:
        Kosten in USD; 0.0, wenn das Modell keinen Preis hat oder tokens <= 0
        (0.0 bedeutet in der Metrik „Preis unbekannt", siehe LLMRequest.cost).
    """
    if tokens <= 0:
        return 0.0
    price = EMBEDDING_USD_PER_MILLION_TOKENS.get(model)
    if price is None:
        return 0.0
    return float(tokens) * (price / 1_000_000.0)
