from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path


class DataError(ValueError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.schema = json.loads((self.root / 'schema.json').read_text())
        self._tables = {}
        for name in self.schema:
            self._tables[name] = json.loads((self.root / (name + '.json')).read_text())
        self.validate()

    def validate(self):
        for name, contract in self.schema.items():
            rows = self._tables[name]
            if not isinstance(rows, list):
                raise DataError(name + ': table must be a list')
            keys = set()
            for position, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise DataError(name + ': invalid row')
                for field in contract['required']:
                    if field not in row or row[field] is None:
                        raise DataError(name + ': required ' + field)
                key = tuple(row[field] for field in contract['key'])
                if key in keys:
                    raise DataError(name + ': duplicate key ' + str(key))
                keys.add(key)
                for field, value in row.items():
                    if isinstance(value, float) and not math.isfinite(value):
                        raise DataError(name + ': nonfinite ' + field)
            for field, target in contract.get('foreign', {}).items():
                other, target_field = target
                allowed = {row[target_field] for row in self._tables[other]}
                for row in rows:
                    if row.get(field) is not None and row[field] not in allowed:
                        raise DataError(name + ': unknown ' + field)

    def table(self, name):
        if name not in self._tables:
            raise DataError('unknown table: ' + name)
        return deepcopy(self._tables[name])

    def select(self, name, **filters):
        return [row for row in self.table(name)
                if all(row.get(field) == value for field, value in filters.items())]

    def find(self, name, **filters):
        matches = self.select(name, **filters)
        if len(matches) != 1:
            raise DataError(name + ': expected one row, got ' + str(len(matches)))
        return matches[0]

    def fingerprint(self):
        encoded = json.dumps(self._tables, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')).encode()
        return sha256(encoded).hexdigest()

    def inventory(self):
        return {name: len(rows) for name, rows in self._tables.items()}


def single(query, name, default=None):
    values = query.get(name)
    if values is None:
        return default
    if len(values) != 1 or values[0] == '':
        raise DataError('one nonempty value required: ' + name)
    return values[0]


def integer(query, name, default, minimum=0, maximum=10000):
    raw = single(query, name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise DataError('integer required: ' + name) from None
    if not minimum <= value <= maximum:
        raise DataError('out of range: ' + name)
    return value


def mean(values):
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else None
