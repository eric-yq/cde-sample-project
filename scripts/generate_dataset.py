#!/usr/bin/env python3
"""Generate the synthetic evaluation dataset (R8.1, R8.3).

Produces ``tests/data/dataset.json`` deterministically (no randomness) with:

* ``clean``: 100 reviews (50 French + 50 German) built from 10 parallel
  template triples x 5 products. Each entry carries a reference English
  translation (used as the "expected output" and by the offline evaluation
  engines) and synthetic PII fields (reviewer_name/email) to exercise stripping.
* ``noisy``: labeled bad inputs that MUST be rejected, each annotated with the
  expected rejection reason and stage. Offline-only flags
  (``_offline_bad_translation`` / ``_offline_bad_summary`` / ``_offline_bad_json``)
  let the offline evaluation engines simulate gate failures for inputs that are
  structurally valid but should fail on quality.

The ``review`` object of every entry is a clean vendor payload; all evaluation
metadata lives outside it under ``expected`` / ``_meta``.

Usage:  python scripts/generate_dataset.py
"""

from __future__ import annotations

import json
import os

# 10 parallel template triples. {p} is replaced by the product noun in each
# language. Ratings reflect the sentiment so the dataset is realistic.
TEMPLATES = [
    {"fr": "Ce {p} est incroyablement doux et taille parfaitement.",
     "de": "Dieses {p} ist unglaublich weich und passt perfekt.",
     "en": "This {p} is incredibly soft and fits perfectly.", "rating": 5},
    {"fr": "La qualite du {p} est excellente pour le prix.",
     "de": "Die Qualitaet des {p} ist ausgezeichnet fuer den Preis.",
     "en": "The quality of the {p} is excellent for the price.", "rating": 5},
    {"fr": "Livraison rapide et le {p} correspond a la description.",
     "de": "Schnelle Lieferung und das {p} entspricht der Beschreibung.",
     "en": "Fast delivery and the {p} matches the description.", "rating": 4},
    {"fr": "Le {p} a retreci apres le premier lavage, decevant.",
     "de": "Das {p} ist nach der ersten Waesche eingelaufen, enttaeuschend.",
     "en": "The {p} shrank after the first wash, disappointing.", "rating": 2},
    {"fr": "Couleur magnifique mais le {p} taille un peu petit.",
     "de": "Wunderschoene Farbe, aber das {p} faellt etwas klein aus.",
     "en": "Beautiful color but the {p} runs a bit small.", "rating": 3},
    {"fr": "Tres confortable, je recommande ce {p} sans hesiter.",
     "de": "Sehr bequem, ich empfehle dieses {p} ohne zu zoegern.",
     "en": "Very comfortable, I recommend this {p} without hesitation.", "rating": 5},
    {"fr": "Le tissu du {p} est fin mais agreable a porter.",
     "de": "Der Stoff des {p} ist duenn, aber angenehm zu tragen.",
     "en": "The fabric of the {p} is thin but pleasant to wear.", "rating": 4},
    {"fr": "Rapport qualite-prix imbattable pour ce {p}.",
     "de": "Unschlagbares Preis-Leistungs-Verhaeltnis fuer dieses {p}.",
     "en": "Unbeatable value for money for this {p}.", "rating": 5},
    {"fr": "Le {p} est arrive avec un petit defaut de couture.",
     "de": "Das {p} kam mit einem kleinen Nahtfehler an.",
     "en": "The {p} arrived with a small stitching defect.", "rating": 2},
    {"fr": "Parfait pour l'ete, ce {p} est leger et respirant.",
     "de": "Perfekt fuer den Sommer, dieses {p} ist leicht und atmungsaktiv.",
     "en": "Perfect for summer, this {p} is light and breathable.", "rating": 5},
]

PRODUCTS = [
    {"fr": "t-shirt", "de": "T-Shirt", "en": "t-shirt", "sku": "TSHIRT"},
    {"fr": "pull", "de": "Pullover", "en": "sweater", "sku": "SWEATER"},
    {"fr": "robe", "de": "Kleid", "en": "dress", "sku": "DRESS"},
    {"fr": "veste", "de": "Jacke", "en": "jacket", "sku": "JACKET"},
    {"fr": "chemise", "de": "Hemd", "en": "shirt", "sku": "SHIRT"},
]

FIRST_NAMES = ["Camille", "Lucas", "Emma", "Louis", "Chloe", "Jonas", "Mia", "Finn", "Lea", "Noah"]


