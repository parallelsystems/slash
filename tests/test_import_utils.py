# pylint: disable=redefined-outer-name
import os
import sys
import warnings
from uuid import uuid4

import pytest
from slash.utils.import_utils import NoInitFileFound, import_file


@pytest.fixture
def module_file_factory():
    def create_module_file(directory, filename):
        directory = str(directory)
        os.makedirs(directory, exist_ok=True)
        value = str(uuid4())
        full_filename = os.path.join(directory, filename)
        with open(full_filename, 'w') as f:
            f.write('value = {!r}'.format(value))
        return full_filename, value
    return create_module_file


def test_import_from_non_package(tmpdir, module_file_factory):
    for i in range(5):
        _import_and_verify(*module_file_factory(tmpdir, 'module{}.py'.format(i)))


def test_multiple_imports_from_same_non_package(tmpdir, module_file_factory):
    module1 = _import_and_verify(*module_file_factory(tmpdir, 'module1.py'))
    module2 = _import_and_verify(*module_file_factory(tmpdir, 'module2.py'))
    assert _package_name(module1) == _package_name(module2)
    assert module1 is not module2


def test_importing_sub_package(tmpdir, module_file_factory):
    subpackage_dir = tmpdir.join('subpackage')
    subpackage_dir.join('__init__.py').ensure(file=True)
    filename, _ = module_file_factory(subpackage_dir, 'module.py')
    assert import_file(filename).__name__.endswith('.subpackage.module')


def test_importing_sub_package_and_subdir(tmpdir, module_file_factory):
    module = _import_and_verify(*module_file_factory(tmpdir, 'module.py'))
    subdir = tmpdir.join('sub')
    subdir.join('__init__.py').ensure(file=True)
    sub_module = _import_and_verify(*module_file_factory(subdir, 'module.py'))
    assert _package_name(module) + '.sub' == _package_name(sub_module)


def test_importing_different_directories_same_escaping(tmpdir, module_file_factory):
    module1 = _import_and_verify(*module_file_factory(tmpdir.join('pkg+'), 'module.py'))
    module2 = _import_and_verify(*module_file_factory(tmpdir.join('pkg-'), 'module.py'))
    assert _package_name(module1) != _package_name(module2)


def test_importing_dotted_name(tmpdir, module_file_factory):
    path = tmpdir
    for component in ('a', 'b.c', 'd'):
        path = path.join(component)
        path.join('__init__.py').ensure(file=True)
    _import_and_verify(*module_file_factory(path, 'module.py'))


def test_importing_directory_no_init_file(tmpdir):
    with pytest.raises(NoInitFileFound):
        import_file(str(tmpdir))


@pytest.mark.parametrize('init_py_directly', [True, False])
def test_importing_directory(init_py_directly, tmpdir, module_file_factory):
    directory = str(tmpdir.join('pkg'))
    init_filename, value = module_file_factory(directory, '__init__.py')
    module = import_file(init_filename if init_py_directly else directory)
    assert module.__name__.endswith('.pkg')
    assert module.value == value


def test_importing_subdirectory_init_file(tmpdir, module_file_factory):
    directory = tmpdir.join('pkg')
    module_file_factory(directory, '__init__.py')
    filename, value = module_file_factory(directory.join('subpkg'), '__init__.py')
    assert import_file(filename).value == value


def test_relative_imports(tmpdir):
    directory = tmpdir.join('dir')
    directory.join('__init__.py').ensure(file=True)
    directory.join('file_1.py').write('value = "file_1"')
    directory.join('proxy.py').write('from .file_1 import value as file_1_value')
    assert import_file(str(directory.join('proxy.py'))).file_1_value == 'file_1'


def test_module_specs(tmpdir):
    package_dir = tmpdir.join('package')
    subpackage_dir = package_dir.join('sub')
    for p in (package_dir, subpackage_dir):
        p.join('__init__.py').ensure(file=True)
    subpackage_dir.join('utils.py').ensure(file=True)
    filename = subpackage_dir.join('module.py')
    filename.write('from . import utils')

    module = import_file(str(filename))

    for m in (module, module.utils):
        metapackage_name, remainder = m.__spec__.name.split('.', 1)
        assert remainder == 'package.sub.{}'.format(m.__name__.split('.')[-1])
        assert m.__spec__.parent == '{}.package.sub'.format(metapackage_name)

    metapackage = sys.modules[metapackage_name]
    assert metapackage.__spec__.origin == str(package_dir.dirname)
    assert metapackage.__spec__.name == metapackage_name
    assert str(package_dir.dirname) in metapackage.__spec__.submodule_search_locations
    assert metapackage.__package__ == metapackage_name


@pytest.mark.parametrize('add_init_py', [True, False])
def test_importing_doesnt_emit_warnings(tmpdir, add_init_py):
    value = str(uuid4())
    directory = tmpdir.join('files')
    directory.join('utils.py').write('value = {!r}'.format(value), ensure=True)
    filename = directory.join('testfile.py')
    filename.write('from .utils import value as new_value')
    if add_init_py:
        directory.join('__init__.py').ensure(file=True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        module = import_file(str(filename))

    assert module.new_value == value
    assert not caught


def test_failed_package_import_is_not_left_in_sys_modules(tmpdir):
    directory = tmpdir.join('broken_pkg')
    directory.join('__init__.py').write('raise RuntimeError("broken")', ensure=True)
    directory.join('module.py').ensure(file=True)

    with pytest.raises(RuntimeError, match='broken'):
        import_file(str(directory.join('module.py')))

    assert not [name for name in sys.modules if name.endswith('.broken_pkg')]


def _import_and_verify(filename, value):
    module = import_file(filename)
    assert module.value == value
    return module


def _package_name(module):
    return module.__name__.rsplit('.', 1)[0]
