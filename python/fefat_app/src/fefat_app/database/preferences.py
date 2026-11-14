"""The trader's preferences over the app's database (step 4.3, D-83): the theme as the `settings`
row `theme` (`fefat_app.ports.Preferences`), dark while the row is missing, as the design brief
sets it, and from step 5.4 the charts' style as the row `chart_style`, FEAT's while it is
missing."""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from fefat_app.chart_style import ChartStyle
from fefat_app.database.models import SettingRow
from fefat_app.database.schema import reading
from fefat_app.ports import Theme

THEME_KEY = "theme"
"""The `settings` row that keeps the theme."""
CHART_STYLE_KEY = "chart_style"
"""The `settings` row that keeps the charts' style."""


@dataclass(frozen=True)
class PreferenceRows:
    """`Preferences` in the `settings` table of `engine`'s database."""

    engine: Engine

    def theme(self) -> Theme:
        kept = self._kept(THEME_KEY)
        if kept is None:
            return Theme.DARK
        if not isinstance(kept, str) or kept not in Theme:
            choices = ", ".join(theme.value for theme in Theme)
            raise ValueError(
                f"Expected the settings row {THEME_KEY} to hold one of {choices}, got {kept!r}."
            )
        return Theme(kept)

    def replace_theme(self, theme: Theme) -> None:
        self._replace(THEME_KEY, theme.value)

    def chart_style(self) -> ChartStyle:
        kept = self._kept(CHART_STYLE_KEY)
        if kept is None:
            return ChartStyle()
        try:
            return ChartStyle.model_validate(kept)
        except ValidationError as refused:
            raise ValueError(
                f"Expected the settings row {CHART_STYLE_KEY} to hold a chart style, got "
                f"{refused.error_count()} errors: {refused}"
            ) from refused

    def replace_chart_style(self, style: ChartStyle) -> None:
        self._replace(CHART_STYLE_KEY, style.model_dump(mode="json"))

    def _kept(self, key: str) -> object:
        """The value the row `key` holds, None while there is no such row."""
        with Session(reading(self.engine)) as session:
            row = session.get(SettingRow, key)
            return None if row is None else row.value_json

    def _replace(self, key: str, value: object) -> None:
        """Keep `value` in the row `key`, made where there is none."""
        with Session(self.engine) as session, session.begin():
            row = session.get(SettingRow, key)
            if row is None:
                session.add(SettingRow(key=key, value_json=value))
            else:
                row.value_json = value
