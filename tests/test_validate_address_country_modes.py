"""What UPS actually receives, per country.

There are no live credentials in CI, and the UPS test environment only returns
street-level results for New York and California, so an integration test would
prove nothing about Canada. These tests instead pin the request that leaves the
process: the URL, the regionalrequestindicator flag, and the payload keys.

The regression they exist to catch is the original hardcoded
regionalrequestindicator=False, which silently sent every non-US/PR address down
the street-level path that only works for the US and Puerto Rico.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from ups_mcp import constants
from ups_mcp.tools import ToolManager


def _manager():
    with patch("ups_mcp.tools.OAuthManager") as oauth:
        oauth.return_value.get_access_token.return_value = "test-token"
        return ToolManager(
            base_url=constants.CIE_URL,
            client_id="id",
            client_secret="secret",
        )


def _call(**overrides):
    """Run validate_address against a mocked transport and return the request."""
    kwargs = dict(
        addressLine1="123 Main St",
        addressLine2="",
        politicalDivision1="NY",
        politicalDivision2="New York",
        zipPrimary="10001",
        zipExtended="",
        urbanization="",
        countryCode="US",
    )
    kwargs.update(overrides)

    manager = _manager()

    response = MagicMock()
    response.status_code = 200
    response.text = json.dumps({"XAVResponse": {}})

    with patch("ups_mcp.tools.requests.post", return_value=response) as post:
        manager.validate_address(**kwargs)

    assert post.call_count == 1
    _, call_kwargs = post.call_args
    return {
        "url": post.call_args[0][0],
        "params": call_kwargs["params"],
        "address": call_kwargs["json"]["XAVRequest"]["AddressKeyFormat"],
    }


# --- the mode is chosen from the country, not hardcoded ----------------------

@pytest.mark.parametrize("country", ["US", "PR", "us", " Us "])
def test_street_level_countries_do_not_set_the_regional_flag(country):
    req = _call(countryCode=country)
    assert req["params"]["regionalrequestindicator"] is False


@pytest.mark.parametrize("country", ["CA", "ca", "GB", "MX", "DE"])
def test_every_other_country_sets_the_regional_flag(country):
    req = _call(countryCode=country, politicalDivision1="ON",
                politicalDivision2="Toronto", zipPrimary="M5H 2N2")
    assert req["params"]["regionalrequestindicator"] is True


# --- AddressLine is only meaningful at street level --------------------------

def test_us_sends_the_street_address():
    req = _call(addressLine1="123 Main St", addressLine2="Apt 4B")
    assert req["address"]["AddressLine"] == ["123 Main St", "Apt 4B"]


def test_canada_omits_the_street_address_rather_than_sending_it_to_be_ignored():
    req = _call(countryCode="CA", addressLine1="100 Queen St W",
                politicalDivision1="ON", politicalDivision2="Toronto",
                zipPrimary="M5H 2N2")
    assert "AddressLine" not in req["address"]
    assert req["address"]["PoliticalDivision1"] == "ON"
    assert req["address"]["PoliticalDivision2"] == "Toronto"
    assert req["address"]["PostcodePrimaryLow"] == "M5H 2N2"


# --- country-specific fields stay in their own country -----------------------

def test_zip_extension_is_us_only():
    assert "PostcodeExtendedLow" in _call(countryCode="US", zipExtended="1521")["address"]
    assert "PostcodeExtendedLow" not in _call(
        countryCode="CA", zipExtended="1521", politicalDivision1="ON",
        politicalDivision2="Toronto", zipPrimary="M5H 2N2")["address"]


def test_urbanization_is_puerto_rico_only():
    assert "Urbanization" in _call(countryCode="PR", urbanization="porto arundal")["address"]
    assert "Urbanization" not in _call(countryCode="CA", urbanization="porto arundal",
                                       politicalDivision1="ON")["address"]


# --- endpoint shape ----------------------------------------------------------

def test_uses_v2_not_the_deprecated_v1():
    assert "/addressvalidation/v2/" in _call()["url"]
    assert "/addressvalidation/v1/" not in _call()["url"]


def test_defaults_to_validation_plus_classification():
    assert _call()["url"].endswith(f"/{constants.REQUEST_OPTION_BOTH}")


def test_request_option_is_overridable_for_countries_that_reject_classification():
    url = _call(requestOption=constants.REQUEST_OPTION_VALIDATION)["url"]
    assert url.endswith(f"/{constants.REQUEST_OPTION_VALIDATION}")


def test_country_code_is_normalised_in_the_payload():
    assert _call(countryCode=" ca ")["address"]["CountryCode"] == "CA"
