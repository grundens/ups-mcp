from typing import Any
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import os
from . import tools
from . import constants

# Initialize FastMCP server
mcp = FastMCP("ups-mcp")

# Initialize tool manager
load_dotenv()
if (os.getenv("ENVIRONMENT") or os.getenv("UPS_ENVIRONMENT")) == "production":
    base_url = constants.PRODUCTION_URL
else:
    base_url = constants.CIE_URL

# Credentials resolve from the environment first, then Azure Key Vault. See
# credentials.py for why, and for what the failure message has to say.
#
# Resolution is deliberately deferred to first use rather than done here: a
# vault round-trip at import would add latency to every launch, and a failure
# would stop the server attaching at all. A server that does not attach is
# invisible in the host; one that attaches and returns a clear error on first
# call tells the user exactly what to fix.
tool_manager = tools.ToolManager(base_url=base_url)

@mcp.tool()
async def track_package(inquiryNumber: str, locale:str="en_US", returnSignature:bool=False, returnMilestones:bool=False, returnPOD:bool=False) -> str:
    """
    The Track API retrieves current status of shipments such as Small Package 1Z, Infonotice, Mail Innovations, FGV, or UPS Freight shipments
    using the inquiry number. The tracking response data typically includes package movements/activities, destination UPS access point
    information, expected delivery dates/times, etc. The response returns an array of shipment objects containing detailed tracking information 
    and status for the package(s) associated with the inquiryNumber, including current status, activity history, delivery details, package details, and more.
    
    Args:
        inquiryNumber (str): the unique package identifier. Each inquiry number must be between 7 and 34 characters in length. Required.
        locale (str): Language and country code of the user, separated by an underscore. Default value is 'en_US'. Not required.
        returnSignature (bool): a boolean to indicate whether a signature is required, default is false. Not required.
        returnMilestones (bool): a boolean to indicate whether detailed information on a package's movements is required, default is false. Not required
        returnPOD (bool): a boolean to indicate whether a proof of delivery is required, default is false. Not required

    Returns:
        str: The response from the tracking capability, this is a string of json tracking data.
    """
    tracking_data = tool_manager.track_package(inquiryNum=inquiryNumber, locale=locale, returnSignature=returnSignature, returnMilestones=returnMilestones, returnPOD=returnPOD)

    return tracking_data

@mcp.tool()
async def track_by_reference(reference: str, fromPickUpDate: str="", toPickUpDate: str="", destCountry: str="", destZip: str="", shipperNum: str="", locale: str="en_US") -> str:
    """
    Find UPS shipments by a SHIPPER-ASSIGNED reference number instead of a 1Z tracking number.

    Use this when you have an internal order or shipment number and do NOT have the tracking
    number - it saves looking the tracking number up first. If you already have a 1Z number,
    use track_package instead.

    Works for any destination country, Canada included.

    IMPORTANT - the reference must be the one the shipper actually sent to UPS, which is not
    always the number you would expect:
    - At Grundens, the Holman warehouse sends the NAV *leg* number, e.g. "SP-327741-2".
      The base order number "SP-327741" does NOT match, and neither does the NAV shipment
      number ("SSH+..."). Try the leg suffixes.
    - Shipments from the TAC warehouse are not currently findable this way; TAC does not
      appear to send a reference. Fall back to looking up the tracking number and using
      track_package.
    A reference that was never sent to UPS returns "Tracking Information Not Found" rather
    than an error, so a miss is indistinguishable from a wrong reference. Try the variants
    before concluding the shipment does not exist.

    Args:
        reference (str): The shipper-assigned reference, e.g. an order or leg number. Required.
        fromPickUpDate (str): Start of the search window, YYYYMMDD. UPS defaults to 14 days ago, so set this explicitly for anything older or the shipment will appear not to exist. Optional.
        toPickUpDate (str): End of the search window, YYYYMMDD. Defaults to today. Optional.
        destCountry (str): Two-letter destination country code to narrow the search, e.g. CA. Note this is ISO2; systems that store ISO3 ("CAN") must convert. Optional.
        destZip (str): Destination postal code to narrow the search. Optional.
        shipperNum (str): UPS shipper (account) number to narrow the search. Optional.
        locale (str): Language and country code, e.g. en_US. Optional.

    Returns:
        str: JSON tracking data in the same shape as track_package, potentially covering several
        shipments if the reference matches more than one. A response carrying a 'warnings' entry
        with code TW0001 means no shipment matched the reference within the date window.
    """
    return tool_manager.track_by_reference(
        reference=reference, fromPickUpDate=fromPickUpDate, toPickUpDate=toPickUpDate,
        destCountry=destCountry, destZip=destZip, shipperNum=shipperNum, locale=locale,
    )

