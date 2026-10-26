"""Actual acquired past spells with physical recruitment and ranked resurrection."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery, Resurrect, SummonFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOTS = ('SCH_610', 'VAC_948')
PREFIX = 'cards.past_recruit_resurrection.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-recruit-resurrection-v1.json'
BATCH_HASH = '5cb72e97c39f2effb8e9d5673509b61afb0334cc397d59796f0520f862916bde'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            tuple(x['record']['id'] for x in value['cards']) != ROOTS or value['dependencies'] or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            len(value['official_faces']) != 4 or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in value['cards'])):
        raise TargetValidationError('Past recruit/resurrection spells lost their complete native source scope')
    return value


def register_past_recruit_resurrection(registry):
    value = load_batch()
    if any(cid in registry.cards for cid in ROOTS):
        raise TargetValidationError('Past recruit/resurrection cannot replace existing native identities')

    def rush(c):
        return (GrantCapturedKeyword(MinionReference.capture(c.state.entities[c.target_id]),
            Keyword.RUSH, c.source_id),)

    bodies = {
        'SCH_610': lambda c: (SummonFromZone(c.player_id, 2,
            query=PoolQuery(kinds=(CardType.MINION,), max_cost=5, tribes_any=('beast',)),
            source_id=c.source_id, cause=SummonCause.capture(c), cost_basis='local',
            on_summon=PREFIX+'rush'),),
        'VAC_948': lambda c: (Resurrect(c.player_id, 3,
            query=DeathQuery(cards=PoolQuery(keywords_all=(Keyword.TAUNT,)),
                keywords_at_death=True, cost_basis='printed'),
            distinct='card', selection='highest_cost', source_id=c.source_id,
            cause=SummonCause.capture(c)),),
        'rush': rush,
    }
    for key, body in bodies.items(): registry.register_behavior(PREFIX+key, body)
    for row in value['cards']:
        raw = row['record']
        card = CardDefinition(raw['id'], raw['name'], CardType.SPELL, cost=raw['cost'],
            metadata=metadata_from_record(raw), spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            on_play=PREFIX+raw['id'])
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
