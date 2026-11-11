import colorsys
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "annalist" / "site" / "app.css").read_text(encoding="utf-8")
THEMES = {"default": {}, **{p.stem: json.loads(p.read_text(encoding="utf-8"))["theme"]
                            for p in sorted((ROOT / "annalist" / "themes").glob("*.json"))}}


def tokens(name, mode):
    body = re.search(r':root\[data-theme="%s"\]\{([^}]*)\}' % mode, CSS).group(1)
    found = dict(re.findall(r"--([\w-]+):([^;]+)", body))
    return {**found, **THEMES[name].get(mode, {})}


def block(selector):
    found = re.search(re.escape(selector) + r"\{([^}]*)\}", CSS)
    return dict(re.findall(r"--([\w-]+):([^;]+)", found.group(1))) if found else {}


OPTIONS = re.findall(r':root\[data-theme="light"\]\[data-light="(\w+)"\]\{', CSS)


def option_tokens(name, option):
    """Light tokens with a data-light option on, in cascade order: the option's :where() defaults lose to the book theme, its own block beats it."""
    t = {**tokens("default", "light"), **block(f':root[data-theme="light"]:where([data-light="{option}"])')}
    t.update(THEMES[name].get("light", {}))
    t = {**t, **block(':root[data-theme="light"][data-light]'), **block(f':root[data-theme="light"][data-light="{option}"]')}
    return {k: solid(t, v) for k, v in t.items()}


def solid(t, value):
    """A token as #rrggbb when it is a colour, resolving var() and an opaque color-mix(in srgb, ...)."""
    value = value.strip()
    if value.startswith("var("):
        return solid(t, t[value[6:-1]])
    mix = re.fullmatch(r"color-mix\(in srgb,(.+) (\d+)%,(.+)\)", value)
    if mix:
        a, b = solid(t, mix.group(1)), solid(t, mix.group(3))
        return over(a, b, int(mix.group(2)) / 100) if a.startswith("#") and b.startswith("#") else value
    return value


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
    def test_text_meets_wcag_aa_on_page_and_card_in_every_theme(self):
        for name in THEMES:
            for mode in ("light", "dark"):
                t = tokens(name, mode)
                for role in ("fg", "muted", "link", "accent"):
                    colour = t.get(role) or t["accent"]
                    for surface in ("bg", "card"):
                        with self.subTest(theme=name, mode=mode, text=role, on=surface):
                            self.assertGreaterEqual(ratio(colour, t[surface]), 4.5)

    def test_small_counts_in_light_themes_meet_wcag_aa(self):
        for name in THEMES:
            t = tokens(name, "light")
            faded = over(t["muted"], t["bg"], 1 - 0.2 * float(t.get("fade", 1)))
            with self.subTest(theme=name):
                self.assertGreaterEqual(ratio(faded, t["bg"]), 4.5)

    def test_light_cards_are_brighter_than_the_page(self):
        for name in THEMES:
            t = tokens(name, "light")
            with self.subTest(theme=name):
                self.assertGreater(ratio(t["card"], t["bg"]), 1.05)

    def test_every_light_option_keeps_text_at_aa_and_links_off_the_accent_for_every_book(self):
        self.assertEqual(OPTIONS, ["a", "b", "c"])
        for name in THEMES:
            for option in OPTIONS:
                t = option_tokens(name, option)
                self.assertNotEqual(t["link"].lower(), t["accent"].lower())
                self.assertTrue(200 <= hue(t["link"]) <= 235, f"{name} {option} link {t['link']} is not blue")
                for role in ("fg", "muted", "link", "accent-text"):
                    for surface in ("bg", "card", "hover", "frame"):
                        with self.subTest(theme=name, option=option, text=role, on=surface):
                            self.assertGreaterEqual(ratio(t[role], t[surface]), 4.5)
                with self.subTest(theme=name, option=option, mark="accent"):
                    self.assertGreaterEqual(ratio(t["accent"], t["bg"]), 3)

    def test_every_light_option_draws_resting_graph_edges_at_three_to_one(self):
        for name in THEMES:
            for option in OPTIONS:
                t = option_tokens(name, option)
                for group in ("close", "allies", "conflict", "belong", "things"):
                    with self.subTest(theme=name, option=option, group=group):
                        self.assertGreaterEqual(ratio(over(t["r-" + group], t["card"], float(t["edge-rest"])), t["card"]), 3)
