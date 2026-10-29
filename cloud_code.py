"""
Backend for the SF Cloud Code page — a lightweight IDE for Apex classes,
Apex triggers, and Lightning Web Components, backed by the Salesforce
Tooling API.

Design
------
* Listing and reading go through Tooling SOQL / sobjects reads.
* Saving *is* deploying. LWC files write directly (``PATCH`` on
  ``LightningComponentResource``). Apex class and trigger *updates* go
  through the documented Tooling compile flow — ``MetadataContainer`` →
  ``ApexClassMember`` / ``ApexTriggerMember`` → ``ContainerAsyncRequest`` —
  because a direct ``PATCH`` on ``ApexClass`` is rejected by some orgs with
  ``INVALID_CROSS_REFERENCE_KEY`` ("insufficient access rights on
  cross-reference id"). Compile errors come back on the async request,
  which is the page's real-time feedback loop.
* The page keeps a client-side *workspace* (in ``st.session_state``) of
  opened files. Each entry tracks the last-known server copy (``original``)
  next to the user's draft (``current``); comparing the two yields
  Git-style status letters:

    ``U``  untracked — created locally, not on the server yet
    ``M``  modified  — draft differs from the server copy
    ``C``  conflict  — the server copy changed after the draft was fetched
    ``""`` clean

Everything here is UI-free and unit-testable; the page file only renders.
"""

import difflib
import io
import json
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone

# ------------------------------------------------------------
# Listing
# ------------------------------------------------------------

_APEX_LIST_SOQL = (
    "SELECT Id, Name, ApiVersion, NamespacePrefix, LastModifiedDate "
    "FROM ApexClass ORDER BY Name"
)

_TRIGGER_LIST_SOQL = (
    "SELECT Id, Name, ApiVersion, Status, TableEnumOrId, NamespacePrefix, "
    "LastModifiedDate FROM ApexTrigger ORDER BY Name"
)

_LWC_LIST_SOQL = (
    "SELECT Id, DeveloperName, MasterLabel, NamespacePrefix, LastModifiedDate "
    "FROM LightningComponentBundle ORDER BY DeveloperName"
)

_LWC_RESOURCES_SOQL = (
    "SELECT Id, FilePath, Format, Source, LastModifiedDate "
    "FROM LightningComponentResource "
    "WHERE LightningComponentBundleId = '{bundle_id}' ORDER BY FilePath"
)

_LWC_FILES_SOQL = (
    "SELECT Id, FilePath, Format, LastModifiedDate "
    "FROM LightningComponentResource "
    "WHERE LightningComponentBundleId = '{bundle_id}' ORDER BY FilePath"
)


def _tooling_query_all(sf, soql: str) -> list[dict]:
    """Run a Tooling SOQL query and follow pagination to the last page."""
    records: list[dict] = []
    result = sf.toolingexecute("query/", method="GET", params={"q": soql})
    while isinstance(result, dict):
        records.extend(result.get("records") or [])
        if result.get("done", True):
            break
        next_url = result.get("nextRecordsUrl") or ""
        marker = "/tooling/"
        if marker not in next_url:
            break
        result = sf.toolingexecute(next_url.split(marker, 1)[1], method="GET")
    return records


def list_apex_classes(sf) -> list[dict]:
    """Org Apex classes (metadata only — bodies are fetched on open)."""
    out = []
    for rec in _tooling_query_all(sf, _APEX_LIST_SOQL):
        out.append(
            {
                "id": rec.get("Id"),
                "name": rec.get("Name") or "",
                "api_version": rec.get("ApiVersion"),
                "namespace": rec.get("NamespacePrefix") or "",
                "last_modified": rec.get("LastModifiedDate") or "",
            }
        )
    return out


def list_apex_triggers(sf) -> list[dict]:
    """Org Apex triggers (metadata only — bodies are fetched on open)."""
    out = []
    for rec in _tooling_query_all(sf, _TRIGGER_LIST_SOQL):
        out.append(
            {
                "id": rec.get("Id"),
                "name": rec.get("Name") or "",
                "api_version": rec.get("ApiVersion"),
                "status": rec.get("Status") or "",
                "sobject": rec.get("TableEnumOrId") or "",
                "namespace": rec.get("NamespacePrefix") or "",
                "last_modified": rec.get("LastModifiedDate") or "",
            }
        )
    return out


def list_triggerable_objects(sf) -> list[dict]:
    """Objects that accept Apex triggers, from the REST global describe.

    Only objects whose describe entry says ``triggerable`` are returned,
    so system objects that cannot carry a trigger never appear. Change
    Event objects (``*ChangeEvent``) are excluded even though describe
    marks them triggerable: they are auto-generated event shadows, not
    real objects, their labels read "Change Event: X", and they pollute
    ``__c`` searches (``Skill__ChangeEvent`` matches ``__c``). Sorted by
    API name, same ordering as the Field Analysis object list; each item
    is {"name", "label"}.
    """
    desc = sf.describe() or {}
    out = []
    for obj in desc.get("sobjects", []):
        name = obj.get("name") or ""
        if obj.get("triggerable") and name and not name.endswith("ChangeEvent"):
            out.append({"name": name,
                        "label": obj.get("label") or name})
    return sorted(out, key=lambda o: o["name"].lower())


def list_lwc_bundles(sf) -> list[dict]:
    """Org LWC bundles (metadata only — resources are fetched on open)."""
    out = []
    for rec in _tooling_query_all(sf, _LWC_LIST_SOQL):
        out.append(
            {
                "id": rec.get("Id"),
                "name": rec.get("DeveloperName") or "",
                "label": rec.get("MasterLabel") or rec.get("DeveloperName") or "",
                "namespace": rec.get("NamespacePrefix") or "",
                "last_modified": rec.get("LastModifiedDate") or "",
            }
        )
    return out


