"""Top-level package for mt-io."""

# =============================================================================
# Imports
# =============================================================================
import sys
import xarray as xr
from loguru import logger

from mt_io.reader import read_file

# =============================================================================
# Package Variables
# =============================================================================

__author__ = """MT-IO Development Team"""
__email__ = "jpeacock@usgs.gov"
__version__ = "0.0.1"


# =============================================================================
# Initialize Loggers
# =============================================================================
config = {
    "handlers": [
        {
            "sink": sys.stdout,
            "level": "INFO",
            "colorize": True,
            "format": "<level>{time} | {level: <3} | {name} | {function} | line: {line} | {message}</level>",
        },
    ],
    "extra": {"user": "someone"},
}
logger.configure(**config)

# need to set this to make sure attributes of data arrays and data sets
# are kept when doing xarray computations like merge.
xr.set_options(keep_attrs=True)
