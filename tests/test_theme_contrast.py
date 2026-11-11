import colorsys
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "annalist" / "site" / "app.css").read_text(encoding="utf-8")
THEMES = {"default": {}, **{p.stem: json.loads(p.read_text(encoding="utf-8"))["theme"]
                            for p in sorted((ROOT / "annalist" / "themes").glob("*.json"))}}
MODES = ("light", "dark")
TEXT = ("fg", "muted", "heading", "link", "accent-text", "side-label")
SURFACES = (("bg", "bg"), ("card", "card"), ("frame", "frame"), ("top-bg", "frame"), ("side-on", "frame"),
            ("hover", "bg"), ("hover", "card"), ("ib-head-bg", "card"), ("new-bg", "bg"))
EDGES = ("close", "allies", "conflict", "belong", "things")


def declared(selector):
    found = {}
    for body in re.findall(selector + r"\{([^}]*)\}", CSS):
        found.update(re.findall(r"--([\w-]+):([^;]+)", body))
    return found


def tokens(name, mode):
    """Custom properties in cascade order: the :root defaults, the mode's block, then the book theme, which the site appends last."""
    return {**declared(r"(?m)^:root"), **declared(r':root\[data-theme="%s"\]' % mode), **THEMES[name].get(mode, {})}


def colour(t, value):
    """A token as [r, g, b, alpha], resolving var() and color-mix(in srgb, ...) with premultiplied alpha."""
    value = value.strip()
    if value.startswith("var("):
        return colour(t, t[value[6:-1]])
    if value == "transparent":
        return [0, 0, 0, 0.0]
    if value.startswith("#"):
        return rgb(value) + [1.0]
    a, p, b = re.fullmatch(r"color-mix\(in srgb,\s*(.+?)\s+(\d+)%,\s*(.+)\)", value).groups()
    a, b, p = colour(t, a), colour(t, b), int(p) / 100
    wa, wb = p * a[3], (1 - p) * b[3]
    if wa + wb == 0:
        return [0, 0, 0, 0.0]
    return [(a[i] * wa + b[i] * wb) / (wa + wb) for i in range(3)] + [wa + wb]


def flat(t, token, under):
    """A token painted over another, as #rrggbb."""
    c, u = colour(t, t[token]), colour(t, t[under])
    return "#" + "".join("%02x" % round(c[i] * c[3] + u[i] * (1 - c[3])) for i in range(3))


def rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def hue(h):
    return colorsys.rgb_to_hls(*(v / 255 for v in rgb(h)))[0] * 360


def over(fg, bg, alpha):
    return "#" + "".join("%02x" % round(a * alpha + b * (1 - alpha)) for a, b in zip(rgb(fg), rgb(bg)))


def ratio(a, b):
    def lum(h):
        c = [v / 255 for v in rgb(h)]
        c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ThemeContrast(unittest.TestCase):
    def test_every_text_colour_meets_wcag_aa_on_every_surface_in_every_theme(self):
        for name in THEMES:
            for mode in MODES:
                t = tokens(name, mode)
                for surface, under in SURFACES:
                    paper = flat(t, surface, under)
                    for role in TEXT:
                        with self.subTest(theme=name, mode=mode, text=role, on=f"{surface} over {under}"):
                            self.assertGreaterEqual(ratio(flat(t, role, surface), paper), 4.5)

    def test_accent_marks_and_control_borders_reach_three_to_one(self):
        for name in THEMES:
            for mode in MODES:
                t = tokens(name, mode)
                for surface in ("bg", "card", "frame", "top-bg"):
                    with self.subTest(theme=name, mode=mode, mark="accent", on=surface):
                        self.assertGreaterEqual(ratio(flat(t, "accent", "bg"), flat(t, surface, "bg")), 3)
                for surface in ("bg", "frame", "top-bg"):
                    with self.subTest(theme=name, mode=mode, mark="control border", on=surface):
                        self.assertGreaterEqual(ratio(flat(t, "line-strong", "bg"), flat(t, surface, "bg")), 3)

    def test_graph_edges_at_rest_and_tie_bars_reach_three_to_one(self):
        for name in THEMES:
            for mode in MODES:
                t = tokens(name, mode)
                for group in EDGES:
                    c = flat(t, "r-" + group, "card")
                    with self.subTest(theme=name, mode=mode, edge=group):
                        self.assertGreaterEqual(ratio(over(c, flat(t, "card", "bg"), float(t["edge-rest"])), flat(t, "card", "bg")), 3)
                    with self.subTest(theme=name, mode=mode, bar=group):
                        self.assertGreaterEqual(ratio(c, flat(t, "bg", "bg")), 3)

    def test_links_differ_from_the_accent_and_are_blue_in_light_mode(self):
        for name in THEMES:
            for mode in MODES:
                t = tokens(name, mode)
                with self.subTest(theme=name, mode=mode):
                    self.assertNotEqual(flat(t, "link", "bg"), flat(t, "accent", "bg"))
            link = flat(tokens(name, "light"), "link", "bg")
            self.assertTrue(200 <= hue(link) <= 235, f"{name} light link {link} is not blue")

    def test_a_book_theme_sets_only_its_accent_and_heading_in_light_mode(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertLessEqual(set(theme.get("light", {})), {"accent", "heading"})

    def test_light_cards_are_brighter_than_the_page(self):
        for name in THEMES:
            t = tokens(name, "light")
            with self.subTest(theme=name):
                self.assertGreater(ratio(flat(t, "card", "bg"), flat(t, "bg", "bg")), 1.05)