@mcp.tool()
async def validate_address(addressLine1: str, politicalDivision1: str, politicalDivision2: str, zipPrimary: str, countryCode: str, addressLine2: str="", urbanization: str="", zipExtended: str="", requestOption: int=constants.REQUEST_OPTION_BOTH) -> str:
    """
    Validates a US or Puerto Rico shipping address against the USPS database, and
    classifies it as residential or commercial.

    IMPORTANT - COVERAGE. This tool works for the United States and Puerto Rico ONLY.
    Every other country, Canada included, is rejected by UPS. Verified against UPS
    production: CA, GB, MX, DE, FR and NL all return error 264008 regardless of how the
    request is phrased. Calling this for a non-US/PR address raises an error rather than
    returning a result.

    Do not offer this tool as a way to check a Canadian or international address, and do
    not suggest rephrasing the address to get around the restriction - there is no
    phrasing that works. Recommend a different address-validation provider instead.

    This restriction is specific to address validation. TRACKING works worldwide, Canada
    included, so do not generalise this limit to track_package or track_by_reference.

    Note that UPS's own published appendix lists 42 countries as supporting
    residential/commercial classification. That is not deliverable through this endpoint,
    whatever else it may apply to.

    Args:
        addressLine1 (str): The primary address details including the house or building number and the street name, e.g. 123 Main St. Required.
        addressLine2 (str): Additional information like apartment or suite numbers. E.g. Apt 4B. Optional.
        politicalDivision1 (str): The two-letter state code, e.g. GA for Georgia. Required.
        politicalDivision2 (str): The city or town name, e.g. Springfield. Required.
        zipPrimary (str): The postal code. Required.
        zipExtended (str): 4 digit Postal Code extension. US only. Optional.
        urbanization (str): Puerto Rico Political Division 3. Puerto Rico only. Optional.
        countryCode (str): The two-letter country code. Must be US or PR. Required.
        requestOption (int): 1 = validation only, 2 = classification only, 3 = both (default).

    Returns:
        str: A JSON response containing address validation results. The response includes one of three indicators:
        - ValidAddressIndicator: Address is valid. Contains a 'Candidate' array with the corrected and standardized address, including normalized formatting and ZIP+4.
        - AmbiguousAddressIndicator: Multiple possible address matches found. Review candidates to select the correct address.
        - NoCandidatesIndicator: The address is not in the USPS database. Note this is also what a valid address returns when the street line is missing, since matching is street-level.

        May also include AddressClassification with Code 0 (UnClassified), 1 (Commercial) or 2 (Residential).

        NOTE: in the UPS Customer Integration Environment (ENVIRONMENT=test), validation
        only returns results for New York and California. Every other state returns error
        9264030. That is a test-environment limit, not a bad address, and it does not
        occur in production.
    """
    validation_data = tool_manager.validate_address(addressLine1=addressLine1, addressLine2=addressLine2, politicalDivision1=politicalDivision1, politicalDivision2=politicalDivision2, zipPrimary=zipPrimary, zipExtended=zipExtended, urbanization=urbanization, countryCode=countryCode, requestOption=requestOption)

    return validation_data

def main():
    print("Starting UPS MCP Server...")
    try:
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()