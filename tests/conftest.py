"""Keep the original acceptance suite on its explicit legacy contract.

The running prototype defaults to the chapter entitlement model. The existing
specification tests exercise the retired five-session trial because they also
cover preview, grant, expiry and refund behavior. New chapter-model tests opt
in explicitly so both migrations remain covered while the product changes.
"""

import os


os.environ.setdefault("MEMORY_SPARK_ENTITLEMENT_MODEL", "legacy")
os.environ.setdefault("MEMORY_SPARK_TEST_MODE", "1")
