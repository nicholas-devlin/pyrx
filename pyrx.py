"""
    pyrx
    ~~~~

    Python implementation of the Rx schema and validation system
    http://rx.codesimply.com/

    Forked from the main rx github repo (https://github.com/rjbs/rx) Nov 25 '13
    because the python implementation deserves its own place and testin and
    stuff.

    The copyright line of the license for the rx repository reads:
    The contents of the Rx repository are copyright (C) 2008, Ricardo SIGNES.

    The license itself is GPL2: https://github.com/rjbs/rx/blob/master/LICENSE
"""

from __future__ import print_function
import re
import sys
import types

core_types = []

if sys.version_info[0] == 2:
    string_types = (str, unicode)
    num_types = (float, long, int)
else:
    string_types = (str,)
    num_types = (float, int)


class RxError(Exception):
    pass


class Util(object):
    @staticmethod
    def make_range_check(opt):
        range = {}
        for entry in opt.keys():
            if entry not in ('min', 'max', 'min-ex', 'max-ex'):
                raise ValueError("illegal argument to make_range_check")

            range[entry] = opt[entry]

        def check_range(value, explain=False):
            if range.get('min') is not None and value < range['min']:
                return False
            if range.get('min-ex') is not None and value <= range['min-ex']:
                return False
            if range.get('max-ex') is not None and value >= range['max-ex']:
                return False
            if range.get('max') is not None and value > range['max']:
                return False
            return True

        return check_range


def _get_logger(trace):
    def log(frame, event, arg):
        if event == 'return' and arg is False:
            message = "False "
            context = frame.f_locals
            if 'self' in context and hasattr(context['self'], 'subname'):
                message += ' while checking {}'.format(context['self'].subname())
            elif 'self' in context and hasattr(context['self'], 'uri'):
                message += ' while checking {}'.format(context['self'].uri())
            if 'value' in context:
                message += ', value {}'.format(context['value'])
            trace.append(message)
        #debug print frame.f_lineno, event, arg, frame.f_locals
        return log
    return log


def trace_wrap(type_class):
    class TracedType(type_class):
        def __init__(self, *args, **kwargs):
            super(TracedType, self).__init__(*args, **kwargs)
            self.trace = []

        def check(self, value, *args, **kwargs):
            self.trace = []

            result = super(TracedType, self).check(value, *args, **kwargs)
            if not result:
                sys.settrace(_get_logger(self.trace))
                super(TracedType, self).check(value, *args, **kwargs)
                sys.settrace(None)

            return result

    return lambda *args, **kwargs: TracedType(*args, **kwargs)


class Factory(object):
    def __init__(self, opt={}):
        self.prefix_registry = {
            '': 'tag:codesimply.com,2008:rx/core/',
            '.meta': 'tag:codesimply.com,2008:rx/meta/',
        }

        self.type_registry = {}
        if opt.get("register_core_types", False):
            for t in core_types:
                self.register_type(t)

    @staticmethod
    def _default_prefixes():
        pass

    def expand_uri(self, type_name):
        if re.match('^\w+:', type_name):
            return type_name

        m = re.match('^/([-._a-z0-9]*)/([-._a-z0-9]+)$', type_name)

        if not m:
            raise RxError("couldn't understand type name '%s'" % type_name)

        if not self.prefix_registry.get(m.group(1)):
            raise RxError("unknown prefix '%s' in type name '%s'" %
                          (m.group(1), type_name))

        return '%s%s' % (self.prefix_registry[m.group(1)], m.group(2))

    def add_prefix(self, name, base):
        if self.prefix_registry.get(name, None):
            raise RxError("the prefix '%s' is already registered" % name)

        self.prefix_registry[name] = base

    def register_type(self, t):
        t_uri = t.uri()

        if self.type_registry.get(t_uri, None):
            raise ValueError("type already registered for %s" % t_uri)

        self.type_registry[t_uri] = t

    def learn_type(self, uri, schema):
        if self.type_registry.get(uri, None):
            raise RxError("tried to learn type for already-registered uri %s"
                          % uri)

        # make sure schema is valid
        # should this be in a try/except?
        self.make_schema(schema)

        self.type_registry[uri] = {"schema": schema}

    def make_schema(self, schema, trace=False):
        if isinstance(schema, string_types):
            schema = {"type": schema}

        if not isinstance(schema, dict):
            raise RxError('invalid schema argument to make_schema')

        uri = self.expand_uri(schema["type"])

        if not self.type_registry.get(uri):
            raise RxError("unknown type %s" % uri)

        type_class = self.type_registry[uri]
        if trace:
            type_class = trace_wrap(type_class)

        if isinstance(type_class, dict):
            if not set(schema.keys()) <= set(['type']):
                raise RxError('composed type does not take check arguments')
            return self.make_schema(type_class["schema"])
        else:
            return type_class(schema, self)