def fetch_apex_body(sf, class_id: str) -> dict:
    """Full ApexClass record, including the source ``Body``."""
    rec = sf.toolingexecute(f"sobjects/ApexClass/{class_id}", method="GET")
    return {
        "body": (rec or {}).get("Body") or "",
        "api_version": (rec or {}).get("ApiVersion"),
        "last_modified": (rec or {}).get("LastModifiedDate") or "",
    }


def fetch_trigger_body(sf, trigger_id: str) -> dict:
    """Full ApexTrigger record, including the source ``Body``."""
    rec = sf.toolingexecute(f"sobjects/ApexTrigger/{trigger_id}", method="GET")
    return {
        "body": (rec or {}).get("Body") or "",
        "api_version": (rec or {}).get("ApiVersion"),
        "status": (rec or {}).get("Status") or "",
        "sobject": (rec or {}).get("TableEnumOrId") or "",
        "last_modified": (rec or {}).get("LastModifiedDate") or "",
    }


def fetch_lwc_resources(sf, bundle_id: str) -> list[dict]:
    """All source files of one LWC bundle."""
    soql = _LWC_RESOURCES_SOQL.format(bundle_id=bundle_id)
    out = []
    for rec in _tooling_query_all(sf, soql):
        file_path = rec.get("FilePath") or ""
        out.append(
            {
                "id": rec.get("Id"),
                "file_path": file_path,
                "file_name": file_path.rsplit("/", 1)[-1] if file_path else "",
                "format": rec.get("Format") or "",
                "source": rec.get("Source") or "",
                "last_modified": rec.get("LastModifiedDate") or "",
            }
        )
    return out


def list_lwc_files(sf, bundle_id: str) -> list[dict]:
    """File *metadata* of one bundle (no Source) — feeds the File dropdown
    without pulling every file's contents into the workspace."""
    soql = _LWC_FILES_SOQL.format(bundle_id=bundle_id)
    out = []
    for rec in _tooling_query_all(sf, soql):
        file_path = rec.get("FilePath") or ""
        out.append(
            {
                "id": rec.get("Id"),
                "file_path": file_path,
                "file_name": file_path.rsplit("/", 1)[-1] if file_path else "",
                "format": rec.get("Format") or "",
                "last_modified": rec.get("LastModifiedDate") or "",
            }
        )
    return out


def fetch_lwc_resource(sf, resource_id: str) -> dict:
    """One resource record, including its ``Source``."""
    rec = sf.toolingexecute(
        f"sobjects/LightningComponentResource/{resource_id}", method="GET"
    )
    return {
        "source": (rec or {}).get("Source") or "",
        "last_modified": (rec or {}).get("LastModifiedDate") or "",
    }


# ------------------------------------------------------------
# Workspace model
# ------------------------------------------------------------

def apex_key(name: str) -> str:
    return f"apex:{name}"


def trigger_key(name: str) -> str:
    return f"trigger:{name}"


def lwc_key(bundle: str, file_name: str) -> str:
    return f"lwc:{bundle}/{file_name}"


def new_apex_entry(name: str, class_id: str | None, body: str,
                   last_modified: str = "", namespace: str = "",
                   api_version=None) -> dict:
    return {
        "kind": "apex",
        "id": class_id,
        "name": name,
        "file_name": f"{name}.cls",
        "namespace": namespace,
        "api_version": api_version,
        "original": body,
        "current": body,
        "server_modified": last_modified,
        "is_new": class_id is None,
        "conflict": False,
        "server_copy": None,
    }


def new_trigger_entry(name: str, trigger_id: str | None, body: str,
                      sobject: str = "", status: str = "Active",
                      last_modified: str = "", namespace: str = "",
                      api_version=None) -> dict:
    return {
        "kind": "trigger",
        "id": trigger_id,
        "name": name,
        "file_name": f"{name}.trigger",
        "namespace": namespace,
        "api_version": api_version,
        "sobject": sobject,
        "status": status,
        "original": body,
        "current": body,
        "server_modified": last_modified,
        "is_new": trigger_id is None,
        "conflict": False,
        "server_copy": None,
    }


def new_lwc_entry(bundle: str, bundle_id: str | None, resource_id: str | None,
                  file_name: str, source: str, file_format: str = "",
                  last_modified: str = "", namespace: str = "") -> dict:
    return {
        "kind": "lwc",
        "id": resource_id,
        "bundle_id": bundle_id,
        "bundle": bundle,
        "name": file_name,
        "file_name": file_name,
        "format": file_format or format_for_file(file_name),
        "namespace": namespace,
        "original": source,
        "current": source,
        "server_modified": last_modified,
        "is_new": resource_id is None,
        "conflict": False,
        "server_copy": None,
    }


def is_gone_error(exc: Exception) -> bool:
    """True when the failure means 'that org record no longer exists'.

    Salesforce answers a GET on a deleted Tooling record with 404
    ("The requested resource does not exist"). Callers use this to tell
    'deleted outside this app' apart from a genuine failure — the two
    need very different UI (a recreate path, not a red error banner).
    """
    for attr in ("status_code", "status"):
        if getattr(exc, attr, None) == 404:
            return True
    if type(exc).__name__ in ("SalesforceResourceNotFound",):
        return True
    content = getattr(exc, "content", None)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("errorCode") == "NOT_FOUND":
                return True
    return "requested resource does not exist" in str(exc).lower()


def file_status(entry: dict) -> str:
    """Git-style status letter for one workspace entry."""
    if entry.get("org_deleted"):
        # Checked first: a deleted org copy supersedes conflict/modified
        # — the local draft is now the only copy, whatever it was.
        return "D"
    if entry.get("conflict"):
        return "C"
    if entry.get("is_new"):
        return "U"
    if entry.get("current") != entry.get("original"):
        return "M"
    return ""


STATUS_META = {
    "U": ("🟢", "Untracked — not on the server yet"),
    "M": ("🟠", "Modified — unsaved changes"),
    "C": ("🔴", "Conflict — server changed since fetch"),
    "D": ("🗑️", "Deleted from the org — local copy only"),
    "": ("", "Clean"),
}


