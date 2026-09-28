"""Dependency ratchet: migration exceptions may be removed, never expanded."""

import ast
import json
from pathlib import Path

APP = Path(__file__).parents[2] / "app"
BASELINE = Path(__file__).with_name("legacy_dependencies.json")


def imports():
    result = {}
    for path in APP.rglob("*.py"):
        module = "app." + ".".join(path.relative_to(APP).with_suffix("").parts)
        if module.endswith(".__init__"):
            module = module.removesuffix(".__init__")
        result[module] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                result[module].add(node.module)
                result[module].update(f"{node.module}.{name.name}" for name in node.names)
            elif isinstance(node, ast.Import):
                result[module].update(alias.name for alias in node.names)
    return result


def violations():
    found = set()
    for source, targets in imports().items():
        name = source.rsplit(".", 1)[-1]
        for target in targets:
            if target == "app.postgres.models" and source not in {"app.postgres.models"}:
                found.add(f"{source} -> {target}")
            if source.startswith("app.chat.") and target in {
                "app.clickhouse",
                "app.clickhouse.client",
                "app.clickhouse.queries",
            }:
                found.add(f"{source} -> {target}")
            if name == "router" and target in {
                "app.clickhouse",
                "app.clickhouse.client",
                "app.clickhouse.queries",
                "sqlmodel.select",
                "sqlalchemy.select",
                "stripe",
            }:
                found.add(f"{source} -> {target}")
            if source == "app.feasibility.workbook" and target == "app.feasibility.queries":
                found.add(f"{source} -> {target}")
            if target in {
                "app.core.normalization",
                "app.core.market_constants",
                "app.core.reelly_scope",
                "app.clickhouse.queries",
            }:
                found.add(f"{source} -> {target}")
            if (
                source.startswith("app.")
                and not source.startswith(("app.chat.", "app.main", "app.postgres.models"))
                and target.startswith("app.chat.")
                and target != "app.chat.models"
            ):
                found.add(f"{source} -> {target}")
    return sorted(found)


def test_no_new_boundary_violations():
    allowed = set(json.loads(BASELINE.read_text()))
    current = set(violations())
    assert not current - allowed, "New architectural violations: " + repr(sorted(current - allowed))
    assert not allowed - current, "Remove resolved exceptions: " + repr(sorted(allowed - current))


def test_application_imports_are_acyclic():
    graph = imports()
    graph = {name: targets & graph.keys() for name, targets in graph.items()}
    complete = set()

    def visit(name, path):
        assert name not in path, "Import cycle: " + " -> ".join([*path, name])
        if name in complete:
            return
        for target in graph[name]:
            if target != name:
                visit(target, [*path, name])
        complete.add(name)

    for module in graph:
        visit(module, [])


def test_chat_orchestration_cannot_own_warehouse_queries():
    graph = imports()
    for path in (APP / "chat").glob("*.py"):
        tree = ast.parse(path.read_text())
        module = "app.chat." + path.stem
        assert not any(target.startswith("app.clickhouse") for target in graph[module])
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.upper()
                assert not value.lstrip().startswith(("SELECT ", "SELECT\n", "WITH\n")), path
        if path.stem != "repository":
            assert "sqlmodel.select" not in graph[module]
            assert "sqlalchemy.delete" not in graph[module]
