"""Coverage, caching, and reference tracking.

History worth keeping: an earlier version of this file asserted that non-US/PR
countries were sent as "regional" requests, on the theory that this was how UPS
covered Canada. That was wrong. Against production, every non-US/PR country code
returns 264008 in every payload shape, including a request carrying nothing but
{"CountryCode": "CA"}. The tests now pin the real behaviour: validation refuses
those countries up front, and tracking is unaffected.
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from ups_mcp import cache, constants
from ups_mcp.tools import ToolManager


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.responses._data.clear()
    yield
    cache.responses._data.clear()


def _manager():
    with patch("ups_mcp.tools.OAuthManager") as oauth:
        oauth.return_value.get_access_token.return_value = "test-token"
        return ToolManager(base_url=constants.CIE_URL, client_id="id", client_secret="secret")


def _validate(**overrides):
    kwargs = dict(
        addressLine1="123 Main St", addressLine2="", politicalDivision1="NY",
        politicalDivision2="New York", zipPrimary="10001", zipExtended="",
        urbanization="", countryCode="US",
    )
    kwargs.update(overrides)

    response = MagicMock()
    response.status_code = 200
    response.text = json.dumps({"XAVResponse": {}})

    with patch("ups_mcp.tools.requests.post", return_value=response) as post:
        _manager().validate_address(**kwargs)

    _, call_kwargs = post.call_args
    return {
        "url": post.call_args[0][0],
        "params": call_kwargs["params"],
        "address": call_kwargs["json"]["XAVRequest"]["AddressKeyFormat"],
    }


# --- coverage: US and PR only ------------------------------------------------

@pytest.mark.parametrize("country", ["US", "PR", "us", " Pr "])
def test_supported_countries_are_accepted(country):
    assert _validate(countryCode=country)["address"]["CountryCode"] == country.strip().upper()


@pytest.mark.parametrize("country", ["CA", "GB", "MX", "DE", "FR", "NL", ""])
def test_unsupported_countries_fail_before_calling_ups(country):
    """A clear refusal beats forwarding a request that always returns 264008."""
    with patch("ups_mcp.tools.requests.post") as post:
        with pytest.raises(ValueError, match="does not support country"):
            _manager().validate_address(
                addressLine1="100 Queen St W", addressLine2="", politicalDivision1="ON",
                politicalDivision2="Toronto", zipPrimary="M5H 2N2", zipExtended="",
                urbanization="", countryCode=country,
            )
        post.assert_not_called()


def test_the_refusal_names_the_supported_countries():
    with pytest.raises(ValueError) as exc:
        _manager().validate_address(
            addressLine1="", addressLine2="", politicalDivision1="", politicalDivision2="",
            zipPrimary="", zipExtended="", urbanization="", countryCode="CA",
        )
    assert "PR" in str(exc.value) and "US" in str(exc.value)


# --- request shape -----------------------------------------------------------

def test_street_address_is_sent():
    assert _validate(addressLine1="20 W 34th St", addressLine2="Apt 4B")["address"]["AddressLine"] \
        == ["20 W 34th St", "Apt 4B"]


def test_zip_extension_is_us_only():
    assert "PostcodeExtendedLow" in _validate(countryCode="US", zipExtended="1521")["address"]
    assert "PostcodeExtendedLow" not in _validate(
        countryCode="PR", zipExtended="1521", politicalDivision1="PR")["address"]


def test_urbanization_is_puerto_rico_only():
    assert "Urbanization" in _validate(countryCode="PR", urbanization="porto arundal")["address"]
    assert "Urbanization" not in _validate(countryCode="US", urbanization="porto arundal")["address"]


def test_uses_v2_not_the_deprecated_v1():
    assert "/addressvalidation/v2/" in _validate()["url"]


def test_defaults_to_validation_plus_classification():
    assert _validate()["url"].endswith(f"/{constants.REQUEST_OPTION_BOTH}")


# --- caching -----------------------------------------------------------------

def _tracking_payload(status_code=None, warning=False):
    if warning:
        shipment = {"inquiryNumber": "1Z", "warnings": [{"code": "TW0001",
                                                         "message": "Tracking Information Not Found"}]}
    else:
        shipment = {"inquiryNumber": "1Z",
                    "package": [{"currentStatus": {"statusCode": status_code}}]}
    return json.dumps({"trackResponse": {"shipment": [shipment]}})


def test_a_repeated_lookup_does_not_hit_ups_twice():
    """The shared rate limit is the reason this matters."""
    response = MagicMock()
    response.status_code = 200
    response.text = _tracking_payload("011")

    mgr = _manager()
    with patch("ups_mcp.tools.requests.get", return_value=response) as get:
        first = mgr.track_package("1Z999", "en_US", False, True, False)
        second = mgr.track_package("1Z999", "en_US", False, True, False)

    assert first == second
    assert get.call_count == 1


def test_different_tracking_numbers_are_cached_separately():
    response = MagicMock()
    response.status_code = 200
    response.text = _tracking_payload("011")

    mgr = _manager()
    with patch("ups_mcp.tools.requests.get", return_value=response) as get:
        mgr.track_package("1Z111", "en_US", False, True, False)
        mgr.track_package("1Z222", "en_US", False, True, False)

    assert get.call_count == 2


def test_delivered_packages_are_cached_for_a_long_time():
    """A delivered package is finished; its history will never change."""
    assert cache.tracking_ttl(_tracking_payload("011")) == cache.TTL_TERMINAL


def test_in_transit_packages_get_a_short_ttl():
    assert cache.tracking_ttl(_tracking_payload("021")) == cache.TTL_IN_TRANSIT


def test_not_found_is_barely_cached_at_all():
    """TW0001 means the label exists but UPS has not scanned it yet. That flips
    within hours, and a stale negative would read as a lost package."""
    assert cache.tracking_ttl(_tracking_payload(warning=True)) == cache.TTL_NOT_FOUND


def test_malformed_response_does_not_blow_up_the_ttl_choice():
    assert cache.tracking_ttl("not json") == cache.TTL_IN_TRANSIT


# --- track_by_reference ------------------------------------------------------

def _reference_call(**kwargs):
    response = MagicMock()
    response.status_code = 200
    response.text = _tracking_payload("011")

    with patch("ups_mcp.tools.requests.get", return_value=response) as get:
        _manager().track_by_reference(**kwargs)

    return {"url": get.call_args[0][0], "params": get.call_args[1]["params"]}


def test_reference_lookup_uses_the_reference_endpoint():
    assert _reference_call(reference="SP-327741-2")["url"].endswith(
        "/api/track/v1/reference/details/SP-327741-2")


def test_optional_filters_are_omitted_when_not_supplied():
    """Sending empty filters would narrow the search to nothing."""
    params = _reference_call(reference="SP-327741-2")["params"]
    for key in ("destCountry", "destZip", "shipperNum", "fromPickUpDate", "toPickUpDate"):
        assert key not in params


def test_missing_credentials_tell_the_user_what_to_do():
    """The first tool call is where a user discovers anything is wrong.

    The server starts and lists its tools without credentials, which is the good
    failure mode, but it means this string is the entire onboarding experience.
    Credentials come from Key Vault via the operator's Azure sign-in, so the
    remedy is 'az login' and group membership - not anything they set by hand.
    """
    from ups_mcp import credentials
    from ups_mcp.authorization import OAuthManager

    mgr = OAuthManager(token_url="https://example.invalid/token",
                       client_id="", client_secret="")

    # No env credentials, and the vault unreachable.
    with patch.object(credentials, "_from_env", return_value=None), \
         patch.object(credentials, "_from_key_vault", return_value=None), \
         patch.object(credentials, "_cached", None):
        with pytest.raises(ValueError) as exc:
            mgr.get_access_token()

    msg = str(exc.value)
    assert "az login" in msg, "the error must name the remedy, not just the symptom"
    assert "sg-grundens-data-access" in msg
    assert "Key Vault" in msg


def test_environment_credentials_win_over_the_vault():
    """An explicit override must not be silently ignored, and CI relies on it."""
    from ups_mcp import credentials

    with patch.dict(os.environ, {"UPS_CLIENT_ID": "env-id", "UPS_CLIENT_SECRET": "env-sec"}), \
         patch.object(credentials, "_cached", None), \
         patch.object(credentials, "_from_key_vault") as vault:
        assert credentials.get_credentials() == ("env-id", "env-sec")
        vault.assert_not_called()


def test_supplied_filters_are_passed_through():
    params = _reference_call(reference="SP-327741-2", shipperNum="5Y7584",
                             destCountry="ca", fromPickUpDate="20260701")["params"]
    assert params["shipperNum"] == "5Y7584"
    assert params["destCountry"] == "CA"      # normalised; UPS wants ISO2 upper
    assert params["fromPickUpDate"] == "20260701"