def change_counts(workspace: dict) -> dict:
    counts = {"M": 0, "U": 0, "C": 0}
    for entry in workspace.values():
        status = file_status(entry)
        if status in counts:
            counts[status] += 1
    return counts


# ------------------------------------------------------------
# Diff
# ------------------------------------------------------------

def diff_stats(original: str, current: str) -> tuple[int, int]:
    """(added, removed) line counts between two source texts."""
    diff = difflib.unified_diff(
        (original or "").splitlines(), (current or "").splitlines(), lineterm=""
    )
    added = removed = 0
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def unified_diff(original: str, current: str, from_name: str, to_name: str) -> list[str]:
    return list(
        difflib.unified_diff(
            (original or "").splitlines(),
            (current or "").splitlines(),
            fromfile=from_name,
            tofile=to_name,
            lineterm="",
        )
    )


def diff_rows(original: str, current: str, context: int = 3) -> list[dict]:
    """
    Line-numbered diff rows between the server copy and the saved draft.

    Each row is ``{"kind", "old_no", "new_no", "text"}`` where kind is
    "context" | "add" | "del" | "hunk"; line numbers are 1-based and
    ``None`` on the side a row doesn't exist on. Unchanged stretches are
    folded into "hunk" separator rows, unified-diff style.
    """
    a = (original or "").splitlines()
    b = (current or "").splitlines()
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    rows: list[dict] = []
    for group in matcher.get_grouped_opcodes(context):
        first, last = group[0], group[-1]
        rows.append({
            "kind": "hunk", "old_no": None, "new_no": None,
            "text": f"@@ −{first[1] + 1},{last[2] - first[1]} "
                    f"+{first[3] + 1},{last[4] - first[3]} @@",
        })
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for k in range(i2 - i1):
                    rows.append({"kind": "context", "old_no": i1 + k + 1,
                                 "new_no": j1 + k + 1, "text": a[i1 + k]})
                continue
            if tag in ("replace", "delete"):
                for i in range(i1, i2):
                    rows.append({"kind": "del", "old_no": i + 1,
                                 "new_no": None, "text": a[i]})
            if tag in ("replace", "insert"):
                for j in range(j1, j2):
                    rows.append({"kind": "add", "old_no": None,
                                 "new_no": j + 1, "text": b[j]})
    return rows


# ------------------------------------------------------------
# Validation + templates
# ------------------------------------------------------------

_APEX_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_LWC_NAME_RE = re.compile(r"^[a-z][a-zA-Z0-9]*(_[a-zA-Z0-9]+)*$")


def validate_apex_name(name: str) -> str | None:
    """None if valid, else a human-readable problem."""
    if not name:
        return "Enter a class name."
    if len(name) > 40:
        return "Apex class names are at most 40 characters."
    if not _APEX_NAME_RE.match(name):
        return "Use letters, numbers and underscores, starting with a letter."
    return None


def validate_trigger_name(name: str) -> str | None:
    """None if valid, else a human-readable problem (same Apex rules)."""
    if not name:
        return "Enter a trigger name."
    if len(name) > 40:
        return "Apex trigger names are at most 40 characters."
    if not _APEX_NAME_RE.match(name):
        return "Use letters, numbers and underscores, starting with a letter."
    return None


def validate_sobject_name(name: str) -> str | None:
    """None if valid, else a human-readable problem (API name of an object)."""
    if not name:
        return "Enter the object API name (e.g. Account)."
    if not _APEX_NAME_RE.match(name):
        return "Use letters, numbers and underscores, starting with a letter."
    return None


def validate_lwc_name(name: str) -> str | None:
    """None if valid, else a human-readable problem (LWC naming rules)."""
    if not name:
        return "Enter a component name."
    if len(name) > 40:
        return "Component names are at most 40 characters."
    if not _LWC_NAME_RE.match(name):
        return (
            "LWC names start with a lowercase letter and use camelCase "
            "(letters/numbers, single underscores between words, no trailing "
            "underscore)."
        )
    return None


def apex_template(name: str) -> str:
    return (
        f"public with sharing class {name} {{\n"
        f"    public {name}() {{\n"
        "\n"
        "    }\n"
        "}\n"
    )


def trigger_template(name: str, sobject: str) -> str:
    return (
        f"trigger {name} on {sobject} (before insert) {{\n"
        "\n"
        "}\n"
    )


def lwc_templates(name: str, api_version: str) -> dict[str, str]:
    """Starter files for a brand-new LWC bundle: {file_name: source}."""
    pascal = name[0].upper() + name[1:] if name else name
    meta = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<LightningComponentBundle xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        f"    <apiVersion>{api_version}</apiVersion>\n"
        "    <isExposed>false</isExposed>\n"
        "</LightningComponentBundle>\n"
    )
    js = (
        "import { LightningElement } from 'lwc';\n"
        "\n"
        f"export default class {pascal} extends LightningElement {{}}\n"
    )
    css = f"/* Styles for the {name} component. */\n"
    return {
        f"{name}.js": js,
        f"{name}.html": "<template>\n    \n</template>\n",
        f"{name}.css": css,
        f"{name}.js-meta.xml": meta,
    }


_FORMAT_BY_EXT = {
    "js": "js",
    "html": "html",
    "css": "css",
    "xml": "xml",
    "svg": "svg",
    "json": "json",
}


