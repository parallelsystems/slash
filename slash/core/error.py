import sys
import traceback
from collections.abc import Iterator
from itertools import pairwise

import arrow
import logbook
from vintage import deprecated, get_no_deprecations_context

from io import StringIO
from ..conf import config
from ..exception_handling import is_exception_fatal, get_exception_frame_correction
from ..exceptions import FAILURE_EXCEPTION_TYPES
from ..utils.formatter import Formatter
from ..utils.python import safe_set_attribute
from ..utils.traceback_utils import distill_call_stack, distill_traceback, distill_object_attributes


_logger = logbook.Logger(__name__)
_CAPTURED_ERROR_MARKER = "__slash_captured_error__"


def _iter_exception_chain(exc_value: BaseException | None) -> Iterator[BaseException]:
    seen: set[int] = set()
    while exc_value is not None and id(exc_value) not in seen:
        seen.add(id(exc_value))
        yield exc_value
        exc_value = exc_value.__cause__ if exc_value.__suppress_context__ else exc_value.__context__


def _format_exception_chain(exc_type: type[BaseException] | None, exc_value: BaseException | None) -> str:
    lines = [_format_exception(exc_type, exc_value)]
    for outer, inner in pairwise(_iter_exception_chain(exc_value)):
        label = "Caused by" if inner is outer.__cause__ else "While handling"
        lines.append(f"{label}: {_format_exception(type(inner), inner)}")
    return "\n".join(lines)

def _format_exception(exc_type: type[BaseException] | None, exc_value: BaseException | None) -> str:
    return traceback.format_exception_only(exc_type, exc_value)[0].strip()


class Error(object):

    traceback = exception_type = arg = _cached_detailed_traceback_str = None

    def __init__(self, msg=None, exc_info=None, frame_correction=0):
        super(Error, self).__init__()
        self.time = arrow.utcnow()
        self._fatal = False
        self._has_custom_message = (msg is not None)
        if msg is None and exc_info is not None:
            msg = _format_exception_chain(exc_info[0], exc_info[1])
        if not isinstance(msg, str):
            self.arg = msg
            msg = repr(msg)
        self.message = msg
        #: A string representation of the exception caught, if exists
        self.exception_str = exception = None
        #: A dictionary of distilled attributes of the exception object
        self._exception_attributes = None
        self.exc_info = exc_info
        if exc_info is not None:
            self.exception_type, exception, tb = exc_info  # pylint: disable=unpacking-non-sequence
            self.exception_str = repr(exception)
            self._exception_attributes = distill_object_attributes(exception, truncate=False)
            self.traceback = distill_traceback(
                tb, frame_correction=get_exception_frame_correction(exception))
        else:
            self.traceback = distill_call_stack(frame_correction=frame_correction+4)
        self._is_failure = False
        self._fatal = exception is not None and is_exception_fatal(exception)
        self._is_failure = isinstance(exception, FAILURE_EXCEPTION_TYPES)

    @property
    @deprecated(since='1.5.0', what='error.exception_attributes')
    def exception_attributes(self):
        return self._exception_attributes

    def forget_exc_info(self):
        assert hasattr(self, 'exc_info')
        self.exc_info = None
        for frame in self.traceback.frames:
            frame.forget_python_frame()

    def log_added(self):
        tb = self.traceback.to_string(include_vars=config.root.log.traceback_variables)
        _logger.trace('Error added: {}\n{}', self, tb, extra={'highlight': True})

    def has_custom_message(self):
        return self._has_custom_message

    def mark_as_failure(self):
        self._is_failure = True

    def is_fatal(self):
        return self._fatal

    @property
    @deprecated('Use error.exception_str', what='error.exception', since='1.2.3')
    def exception(self):
        return self.exception_str

    def mark_fatal(self):
        """Marks this error as fatal, causing session termination
        """
        self._fatal = True
        return self

    def is_failure(self):
        return self._is_failure

    @classmethod
    def capture_exception(cls, exc_info=None):
        if exc_info is None:
            exc_info = sys.exc_info()
        _, exc_value, _ = exc_info
        if exc_value is None:
            return None
        cached = getattr(exc_value, _CAPTURED_ERROR_MARKER, None)
        if cached is not None:
            return cached
        returned = cls(exc_info=exc_info)
        safe_set_attribute(exc_value, _CAPTURED_ERROR_MARKER, returned)
        return returned

    @property
    def cause(self):
        if self.traceback is not None:
            return self.traceback.cause

    @property
    def filename(self):
        if self.traceback is not None:
            return self.traceback.cause.filename

    @property
    def lineno(self):
        """Line number from which the error was raised
        """
        if self.traceback is not None:
            return self.traceback.cause.lineno

    @property
    def func_name(self):
        """Function name from which the error was raised
        """
        if self.traceback is not None:
            return self.traceback.cause.func_name

    def __repr__(self):
        first_line = self.message.partition('\n')[0]
        return '<{}: {}>'.format(self.__class__.__name__, first_line)

    def get_detailed_traceback_str(self):
        """Returns a formatted traceback string for the exception caught
        """
        if self._cached_detailed_traceback_str is None:
            stream = StringIO()
            f = Formatter(stream, indentation_string='  ')
            f.writeln("Traceback (most recent call last):")
            with f.indented():
                for frame in self.traceback.frames:
                    with get_no_deprecations_context():
                        locals_ = frame.locals
                        globals_ = frame.globals
                    f.writeln('File "{f.filename}", line {f.lineno}, in {f.func_name}:'.format(f=frame))
                    with f.indented():
                        f.writeln('>', frame.code_line.strip() or '?')
                        with f.indented():
                            for title, vars in [('globals', globals_), ('locals', locals_)]:
                                for index, (var_name, var_repr) in enumerate(vars.items()):
                                    if index == 0:
                                        f.writeln(title)
                                        f.indent()
                                    f.writeln(' - {}: {}'.format(var_name, var_repr['value']))
                            f.dedent()
            self._cached_detailed_traceback_str = stream.getvalue()

        return self._cached_detailed_traceback_str

    def get_detailed_str(self):
        return '{}*** {}'.format(
            self.get_detailed_traceback_str(), self)
