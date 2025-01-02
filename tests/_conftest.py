import pytest
pytestmark = pytest.mark.asyncio
from core.resource_tracking import ResourceCalculator

pytest_plugins = ["pytest_asyncio"]

@pytest.fixture
def resource_calculator():
    """Fixture für den ResourceCalculator"""
    return ResourceCalculator() 