"""Alembic's environment for the app's database (`fefat_app.database.schema`): the migrations run
on the connection that `upgrade_schema` or `empty_schema` passes, inside its transaction, in
batch mode, as SQLite needs to change a table, against the models' metadata."""

from alembic import context
from sqlalchemy import Connection

from fefat_app.database.models import Base

connection: Connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
