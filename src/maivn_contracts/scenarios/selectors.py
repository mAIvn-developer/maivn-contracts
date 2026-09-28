"""Public saved-connection selectors shared by HTTP and SDK consumers."""

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class OutputConnectionSelector(BaseModel):
    """Safe saved-connection selector for a scenario output."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    connection_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$',
    )
