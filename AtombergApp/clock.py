from datetime import datetime

# ponytail: the CSVs are a snapshot, not live data, so "now" is a constant.
# Swap this for datetime.now() the day real events start arriving.
FACTORY_NOW = datetime(2026, 8, 17, 9, 15)


def now():
    return FACTORY_NOW
