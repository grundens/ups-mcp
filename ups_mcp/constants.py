CIE_URL = "https://wwwcie.ups.com"
PRODUCTION_URL = "https://onlinetools.ups.com"

# Address Validation API version. v1 is marked deprecated in UPS's current
# OpenAPI spec. v2 also normalises the response: Candidate is always an array,
# where v1 returns a bare object when there is exactly one match.
ADDRESS_VALIDATION_VERSION = "v2"

# Countries/territories where UPS validates at STREET level, against the USPS
# database. Everywhere else, street-level validation returns nothing useful and
# the request must set regionalrequestindicator=True to validate at the
# city / political-division / postal-code level instead.
STREET_LEVEL_COUNTRIES = frozenset({"US", "PR"})

# requestoption path segment on /addressvalidation/{version}/{requestoption}:
#   1 - Address Validation
#   2 - Address Classification (residential vs commercial; US and CA)
#   3 - both
REQUEST_OPTION_VALIDATION = 1
REQUEST_OPTION_CLASSIFICATION = 2
REQUEST_OPTION_BOTH = 3
