from pathlib import Path

from .files import read_json
from .template import book_additions, DEFAULT_POWER_TYPES, RELATION_TYPES


DEFAULT_BOOK = {"power_system": "", "power_types": DEFAULT_POWER_TYPES,
                "relation_example": RELATION_TYPES[1], "extra_fields": {}, "power_keywords": [],
                "models": {}, "view": {"recent_entities": 25, "recent_questions": 40, "matched_questions": 15},
                "tiers": {"arc_age": 3, "arc_entity_facts": 20, "series_age": 20, "series_engaged": 2, "promote_engaged": 12},
                "timeline_kind": "linear", "timeline_note": "", "complete": False, "ladder": None}


def load_book(workdir):
    book = dict(DEFAULT_BOOK)
    book.update(read_json(Path(workdir) / "book.json", {}))
    book["view"] = {**DEFAULT_BOOK["view"], **book["view"]}
    book["tiers"] = {**DEFAULT_BOOK["tiers"], **book["tiers"]}
    book["power_types"], book["extra_fields"], book["field_values"] = book_additions(book)
    return book
