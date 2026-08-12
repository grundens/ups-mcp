CIE_URL = "https://wwwcie.ups.com"
PRODUCTION_URL = "https://onlinetools.ups.com"

# Address Validation API version. v1 is marked deprecated in UPS's current
# OpenAPI spec. v2 also normalises the response: Candidate is always an array,
# where v1 returns a bare object when there is exactly one match.
ADDRESS_VALIDATION_VERSION = "v2"

# The ONLY countries this endpoint accepts. Verified empirically against
# production on 2026-08-12: every other country code returns
#   264008 "Country code and address format combination is not allowed"
# in every payload shape tried, including a request carrying nothing but
# {"CountryCode": "CA"}. CA, GB, MX, DE, FR and NL were all tested; all failed.
#
# This contradicts UPS's own Address Validation appendix, which lists 42
# countries under "Residential / Commercial Classification". Whatever delivers
# that classification, it is not this endpoint. Note the appendix's other
# column, "Street Level Validation", is marked for US and PR only, which does
# match observed behaviour.
SUPPORTED_COUNTRIES = frozenset({"US", "PR"})

# requestoption path segment on /addressvalidation/{version}/{requestoption}:
#   1 - Address Validation
#   2 - Address Classification (residential vs commercial)
#   3 - both
# Option 3 confirmed working against production and CIE: a US response carries
# AddressClassification alongside the validated Candidate.
REQUEST_OPTION_VALIDATION = 1
REQUEST_OPTION_CLASSIFICATION = 2
REQUEST_OPTION_BOTH = 3
