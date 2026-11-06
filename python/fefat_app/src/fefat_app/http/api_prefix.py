"""Where the API lives among the server's paths: `/v1` and under it (`01-architecture.md` section
7), which only the API answers, never the built web app."""

API_PREFIX = "/v1"


def is_api_path(path: str) -> bool:
    """Whether `path` is the API's."""
    return path == API_PREFIX or path.startswith(f"{API_PREFIX}/")
