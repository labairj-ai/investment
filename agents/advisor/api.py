"""HTTP-independent request contract shared by the server and integration tests."""
from .service import run_decision
from . import persistence
from .context import build_advisor_decision_context


def decision_response(conn, body, **dependencies):
    if not isinstance(body,dict) or set(body)-{'request','account_id','advisor_decision_id'}:
        raise ValueError('INVALID_DECISION_REQUEST_FIELDS')
    if body.get('account_id') is not None and not isinstance(body['account_id'],str): raise ValueError('INVALID_ACCOUNT_ID')
    return run_decision(conn,body.get('request'),account_id=body.get('account_id'),
                        decision_id=body.get('advisor_decision_id'),**dependencies)


def get_decision(conn, decision_id):
    old=persistence.load(conn,decision_id)
    if old is None: return None
    context=build_advisor_decision_context(conn,account_id=old.get('account_id'))
    return persistence.load(conn,decision_id,context=context,update=True)
