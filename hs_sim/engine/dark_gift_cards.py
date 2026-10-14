"""Two pinned real sources over an explicitly limited representative minion pool."""
import json
from pathlib import Path

from hs_sim.targets import TargetValidationError, canonical_digest
from .dark_gifts import dark_gift_pool
from .model import CardDefinition, CardType, CostSpec, Keyword, SpellSchool
from .pools import DiscoverFromPool, PoolCard, PoolDefinition, PoolMember, PoolQuery


INVENTORY_HASH = '9e2bd089c273012e543d97eaad81d73887c14a4b994bd66ed0668d5c1ef5e269'
MINION_POOL_ID = 'representative.dark_gift_minions'


def register_representatives(registry, generation_target):
    from .representative import metadata_from_record
    data = json.loads((Path(__file__).resolve().parents[2]/'data/support/dark-gifts-core.json').read_text(encoding='utf-8'))
    if canonical_digest(data) != INVENTORY_HASH:
        raise TargetValidationError('Dark Gift adapter requires its pinned card records')
    records = {row['id']: row for row in data['records']}
    for cid in ('CS2_118', 'CS2_125', 'CS2_127'):
        raw = records[cid]
        registry.register_card(CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw),
            keywords=(Keyword.TAUNT,) if raw['tags'].get('TAUNT') else ()))
    gifts = dark_gift_pool(generation_target)
    query = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current')
    registry.register_behavior('dark_gifts.creature', lambda c: (
        DiscoverFromPool(c.player_id, MINION_POOL_ID,
            PoolQuery(kinds=(CardType.MINION,), min_cost=3, max_cost=3,
                      collectible=True, class_mode='current'), source_id=c.source_id, gift_pool=gifts),))
    registry.register_behavior('dark_gifts.cremate', lambda c: (
        DiscoverFromPool(c.player_id, MINION_POOL_ID, query, source_id=c.source_id,
                         cost=CostSpec(delta=-2), gift_pool=gifts),))
    for cid, body in (('EDR_105', 'dark_gifts.creature'), ('FIR_900', 'dark_gifts.cremate')):
        raw = records[cid]
        registry.register_card(CardDefinition(cid, raw['name'],
            CardType.MINION if cid == 'EDR_105' else CardType.SPELL,
            cost=raw['cost'], attack=raw.get('attack', 0) or 0, health=raw.get('health', 0) or 0,
            metadata=metadata_from_record(raw), battlecry=body if cid == 'EDR_105' else None,
            on_play=body if cid == 'FIR_900' else None, spell_school=SpellSchool.FIRE if cid == 'FIR_900' else None))
    members = tuple(data['representative_minions'])
    for cid in members:
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(registry.card(cid)))
    registry.register_pool(PoolDefinition(MINION_POOL_ID, 'representative-dark-gift-minions-v1',
        generation_target, 'experimental', tuple(PoolMember(cid) for cid in members), complete=False))
