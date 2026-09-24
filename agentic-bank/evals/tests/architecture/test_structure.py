"""S1-S4, S13: structural gates. Each rule first proves it rejects a synthetic
violation, then holds on the real tree."""

from tests.support.architecture import (
    cross_test_imports,
    import_violations,
    long_functions,
    modules,
    protocol_names,
    wide_classes,
)

PRODUCT = modules("harness", "baselines")
TESTS = modules("tests")
PORTS = protocol_names(source for name, source in PRODUCT.items() if ".ports" in name)


def lines(count: int) -> str:
    body = "".join(f"    x{i} = {i}\n" for i in range(count - 2))
    return f"def f() -> int:\n{body}    return 0\n"


# S1
def test_an_adapter_import_in_the_domain_is_rejected() -> None:
    source = "from harness.adapters.bank import SqliteBank\n"

    assert import_violations("harness.domain.judging", source)
    assert not import_violations("harness.run", source)


def test_a_framework_import_in_the_domain_is_rejected() -> None:
    assert import_violations("harness.domain.judging", "import httpx\n")
    assert not import_violations("harness.domain.judging", "import pydantic\n")


def test_every_module_imports_only_what_its_layer_allows() -> None:
    violations = [
        v for name, source in PRODUCT.items() for v in import_violations(name, source)
    ]

    assert violations == []


# S2
def test_a_function_of_51_lines_is_rejected() -> None:
    assert long_functions("m", lines(51))
    assert not long_functions("m", lines(50))


def test_no_function_is_longer_than_50_lines() -> None:
    violations = [
        v for name, source in PRODUCT.items() for v in long_functions(name, source)
    ]

    assert violations == []


# S3, S4
CLASS_WITH_FOUR = """
class Wide:
    def a(self) -> None: ...
    def b(self) -> None: ...
    def c(self) -> None: ...
    def d(self) -> None: ...
"""


def test_a_plain_class_with_four_public_methods_is_rejected() -> None:
    assert wide_classes("m", CLASS_WITH_FOUR, frozenset())


def test_an_adapter_that_declares_a_protocol_is_exempt() -> None:
    adapter = CLASS_WITH_FOUR.replace("class Wide:", "class Wide(BankObservation):")

    assert not wide_classes("m", adapter, frozenset({"BankObservation"}))
    assert wide_classes("m", adapter, frozenset())


def test_no_class_exposes_more_than_3_public_methods() -> None:
    violations = [
        v for name, source in PRODUCT.items() for v in wide_classes(name, source, PORTS)
    ]

    assert violations == []


# S13
def test_a_test_importing_another_test_is_rejected() -> None:
    assert cross_test_imports("tests.a", "from tests.test_run import lines\n")
    assert not cross_test_imports("tests.a", "from tests.support import lines\n")


def test_no_test_imports_another_test_module() -> None:
    violations = [
        v for name, source in TESTS.items() for v in cross_test_imports(name, source)
    ]

    assert violations == []
