"""Where UPS credentials come from.

Resolution order, first hit wins:

  1. CLIENT_ID / CLIENT_SECRET        - upstream's names, honoured unchanged
  2. UPS_CLIENT_ID / UPS_CLIENT_SECRET - explicit override, and what CI uses
  3. Azure Key Vault                   - the normal path at Grundens

Key Vault is last in the list but first in practice: nobody sets the env vars by
hand. It is read with DefaultAzureCredential, which picks up whatever the
operator already has - `az login` in the normal case - so there is no per-user
credential step at all. Membership of sg-grundens-data-access plus a current
az login is the entire requirement, which is exactly what the NAV SQL servers
already need.

This deliberately replaces a design where a setup script synced the secrets into
Windows user environment variables. That worked, but it meant every operator had
to run setup before UPS did anything, and a bug in the sync could write an empty
value over a working credential and silently delete it. Reading the vault
directly removes both problems: there is nothing to sync and nothing to corrupt.

The vault call is best-effort. If it fails, the server still starts and the tools
still list; the first tool call raises with an actionable message. A server that
refuses to start is invisible in the host and tells the user nothing.
"""
import logging
import os
import threading

VAULT_NAME = os.getenv("UPS_KEY_VAULT", "kv-grus-dataaccess-prd")
CLIENT_ID_SECRET = os.getenv("UPS_CLIENT_ID_SECRET", "ups-client-id")
CLIENT_SECRET_SECRET = os.getenv("UPS_CLIENT_SECRET_SECRET", "ups-client-secret")

_lock = threading.Lock()
_cached = None          # (client_id, client_secret)
_vault_error = None     # why the vault lookup failed, for the error message


def _from_env():
    cid = os.getenv("CLIENT_ID") or os.getenv("UPS_CLIENT_ID")
    sec = os.getenv("CLIENT_SECRET") or os.getenv("UPS_CLIENT_SECRET")
    if cid and sec:
        return cid.strip(), sec.strip()
    return None


def _from_key_vault():
    """Read both secrets from Key Vault. Returns None and records why on failure.

    Uses AzureCliCredential specifically, NOT DefaultAzureCredential.

    DefaultAzureCredential walks a chain that includes managed-identity probes.
    On a developer laptop those endpoints do not exist, and the probe blocks for
    a long time before giving up - long enough that the first UPS tool call
    appears to hang rather than fail. Measured that the hard way.

    AzureCliCredential is also simply the honest description of the requirement:
    operators authenticate with `az login`, exactly as they already do for the
    NAV SQL servers. If that is not present, failing in a second with a message
    saying "run az login" beats stalling for a minute and then saying it.
    """
    global _vault_error
    try:
        from azure.identity import AzureCliCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as exc:
        _vault_error = f"azure-identity/azure-keyvault-secrets not installed ({exc})"
        return None

    # The Azure SDK logs every request and every response header at INFO. In a
    # stdio MCP server that is at best noise in the host log, and at worst a way
    # for library output to reach a stream that must carry only JSON-RPC. It also
    # echoes request ids and vault URLs, which nobody needs by default.
    for name in ("azure", "azure.core.pipeline.policies.http_logging_policy",
                 "azure.identity"):
        logging.getLogger(name).setLevel(logging.WARNING)

    try:
        credential = AzureCliCredential(process_timeout=20)
        client = SecretClient(
            vault_url=f"https://{VAULT_NAME}.vault.azure.net",
            credential=credential,
            connection_timeout=10,
            read_timeout=20,
            retry_total=1,
        )
        cid = client.get_secret(CLIENT_ID_SECRET).value
        sec = client.get_secret(CLIENT_SECRET_SECRET).value
        if not cid or not sec:
            _vault_error = f"{VAULT_NAME} returned an empty value"
            return None
        return cid.strip(), sec.strip()
    except Exception as exc:  # noqa: BLE001 - any failure here is the same to the caller
        _vault_error = f"{type(exc).__name__}: {exc}"
        return None


def get_credentials():
    """Resolve once per process, then reuse."""
    global _cached
    if _cached is not None:
        return _cached
    with _lock:
        if _cached is not None:
            return _cached
        found = _from_env() or _from_key_vault()
        if found:
            _cached = found
        return found


def failure_message():
    """What to tell the user when nothing resolved.

    This is the entire onboarding path: the server starts and lists its tools
    without credentials, so the first tool call is where anyone discovers there
    is a problem. Name the remedy, not just the symptom.
    """
    detail = f" Key Vault lookup failed with: {_vault_error}." if _vault_error else ""
    return (
        f"No UPS credentials. They are read from Azure Key Vault '{VAULT_NAME}' "
        f"using your existing Azure sign-in.{detail} "
        "Fix: run 'az login', and make sure you are in the sg-grundens-data-access "
        "group, then restart Claude Desktop. Setting UPS_CLIENT_ID and "
        "UPS_CLIENT_SECRET in your environment also works as an override."
    )
