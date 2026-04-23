# -*- coding: utf-8 -*-
"""
Root conftest.py for mt-io tests.

Provides session-wide test data availability detection and fixtures.

Usage in test modules:
    # Method 1: Use pytest.mark with pytest_configure (recommended for module-level)
    import pytest

    # In pytest_configure, HAS_MTH5_TEST_DATA is stored in config.HAS_MTH5_TEST_DATA
    # Access it through request.config in tests

    # Method 2: Quick check - import from parent conftest
    # pytest automatically discovers conftest.py, so you can use:
    import pytest
    pytestmark = pytest.mark.skipif(
        pytest.config.HAS_MTH5_TEST_DATA if hasattr(pytest, 'config') else False,
        reason="Skipping mock tests - real data available"
    )

    # Method 3: Using fixture (most flexible)
    def test_something(mth5_test_data_available):
        if mth5_test_data_available:
            pytest.skip("reason")
"""

from pathlib import Path

import pytest

# ============================================================================
# Master test data availability flag
# ============================================================================


def has_mth5_test_data() -> bool:
    """
    Check if mth5_test_data is installed and accessible.

    This is a high-level check that looks for the mth5_test_data package
    which contains all real test data files. If this is available, mock
    tests are skipped in favor of real data tests.

    Returns
    -------
    bool
        True if mth5_test_data is available, False otherwise
    """
    try:
        import mth5_test_data

        # Also verify the test data directory exists
        test_data_path = Path(mth5_test_data.__file__).parent / "data"
        return test_data_path.exists()
    except (ImportError, AttributeError):
        return False


# Module-level constant computed at conftest load time
_HAS_MTH5_TEST_DATA = has_mth5_test_data()


def pytest_configure(config):
    """
    Configure pytest with test data availability flag.

    This runs once at session initialization and stores HAS_MTH5_TEST_DATA
    in the pytest config object so it can be accessed from test modules.
    """
    config.HAS_MTH5_TEST_DATA = _HAS_MTH5_TEST_DATA
    config.addinivalue_line(
        "markers", "skip_if_has_test_data: skip test if mth5_test_data is available"
    )


# ============================================================================
# Pytest Marks
# ============================================================================


def pytest_collection_modifyitems(config, items):
    """
    Automatically skip entire modules of mock tests if mth5_test_data is available.

    This hook processes all collected test items and:
    1. Identifies modules that are *_mock.py files
    2. If HAS_MTH5_TEST_DATA is True, skips all tests in those modules
    3. This provides a "master skip" at the module level
    """
    if not config.HAS_MTH5_TEST_DATA:
        return  # Don't skip anything if test data isn't available

    # Skip markers to apply
    skip_marker = pytest.mark.skipif(
        True, reason="Skipping mock tests - real data available"
    )

    # Track which modules we've already marked
    marked_modules = set()

    for item in items:
        # Check if this test is from a *_mock.py module
        module_path = item.fspath.strpath
        if "_mock.py" in module_path:
            if module_path not in marked_modules:
                marked_modules.add(module_path)
            item.add_marker(skip_marker)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def mth5_test_data_available(pytestconfig) -> bool:
    """
    Session-scoped fixture indicating if mth5_test_data is available.

    Can be used in test functions like:
        def test_something(mth5_test_data_available):
            if mth5_test_data_available:
                pytest.skip("reason")
    """
    return pytestconfig.HAS_MTH5_TEST_DATA


def skip_mock_tests_if_data_available(config) -> pytest.mark:
    """
    Helper to create a skipif marker for mock tests.

    Usage in test modules:
        pytestmark = skip_mock_tests_if_data_available(pytest.config)

    However, pytest.config is not available at import time.
    Better approach: use request.config in the fixture or pytest plugin hook.
    """
    return pytest.mark.skipif(
        config.HAS_MTH5_TEST_DATA, reason="Skipping mock tests - real data available"
    )
