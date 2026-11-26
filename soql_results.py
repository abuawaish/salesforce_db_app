"""Tabular Section 1 results. Query projections supply headers for absent relationships."""
import json
import re

import pandas as pd


_NAME = re.compile(r"[A-Za-z_]\w*")
_TOKEN = re.compile(r"'(?:\\.|[^'\\])*'|[A-Za-z_]\w*|[^\s]", re.DOTALL)
_CLAUSES = {"where", "with", "group", "having", "order", "limit", "offset", "for", "using"}


def _select_list(tokens):
    """Read one SELECT list, keeping function calls, TYPEOF and subqueries intact."""
    start = 1
    groups = []
    depth = 0
    in_typeof = False
    for i, token in enumerate(tokens[1:], 1):
        word = token.casefold()
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif not depth:
            if word == "typeof":
                in_typeof = True
            elif word == "end":
                in_typeof = False
            elif not in_typeof and token == ",":
                groups.append(tokens[start:i])
                start = i + 1
            elif not in_typeof and word == "from" and i + 1 < len(tokens):
                source = tokens[i + 1]
                alias = tokens[i + 2] if i + 2 < len(tokens) else ""
                if not _NAME.fullmatch(alias) or alias.casefold() in _CLAUSES:
                    alias = ""
                return groups + [tokens[start:i]], source, alias
    return [], "", ""


def _path(tokens, source, alias):
    if not tokens or len(tokens) % 2 == 0:
        return ""
    if any(not _NAME.fullmatch(t) for t in tokens[::2]) or any(t != "." for t in tokens[1::2]):
        return ""
    names = tokens[::2]
    if len(names) > 1 and names[0].casefold() in {alias.casefold(), source.casefold()}:
        names = names[1:]
    return ".".join(names)


def _projected_columns(tokens):
    """Return source and ordered column hints. A wildcard keeps response-defined keys."""
    groups, source, alias = _select_list(tokens)
    hints = []
    for group in groups:
        if not group:
            continue
        if group[0] == "(" and len(group) > 1 and group[1].casefold() == "select":
            child, columns = _projected_columns(group[1:-1])
            hints.extend((kind, child + "." + name if name else child)
                         for kind, name in columns)
        elif group[0].casefold() == "typeof" and len(group) >= 3:
            # WHEN branches can return different fields. Include each branch's
            # selected paths even if all matching records have a null relationship.
            first_when = next((i for i, t in enumerate(group) if t.casefold() == "when"), 1)
            rel = _path(group[1:first_when], source, alias)
            if rel:
                for branch in re.finditer(r"\b(?:THEN|ELSE)\s+(.+?)(?=\s+(?:WHEN|ELSE|END)\b)",
                                          " ".join(group), re.I):
                    for field in branch[1].split(","):
                        path = _path(_TOKEN.findall(field), "", "")
                        if path:
                            hints.append(("field", rel + "." + path))
        else:
            path = _path(group, source, alias)
            if path:
                hints.append(("field", path))
            elif _NAME.fullmatch(group[-1]) and len(group) > 1:
                hints.append(("field", group[-1]))  # explicit result alias
            elif group[0].casefold() == "fields":
                hints.append(("wildcard", ""))
            else:
                # Function results may use the argument name or an exprN key.
                argument = _path(group[2:-1], source, alias) if group[-1] == ")" else ""
                hints.append(("function", argument))
    return source, hints


def _clean_list(value):
    if isinstance(value, dict):
        return {k: _clean_list(v) for k, v in value.items() if k != "attributes"}
    if isinstance(value, list):
        return [_clean_list(v) for v in value]
    return value


def _rows(record, prefix=""):
    parent = {}
    children = []

    def visit(obj, path):
        for name, value in obj.items():
            if name == "attributes":
                continue
            column = path + name
            if isinstance(value, dict):
                if "totalSize" in value and "records" in value:
                    children.append((column + ".", value["records"] or []))
                else:
                    visit(value, column + ".")
            elif isinstance(value, list):
                parent[column] = json.dumps(_clean_list(value), indent=2)
            else:
                parent[column] = value

    visit(record, prefix)
    rows = [parent]
    for child_prefix, records in children:
        if records:
            # Preserve the editor's child-major order and sibling-subquery expansion.
            rows = [base | child for rec in records for child in _rows(rec, child_prefix)
                    for base in rows]
    return rows


def result_frame(records, query):
    """Build one scalar-valued DataFrame for the results grid, search and CSV export."""
    _, hints = _projected_columns(_TOKEN.findall(query))
    rows = [row for record in records for row in _rows(record)]
    frame = pd.DataFrame(rows, index=range(len(rows)))
    aggregate = bool(records and (records[0].get("attributes") or {}).get("type") == "AggregateResult")
    if aggregate:
        # Aggregated GROUP BY relationship fields can be returned as a flat
        # leaf name. Map unambiguous leaves back to the selected dotted path.
        paths = {}
        for kind, name in hints:
            if kind == "field":
                paths.setdefault(name.rsplit(".", 1)[-1].casefold(), []).append(name)
        names = {c.casefold() for c in frame.columns}
        rename = {}
        for col in frame.columns:
            candidates = paths.get(col.casefold(), [])
            if len(candidates) == 1 and "." in candidates[0] and candidates[0].casefold() not in names:
                rename[col] = candidates[0]
        if rename:
            frame = frame.rename(columns=rename)
    observed = {col.casefold(): col for col in frame.columns}
    # A null parent may appear in the response as "Account" or "Account.Owner".
    # Retain its selected leaves, even when they are absent from every record.
    prefixes = set()
    for path in [*observed, *(name.casefold() for kind, name in hints if kind == "field")]:
        while "." in path:
            path = path.rsplit(".", 1)[0]
            prefixes.add(path)
    leaves = {key: col for key, col in observed.items() if key not in prefixes}
    branches = {}
    for leaf, col in leaves.items():
        while "." in leaf:
            leaf = leaf.rsplit(".", 1)[0]
            branches.setdefault(leaf, []).append(col)

    used = set()
    slots = []
    expressions = iter(col for key, col in leaves.items() if re.fullmatch(r"expr\d+", key))
    for kind, name in hints:
        key = name.casefold()
        if kind == "wildcard":
            slots.append((True, name))
            continue
        if kind == "function":
            # Never synthesize columns for expressions with API-defined result names.
            # Aggregate results use exprN even when the grouped argument is also selected.
            col = next(expressions, None) if aggregate else None
            cols = [col or leaves.get(key)] if col or key in leaves else []
        else:
            cols = branches.get(key) or [leaves.get(key, name)]
        for col in cols:
            if col not in used:
                slots.append((False, col))
                used.add(col)

    order = []
    for wildcard, name in slots:
        if wildcard:
            prefix = name.casefold() + "." if name else ""
            for key, col in leaves.items():
                if key.startswith(prefix) and col not in used:
                    order.append(col)
                    used.add(col)
        else:
            order.append(name)
    order.extend(col for col in leaves.values() if col not in used)
    return frame.reindex(columns=order)