class _CoreType(object):
    @classmethod
    def uri(self):
        return 'tag:codesimply.com,2008:rx/core/' + self.subname()

    def __init__(self, schema, rx):
        if not set(schema.keys()) <= set(['type']):
            raise RxError('unknown parameter for //%s' % self.subname())

    def check(self, value):
        return False


class AllType(_CoreType):
    @staticmethod
    def subname():
        return 'all'

    def __init__(self, schema, rx):
        if not set(schema.keys()) <= set(('type', 'of')):
            raise RxError('unknown parameter for //all')

        if not(schema.get('of') and len(schema.get('of'))):
            raise RxError('no alternatives given in //all of')

        self.alts = [rx.make_schema(s) for s in schema['of']]

    def check(self, value):
        for schema in self.alts:
            if (not schema.check(value)):
                return False
        return True


class AnyType(_CoreType):
    @staticmethod
    def subname():
        return 'any'

    def __init__(self, schema, rx):
        self.alts = None

        if not set(schema.keys()) <= set(('type', 'of')):
            raise RxError('unknown parameter for //any')

        if schema.get('of') is not None:
            if not schema['of']:
                raise RxError('no alternatives given in //any of')
            self.alts = [rx.make_schema(alt) for alt in schema['of']]

    def check(self, value):
        if self.alts is None:
            return True

        for alt in self.alts:
            if alt.check(value):
                return True

        return False


class ArrType(_CoreType):
    @staticmethod
    def subname():
        return 'arr'

    def __init__(self, schema, rx):
        self.length = None

        if not set(schema.keys()) <= set(('type', 'contents', 'length')):
            raise RxError('unknown parameter for //arr')

        if not schema.get('contents'):
            raise RxError('no contents provided for //arr')

        self.content_schema = rx.make_schema(schema['contents'])

        if schema.get('length'):
            self.length = Util.make_range_check(schema["length"])

    def check(self, value):
        if not isinstance(value, (list, tuple)):
            return False
        if self.length and not self.length(len(value)):
            return False

        for item in value:
            if not self.content_schema.check(item):
                return False

        return True


class BoolType(_CoreType):
    @staticmethod
    def subname():
        return 'bool'

    def check(self, value):
        if value is True or value is False:
            return True
        return False


class DefType(_CoreType):
    @staticmethod
    def subname():
        return 'def'

    def check(self, value):
        return not(value is None)


class FailType(_CoreType):
    @staticmethod
    def subname():
        return 'fail'

    def check(self, value):
        return False


class IntType(_CoreType):
    @staticmethod
    def subname():
        return 'int'

    def __init__(self, schema, rx):
        if not set(schema.keys()) <= set(('type', 'range', 'value')):
            raise RxError('unknown parameter for //int')

        self.value = None
        if 'value' in schema:
            if not isinstance(schema['value'], num_types) or \
               isinstance(schema['value'], bool):
                raise RxError('invalid value parameter for //int')
            if schema['value'] % 1 != 0:
                raise RxError('invalid value parameter for //int')
            self.value = schema['value']

        self.range = None
        if 'range' in schema:
            self.range = Util.make_range_check(schema["range"])

    def check(self, value):
        if not isinstance(value, num_types) or isinstance(value, bool):
            return False
        if value % 1 != 0:
            return False
        if self.range and not self.range(value):
            return False
        if (not self.value is None) and value != self.value:
            return False
        return True


class MapType(_CoreType):
    @staticmethod
    def subname():
        return 'map'

    def __init__(self, schema, rx):
        self.allowed = set()

        if not set(schema.keys()) <= set(('type', 'values')):
            raise RxError('unknown parameter for //map')

        if not schema.get('values'):
            raise RxError('no values given for //map')

        self.value_schema = rx.make_schema(schema['values'])

    def check(self, value):
        if not isinstance(value, dict):
            return False

        for v in value.values():
            if not self.value_schema.check(v):
                return False

        return True


