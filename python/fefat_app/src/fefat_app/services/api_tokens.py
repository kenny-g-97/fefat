"""The API tokens of notebooks and scripts (steps 4.2 and 4.3, D-86): `fefat token create <name>`
or the settings page makes one and shows it once, a request carries it as `Authorization: Bearer
<token>`, the database keeps its SHA-256 alone, and `fefat token revoke <name>` or the page
revokes it."""

import re
from dataclasses import dataclass

from fefat_app.ports import AccessRecords, ApiToken, Clock
from fefat_app.services.identity import SEEN_EVERY, ApiTokenIdentity, new_token, token_hash

TOKEN_PREFIX = "fefat_"
"""What every API token starts with, so that a reader or a secret scanner can tell one."""
TOKEN_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
"""A token's name: 1 to 64 letters, digits, dots, dashes, or underscores."""


class NoSuchApiTokenError(ValueError):
    """A revocation of a name that no live API token has."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Expected the name of a live API token, got {name!r}.")


@dataclass(frozen=True)
class ApiTokenIssuer:
    """Makes, lists, and revokes API tokens, and tells whose a presented token is."""

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

    def live_tokens(self) -> tuple[ApiToken, ...]:
        """The API tokens not revoked, by when they were made: their names and times, never a
        token."""
        return self.records.live_api_tokens()

    def revoke(self, name: str) -> None:
        """Revoke the live API token `name`, which is refused from then on; refused with
        `NoSuchApiTokenError` where no live token has the name."""
        if not self.records.revoke_api_token(name, revoked_at=self.clock()):
            raise NoSuchApiTokenError(name)