def format_for_file(file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return _FORMAT_BY_EXT.get(ext, "js")


# ------------------------------------------------------------
# Deploy (Tooling API writes compile server-side)
# ------------------------------------------------------------

class ToolingDeployError(Exception):
    """A deploy that Salesforce processed and rejected (e.g. Apex compile
    failure). ``rows`` is already in the {message, line, column} shape the
    page renders. ``compile_failure`` is True when the Apex compiler itself
    rejected the code — retrying through another deploy path would fail
    identically, so callers must not fall back in that case."""

    def __init__(self, rows: list[dict], *, compile_failure: bool = False):
        self.rows = rows
        self.compile_failure = compile_failure
        super().__init__(rows[0]["message"] if rows else "Deploy failed.")


def _num(value) -> int | None:
    return int(value) if str(value or "").isdigit() else None


def _parse_compiler_errors(raw) -> list[dict]:
    """ContainerAsyncRequest.CompilerErrors is a JSON string of
    [{line, column, problem, ...}] (keys sometimes capitalised)."""
    if not raw:
        return []
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return [{"message": str(raw), "line": None, "column": None}]
    if isinstance(items, dict):
        items = [items]
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        message = (
            item.get("problem") or item.get("Problem")
            or item.get("message") or item.get("Message") or str(item)
        )
        rows.append(
            {
                "message": str(message),
                "line": _num(item.get("line") or item.get("Line")
                              or item.get("lineNumber")),
                "column": _num(item.get("column") or item.get("Column")
                                or item.get("columnNumber")),
            }
        )
    return rows


_CONTAINER_DONE_STATES = {"Completed"}
_CONTAINER_FAIL_STATES = {"Failed", "Error", "Aborted", "Invalidated"}


def _container_step(description: str, fn):
    """Run one container-flow call, labelling any failure with the step so
    the user can see exactly which call Salesforce rejected."""
    try:
        return fn()
    except ToolingDeployError:
        raise
    except Exception as exc:
        rows = parse_deploy_error(exc)
        rows[0] = {**rows[0], "message": f"{description}: {rows[0]['message']}"}
        raise ToolingDeployError(rows) from exc


def _deploy_apex_container(sf, class_id: str, body: str, *,
                           member: str = "ApexClassMember",
                           timeout_s: float = 120.0, poll_s: float = 1.0) -> None:
    """
    Update an existing Apex class or trigger via the documented Tooling
    compile flow: MetadataContainer → ApexClassMember / ApexTriggerMember
    (the working copy) → ContainerAsyncRequest → poll to completion.

    A direct PATCH on ApexClass is rejected by some orgs with
    INVALID_CROSS_REFERENCE_KEY, which is why this longer path exists.
    Raises ToolingDeployError on failure (compile_failure=True only when
    the compiler itself rejected the code).
    """
    container_name = f"SFCloudCode-{int(time.time() * 1000)}"
    created = _container_step(
        "Creating MetadataContainer",
        lambda: sf.toolingexecute(
            "sobjects/MetadataContainer", method="POST",
            data={"Name": container_name},
        ),
    )
    container_id = (created or {}).get("id")
    if not container_id:
        raise ToolingDeployError([{
            "message": f"MetadataContainer creation returned no Id: {created!r}",
            "line": None, "column": None,
        }])
    try:
        _container_step(
            f"Adding {member} working copy",
            lambda: sf.toolingexecute(
                f"sobjects/{member}",
                method="POST",
                data={
                    "MetadataContainerId": container_id,
                    "ContentEntityId": class_id,
                    "Body": body,
                },
            ),
        )
        request = _container_step(
            "Starting ContainerAsyncRequest",
            lambda: sf.toolingexecute(
                "sobjects/ContainerAsyncRequest",
                method="POST",
                data={"MetadataContainerId": container_id, "IsCheckOnly": False},
            ),
        )
        request_id = (request or {}).get("id")
        if not request_id:
            raise ToolingDeployError([{
                "message": f"ContainerAsyncRequest creation returned no Id: {request!r}",
                "line": None, "column": None,
            }])
        deadline = time.time() + timeout_s
        while True:
            status = sf.toolingexecute(
                f"sobjects/ContainerAsyncRequest/{request_id}", method="GET"
            ) or {}
            state = status.get("State") or ""
            if state in _CONTAINER_DONE_STATES:
                return
            if state in _CONTAINER_FAIL_STATES:
                rows = _parse_compiler_errors(status.get("CompilerErrors"))
                from_compiler = bool(rows)
                if not rows and status.get("ErrorMsg"):
                    rows = [{
                        "message": status["ErrorMsg"],
                        "line": None, "column": None,
                    }]
                if not rows:
                    # The sobject GET sometimes returns the request with
                    # its diagnostic fields empty; re-read them via SOQL,
                    # which returns the long-text fields in full.
                    try:
                        q = sf.toolingexecute(
                            "query/",
                            params={"q": (
                                "SELECT State, ErrorMsg, CompilerErrors "
                                "FROM ContainerAsyncRequest "
                                f"WHERE Id = '{request_id}'"
                            )},
                        )
                        recs = (q or {}).get("records") or []
                        if recs:
                            rows = _parse_compiler_errors(recs[0].get("CompilerErrors"))
                            from_compiler = bool(rows)
                            if not rows and recs[0].get("ErrorMsg"):
                                rows = [{
                                    "message": recs[0]["ErrorMsg"],
                                    "line": None, "column": None,
                                }]
                    except Exception:
                        pass
                if rows:
                    # Only genuine compiler output marks this a compile
                    # failure (no fallback); an ErrorMsg-only or detail-
                    # less rejection may still succeed via Metadata API.
                    raise ToolingDeployError(rows, compile_failure=from_compiler)
                raise ToolingDeployError([{
                    "message": (
                        f"Apex compilation {state.lower()}, but Salesforce "
                        f"returned no error detail for the request "
                        f"(ContainerAsyncRequest {request_id})."
                    ),
                    "line": None, "column": None,
                }])
            if time.time() >= deadline:
                raise ToolingDeployError([{
                    "message": (
                        f"Apex compilation did not finish within "
                        f"{int(timeout_s)}s (last state: {state or 'unknown'})."
                    ),
                    "line": None, "column": None,
                }])
            time.sleep(poll_s)
    finally:
        # Best-effort cleanup — a leftover container blocks nothing, but a
        # pile of them clutters the org and container names must stay free.
        try:
            sf.toolingexecute(
                f"sobjects/MetadataContainer/{container_id}", method="DELETE"
            )
        except Exception:
            pass


def _package_xml(member_name: str, api_version: str,
                 metadata_type: str = "ApexClass") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Package xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        "    <types>\n"
        f"        <members>{member_name}</members>\n"
        f"        <name>{metadata_type}</name>\n"
        "    </types>\n"
        f"    <version>{api_version}</version>\n"
        "</Package>\n"
    )


