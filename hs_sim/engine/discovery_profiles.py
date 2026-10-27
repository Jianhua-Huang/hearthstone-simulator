"""Finite selected-copy and board-entry policies required by real spells."""
from dataclasses import MISSING, fields, replace

from .model import CardType, Keyword


def validate_spec(spec):
    from .pools import PoolQuery
    if type(spec.summon_copies) is not int or spec.summon_copies not in (1,2):
        raise ValueError('Selected discovery copies require one or two original entries')
    if type(spec.entry_keywords) is not tuple or spec.entry_keywords not in ((),(Keyword.TAUNT,Keyword.ELUSIVE)) or any(
            type(k) is not Keyword for k in spec.entry_keywords):
        raise ValueError('Discovery entry boons require the original Taunt and Elusive pair')
    active = (spec.summon_copies==2,bool(spec.entry_keywords))
    if not any(active): return
    if sum(active) != 1:
        raise ValueError('Independent finite discovery policies cannot be combined')
    allowed = {'player_id','pool_id','query','source_id','prompt','policy','destination','cause','discoveries',
        'summon_copies','entry_keywords'}
    for field in fields(spec):
        if field.name not in allowed and field.default is not MISSING and getattr(spec,field.name) != field.default:
            raise ValueError('Finite discovery policy borrowed unrelated delivery or reward fields')
    if spec.source_id is None or type(spec.query) is not PoolQuery:
        raise ValueError('Finite discovery policy requires its actual source and complete query')
    spec.query.__post_init__()
    q = spec.query
    if (spec.destination!='board' or spec.cause is None or q.min_cost is None or q.min_cost!=q.max_cost or
            replace(q,min_cost=None,max_cost=None)!=PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current') or
            spec.discoveries != (1 if spec.summon_copies==2 else 2)):
        raise ValueError('Selected copies and entry boons require their original fixed-cost board discovery shape')
