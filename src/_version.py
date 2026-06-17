"""Application version.

Default development value committed to the repo so a plain dev checkout can
``from _version import __version__`` without failing. CI overwrites this file
from the git tag during the packaging step (see §7.1 of SPEC.md).
"""

__version__ = "0.0.0+dev"
