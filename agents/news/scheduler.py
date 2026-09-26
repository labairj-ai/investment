"""Daily Eastern-time news slots, with durable bounded retries."""
from agents.news.brief import read_json, atomic_json

SLOTS = [('06', 6), ('12', 12), ('17', 17)]
RETRY_SECONDS = 300
MAX_ATTEMPTS = 3


def run_due_refresh(now, path, refresh):
    due = [label for label, hour in SLOTS if now.hour >= hour]
    if not due:
        return None
    day, slot = now.date().isoformat(), due[-1]
    prior = read_json(path)
    same = prior.get('day') == day and prior.get('slot') == slot
    if same and (prior.get('status') == 'ready' or
                 prior.get('attempts', 0) >= MAX_ATTEMPTS or
                 now.timestamp()-prior.get('attempted_epoch', 0) < RETRY_SECONDS):
        return None
    state = {'day':day, 'slot':slot, 'status':'running',
             'attempts':prior.get('attempts',0)+1 if same else 1,
             'attempted_epoch':now.timestamp()}
    atomic_json(path, state)
    try:
        result = refresh(slot, day)
    except Exception:
        result = False
    state['status'] = 'ready' if result is True else 'error'
    if result is None:  # Another worker owns the refresh; retry without spending an attempt.
        state['attempts'] -= 1
    atomic_json(path, state)
    return state
