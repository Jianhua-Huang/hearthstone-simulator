"""Mend the Timeline consumes its actual generated Holy spell costs."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.generated_spell_healing import GenerateSpellsAndHeal
from hs_sim.engine.model import CardDefinition, CardType, Keyword, RewindSpec, SpellSchool
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-generated-cost-heal-v1.json'
BATCH_HASH = '33292e5e5d4719f1069ed75ce77d8330df5e0b6010d44457ba5e68b9dd44b50b'
MEND = 'TIME_018'
BODY = 'cards.native_generated_cost_heal.mend'
POOL_ID = 'constructed.cards'
HOLY = PoolQuery(kinds=(CardType.SPELL,), collectible=True, spell_schools=(SpellSchool.HOLY,))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (MEND,) or
            any(d[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            canonical_digest(d['cards'][0]['record']) != d['cards'][0]['record_sha256']):
        raise TargetValidationError('Mend the Timeline requires its complete pinned source')
    return d


def register_native_generated_cost_heal_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('REWIND'), SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))) != (
            'SPELL', 3, 1, SpellSchool.HOLY):
        raise TargetValidationError('Mend the Timeline requires its actual Holy Rewind spell face')

    def body(c):
        if c.cast is None:
            raise ResolutionError('Mend the Timeline requires its actual physical spell cast')
        return (GenerateSpellsAndHeal(c.player_id, c.cast.id, c.source_id, POOL_ID, HOLY, 2),)

    registry.register_behavior(BODY, body)
    card = CardDefinition(MEND, raw['name'], CardType.SPELL, cost=raw['cost'],
        keywords=(Keyword.REWIND,), rewind=RewindSpec(), spell_school=SpellSchool.HOLY,
        metadata=metadata_from_record(raw), on_play=BODY)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