def _apex_meta_xml(api_version: str, metadata_type: str = "ApexClass",
                   status: str = "Active") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<{metadata_type} xmlns=\"http://soap.sforce.com/2006/04/metadata\">\n"
        f"    <apiVersion>{api_version}</apiVersion>\n"
        f"    <status>{status}</status>\n"
        f"</{metadata_type}>\n"
    )


_MDAPI_DONE_STATES = {"Succeeded"}
_MDAPI_FAIL_STATES = {"Failed", "SucceededPartial", "Canceled"}


def _mdapi_deploy_zip(sf, buffer, timeout_s: float, poll_s: float) -> None:
    """Deploy a zip via the Metadata API and poll to completion.

    Shared by the Apex fallback and the LWC bundle deploy. Raises
    ToolingDeployError on failure (rows already in the
    {message, line, column} shape). Restores the connection headers
    afterwards: simple-salesforce's raw SOAP calls mutate them.
    """
    sandbox = getattr(sf, "domain", "") == "test"
    # simple-salesforce's raw SOAP deploy calls MUTATE the
    # connection's shared headers dict (Content-Type becomes text/xml,
    # plus a stray SOAPAction), which then breaks every later
    # REST/Tooling call in the session: "MediaType of 'text/xml' is
    # not supported by this resource". Snapshot the headers and
    # restore them afterwards, whatever happens.
    _headers = getattr(sf, "headers", None)
    _saved_headers = dict(_headers) if isinstance(_headers, dict) else None
    try:
        async_id, _state = sf.mdapi.deploy(buffer, sandbox)
        if not async_id:
            raise ToolingDeployError([{
                "message": "Metadata API deploy returned no async Id.",
                "line": None, "column": None,
            }])
        deadline = time.time() + timeout_s
        while True:
            state, state_detail, deployment_detail, unit_test_detail = (
                sf.mdapi.check_deploy_status(async_id)
            )
            if state in _MDAPI_DONE_STATES:
                return
            if state in _MDAPI_FAIL_STATES:
                # check_deploy_status returns detail DICTS:
                #   deployment_detail = {"errors": [{type, file, status,
                #       message}], "failed_count": ..., ...}
                #   unit_test_detail  = {"errors": [{class, method, message,
                #       stack_trace}], ...}
                rows = []
                comp_errors = deployment_detail
                if isinstance(comp_errors, dict):
                    comp_errors = comp_errors.get("errors") or []
                for d in comp_errors or []:
                    if isinstance(d, dict) and d.get("message"):
                        where = f"{d['file']}: " if d.get("file") else ""
                        translated, ref = translate_platform_message(
                            str(d["message"]))
                        row = {
                            "message": where + translated,
                            "line": None, "column": None,
                        }
                        if ref:
                            row["ref"] = ref
                        if d.get("file"):
                            row["file"] = d["file"]
                        rows.append(row)
                test_errors = unit_test_detail
                if isinstance(test_errors, dict):
                    test_errors = test_errors.get("errors") or []
                for t in test_errors or []:
                    if isinstance(t, dict) and t.get("message"):
                        label = ".".join(
                            x for x in [t.get("class"), t.get("method")] if x
                        )
                        rows.append({
                            "message": f"Test failure {label}: {t['message']}",
                            "line": None, "column": None,
                        })
                if not rows and state_detail:
                    rows = [{
                        "message": str(state_detail),
                        "line": None, "column": None,
                    }]
                if not rows:
                    rows = [{
                        "message": (
                            f"Metadata deployment {state}, but Salesforce "
                            "returned no error detail."
                        ),
                        "line": None, "column": None,
                    }]
                raise ToolingDeployError(rows, compile_failure=(state == "Failed"))
            if time.time() >= deadline:
                raise ToolingDeployError([{
                    "message": (
                        f"Metadata deployment did not finish within "
                        f"{int(timeout_s)}s (last state: {state or 'unknown'}). It "
                        "may still complete on the server — check Setup → "
                        "Deployment Status before retrying."
                    ),
                    "line": None, "column": None,
                }])
            time.sleep(poll_s)
    finally:
        if _saved_headers is not None:
            _headers.clear()
            _headers.update(_saved_headers)
            # Also heal a session poisoned before this fix existed: a
            # REST connection must never carry the SOAP content type or
            # a SOAPAction header.
            if _headers.get("Content-Type") == "text/xml":
                _headers["Content-Type"] = "application/json"
            _headers.pop("SOAPAction", None)


def _deploy_apex_metadata(sf, class_name: str, body: str, api_version: str, *,
                          metadata_type: str = "ApexClass",
                          folder: str = "classes", extension: str = ".cls",
                          status: str = "Active",
                          timeout_s: float = 600.0, poll_s: float = 3.0) -> None:
    """
    Fallback: deploy the single class or trigger through the Metadata API
    (the same route Workbench/SFDX use). Raises ToolingDeployError on
    failure. For triggers the entry's own status is written to the
    -meta.xml, so a metadata fallback never silently flips an Inactive
    trigger to Active (or vice versa).
    """
    if not class_name:
        raise ToolingDeployError([{
            "message": "Metadata API fallback needs the component name, which is "
                       "unknown for this entry.",
            "line": None, "column": None,
        }])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("package.xml",
                    _package_xml(class_name, api_version, metadata_type))
        zf.writestr(f"{folder}/{class_name}{extension}", body)
        zf.writestr(f"{folder}/{class_name}{extension}-meta.xml",
                    _apex_meta_xml(api_version, metadata_type, status))
    buffer.seek(0)
    _mdapi_deploy_zip(sf, buffer, timeout_s, poll_s)


