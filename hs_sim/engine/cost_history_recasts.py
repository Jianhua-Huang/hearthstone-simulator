"""Finite printed-cost history groups required by The Galactic Projection Orb."""
from dataclasses import MISSING, fields, replace

from .automatic_targets import AutomaticTargetPreference
from .pools import PoolQuery


def validate_spec(spec):
    if spec.distinct != 'cost' and spec.selection != 'cost_ascending':return
    from .spell_history import SpellHistoryQuery
    allowed = {'player_id','query','distinct','selection','source_id','target_preference'}
    if any(field.name not in allowed and field.default is not MISSING and
            getattr(spec,field.name) != field.default for field in fields(spec)):
        raise ValueError('Each-cost history cannot borrow unrelated targeting, counts or repeat policies')
    if (spec.distinct != 'cost' or spec.selection != 'cost_ascending' or spec.source_id is None or
            spec.target_preference is not AutomaticTargetPreference.ENEMY_IF_AVAILABLE or
            len(spec.query.cards.exclude_card_ids) != 1 or
            spec.query != SpellHistoryQuery(cards=PoolQuery(exclude_card_ids=spec.query.cards.exclude_card_ids))):
        raise ValueError('Each-cost history requires frozen own successful spells and its explicit self exclusion')


def validate_progress(state,registry,batch,*,allow_pending=False):
    """Validate original groups and actual child roots, without repricing history."""
    from .spell_history import historical_groups, spell_history_candidates
    validate_spec(batch.spec)
    if batch.before_id > len(state.cast_history)+1:
        raise ValueError('Cost-history boundary cannot enter the future')
    original = spell_history_candidates(state,registry,batch.spec.player_id,
        replace(batch.spec.query,before_id=batch.before_id),batch.spec.source_id)
    if tuple(c.id for c in original) != batch.initial_cast_ids:
        raise ValueError('Cost-history batch changed its complete original eligible cast prefix')
    groups = historical_groups(registry,original,'cost')
    consumed = len(groups)-batch.remaining
    if not 0 <= consumed <= len(groups):raise ValueError('Cost-history progress changed its original group count')
    outstanding = tuple(sorted(c.id for group in groups[consumed:]for c in group))
    if batch.cast_ids != outstanding:
        raise ValueError('Cost-history progress clipped, split or reordered an original cost group')
    children = tuple(c for c in state.cast_history if c.id >= batch.before_id and
        c.origin == 'history' and c.caster_id == batch.spec.source_id)
    if len(children) != consumed:
        raise ValueError('Cost-history progress lost or duplicated an actual original recast root')
    for index,(child,group)in enumerate(zip(children,groups)):
        if child.player_id != batch.spec.player_id or child.recast_id not in {c.id for c in group}:
            raise ValueError('Cost-history recast borrowed a different player, cost or original spell')
        if not child.completed and (not allow_pending or index != len(children)-1):
            raise ValueError('Later cost selection cannot precede completion of the original recast')
