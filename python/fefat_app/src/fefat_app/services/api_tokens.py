"""The API tokens of notebooks and scripts (step 4.2, D-86): `fefat token create <name>` makes one
and shows it once, a request carries it as `Authorization: Bearer <token>`, and the database
keeps its SHA-256 alone."""

import re
from dataclasses import dataclass

from fefat_app.ports import AccessRecords, Clock
from fefat_app.services.identity import SEEN_EVERY, ApiTokenIdentity, new_token, token_hash

TOKEN_PREFIX = "fefat_"
"""What every API token starts with, so that a reader or a secret scanner can tell one."""
TOKEN_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
"""A token's name: 1 to 64 letters, digits, dots, dashes, or underscores."""


@dataclass(frozen=True)
class ApiTokenIssuer:
    """Makes API tokens and tells whose a presented token is."""

    records: AccessRecords
    clock: Clock

    def create(self, name: str) -> str:
        """A new API token named `name`, which this call alone returns; a name in use, or one
        that breaks `TOKEN_NAME`, is refused."""
        if TOKEN_NAME.fullmatch(name) is None:
            raise ValueError(
                "Expected a token name of 1 to 64 letters, digits, dots, dashes, or underscores, "
                f"got {name!r}."
            )
        token = TOKEN_PREFIX + new_token()
        self.records.add_api_token(name, token_hash(token), created_at=self.clock())
        return token

    def identity_of_token(self, token: str) -> ApiTokenIdentity | None:
        """The identity of the API token `token`, or None where no such token is kept or it was
        revoked."""
        hashed = token_hash(token)
        api_token = self.records.api_token_by_hash(hashed)
        if api_token is None:
            return None
        now = self.clock()
        if api_token.last_used_at is None or now - api_token.last_used_at >= SEEN_EVERY:
            self.records.mark_api_token_used(hashed, now)
        return ApiTokenIdentity(token_name=api_token.name)
