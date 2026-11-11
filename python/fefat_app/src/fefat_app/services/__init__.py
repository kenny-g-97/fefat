"""The app's use cases (`08-code-design.md` section 1): each module one area, over the SDK and the
ports, and never over FastAPI, Starlette, SQLAlchemy, or Alembic, which an import-linter
contract holds. Step 4.2 brings the logins, the API tokens, and the settings page's settings,
step 4.4 the jobs, and step 5.1 the data catalog."""
