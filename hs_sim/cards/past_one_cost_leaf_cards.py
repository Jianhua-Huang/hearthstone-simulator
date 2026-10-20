"""Historical one-cost behavior candidates; no past membership is inferred."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, SpellSchool, TriggerSpec
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

SQUIRE, RAVEN, SKYTALON, ARCHER, TROGG, KNIGHT = (
    'EX1_008', 'KAR_300', 'LEG_CS3_037', 'AT_059', 'AV_137', 'BAR_873')
DEPENDENCIES = (SQUIRE, RAVEN, SKYTALON, ARCHER, TROGG, KNIGHT)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_leaves.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-leaves-v1.json'
BATCH_HASH = 'f9345a6067ea5a4e160943fc2af734b0afa8b133c811de57cc4c556d957e588e'
HOLY = PoolQuery(kinds=(CardType.SPELL,), spell_schools=(SpellSchool.HOLY,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['dependencies'])):
        raise TargetValidationError('Historical leaves require their six complete reviewed source faces')
    return data


def register_past_one_cost_leaf_cards(registry):
    def archer(c):
        if not living_source(c) or not is_inspire(c.state, c.event, c.player_id) or c.state.players[c.player_id].hand:
            return ()
        return (Damage(c.state.players[3-c.player_id].hero_id, 2, c.source_id, DamageKind.MINION_ABILITY),)

    def trogg(c):
        record = cast_record(c.state, dict(c.event.data)['cast_id'])
        if (record.source_id, record.player_id, record.target_id) != (c.event.source_id, c.event.player_id, c.event.target_id):
            raise ResolutionError('Irondeep Trogg lost its original completed spell linkage')
        if (record.player_id != 3-c.player_id or not record.completed or not record.payload_started or
                record.failure is not None or record.interrupted or not living_source(c)):
            return ()
        return (SummonByCard(c.player_id, (SummonEntryMaterial(TROGG),), SummonCause.capture(c)),)

    registry.register_behavior(PREFIX+'archer', archer)
    registry.register_behavior(PREFIX+'trogg', trogg)
    registry.register_behavior(PREFIX+'knight', lambda c: (DrawMatching(c.player_id, HOLY, 'skip', source_id=c.source_id),))
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Historical leaves lost their actual printed minion bodies')
        if cid == SQUIRE: fields['keywords'] = (Keyword.DIVINE_SHIELD,)
        elif cid == SKYTALON: fields['keywords'] = (Keyword.RUSH,)
        elif cid == ARCHER: fields['triggers'] = (TriggerSpec('hero_power_used', PREFIX+'archer'),)
        elif cid == TROGG: fields['triggers'] = (TriggerSpec('spell_cast_finished', PREFIX+'trogg'),)
        elif cid == KNIGHT: fields['battlecry'] = PREFIX+'knight'
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1,
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
