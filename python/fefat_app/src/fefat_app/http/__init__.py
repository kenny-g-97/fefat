"""The HTTP ring (`08-code-design.md` section 1, step 4.2): the FastAPI app that `fefat up` serves
on the loopback, its routes under `/v1` over the services, holding no business logic of their
own, its errors as problem+json, its request ids and security headers, the API's docs behind
the login, and the built web app at `/`."""
