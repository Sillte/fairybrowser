import ast
from collections.abc import Collection
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginClassMetadata:
    name: str
    class_name: str


class PluginDiscoveryError(ValueError):
    """A plugin entry class does not declare static discovery metadata."""


def discover_plugin_classes(
    source: str,
    *,
    filename: str,
    base_name: str,
    allowed_import_modules: Collection[str],
) -> tuple[PluginClassMetadata, ...]:
    """Find top-level classes directly based on an allowed, module-level ABC import."""
    module = ast.parse(source, filename=filename)
    imported_base_names: set[str] = set()
    candidates: list[PluginClassMetadata] = []

    for statement in module.body:
        if isinstance(statement, ast.ImportFrom) and statement.level == 0:
            if statement.module in allowed_import_modules:
                imported_base_names.update(
                    alias.asname or alias.name for alias in statement.names if alias.name == base_name
                )
            continue
        if not isinstance(statement, ast.ClassDef) or not any(
            _is_direct_base(base, imported_base_names) for base in statement.bases
        ):
            continue

        candidates.append(
            PluginClassMetadata(
                name=_literal_class_name(statement, filename),
                class_name=statement.name,
            )
        )

    class_names = [candidate.class_name for candidate in candidates]
    if len(class_names) != len(set(class_names)):
        duplicate = next(name for index, name in enumerate(class_names) if name in class_names[:index])
        raise PluginDiscoveryError(f"Plugin class {duplicate!r} is declared more than once in {filename}")

    return tuple(candidates)


def _is_direct_base(base: ast.expr, imported_base_names: set[str]) -> bool:
    base_name = base.value if isinstance(base, ast.Subscript) else base
    return isinstance(base_name, ast.Name) and base_name.id in imported_base_names


def _literal_class_name(node: ast.ClassDef, filename: str) -> str:
    assignments: list[ast.expr | None] = []
    for statement in node.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "name" for target in statement.targets
        ):
            assignments.append(statement.value)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.target.id == "name":
                assignments.append(statement.value)

    if len(assignments) != 1 or not isinstance(assignments[0], ast.Constant) or not isinstance(
        assignments[0].value, str
    ):
        raise PluginDiscoveryError(
            f"Plugin class {node.name!r} in {filename} must declare one literal string name"
        )
    return assignments[0].value