def deploy_lwc_bundle_mdapi(sf, bundle_name: str, files: dict[str, str],
                            api_version: str, timeout_s: float = 600.0,
                            poll_s: float = 3.0) -> None:
    """Deploy a whole LWC bundle atomically via the Metadata API.

    Tooling API resource creates cannot bootstrap a new bundle: the
    first file (.js) lands, but every later file fails with "No MODULE
    named markup://c:<name>" — the platform builds the component module
    only from a complete bundle, and a partial bundle never qualifies
    (three orders tried live: meta-first, js/html/css/meta, js/meta —
    the second file always failed). The Metadata API deploys all files
    as one package, the same route SFDX uses, so it works for fresh
    bundles, partial states, and added files alike. Raises
    ToolingDeployError on failure.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "package.xml",
            _package_xml(bundle_name, api_version, "LightningComponentBundle"),
        )
        for file_name, source in files.items():
            zf.writestr(f"lwc/{bundle_name}/{file_name}", source)
    buffer.seek(0)
    _mdapi_deploy_zip(sf, buffer, timeout_s, poll_s)

def deploy_apex_body(sf, class_id: str, body: str, *,
                     class_name: str = "", api_version: str = "",
                     kind: str = "apex", status: str = "Active",
                     timeout_s: float = 120.0, poll_s: float = 1.0) -> str:
    """
    Update an existing Apex class or trigger. Primary path: the Tooling
    container flow. If Salesforce rejects that *machinery* (e.g. the
    cross-reference error some orgs return for the working-copy step),
    fall back to a Metadata API deployment of the single component. A
    genuine compile error is re-raised at once — no path deploys
    uncompilable code.

    Returns which path deployed: "tooling" or "metadata".
    """
    if kind == "trigger":
        member = "ApexTriggerMember"
        metadata_type, folder, extension = "ApexTrigger", "triggers", ".trigger"
    else:
        member = "ApexClassMember"
        metadata_type, folder, extension = "ApexClass", "classes", ".cls"
    try:
        _deploy_apex_container(sf, class_id, body, member=member,
                               timeout_s=timeout_s, poll_s=poll_s)
        return "tooling"
    except ToolingDeployError as exc:
        if exc.compile_failure:
            raise
        container_rows = exc.rows
    version = str(api_version or getattr(sf, "sf_version", "") or "59.0")
    try:
        _deploy_apex_metadata(sf, class_name, body, version,
                              metadata_type=metadata_type, folder=folder,
                              extension=extension, status=status)
        return "metadata"
    except ToolingDeployError as md_exc:
        rows = (
            [{"message": "Tooling container deploy was rejected:",
              "line": None, "column": None}]
            + container_rows
            + [{"message": "Metadata API deploy also failed:",
                "line": None, "column": None}]
            + md_exc.rows
        )
        raise ToolingDeployError(
            rows, compile_failure=md_exc.compile_failure
        ) from md_exc
    except Exception as exc:
        rows = (
            [{"message": "Tooling container deploy was rejected:",
              "line": None, "column": None}]
            + container_rows
            + [{"message": "Metadata API deploy also failed:",
                "line": None, "column": None}]
            + parse_deploy_error(exc)
        )
        raise ToolingDeployError(rows) from exc


# Common Lightning base components, for "did you mean" suggestions when a
# deploy fails on an unknown lightning:* reference. Only well-known names
# are listed; an unknown name simply gets no suggestion.
_LIGHTNING_BASE_COMPONENTS = [
    "accordion", "accordion-section", "avatar", "badge", "breadcrumb",
    "button", "button-group", "button-icon", "button-menu", "card",
    "checkbox", "checkbox-group", "combobox", "datatable", "dual-listbox",
    "dynamic-icon", "file-upload", "formatted-date-time", "formatted-email",
    "formatted-location", "formatted-number", "formatted-phone",
    "formatted-rich-text", "formatted-text", "formatted-time",
    "formatted-url", "helptext", "icon", "input", "layout", "layout-item",
    "menu-item", "pill", "pill-container", "progress-bar", "progress-ring",
    "radio-group", "record-edit-form", "record-form", "record-view-form",
    "relative-date-time", "select", "slider", "spinner", "tab", "tabset",
    "textarea", "tree", "tree-grid",
]

_MODULE_RE = re.compile(
    r"No MODULE named markup://([A-Za-z0-9_]+):([A-Za-z0-9_\-]+) found"
)
_BASE_FILE_RE = re.compile(r"No base file for markup://c:([A-Za-z0-9_\-]+)")
_PARSE_SEMI_RE = re.compile(r"Parsing error:\s*Missing semicolon")
_PARSE_LOC_RE = re.compile(r"([A-Za-z0-9_\-./]+\.[A-Za-z]+):(\d+)[,:](\d+)")
_SEMI_HINT = (
    "This usually means a typo or a missing operator just before this "
    "spot (for example, a misspelled keyword like 'clss' instead of "
    "'class'), not a semicolon that is actually missing."
)
_PARSE_UNEXPECTED_HINT = (
    "Check this token and the one just before it — something there is "
    "not what the parser expected."
)
# "Compilation Failure <file>:<line>,<col> : [<CODE>: ]<detail> (<line>:<col>): Source"
_COMPILATION_RE = re.compile(
    r"Compilation Failure\s+(?P<file>[^\s:]+):(?P<line>\d+)[,:](?P<col>\d+)"
    r"\s*:\s*(?:[A-Z]+\d+:\s*)?(?P<detail>.*?)\s*\(\d+:\d+\)\s*:\s*Source"
)


def _levenshtein(a: str, b: str) -> int:
    """Edit distance between two short names (no dependency)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _suggest_lightning(name: str) -> str | None:
    """Closest known base component within edit distance 2, else None."""
    best, best_d = None, 3
    for cand in _LIGHTNING_BASE_COMPONENTS:
        d = _levenshtein(name, cand)
        if d < best_d:
            best, best_d = cand, d
    return best if best_d in (1, 2) else None