class NilType(_CoreType):
    @staticmethod
    def subname():
        return 'nil'

    def check(self, value):
        return value is None


class NumType(_CoreType):
    @staticmethod
    def subname():
        return 'num'

    def __init__(self, schema, rx):
        if not set(schema.keys()) <= set(('type', 'range', 'value')):
            raise RxError('unknown parameter for //num')

        self.value = None
        if 'value' in schema:
            if not isinstance(schema['value'], num_types) or \
               isinstance(schema['value'], bool):
                raise RxError('invalid value parameter for //num')
            self.value = schema['value']

        self.range = None

        if schema.get('range'):
            self.range = Util.make_range_check(schema["range"])

    def check(self, value):
        if not isinstance(value, num_types) or isinstance(value, bool):
            return False
        if self.range and not self.range(value):
            return False
        if (not self.value is None) and value != self.value:
            return False
        return True


class OneType(_CoreType):
    @staticmethod
    def subname():
        return 'one'

    def check(self, value):
        if isinstance(value, num_types + string_types + (bool,)):
            return True

        return False


class RecType(_CoreType):
    @staticmethod
    def subname():
        return 'rec'

    def __init__(self, schema, rx):
        if not set(schema.keys()) <= \
                set(('type', 'rest', 'required', 'optional')):
            raise RxError('unknown parameter for //rec')

        self.known = set()
        self.rest_schema = None
        if schema.get('rest'):
            self.rest_schema = rx.make_schema(schema['rest'])

        for which in ('required', 'optional'):
            self.__setattr__(which, {})
            for field in schema.get(which, {}).keys():
                if field in self.known:
                    raise RxError('%s appears in both required and optional' %
                                  field)

                self.known.add(field)

                self.__getattribute__(which)[field] = rx.make_schema(
                    schema[which][field]
                )

    def check(self, value):
        if not isinstance(value, dict):
            return False

        unknown = []
        for field in value.keys():
            if not field in self.known:
                unknown.append(field)

        if len(unknown) and not self.rest_schema:
            return False

        for field in self.required.keys():
            if field not in value:
                return False
            if not self.required[field].check(value[field]):
                return False

        for field in self.optional.keys():
            if field not in value:
                continue
            if not self.optional[field].check(value[field]):
                return False

        if len(unknown):
            rest = {}
            for field in unknown:
                rest[field] = value[field]
            if not self.rest_schema.check(rest):
                return False

        return True


class SeqType(_CoreType):
    @staticmethod
    def subname():
        return 'seq'

    def __init__(self, schema, rx):
        if not set(schema.keys()) <= set(('type', 'contents', 'tail')):
            raise RxError('unknown parameter for //seq')

        if not schema.get('contents'):
            raise RxError('no contents provided for //seq')

        self.content_schema = [rx.make_schema(s) for s in schema["contents"]]

        self.tail_schema = None
        if (schema.get('tail')):
            self.tail_schema = rx.make_schema(schema['tail'])

    def check(self, value):
        if not isinstance(value, (list, tuple)):
            return False

        if len(value) < len(self.content_schema):
            return False

        for i in range(0, len(self.content_schema)):
            if not self.content_schema[i].check(value[i]):
                return False

        if len(value) > len(self.content_schema):
            if not self.tail_schema:
                return False

            if not self.tail_schema.check(value[len(self.content_schema):]):
                return False

        return True


class StrType(_CoreType):
    @staticmethod
    def subname():
        return 'str'

    def __init__(self, schema, rx):
        if not set(schema.keys()) <= set(('type', 'value', 'length')):
            raise RxError('unknown parameter for //str')

        self.value = None
        if 'value' in schema:
            if not isinstance(schema['value'], string_types):
                raise RxError('invalid value parameter for //str')
            self.value = schema['value']

        self.length = None
        if 'length' in schema:
            self.length = Util.make_range_check(schema["length"])

    def check(self, value):
        if not isinstance(value, string_types):
            return False
        if (not self.value is None) and value != self.value:
            return False
        if self.length and not self.length(len(value)):
            return False
        return True


core_types = [
    AllType,  AnyType, ArrType, BoolType, DefType,
    FailType, IntType, MapType, NilType,  NumType,
    OneType,  RecType, SeqType, StrType
]
