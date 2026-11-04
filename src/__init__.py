import os as _os

__version__ = "2.0.0"

# joblib probes physical cores with wmic, which is absent on recent Windows and
# prints a spurious traceback from the first sklearn fit. Cap it explicitly.
_os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")