def translate_platform_message(message: str) -> tuple[str, str | None]:
    """Rewrite a cryptic platform error into a plain explanation.

    Returns (message, ref): ref is the unknown component reference
    ("lightning:car", "c:foo") when one was identified, else None — the
    page uses it to point at the line that references it. Messages that
    match no known pattern pass through unchanged with ref None.
    """
    m = _MODULE_RE.search(message)
    if m:
        ns, name = m.group(1), m.group(2)
        ref = f"{ns}:{name}"
        if ns == "lightning" and name not in _LIGHTNING_BASE_COMPONENTS:
            text = (
                f"Unknown component '{ref}' — no Lightning base component "
                f"with that name exists. Check the spelling of the tag, "
                f"import, or CSS selector."
            )
            suggestion = _suggest_lightning(name)
            if suggestion:
                text += f" Did you mean 'lightning:{suggestion}'?"
            return text, ref
        if ns == "lightning":
            return (
                f"Could not resolve component '{ref}' while compiling — "
                f"check the reference.",
                ref,
            )
        if ns == "c":
            return (
                f"Unknown component '{ref}' — no component with that name "
                f"exists in your org. Check the spelling of the tag, "
                f"import, or CSS selector.",
                ref,
            )
        return (
            f"Unknown component '{ref}' — no such component exists. "
            f"Check the spelling of the tag, import, or CSS selector.",
            ref,
        )
    m = _BASE_FILE_RE.search(message)
    if m:
        return (
            f"Bundle 'c:{m.group(1)}' has no base (.js) file yet — the .js "
            f"file must exist before other files can be added. Deploy the "
            f"whole bundle via the Metadata API.",
            None,
        )
    m = _COMPILATION_RE.search(message)
    if m:
        # Unwrap the platform's envelope for EVERY compilation error:
        # the detail plus file/line/column in plain words, with a
        # kind-specific hint on top when one applies.
        file, line, col = m.group("file"), m.group("line"), m.group("col")
        detail = m.group("detail").strip()
        if detail.endswith("."):
            detail = detail[:-1]
        where = f"in {file} at line {line}, column {col}"
        if "Missing semicolon" in detail:
            return (
                f"Parsing error {where} — the parser stopped here. "
                + _SEMI_HINT,
                None,
            )
        if detail.startswith("Parsing error:"):
            rest = detail[len("Parsing error:"):].strip()
            if rest and rest.lower() != "unexpected token":
                head = f"Parsing error {where} — {rest}. "
            else:
                head = f"Parsing error {where} — the parser stopped here. "
            return head + _PARSE_UNEXPECTED_HINT, None
        return f"{detail} — {where}", None
    if _PARSE_SEMI_RE.search(message):
        # Same hint without the Compilation Failure envelope.
        loc = _PARSE_LOC_RE.search(message)
        if loc:
            head = (f"Parsing error in {loc.group(1)} at line {loc.group(2)}, "
                    f"column {loc.group(3)} — the parser stopped here.")
        else:
            head = "Parsing error — the parser stopped here."
        return head + " " + _SEMI_HINT, None
    return message, None


def parse_deploy_error(exc: Exception) -> list[dict]:
    """
    Normalise a simple-salesforce failure into [{message, line, column}].
    Tooling compile failures arrive as a list of error dicts on the
    exception's ``content``; anything else degrades to one message row.
    """
    preset = getattr(exc, "rows", None)
    if preset:
        return preset
    content = getattr(exc, "content", None)
    rows: list[dict] = []

    def _row(item: dict) -> dict:
        message = (
            item.get("message")
            or item.get("compileProblem")
            or item.get("problem")
            or str(item)
        )
        line = item.get("line") or item.get("lineNumber")
        column = item.get("column") or item.get("columnNumber")
        translated, ref = translate_platform_message(str(message))
        line_n = int(line) if str(line or "").isdigit() else None
        col_n = int(column) if str(column or "").isdigit() else None
        if translated != str(message) and "at line" in translated:
            # The translated message already carries the position; the
            # renderer's "Line X, Col Y" prefix would duplicate it.
            line_n = col_n = None
        row = {
            "message": translated,
            "line": line_n,
            "column": col_n,
        }
        if ref:
            row["ref"] = ref
        return row

    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                rows.append(_row(item))
    elif isinstance(content, dict):
        rows.append(_row(content))
    if not rows:
        rows.append(_row({"message": str(exc)}))
    return rows


def format_server_time(value) -> str:
    """
    Render a Salesforce timestamp for display:
    ``2026-10-23T14:47:44.000+0000`` → ``23 Oct 2026, 8:17 PM IST``.
    IST is a fixed UTC+5:30 offset (no DST), so no tz database is
    needed. Unparseable values are returned unchanged.
    """
    if not value or not isinstance(value, str):
        return value or ""
    text = value.strip()
    # Normalise for fromisoformat: colon in the offset, no trailing Z.
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text.replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(timezone(timedelta(hours=5, minutes=30)))
    return (
        local.strftime("%d %b %Y, ")
        + local.strftime("%I:%M %p").lstrip("0")
        + " IST"
    )


def heal_session_headers(sf) -> bool:
    """
    Repair a connection whose shared headers dict was poisoned by a
    Metadata API (SOAP) call. simple-salesforce's raw SOAP calls mutate
    ``sf.headers`` in place (Content-Type becomes ``text/xml`` and a
    ``SOAPAction`` entry appears); every REST/Tooling call afterwards
    reads those headers and is rejected with "MediaType of 'text/xml'
    is not supported by this resource". Safe to call any time; returns
    True if anything was repaired.
    """
    headers = getattr(sf, "headers", None)
    if not isinstance(headers, dict):
        return False
    healed = False
    if headers.get("Content-Type") == "text/xml":
        headers["Content-Type"] = "application/json"
        healed = True
    if "SOAPAction" in headers:
        headers.pop("SOAPAction", None)
        healed = True
    return healed


