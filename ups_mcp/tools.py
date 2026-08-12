import requests
from requests.auth import HTTPBasicAuth
import os
import uuid
import json
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
        # UPS exposes two validation modes on the same endpoint, and which one is
        # usable depends entirely on the country:
        #
        #   street level (regionalrequestindicator=False) - validates AddressLine
        #       against the USPS database. US and PR ONLY. Sending a non-US/PR
        #       address here is what makes callers conclude "UPS does not do Canada".
        #
        #   regional (regionalrequestindicator=True) - validates the city /
        #       political division / postal code combination. Works internationally,
        #       including CA. AddressLine is ignored by UPS in this mode, so it is
        #       omitted rather than sent and silently dropped.
        #
        # The mode is chosen from countryCode instead of being hardcoded, so US and
        # PR keep exactly the behaviour they had and everywhere else stops failing.
        country = (countryCode or "").strip().upper()
        regional = country not in constants.STREET_LEVEL_COUNTRIES

        url = f"{self.base_url}/api/addressvalidation/{constants.ADDRESS_VALIDATION_VERSION}/{requestOption}"

        query = {
            "regionalrequestindicator": regional,
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

        if not regional:
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

        response = requests.post(url, headers=headers, params=query, json=address_payload)

        if response.status_code != 200:
            raise ValueError(f"Error validating address: {response.status_code} {response.text}")

        response = response.text

        return str(response)

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

        response = requests.get(url, headers=headers, params=query)

        if response.status_code != 200:
            raise ValueError(f"Error tracking package: {response.text}")

        response = response.text

        return str(response)