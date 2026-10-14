"""Composable engine-level read-only scopes without committing caller work."""
from contextlib import contextmanager
import sqlite3


class GuardedConnection(sqlite3.Connection):
    """Track callbacks because sqlite3 exposes set_authorizer but no getter."""
    def set_authorizer(self, callback):
        # Python 3.9 does not support clearing callbacks with None. An explicit
        # allow callback preserves the same semantics across supported runtimes.
        super().set_authorizer(callback if callback is not None else lambda *args: sqlite3.SQLITE_OK)
        self.advisor_authorizer = callback


MUTATIONS = {getattr(sqlite3, name) for name in (
    'SQLITE_INSERT', 'SQLITE_UPDATE', 'SQLITE_DELETE', 'SQLITE_CREATE_TABLE',
    'SQLITE_DROP_TABLE', 'SQLITE_ALTER_TABLE', 'SQLITE_CREATE_TRIGGER',
    'SQLITE_DROP_TRIGGER', 'SQLITE_CREATE_INDEX', 'SQLITE_DROP_INDEX',
    'SQLITE_CREATE_VIEW', 'SQLITE_DROP_VIEW', 'SQLITE_CREATE_TEMP_TABLE',
    'SQLITE_DROP_TEMP_TABLE', 'SQLITE_CREATE_TEMP_TRIGGER', 'SQLITE_DROP_TEMP_TRIGGER',
    'SQLITE_CREATE_TEMP_INDEX', 'SQLITE_DROP_TEMP_INDEX', 'SQLITE_CREATE_TEMP_VIEW',
    'SQLITE_DROP_TEMP_VIEW', 'SQLITE_CREATE_VTABLE', 'SQLITE_DROP_VTABLE',
    'SQLITE_ATTACH', 'SQLITE_DETACH', 'SQLITE_REINDEX', 'SQLITE_ANALYZE')}
READ_PRAGMAS = {'table_info', 'table_xinfo', 'database_list', 'index_list',
                'index_info', 'index_xinfo', 'foreign_key_list', 'compile_options'}


@contextmanager
def read_only(conn, *, denied=None):
    """Preserve query_only, transactions and any existing authorizer exactly.

    Owned connections use GuardedConnection, enabling nested/composed authorizers.
    Plain caller connections retain their unknown callback; SQLite query_only
    still rejects DML and schema writes, including WITH-backed mutations.
    """
    previous = conn.execute('PRAGMA query_only').fetchone()[0]
    tracked = isinstance(conn, GuardedConnection)
    prior = getattr(conn, 'advisor_authorizer', None)
    def authorize(action, arg1, arg2, database, source):
        # Outer scopes must observe an attempted mutation even when the inner
        # scope denies it and its caller catches the SQLite exception.
        prior_decision = prior(action,arg1,arg2,database,source) if prior else sqlite3.SQLITE_OK
        prohibited = action in MUTATIONS or (
            action == sqlite3.SQLITE_PRAGMA and
            str(arg1).lower() not in READ_PRAGMAS and
            not (str(arg1).lower() == 'query_only' and arg2 is None))
        if prohibited:
            if denied is not None:
                denied.append({'opcode': action, 'object': arg1, 'argument': arg2})
            return sqlite3.SQLITE_DENY
        return prior_decision
    if not previous: conn.execute('PRAGMA query_only=ON')
    if tracked: conn.set_authorizer(authorize)
    try:
        yield conn
    finally:
        if tracked: conn.set_authorizer(prior)
        # An enclosing guard still requires ON; avoid a forbidden setter in it.
        if not previous: conn.execute('PRAGMA query_only=OFF')