def _reviewer(idx: int) -> tuple[str, str]:
    name = FIRST_NAMES[idx % len(FIRST_NAMES)]
    email = f"{name.lower()}{idx}@example.com"
    return name, email


def _clean_entries(language: str) -> list[dict]:
    entries: list[dict] = []
    counter = 0
    for t_idx, template in enumerate(TEMPLATES):
        for p_idx, product in enumerate(PRODUCTS):
            counter += 1
            text = template[language].format(p=product[language])
            reference = template["en"].format(p=product["en"])
            name, email = _reviewer(counter)
            review_id = f"r-{language}-{counter:03d}"
            entries.append(
                {
                    "review": {
                        "review_id": review_id,
                        "product_id": f"SKU-{product['sku']}-{p_idx+1:02d}",
                        "text": text,
                        "rating": template["rating"],
                        "source_language": language,
                        "reviewer_name": name,
                        "reviewer_email": email,
                    },
                    "expected": {"outcome": "approved"},
                    "_meta": {"reference_translation": reference, "template": t_idx},
                }
            )
    return entries


def _noisy_entries() -> list[dict]:
    def entry(review, reason, stage, **flags):
        e = {"review": review, "expected": {"outcome": "rejected", "reason": reason, "stage": stage}}
        e.update(flags)
        return e

    base_pii = {"reviewer_name": "Test User", "reviewer_email": "test@example.com"}
    return [
        entry(
            {"review_id": "n-001", "product_id": "SKU-TSHIRT-01", "text": "", "rating": 5, "source_language": "fr", **base_pii},
            "validation_error", "ingest",
        ),
        entry(
            {"review_id": "n-002", "product_id": "SKU-TSHIRT-01", "text": "   ", "rating": 5, "source_language": "de", **base_pii},
            "validation_error", "ingest",
        ),
        entry(
            {"review_id": "n-003", "text": "Bon produit", "rating": 5, "source_language": "fr", **base_pii},
            "validation_error", "ingest",  # missing product_id
        ),
        entry(
            {"review_id": "n-004", "product_id": "SKU-TSHIRT-01", "text": "Produit correct", "rating": 9, "source_language": "fr", **base_pii},
            "validation_error", "ingest",  # rating out of range
        ),
        entry(
            {"review_id": "n-005", "product_id": "SKU-TSHIRT-01", "text": "Produit correct", "rating": "abc", "source_language": "fr", **base_pii},
            "validation_error", "ingest",  # non-numeric rating
        ),
        entry(
            {"review_id": "n-006", "product_id": "SKU-TSHIRT-01", "text": "Good product overall", "rating": 5, "source_language": "ja", **base_pii},
            "unsupported_language", "ingest",
        ),
        entry(
            {"review_id": "n-007", "product_id": "SKU-TSHIRT-01",
             "text": "Ce produit est vraiment excellent et tres confortable a porter tous les jours de la semaine.",
             "rating": 5, "source_language": "fr", **base_pii},
            "low_translation_quality", "translation_gate", _offline_bad_translation=True,
        ),
        entry(
            {"review_id": "n-008", "product_id": "SKU-DRESS-03",
             "text": "La robe est jolie et le tissu agreable au toucher.",
             "rating": 4, "source_language": "fr", **base_pii},
            "low_summary_quality", "summary_gate", _offline_bad_summary=True,
        ),
        entry(
            {"review_id": "n-009", "product_id": "SKU-JACKET-04",
             "text": "Die Jacke ist warm und gut verarbeitet.",
             "rating": 5, "source_language": "de", **base_pii},
            "summarization_error", "summarize", _offline_bad_json=True,
        ),
    ]


def build_dataset() -> dict:
    clean = _clean_entries("fr") + _clean_entries("de")
    return {"clean": clean, "noisy": _noisy_entries()}


def main() -> None:
    dataset = build_dataset()
    out_dir = os.path.join(os.path.dirname(__file__), "..", "tests", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dataset.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(dataset, fh, ensure_ascii=False, indent=2)
    n_fr = sum(1 for e in dataset["clean"] if e["review"]["source_language"] == "fr")
    n_de = sum(1 for e in dataset["clean"] if e["review"]["source_language"] == "de")
    print(f"Wrote {out_path}")
    print(f"  clean: {len(dataset['clean'])} (fr={n_fr}, de={n_de})")
    print(f"  noisy: {len(dataset['noisy'])}")


if __name__ == "__main__":
    main()
