"""Importing Python files by path, as modules of synthetic top-level packages.

Adapted from emport (https://github.com/vmalloc/emport, BSD license, by Rotem Yaari).
"""
import importlib.util
import itertools
import os
import sys
from importlib.machinery import ModuleSpec, SourceFileLoader

import logbook

_logger = logbook.Logger(__name__)


class NoInitFileFound(Exception):
    pass


def import_file(filename):
    """Given a path to a file, imports it as a Python module
    """
    module_name = _create_new_module_name(filename)
    return importlib.import_module(module_name)


_package_name_generator = ('_{}'.format(x) for x in itertools.count())
_cached_package_names = {}


def _generate_package_name():
    for suggested in _package_name_generator:
        if suggested not in sys.modules:
            return suggested


def _create_new_module_name(filename):
    _logger.trace('Creating new package for {}', filename)
    nonpackage_dir, remainder = _split_nonpackage_dir(filename)
    _logger.trace('After split: {}, {}', nonpackage_dir, remainder)
    package_name = _cached_package_names.get(nonpackage_dir, None)
    if package_name is None:
        package_name = _generate_package_name()
        _create_package_module(package_name, nonpackage_dir)
        _cached_package_names[nonpackage_dir] = package_name
    returned = '{}.{}'.format(package_name, remainder)
    if returned.endswith('.__init__'):
        returned = returned.rsplit('.', 1)[0]
    return returned


def _split_nonpackage_dir(path):
    if not os.path.isdir(path):
        nonpackage_dir, module = os.path.split(_normalize_path(path))
        module = _make_module_name(module).split('.')
    else:
        nonpackage_dir = path
        module = []
    while os.path.isfile(os.path.join(nonpackage_dir, '__init__.py')):
        if '.' in os.path.split(nonpackage_dir)[-1]:
            # we cannot import from such packages, stop traversing upwards...
            break
        nonpackage_dir, current_component = os.path.split(nonpackage_dir)
        module.insert(0, current_component)
        _logger.trace('Now at {}, {}', nonpackage_dir, module)
    if not module:
        raise NoInitFileFound('Could not find __init__.py file in {}'.format(path))
    return nonpackage_dir, '.'.join(module)


def _normalize_path(path):
    return os.path.normpath(os.path.abspath(str(path)))


def _make_module_name(filename):
    assert filename.endswith('.py') or filename.endswith('.pyc')
    return filename.rsplit('.', 1)[0].replace(os.path.sep, '.')


def _create_package_module(name, path):
    spec = ModuleSpec(origin=path, name=name, loader=SourceFileLoader(name, path), is_package=True)
    spec.submodule_search_locations.append(path)
    returned = importlib.util.module_from_spec(spec)
    returned.__path__ = [path]
    sys.modules[name] = returned
    return returned
