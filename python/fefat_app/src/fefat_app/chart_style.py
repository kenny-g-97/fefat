"""The charts' style the trader chooses (step 5.4, the builder's answers at its plan): hollow or
filled candle bodies, the volume pane shown or hidden and coloured by direction or in one grey,
the grid and the sessions' shading shown or hidden, and, for each theme, colours of the trader's
own for rising and falling bars, the background, the grid, and the text, each `#rrggbb` or null
for the theme's own. The app keeps it as the `settings` row `chart_style` (`Preferences`, D-83),
so that every chart of the app and every browser draw with the same style."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Colour = Annotated[str, Field(pattern=r"^#[0-9a-f]{6}$")]
"""A colour as a browser's colour field gives it: `#` and six lowercase hex digits."""


class CandleBody(StrEnum):
    """A candle's body: outlined in its colour, or filled with it."""

    HOLLOW = "hollow"
    FILLED = "filled"


class VolumeColouring(StrEnum):
    """The volume pane's bars: in one grey, or in their candle's colour."""

    NEUTRAL = "neutral"
    DIRECTION = "direction"


class ThemeColours(BaseModel):
    """The trader's own colours in one theme, each null for the theme's own: rising and falling
    bars, which the theme gives its sign colours, the chart's background, its grid, and its
    text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    up: Colour | None = None
    down: Colour | None = None
    background: Colour | None = None
    grid: Colour | None = None
    text: Colour | None = None


class ChartStyle(BaseModel):
    """The charts' style (module docstring); its defaults are FEAT's, hollow green rising bars
    and hollow red falling ones, the builder's answer at step 5.4's plan, with the volume pane,
    the grid, and the sessions' shading shown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    up_body: CandleBody = CandleBody.HOLLOW
    down_body: CandleBody = CandleBody.HOLLOW
    volume_shown: bool = True
    volume_colouring: VolumeColouring = VolumeColouring.NEUTRAL
    grid_shown: bool = True
    sessions_shaded: bool = True
    dark: ThemeColours = ThemeColours()
    light: ThemeColours = ThemeColours()
