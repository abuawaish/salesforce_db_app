"""
Salesforce authentication for SF Query Studio.

OAuth 2.0 Client Credentials flow
---------------------------------
Salesforce retired the SOAP ``login()`` endpoint (unavailable from API 65.0,
fully removed for 31.0–64.0 in Summer '27), so username/password/security-token
authentication no longer works. This module replaces it with the OAuth 2.0
client credentials grant, using the values an admin copies from an
**External Client App**:

    Client ID      -> Consumer Key
    Client Secret  -> Consumer Secret

The app POSTs those to ``/services/oauth2/token`` and receives an access token
plus an instance URL. There is deliberately no username or password here: the
External Client App must have *Enable Client Credentials Flow* turned on and a
**Run As** user assigned, and Salesforce issues the token for that user.

Since client credentials tokens carry no refresh token, an expired token is
"refreshed" by requesting a new one with the same key/secret. That is wired
into ``simple-salesforce`` so an ``INVALID_SESSION_ID`` response is retried
automatically.

Secrets handling
----------------
The Consumer Secret is never written to ``st.session_state``, disk, or logs.
It lives only inside the ``Salesforce`` session object created here (via the
refresh closure) for as long as the connection exists.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests
from simple_salesforce import Salesforce

from permissions import escape_soql_literal

TOKEN_PATH = "/services/oauth2/token"
REQUEST_TIMEOUT = (10, 30)

# Login hosts. External Client Apps in a sandbox only accept test.salesforce.com
# (or the org's My Domain); mixing the two produces a misleading invalid_grant.
ENVIRONMENT_HOSTS = {
    "Production": "login.salesforce.com",
    "Sandbox": "test.salesforce.com",
}

API_VERSIONS = ("59.0", "60.0", "61.0", "62.0", "63.0", "64.0", "65.0", "66.0", "67.0", "68.0")

_MIN_TOKEN_LENGTH = 20


class _ErrorPageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._suppressed_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._suppressed_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._suppressed_tags:
            self._suppressed_tags.remove(tag)

    def handle_data(self, data: str) -> None:
        if not self._suppressed_tags:
            self.parts.append(data)


def _error_response_description(response: requests.Response) -> str:
    response_text = response.text.strip()
    if not response_text:
        return "No response body."

    content_type = response.headers.get("Content-Type", "").lower()
    is_html = "html" in content_type or response_text.lower().startswith(
        ("<!doctype html", "<html", "<head", "<body")
    )
    if is_html:
        parser = _ErrorPageTextParser()
        parser.feed(response_text[:10_000])
        response_text = " ".join(" ".join(parser.parts).split())
        if not response_text:
            return "The server returned an HTML error page."

    return response_text[:300]


class SalesforceAuthError(RuntimeError):
    """
    Authentication failure with an optional OAuth error code and a
    human-readable fix. The Configuration page renders ``hint`` directly,
    so keep these actionable and free of secrets.
    """

    def __init__(self, message: str, *, code: str | None = None, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


@dataclass(frozen=True)
class OAuthToken:
    """Result of a successful token request."""

    access_token: str
    instance_url: str
    identity_url: str | None
    issued_at: float
    scope: str | None
    login_host: str

    @property
    def instance_host(self) -> str:
        return urlparse(self.instance_url).hostname or self.instance_url


@dataclass(frozen=True)
class SalesforceConnection:
    """
    Everything the app needs after authenticating. ``sf`` goes into
    ``st.session_state["sf"]``; the rest is display and permission context.
    """

    sf: Salesforce
    username: str
    display_name: str
    user_id: str
    org_id: str
    instance_url: str
    environment: str
    api_version: str
    login_host: str
    authenticated_at: float


# ------------------------------------------------------------
# Token endpoint
# ------------------------------------------------------------
def resolve_login_host(environment: str, login_host: str | None = None) -> str:
    """
    Return the host to call for the token request. An explicit My Domain
    override wins over the Production/Sandbox shortcut.
    """
    if login_host and login_host.strip():
        host = login_host.strip()
        for prefix in ("https://", "http://"):
            if host.lower().startswith(prefix):
                host = host[len(prefix):]
        host = host.rstrip("/")
        if host.endswith(TOKEN_PATH):
            host = host[: -len(TOKEN_PATH)]
        if not host or "/" in host or " " in host:
            raise SalesforceAuthError(
                f"'{login_host}' is not a valid login host.",
                hint="Enter a bare host such as *login.salesforce.com* or "
                     "*mycompany.my.salesforce.com* — no path, no trailing slash.",
            )
        if not host.lower().endswith(".salesforce.com"):
            # The Consumer Secret is POSTed to whatever host is entered here.
            # My Domain hosts always live under salesforce.com — anything else
            # is a typo or a look-alike domain that would receive the secret.
            raise SalesforceAuthError(
                f"'{host}' is not a Salesforce domain.",
                hint="Your My Domain host ends in **.salesforce.com** — for "
                     "example *acme.my.salesforce.com* or "
                     "*acme--dev.sandbox.my.salesforce.com*. The Consumer "
                     "Secret is sent to this host, so never enter a domain "
                     "you don't recognise.",
            )
        return host

    try:
        return ENVIRONMENT_HOSTS[environment]
    except KeyError as exc:
        raise SalesforceAuthError(
            f"Unknown environment '{environment}'.",
            hint="Choose either **Production** or **Sandbox**.",
        ) from exc


def request_access_token(
    consumer_key: str,
    consumer_secret: str,
    *,
    environment: str = "Production",
    login_host: str | None = None,
    http: requests.Session | Any | None = None,
    timeout: Any = REQUEST_TIMEOUT,
) -> OAuthToken:
    """
    Exchange a Consumer Key/Secret for an access token using the
    client credentials grant.

    Raises SalesforceAuthError for anything the user can act on:
    bad key, flow not enabled, wrong environment, or network failure.
    """
    key = (consumer_key or "").strip()
    secret = (consumer_secret or "").strip()

    if not key or not secret:
        raise SalesforceAuthError(
            "Both the Consumer Key (Client ID) and the Consumer Secret "
            "(Client Secret) are required.",
            hint="Copy both values from the External Client App in Salesforce "
                 "Setup. The secret is shown only once at creation.",
        )
    if len(key) < _MIN_TOKEN_LENGTH:
        raise SalesforceAuthError(
            "That Consumer Key looks too short to be a Salesforce Client ID.",
            hint="Client IDs are long alphanumeric strings. Make sure you "
                 "copied the whole value and not the app name.",
        )

    host = resolve_login_host(environment, login_host)
    token_url = f"https://{host}{TOKEN_PATH}"
    payload = {
        "grant_type": "client_credentials",
        "client_id": key,
        "client_secret": secret,
    }

    try:
        response = (http or requests).post(
            token_url,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SalesforceAuthError(
            f"Could not reach the Salesforce token endpoint at {host}.",
            hint="Check your network connection, proxy, and the selected "
                 "environment (Production vs Sandbox).",
        ) from exc

    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        body = {}

    if response.status_code != 200 or "access_token" not in body:
        error_code = body.get("error") or f"HTTP_{response.status_code}"
        description = body.get("error_description") or (
            _error_response_description(response)
        )
        raise SalesforceAuthError(
            f"{error_code}: {description}",
            code=error_code,
            hint=_hint_for(error_code, host, description),
        )

    instance_url = str(body.get("instance_url") or "").rstrip("/")
    if not instance_url:
        raise SalesforceAuthError(
            "Salesforce returned a token without an instance URL.",
            hint="Retry the connection. If it persists, verify the External "
                 "Client App's OAuth settings and Run As user.",
        )

    try:
        issued_at = float(body.get("issued_at", 0)) / 1000 or time.time()
    except (TypeError, ValueError):
        issued_at = time.time()

    return OAuthToken(
        access_token=str(body["access_token"]),
        instance_url=instance_url,
        identity_url=body.get("id"),
        issued_at=issued_at,
        scope=body.get("scope"),
        login_host=host,
    )


def _hint_for(error_code: str, host: str, description: str = "") -> str:
    """Map OAuth error codes onto the actual Setup change that fixes them."""
    # Salesforce rejects the client credentials grant on the generic login
    # hosts ("request not supported on this domain"). The grant must be sent
    # to the org's own My Domain, which is also true for sandboxes:
    #   production: acme.my.salesforce.com
    #   sandbox:    acme--dev.sandbox.my.salesforce.com
    lowered = (description or "").lower()
    if "not supported on this domain" in lowered or "mydomain" in lowered:
        return (
            "Salesforce accepts the Client Credentials grant only on your org's "
            "**My Domain**, not on login.salesforce.com or test.salesforce.com. "
            "Open **Setup → Company Settings → My Domain**, copy the domain, and "
            "paste it into the **My Domain login host** field — for example "
            "*acme.my.salesforce.com* (production) or "
            "*acme--dev.sandbox.my.salesforce.com* (sandbox), then connect again."
        )

    if error_code.startswith("HTTP_"):
        # No OAuth JSON came back — Salesforce's edge returned an error page,
        # so the request never reached the token service. (Bad keys or a
        # disabled flow produce proper JSON errors like invalid_grant.) This
        # points at the host/org, not the credentials.
        return (
            f"Salesforce returned an error page (**{error_code.replace('_', ' ')}**) "
            "instead of an OAuth response, so the request never reached the "
            "token service. Double-check the **My Domain login host** — a typo, "
            "or a My Domain that isn't deployed yet, is the usual cause — and "
            "confirm the org isn't under maintenance, then try again."
        )

    hints = {
        "invalid_client_id": (
            "The Consumer Key doesn't match an External Client App in this org. "
            "Confirm the key, and that you selected the same environment the app "
            f"lives in (currently **{host}**)."
        ),
        "invalid_client": (
            "Salesforce rejected the Client ID/Secret pair. Regenerate the "
            "Consumer Secret in the External Client App and paste the new value."
        ),
        "invalid_grant": (
            "The key and secret are valid, but the app isn't allowed to use this "
            "flow. In the External Client App's OAuth settings, enable "
            "**Client Credentials Flow** and assign a **Run As** user who is "
            "active and has *API Enabled*. If both are already set, make sure the "
            "request goes to your My Domain (see the login host field)."
        ),
        "unsupported_grant_type": (
            "This External Client App doesn't permit the client credentials "
            "grant. Enable **Client Credentials Flow** on the app's OAuth "
            "settings, then retry."
        ),
        "invalid_scope": (
            "The requested scope isn't allowed for this app. Add the **api** "
            "scope (Manage user data via APIs) in the External Client App."
        ),
        "invalid_request": (
            "The token request was rejected. Verify the Consumer Key/Secret "
            "were copied without extra whitespace or line breaks."
        ),
    }
    return hints.get(
        error_code,
        "Verify the External Client App's Consumer Key/Secret and that Client "
        "Credentials Flow is enabled, then try again. "
        "Please double-check your domain login URL.",
    )


# ------------------------------------------------------------
# Session construction
# ------------------------------------------------------------
def _install_token_refresh(
    sf: Salesforce,
    *,
    consumer_key: str,
    consumer_secret: str,
    environment: str,
    login_host: str | None,
) -> None:
    """
    Client credentials tokens have no refresh token, so refreshing means
    re-running the grant. simple-salesforce calls this on INVALID_SESSION_ID.

    The returned instance host must match the original session, otherwise the
    stored base/metadata/tooling URLs would point at the wrong org; fail loudly
    in that (unexpected) case instead of silently mixing orgs.
    """
    expected_host = urlparse(sf.base_url).hostname
    lock = threading.Lock()
    # Circuit breaker: if a re-auth attempt just failed (revoked secret,
    # deactivated Run As user, …), simple-salesforce retries the API call up
    # to 3 times and pages make several calls — without this, every one of
    # them would POST the dead credentials to the token endpoint again.
    failure: dict[str, Any] = {"at": 0.0, "error": None}

    def refresh() -> tuple[str, str]:
        with lock:
            if failure["error"] is not None and time.time() - failure["at"] < 30:
                raise failure["error"]
            try:
                token = request_access_token(
                    consumer_key,
                    consumer_secret,
                    environment=environment,
                    login_host=login_host,
                )
            except SalesforceAuthError as exc:
                wrapped = SalesforceAuthError(
                    "Your Salesforce session expired and automatic "
                    f"re-authentication failed — {exc} Reconnect from the "
                    "Configuration page.",
                    code=exc.code,
                    hint=exc.hint,
                )
                failure["at"] = time.time()
                failure["error"] = wrapped
                raise wrapped from exc
            new_host = token.instance_host
            if expected_host and new_host != expected_host:
                raise SalesforceAuthError(
                    "Re-authentication returned a different Salesforce instance "
                    f"({new_host} instead of {expected_host}).",
                    hint="Reconnect from the Configuration page.",
                )
            failure["at"] = 0.0
            failure["error"] = None
            return token.access_token, new_host

    # Private attribute by design: this is exactly the hook simple-salesforce
    # uses to re-authenticate an expired session.
    sf._salesforce_login_partial = refresh


def _connect_salesforce(
    consumer_key: str,
    consumer_secret: str,
    *,
    environment: str,
    api_version: str,
    login_host: str | None,
) -> tuple[Salesforce, OAuthToken]:
    token = request_access_token(
        consumer_key,
        consumer_secret,
        environment=environment,
        login_host=login_host,
    )

    sf = Salesforce(
        instance_url=token.instance_url,
        session_id=token.access_token,
        version=api_version,
    )
    # Keeps session banners/identity output consistent with the old behaviour.
    sf.domain = "test" if environment == "Sandbox" else "login"

    _install_token_refresh(
        sf,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        environment=environment,
        login_host=login_host,
    )
    return sf, token


def _probe_access(sf: Salesforce, api_version: str = "") -> None:
    """
    One cheap call to prove the token can actually read the org. A Run As user
    without API access authenticates fine but fails every subsequent request.
    """
    try:
        sf.describe()
    except Exception as exc:
        hint = (
            "Give the External Client App's Run As user the **API Enabled** "
            "permission (and access to the objects you need), then retry."
        )
        if "404" in str(exc) or "notfound" in type(exc).__name__.lower():
            # A 404 here usually means the org doesn't know the selected API
            # version yet — don't send the user chasing permissions for that.
            hint = (
                f"The org answered 404 — API v{api_version or '?'} may not be "
                "supported by this org yet. Select a lower **API Version** on "
                "the Configuration page and reconnect. If the version is "
                "supported, then check: " + hint[0].lower() + hint[1:]
            )
        raise SalesforceAuthError(
            f"Authenticated, but the API call failed: {exc}",
            hint=hint,
        ) from exc


# ------------------------------------------------------------
# Identity
# ------------------------------------------------------------
def _parse_identity_url(identity_url: str | None) -> tuple[str | None, str | None]:
    """
    Identity URLs look like ``https://na1.salesforce.com/id/{orgId}/{userId}``.
    Return ``(org_id, user_id)``.
    """
    if not identity_url:
        return None, None
    parts = [p for p in urlparse(identity_url).path.split("/") if p]
    if "id" in parts:
        index = parts.index("id")
        rest = parts[index + 1:]
        if len(rest) >= 2:
            return rest[0], rest[1]
    return None, None


def _load_run_as_user(sf: Salesforce, token: OAuthToken) -> dict[str, str]:
    """Resolve the Run As user, with a last-resort Organization lookup so
    ``org_id`` is populated whenever the org is readable at all."""
    user = _resolve_run_as_user(sf, token)

    if not user.get("org_id"):
        # The identity URL is the usual org-id source; if it was missing or
        # unparseable, ask the org directly before giving up.
        try:
            result = sf.query("SELECT Id FROM Organization LIMIT 1")
            records = result.get("records") or []
            if records:
                user["org_id"] = records[0].get("Id") or ""
        except Exception:
            pass
    return user


def _resolve_run_as_user(sf: Salesforce, token: OAuthToken) -> dict[str, str]:
    """
    Resolve the user the token acts as. Client credentials has no interactive
    login, so this is the only way to learn who we are.

    Order: SOQL by user Id (authoritative) -> Chatter ``users/me`` ->
    identity URL -> placeholders.
    """
    org_id, user_id = _parse_identity_url(token.identity_url)
    user_id = user_id or ""
    org_id = org_id or ""

    if user_id:
        try:
            result = sf.query(
                "SELECT Id, Name, Username, Email, Profile.Name "
                "FROM User WHERE Id = '{}' LIMIT 1".format(
                    escape_soql_literal(user_id)
                )
            )
            records = result.get("records") or []
            if records:
                record = records[0]
                profile = record.get("Profile") or {}
                return {
                    "user_id": record.get("Id", user_id),
                    "username": record.get("Username") or "",
                    "display_name": record.get("Name") or "",
                    "email": record.get("Email") or "",
                    "profile_name": profile.get("Name") or "Unknown",
                    "org_id": org_id,
                }
        except Exception:
            pass  # Fall through to the lighter endpoints below.

    try:
        me = sf.restful("chatter/users/me", method="GET")
        if isinstance(me, dict) and me:
            return {
                "user_id": me.get("id") or user_id,
                "username": me.get("username") or "",
                "display_name": me.get("name") or "",
                "email": me.get("email") or "",
                "profile_name": "Unknown",
                "org_id": org_id,
            }
    except Exception:
        pass

    if token.identity_url:
        try:
            response = requests.get(
                token.identity_url,
                headers={"Authorization": f"Bearer {token.access_token}"},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                payload = response.json()
                return {
                    "user_id": payload.get("user_id") or user_id,
                    "username": payload.get("preferred_username") or payload.get("username") or "",
                    "display_name": payload.get("name") or "",
                    "email": payload.get("email") or "",
                    "profile_name": "Unknown",
                    "org_id": payload.get("organization_id") or org_id,
                }
        except Exception:
            pass

    return {
        "user_id": user_id,
        "username": "",
        "display_name": "Client Credentials (Run As user)",
        "email": "",
        "profile_name": "Unknown",
        "org_id": org_id,
    }


# ------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------
def connect(
    consumer_key: str,
    consumer_secret: str,
    *,
    environment: str = "Production",
    api_version: str = API_VERSIONS[-1],
    login_host: str | None = None,
) -> SalesforceConnection:
    """
    Authenticate with an External Client App and return a ready-to-use
    Salesforce session. Raises SalesforceAuthError on any user-fixable failure.
    """
    sf, token = _connect_salesforce(
        consumer_key,
        consumer_secret,
        environment=environment,
        api_version=api_version,
        login_host=login_host,
    )
    _probe_access(sf, api_version)
    user = _load_run_as_user(sf, token)

    return SalesforceConnection(
        sf=sf,
        username=user["username"],
        display_name=user["display_name"],
        user_id=user["user_id"],
        org_id=user["org_id"],
        instance_url=token.instance_url,
        environment=environment,
        api_version=api_version,
        login_host=token.login_host,
        authenticated_at=token.issued_at,
    )
