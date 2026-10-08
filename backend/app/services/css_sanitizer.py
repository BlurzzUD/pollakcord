import re
from collections.abc import Iterable, Iterator

import tinycss2

SCOPE_SELECTOR = ".user-css-scope"
MAX_BYTES = 32 * 1024
MAX_RULES = 600
MAX_DECLARATIONS = 4000
FORBIDDEN_FUNCTIONS = frozenset(
    {"url", "image-set", "-webkit-image-set", "src", "element", "expression", "image", "cross-fade", "paint", "attr", "env"}
)
FORBIDDEN_PROPERTIES = frozenset({"behavior", "-moz-binding", "-webkit-user-modify", "binding"})
SELECTOR_FUNCTIONS = frozenset({"not", "is", "where", "has", "nth-child", "nth-last-child", "nth-of-type", "nth-last-of-type", "lang", "dir"})
MEDIA_WORDS = frozenset(
    {
        "screen",
        "all",
        "and",
        "only",
        "not",
        "light",
        "dark",
        "reduce",
        "no-preference",
        "hover",
        "none",
        "landscape",
        "portrait",
        "fine",
        "coarse",
        "min-width",
        "max-width",
        "min-height",
        "max-height",
        "prefers-color-scheme",
        "prefers-reduced-motion",
        "orientation",
        "pointer",
    }
)
FORBIDDEN_STRING = re.compile(r"(?i)(javascript:|data:text|vbscript:|<script|expression\()")
PROPERTY_NAME = re.compile(r"^(--[a-z0-9_-]+|-?[a-z][a-z0-9-]*)$")
SELECTOR_LITERALS = frozenset({".", "*", ">", "+", "~", ":", "|", "=", "^", "$", "&"})
ROOT_IDENTS = frozenset({"html", "body"})
BLOCK_TYPES = ("() block", "[] block", "{} block")


