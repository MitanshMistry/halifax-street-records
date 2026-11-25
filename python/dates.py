"""ArcGIS dates arrive as milliseconds since 1970 in UTC. Convert to Halifax time before taking the date."""
import pandas as pd

TZ = "America/Halifax"


def ms_to_halifax(series):
    """Return a tz-aware Halifax datetime Series; bad or missing values become NaT."""
    return pd.to_datetime(series, unit="ms", utc=True, errors="coerce").dt.tz_convert(TZ)
