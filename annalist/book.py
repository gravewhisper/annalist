from pathlib import Path

from .files import read_json
from .names import name_key
from .template import book_additions, DEFAULT_POWER_TYPES, RELATION_TYPES


DEFAULT_BOOK = {"power_system": "", "power_types": DEFAULT_POWER_TYPES, "rank_word": "",
                "relation_example": RELATION_TYPES[1], "extra_fields": {}, "power_keywords": [],
                "models": {}, "view": {"recent_entities": 25, "recent_questions": 40, "matched_questions": 15},
                "tiers": {"arc_age": 3, "arc_entity_facts": 20, "series_age": 20, "series_engaged": 2, "promote_engaged": 12},
                "timeline_kind": "linear", "timeline_note": "", "complete": False, "ladder": None}


def ladder_types(ladder):
    return tuple(t for t in (ladder.get("group_type"), ladder["step_type"]) if t) if ladder else ()


def type_named(word, types):
    word = name_key(word or "")
    return next((t for t in types if word and (t == word or t.endswith(f" {word}"))), None)


def rank_type(book):
    return type_named(book.get("rank_word"), book.get("power_types") or {})


NEWTYPES_FILE = "newtypes.json"


def volume_types(workdir):
    return read_json(Path(workdir) / NEWTYPES_FILE, {"volumes": []})["volumes"]


def added_types(workdir, until=None):
    """The types added at volume ends by chapter until, each with the chapter it starts from."""
    return {t: {**spec, "chapter": v["to"]} for v in volume_types(workdir) if until is None or v["to"] <= until for t, spec in v["types"].items()}


def type_moves(workdir, until=None):
    return [{**m, "chapter": v["to"]} for v in volume_types(workdir) if until is None or v["to"] <= until for m in v["moves"]]


def load_book(workdir):
    book = dict(DEFAULT_BOOK)
    book.update(read_json(Path(workdir) / "book.json", {}))
    book["view"] = {**DEFAULT_BOOK["view"], **book["view"]}
    book["tiers"] = {**DEFAULT_BOOK["tiers"], **book["tiers"]}
    book["power_types"], book["extra_fields"], book["field_values"] = book_additions(book)
    return book
