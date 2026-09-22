from importlib.metadata import PackageNotFoundError, version

__version__ = version('slash')

def get_backslash_client_version():
    try:
        return version('backslash')
    except PackageNotFoundError:
        return None

__backslash_version__ = get_backslash_client_version()
