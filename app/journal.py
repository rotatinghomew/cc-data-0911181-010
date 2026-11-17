from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
from threading import RLock
from .storage import DataError


class Journal:
    def __init__(self,path=':memory:'):
        self.lock=RLock()
        self.connection=sqlite3.connect(path,check_same_thread=False,isolation_level=None)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('CREATE TABLE IF NOT EXISTS documents(kind TEXT,key TEXT,body TEXT,PRIMARY KEY(kind,key))')

    @contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                yield self
                self.connection.execute('COMMIT')
            except Exception:
                self.connection.execute('ROLLBACK')
                raise

    def get(self,kind,key):
        row=self.connection.execute('SELECT body FROM documents WHERE kind=? AND key=?',(kind,key)).fetchone()
        if row is None:
            raise DataError('unknown '+kind+': '+str(key))
        return json.loads(row[0])

    def all(self,kind):
        return [json.loads(row[0]) for row in self.connection.execute(
            'SELECT body FROM documents WHERE kind=? ORDER BY key',(kind,))]

    def put(self,kind,key,body):
        encoded=json.dumps(body,ensure_ascii=False,allow_nan=False)
        self.connection.execute('INSERT INTO documents(kind,key,body) VALUES(?,?,?) '
                                'ON CONFLICT(kind,key) DO UPDATE SET body=excluded.body',(kind,key,encoded))
        return deepcopy(body)

    def close(self):
        self.connection.close()
