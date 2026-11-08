"""The trader's preferences over the app's database (step 4.3, D-83): the theme as the `settings`
row `theme` (`fefat_app.ports.Preferences`), dark while the row is missing, as the design brief
sets it."""

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from fefat_app.database.models import SettingRow
from fefat_app.database.schema import reading
from fefat_app.ports import Theme

THEME_KEY = "theme"
"""The `settings` row that keeps the theme."""


@dataclass(frozen=True)
class PreferenceRows:
    """`Preferences` in the `settings` table of `engine`'s database."""

    engine: Engine

    def theme(self) -> Theme:
        with Session(reading(self.engine)) as session:
            row = session.get(SettingRow, THEME_KEY)
            if row is None:
                return Theme.DARK
            kept: object = row.value_json
        if not isinstance(kept, str) or kept not in Theme:
            choices = ", ".join(theme.value for theme in Theme)
            raise ValueError(
                f"Expected the settings row {THEME_KEY} to hold one of {choices}, got {kept!r}."
            )
        return Theme(kept)

    def replace_theme(self, theme: Theme) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(SettingRow, THEME_KEY)
            if row is None:
                session.add(SettingRow(key=THEME_KEY, value_json=theme.value))
            else:
                row.value_json = theme.value
