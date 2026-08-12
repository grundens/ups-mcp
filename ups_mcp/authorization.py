import requests
import time

class OAuthManager:
    def __init__(self, token_url, client_id, client_secret):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expiry = 0

    def get_access_token(self):
        # If token is still valid, return it
        if self.access_token and time.time() < self.token_expiry - 60:
            return self.access_token

        # Resolve credentials at the last possible moment.
        #
        # Not at import: a Key Vault round-trip there would slow every launch and,
        # worse, a vault failure would stop the server attaching to the host at
        # all. An MCP server that fails to attach is invisible - no tools, no
        # error, nothing to act on. Attaching and failing here means the user gets
        # the message below, which names the fix.
        if not self.client_id or not self.client_secret:
            from . import credentials
            found = credentials.get_credentials()
            if found:
                self.client_id, self.client_secret = found

        if not self.client_id or not self.client_secret:
            from . import credentials
            raise ValueError(credentials.failure_message())

        data = {
            "grant_type": "client_credentials"
        }

        response = requests.post(
            self.token_url,
            data=data,
            auth=(self.client_id, self.client_secret)
        )
        response.raise_for_status()
        token_data = response.json()
        self.access_token = token_data["access_token"]
        self.token_expiry = time.time() + int(token_data.get("expires_in", 0))
        return self.access_token