class CssRejected(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def walk(tokens: Iterable) -> Iterator:
    for token in tokens:
        yield token
        if token.type == "function":
            yield from walk(token.arguments)
        elif token.type in BLOCK_TYPES:
            yield from walk(token.content)


def check_value_tokens(tokens: Iterable) -> None:
    for token in walk(tokens):
        if token.type in ("url", "error", "unicode-range", "at-keyword", "{} block"):
            raise CssRejected("css_forbidden_value", token.type)
        if token.type == "function" and token.lower_name in FORBIDDEN_FUNCTIONS:
            raise CssRejected("css_forbidden_function", token.lower_name)
        if token.type == "string" and FORBIDDEN_STRING.search(token.value):
            raise CssRejected("css_forbidden_value", "string")
        if token.type == "ident" and token.lower_value in ("expression", "javascript"):
            raise CssRejected("css_forbidden_value", token.lower_value)


def check_declaration(declaration) -> str:
    name = declaration.lower_name
    if not PROPERTY_NAME.match(name) or name in FORBIDDEN_PROPERTIES:
        raise CssRejected("css_forbidden_property", name[:40])
    check_value_tokens(declaration.value)
    significant = [t for t in declaration.value if t.type not in ("whitespace", "comment")]
    if name == "position" and any(t.type == "ident" and t.lower_value in ("fixed", "sticky") for t in significant):
        raise CssRejected("css_forbidden_value", "position")
    if name == "content":
        serialized = tinycss2.serialize(significant).strip().lower()
        if serialized not in ('""', "''", "none", "normal"):
            raise CssRejected("css_forbidden_value", "content")
    if name == "z-index":
        for token in significant:
            if token.type == "number" and abs(token.value) > 100:
                raise CssRejected("css_forbidden_value", "z-index")
    value = tinycss2.serialize(declaration.value).strip()
    suffix = " !important" if declaration.important else ""
    return f"{declaration.name}: {value}{suffix};"


def check_selector_tokens(tokens: Iterable) -> None:
    for token in tokens:
        kind = token.type
        if kind in ("whitespace", "ident", "hash", "number", "string", "dimension", "percentage"):
            if kind == "string" and FORBIDDEN_STRING.search(token.value):
                raise CssRejected("css_forbidden_selector")
            continue
        if kind == "literal" and token.value in SELECTOR_LITERALS | {","}:
            continue
        if kind == "[] block":
            check_selector_tokens(token.content)
            continue
        if kind == "function" and token.lower_name in SELECTOR_FUNCTIONS:
            check_selector_tokens(token.arguments)
            continue
        if kind == "() block":
            check_selector_tokens(token.content)
            continue
        raise CssRejected("css_forbidden_selector", kind)


def split_selector_list(prelude: list) -> list[list]:
    parts: list[list] = [[]]
    for token in prelude:
        if token.type == "literal" and token.value == ",":
            parts.append([])
        else:
            parts[-1].append(token)
    return parts


def scope_selector(part: list) -> str:
    tokens = list(part)
    while tokens and tokens[0].type == "whitespace":
        tokens.pop(0)
    while tokens and tokens[-1].type == "whitespace":
        tokens.pop()
    if not tokens:
        raise CssRejected("css_forbidden_selector", "empty")
    if tokens[0].type == "ident" and tokens[0].lower_value in ROOT_IDENTS:
        return SCOPE_SELECTOR + tinycss2.serialize(tokens[1:])
    if len(tokens) >= 2 and tokens[0].type == "literal" and tokens[0].value == ":" and tokens[1].type == "ident" and tokens[1].lower_value == "root":
        return SCOPE_SELECTOR + tinycss2.serialize(tokens[2:])
    return SCOPE_SELECTOR + " " + tinycss2.serialize(tokens)


class _Counter:
    def __init__(self) -> None:
        self.rules = 0
        self.declarations = 0


def sanitize_qualified_rule(rule, counter: _Counter) -> str:
    counter.rules += 1
    if counter.rules > MAX_RULES:
        raise CssRejected("css_too_complex")
    check_selector_tokens(rule.prelude)
    selectors = [scope_selector(part) for part in split_selector_list(rule.prelude)]
    declarations = []
    for node in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
        if node.type != "declaration":
            raise CssRejected("css_parse_error", node.type)
        counter.declarations += 1
        if counter.declarations > MAX_DECLARATIONS:
            raise CssRejected("css_too_complex")
        declarations.append(check_declaration(node))
    if not declarations:
        return ""
    return ",\n".join(selectors) + " {\n  " + "\n  ".join(declarations) + "\n}"


def check_media_prelude(tokens: Iterable) -> None:
    for token in tokens:
        kind = token.type
        if kind in ("whitespace", "number", "dimension"):
            if kind == "dimension" and token.lower_unit not in ("px", "em", "rem"):
                raise CssRejected("css_forbidden_media")
            continue
        if kind == "ident" and token.lower_value in MEDIA_WORDS:
            continue
        if kind == "literal" and token.value in (":", ","):
            continue
        if kind == "() block":
            check_media_prelude(token.content)
            continue
        raise CssRejected("css_forbidden_media", kind)


def sanitize_css(source: str) -> str:
    if len(source.encode("utf-8")) > MAX_BYTES:
        raise CssRejected("css_too_large")
    if "\\" in source or "\x00" in source:
        raise CssRejected("css_forbidden_escape")
    counter = _Counter()
    output: list[str] = []
    for node in tinycss2.parse_stylesheet(source, skip_comments=True, skip_whitespace=True):
        if node.type == "qualified-rule":
            rendered = sanitize_qualified_rule(node, counter)
            if rendered:
                output.append(rendered)
        elif node.type == "at-rule" and node.lower_at_keyword == "media" and node.content is not None:
            check_media_prelude(node.prelude)
            inner = []
            for child in tinycss2.parse_rule_list(node.content, skip_comments=True, skip_whitespace=True):
                if child.type != "qualified-rule":
                    raise CssRejected("css_forbidden_at_rule", getattr(child, "type", ""))
                rendered = sanitize_qualified_rule(child, counter)
                if rendered:
                    inner.append(rendered)
            if inner:
                output.append("@media " + tinycss2.serialize(node.prelude).strip() + " {\n" + "\n".join(inner) + "\n}")
        elif node.type == "at-rule":
            raise CssRejected("css_forbidden_at_rule", node.lower_at_keyword[:30])
        else:
            raise CssRejected("css_parse_error", node.type)
    return "\n".join(output)
