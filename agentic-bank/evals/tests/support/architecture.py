"""Structural rules of plan revision 5, read from source with the AST.

Each rule is a function over source text, so the architecture tests can prove
it rejects a synthetic violation before applying it to the real tree.
"""

import ast
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

EVALS = Path(__file__).parents[2]
FUNCTION_LIMIT = 50
PUBLIC_METHOD_LIMIT = 3

# Which first-party layers and third-party packages each layer may import.
# Anything else, including an unmapped first-party module, is a violation.
ALLOWED_FIRST_PARTY: Mapping[str, frozenset[str]] = {
    "domain": frozenset({"domain"}),
    "application": frozenset({"domain", "application"}),
    "adapters": frozenset({"domain", "application", "adapters"}),
    "presentation": frozenset({"domain"}),
    "composition": frozenset(
        {"domain", "application", "adapters", "presentation", "composition"}
    ),
    "baselines": frozenset({"domain", "adapters", "baselines"}),
}
ALLOWED_THIRD_PARTY: Mapping[str, frozenset[str]] = {
    "domain": frozenset({"pydantic"}),
    "application": frozenset({"pydantic"}),
    "adapters": frozenset(
        {"pydantic", "httpx", "mcp", "langfuse", "opentelemetry", "anyio"}
    ),
    "presentation": frozenset(),
    "composition": frozenset({"pydantic"}),
    "baselines": frozenset(
        {"pydantic", "httpx", "mcp", "starlette", "uvicorn", "anyio"}
    ),
}
FIRST_PARTY = frozenset({"harness", "baselines", "tests"})


@dataclass(frozen=True)
class Violation:
    module: str
    detail: str


def layer_of(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] == "baselines":
        return "baselines"
    if parts[0] != "harness" or len(parts) < 2:
        return None
    if parts[1] == "run":
        return "composition"
    if parts[1] in {"domain", "application", "adapters", "presentation"}:
        return parts[1]
    return None


def imported_modules(source: str) -> Iterator[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


def import_violations(module: str, source: str) -> list[Violation]:
    """Imports that break the dependency direction of `module`'s layer."""
    layer = layer_of(module)
    if layer is None:
        return [Violation(module, "module belongs to no layer")]
    violations: list[Violation] = []
    for imported in imported_modules(source):
        root = imported.split(".")[0]
        if root in sys.stdlib_module_names:
            continue
        if root in FIRST_PARTY:
            target = layer_of(imported)
            if target not in ALLOWED_FIRST_PARTY[layer]:
                violations.append(Violation(module, f"imports {imported}"))
        elif root not in ALLOWED_THIRD_PARTY[layer]:
            violations.append(Violation(module, f"imports third-party {imported}"))
    return violations


def long_functions(module: str, source: str) -> list[Violation]:
    return [
        Violation(module, f"{node.name} has {length} lines")
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and (length := (node.end_lineno or node.lineno) - node.lineno + 1)
        > FUNCTION_LIMIT
    ]


def protocol_names(sources: Iterable[str]) -> frozenset[str]:
    """Classes declared as `typing.Protocol` subclasses."""
    names: set[str] = set()
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef) and any(
                _name(base) == "Protocol" for base in node.bases
            ):
                names.add(node.name)
    return frozenset(names)


def wide_classes(
    module: str, source: str, protocols: frozenset[str]
) -> list[Violation]:
    """Classes with more public methods than the limit, unless they declare a port."""
    violations: list[Violation] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef):
            continue
        if any(_name(base) in protocols | {"Protocol"} for base in node.bases):
            continue
        public = [
            item.name
            for item in node.body
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            and not item.name.startswith("_")
        ]
        if len(public) > PUBLIC_METHOD_LIMIT:
            violations.append(
                Violation(module, f"{node.name} has {len(public)} public methods")
            )
    return violations


def cross_test_imports(module: str, source: str) -> list[Violation]:
    """A test may import support code and fixtures, never another test module."""
    return [
        Violation(module, f"imports {imported}")
        for imported in imported_modules(source)
        if imported.startswith("tests.test_") or ".test_" in imported
    ]


def modules(*packages: str) -> dict[str, str]:
    """Module name to source for every Python file under these packages."""
    found: dict[str, str] = {}
    for package in packages:
        for path in sorted((EVALS / package).rglob("*.py")):
            relative = path.relative_to(EVALS).with_suffix("")
            name = ".".join(relative.parts)
            found[name.removesuffix(".__init__")] = path.read_text()
    return found


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    return ""
