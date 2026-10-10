"""The release of the APR Assistant, shown at startup, in /health, on the home page and in the admin console,
so it is always clear which version a server is running."""
import os

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    with open(os.path.join(_HERE, 'VERSION'), encoding='utf-8') as fh:
        APR_VERSION = fh.read().strip() or '2.0.0'
except OSError:
    APR_VERSION = '2.0.0'
