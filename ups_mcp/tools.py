import requests
from requests.auth import HTTPBasicAuth
import os
import uuid
import json
from . import cache
from . import constants
from .authorization import OAuthManager
from dotenv import load_dotenv

class ToolManager:
    def __init__(self, base_url, client_id, client_secret):
        self.base_url = base_url

        self.token_manager = OAuthManager(
            token_url=f"{self.base_url}/security/v1/oauth/token",
            client_id=client_id,
            client_secret=client_secret
        )

    def validate_address(self, addressLine1: str, addressLine2: str, politicalDivision1: str, politicalDivision2: str, zipPrimary: str, zipExtended: str, urbanization: str, countryCode: str, requestOption: int = constants.REQUEST_OPTION_BOTH, maximumCandidateListSize: int = 3):
        # This endpoint accepts US and PR only. Everything else is rejected by UPS
        # with 264008 "Country code and address format combination is not allowed",
        # regardless of payload shape or the regionalrequestindicator flag - see
        # constants.SUPPORTED_COUNTRIES for the evidence.
        #
        # Failing here rather than forwarding the request is deliberate: the raw
        # UPS error reads like a malformed payload and sends the reader looking
        # for a bug in their address, when the real answer is that the country is
        # not covered at all.
        country = (countryCode or "").strip().upper()
        if country not in constants.SUPPORTED_COUNTRIES:
            raise ValueError(
                f"UPS address validation does not support country '{country}'. "
                f"This endpoint covers {', '.join(sorted(constants.SUPPORTED_COUNTRIES))} only "
                f"(verified against UPS production; every other country code returns error "
                f"264008). Use a different address-validation provider for this address."
            )

        url = f"{self.base_url}/api/addressvalidation/{constants.ADDRESS_VALIDATION_VERSION}/{requestOption}"

        query = {
            "regionalrequestindicator": False,
            "maximumcandidatelistsize": maximumCandidateListSize
        }

        token = self.token_manager.get_access_token()

        headers = {
            "transId": str(uuid.uuid4()),
            "transactionSrc": "Local MCP Server",
            "Authorization": f"Bearer {token}"
        }

        addressKeyFormat = {
            "PoliticalDivision2": politicalDivision2,
            "PoliticalDivision1": politicalDivision1,
            "PostcodePrimaryLow": zipPrimary,
            "CountryCode": country
        }

        addressLineList = [addressLine1] if addressLine1 else []

        if addressLine2:
            addressLineList.append(addressLine2)

        if addressLineList:
            addressKeyFormat["AddressLine"] = addressLineList

        # Urbanization is Puerto Rico's political division 3 and is rejected
        # elsewhere. PostcodeExtendedLow is the US-only ZIP+4 extension.
        if urbanization and country == "PR":
            addressKeyFormat["Urbanization"] = urbanization

        if zipExtended and country == "US":
            addressKeyFormat["PostcodeExtendedLow"] = zipExtended

        address_payload = {
            "XAVRequest": {
                "AddressKeyFormat": addressKeyFormat
            }
        }

        # USPS address data barely moves, and the same address gets re-checked a
        # lot inside one session. Key on the payload so any changed field misses.
        cache_key = cache.key("xav", self.base_url, requestOption,
                              json.dumps(addressKeyFormat, sort_keys=True))
        cached = cache.responses.get(cache_key)
        if cached is not None:
            return cached

        response = requests.post(url, headers=headers, params=query, json=address_payload)

        if response.status_code != 200:
            raise ValueError(f"Error validating address: {response.status_code} {response.text}")

        result = str(response.text)
        cache.responses.put(cache_key, result, cache.TTL_ADDRESS)
        return result

    def track_package(self, inquiryNum: str, locale: str, returnSignature: bool, returnMilestones: bool, returnPOD: bool):
        url = f"{self.base_url}/api/track/v1/details/{inquiryNum}"

        query = {
            "locale": locale,
            "returnSignature": returnSignature,
            "returnMilestones": returnMilestones,
            "returnPOD": returnPOD
        }

        token = self.token_manager.get_access_token()

        headers = {
            "transId": str(uuid.uuid4()),
            "transactionSrc": "Local MCP Server",
            "Authorization": f"Bearer {token}"
        }

        cache_key = cache.key("track", self.base_url, inquiryNum, locale,
                              returnSignature, returnMilestones, returnPOD)
        cached = cache.responses.get(cache_key)
        if cached is not None:
            return cached

        response = requests.get(url, headers=headers, params=query)

        if response.status_code != 200:
            raise ValueError(f"Error tracking package: {response.text}")

        result = str(response.text)
        # TTL is read off the response: delivered packages are final, in-transit
        # ones are not, and an unscanned label must not be cached as "not found".
        cache.responses.put(cache_key, result, cache.tracking_ttl(result))
        return result

    def track_by_reference(self, reference: str, fromPickUpDate: str = "", toPickUpDate: str = "",
                           destCountry: str = "", destZip: str = "", shipperNum: str = "",
                           refNumType: str = "SmallPackage", locale: str = "en_US"):
        """Track by a shipper-assigned reference (e.g. a NAV order number) rather than a 1Z number."""
        url = f"{self.base_url}/api/track/v1/reference/details/{reference}"

        query = {"locale": locale, "refNumType": refNumType}

        # UPS defaults the search window to the last 14 days. That silently hides
        # anything older, which reads as "no such shipment" rather than "outside
        # the window", so the caller is given the lever explicitly.
        if fromPickUpDate:
            query["fromPickUpDate"] = fromPickUpDate
        if toPickUpDate:
            query["toPickUpDate"] = toPickUpDate
        if destCountry:
            query["destCountry"] = destCountry.strip().upper()
        if destZip:
            query["destZip"] = destZip
        if shipperNum:
            query["shipperNum"] = shipperNum

        token = self.token_manager.get_access_token()

        headers = {
            "transId": str(uuid.uuid4()),
            "transactionSrc": "Local MCP Server",
            "Authorization": f"Bearer {token}"
        }

        cache_key = cache.key("trackref", self.base_url, reference,
                              json.dumps(query, sort_keys=True))
        cached = cache.responses.get(cache_key)
        if cached is not None:
            return cached

        response = requests.get(url, headers=headers, params=query)

        if response.status_code != 200:
            raise ValueError(f"Error tracking by reference: {response.status_code} {response.text}")

        result = str(response.text)
        cache.responses.put(cache_key, result, cache.tracking_ttl(result))
        return result