def deploy_entry(sf, entry: dict) -> dict:
    """
    Push one workspace entry to the org. Returns {id, last_modified} of the
    saved component. Raises whatever simple-salesforce raises on failure —
    feed it to :func:`parse_deploy_error` for display. Create failures are
    wrapped in ToolingDeployError with labeled rows, so a failed create
    reads with the same detail as a failed update.
    """
    heal_session_headers(sf)  # a poisoned session fails every deploy
    if entry["kind"] in ("apex", "trigger"):
        is_trigger = entry["kind"] == "trigger"
        sobject = "ApexTrigger" if is_trigger else "ApexClass"
        if entry.get("is_new") or entry.get("org_deleted"):
            # Brand-new, or the org copy was deleted outside this app:
            # either way the record must be CREATED, not updated.
            data = {"Name": entry["name"], "Body": entry["current"]}
            if is_trigger:
                # Required on trigger creation; the entry always carries
                # it (the create dialog requires an object).
                data["TableEnumOrId"] = entry.get("sobject") or ""
                data["Status"] = entry.get("status") or "Active"
            try:
                result = sf.toolingexecute(
                    f"sobjects/{sobject}", method="POST", data=data,
                )
            except ToolingDeployError:
                raise
            except Exception as exc:
                # Same detailed shape as the update path: label the step
                # and prefix the platform's message with the file, so a
                # failed create reads like a failed update.
                folder = "triggers" if is_trigger else "classes"
                ext = "trigger" if is_trigger else "cls"
                where = f"{folder}/{entry['name']}.{ext}: "
                detail = []
                for r in parse_deploy_error(exc):
                    r2 = dict(r)
                    r2["message"] = where + r2["message"]
                    detail.append(r2)
                rows = ([{"message": f"Creating {sobject} was rejected:",
                           "line": None, "column": None}]
                        + detail)
                raise ToolingDeployError(rows) from exc
            new_id = (result or {}).get("id")
            if new_id:
                fresh = (fetch_trigger_body(sf, new_id) if is_trigger
                         else fetch_apex_body(sf, new_id))
            else:
                fresh = {"last_modified": ""}
            return {"id": new_id, "last_modified": fresh["last_modified"]}
        via = deploy_apex_body(
            sf, entry["id"], entry["current"],
            class_name=entry["name"],
            api_version=str(entry.get("api_version") or ""),
            kind=entry["kind"],
            status=entry.get("status") or "Active",
        )
        fresh = (fetch_trigger_body(sf, entry["id"]) if is_trigger
                 else fetch_apex_body(sf, entry["id"]))
        out = {"id": entry["id"], "last_modified": fresh["last_modified"],
               "via": via}
        if is_trigger:
            # Refresh status/object from the server copy after deploy.
            out["status"] = fresh.get("status") or ""
            out["sobject"] = fresh.get("sobject") or ""
        return out

    # LWC resource
    if entry.get("is_new") and not entry.get("bundle_id"):
        raise RuntimeError(
            "Bundle has not been created yet — deploy the bundle first."
        )
    if entry.get("is_new") or entry.get("org_deleted"):
        # A deleted resource is recreated the same way as a new one, as
        # long as its bundle still exists.
        result = sf.toolingexecute(
            "sobjects/LightningComponentResource",
            method="POST",
            data={
                "LightningComponentBundleId": entry["bundle_id"],
                "FilePath": f"{entry['bundle']}/{entry['file_name']}",
                "Format": entry.get("format") or format_for_file(entry["file_name"]),
                "Source": entry["current"],
            },
        )
        return {"id": (result or {}).get("id"), "last_modified": ""}
    sf.toolingexecute(
        f"sobjects/LightningComponentResource/{entry['id']}",
        method="PATCH",
        data={"Source": entry["current"]},
    )
    return {"id": entry["id"], "last_modified": ""}


def lwc_bundle_metadata(meta_xml: str, api_version_fallback: str = "59.0") -> dict:
    """The Tooling API Metadata value for creating a LightningComponentBundle.

    Bundle creation without a valid Metadata field is rejected with "You
    must provide a valid Metadata field for LightningComponentBundle",
    so a DeveloperName/MasterLabel-only POST can never succeed. The
    known-good minimal value is just the apiVersion, taken from the
    bundle's own .js-meta.xml when parseable (so the bundle is created
    at the version the user chose, e.g. 60.0, not the session default);
    isExposed/targets ride along on the meta.xml resource created
    immediately after, meta-first. Namespace-agnostic: matches elements
    by local name, with or without the metadata namespace.
    """
    version = ""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(meta_xml or "")
        for child in root:
            if child.tag.rsplit("}", 1)[-1] == "apiVersion":
                version = (child.text or "").strip()
                break
    except Exception:
        version = ""
    try:
        number = float(version or api_version_fallback or "59.0")
    except (TypeError, ValueError):
        number = 59.0
    return {"apiVersion": number}


def create_lwc_bundle(sf, name: str, label: str = "",
                      metadata: dict | None = None) -> str:
    """Create a LightningComponentBundle; returns its Id.

    The org's create rules for this object, learned one error at a
    time, are now fully pinned down by its own messages:
    - Metadata is required ("You must provide a valid Metadata field
      for LightningComponentBundle").
    - FullName is required ("To create an entity, its full name must
      be set and its id must be empty").
    - When Metadata is present, ONLY Metadata and FullName may be
      specified — DeveloperName, MasterLabel and Description are
      rejected as invalid fields. So the payload is exactly those
      two fields. The bundle's exposure and targets are not lost:
      they ride on the .js-meta.xml resource created immediately
      after, meta-first.
    """
    result = sf.toolingexecute(
        "sobjects/LightningComponentBundle",
        method="POST",
        data={
            "FullName": name,
            "Metadata": metadata or {"apiVersion": 59.0},
        },
    )
    bundle_id = (result or {}).get("id")
    if not bundle_id:
        raise RuntimeError(f"Bundle creation returned no Id: {result!r}")
    return bundle_id
