"""
SDK Adapter for dynamic SDK loading based on tenant configuration.

This module provides a facade/adapter pattern to handle the dynamic import
of different SDK packages (fintecture-client, virement-maitrise, etc.) based
on the tenant configuration.

The SDK is lazily loaded once at module level and cached for all subsequent uses.
This provides both clean module-level imports and high performance.
"""

import importlib
import logging
from . import const

_logger = logging.getLogger(__name__)

# SDK module cache - loaded on first access
_sdk_module = None


def _load_sdk():
    """
    Internal function to load and cache the SDK module.

    Returns:
        module: The SDK module (fintecture, virement_maitrise, etc.)

    Raises:
        ImportError: If the SDK package specified in const.SDK_IMPORT_NAME is not installed
    """
    global _sdk_module

    if _sdk_module is not None:
        return _sdk_module

    sdk_import_name = const.SDK_IMPORT_NAME

    _logger.info(f'|SDKAdapter| Loading SDK module: {sdk_import_name}')

    try:
        _sdk_module = importlib.import_module(sdk_import_name)
        _logger.info(f'|SDKAdapter| Successfully loaded SDK: {sdk_import_name}')
        return _sdk_module
    except ImportError as e:
        _logger.error(f'|SDKAdapter| Failed to import SDK "{sdk_import_name}": {e}')
        _logger.error(f'|SDKAdapter| Please install the SDK: pip install {sdk_import_name}')
        raise ImportError(
            f'SDK module "{sdk_import_name}" not found. '
            f'Please install it with: pip install {sdk_import_name}'
        ) from e


class _SDKProxy:
    """
    Proxy class that forwards all attribute access to the dynamically loaded SDK module.

    This allows us to use `fintecture.PIS.request_to_pay()` syntax while the actual
    SDK module is loaded lazily on first access.
    """
    def __getattr__(self, name):
        """Forward all attribute access to the loaded SDK module."""
        sdk = _load_sdk()
        return getattr(sdk, name)

    def __setattr__(self, name, value):
        """Forward all attribute setting to the loaded SDK module."""
        sdk = _load_sdk()
        setattr(sdk, name, value)


# Module-level proxy that acts like the SDK module
# Usage: from ..sdk_adapter import fintecture
fintecture = _SDKProxy()


def reset_sdk_cache():
    """
    Reset the SDK cache. Useful for testing or when SDK needs to be reloaded.

    Note: This should rarely be needed in production code.
    """
    global _sdk_module
    _sdk_module = None
    _logger.info('|SDKAdapter| SDK cache reset')
