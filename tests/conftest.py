import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for mod in [m for m in sys.modules if m == "custom_components" or m.startswith("custom_components.")]:
    del sys.modules[mod]
sys.path.insert(0, ROOT)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
