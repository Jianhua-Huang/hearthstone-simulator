"""Lakkari's story delegates three owner ends to native discard and named fill."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, PlayerEffectSpec, TriggerSpec
from hs_sim.engine.ordered_group_batches import FillBoardWithCard
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import DiscardMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TLC_466'
IMP = 'UNG_829t3'
SPEC = 'cards.lakkari_story.objective'
BODY = 'cards.lakkari_story.owner_end'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-lakkari-story-v1.json'
BATCH_HASH = 'ca7f9641585cb74b22f9d979b860f33a8f2036c1589b7fe1f6b53e2d527752d2'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (IMP,) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards'] + data['existing_dependencies'])):
        raise TargetValidationError('Lakkari requires its complete reviewed story and actual existing Imp')
    return data


def register_native_lakkari_story_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('OBJECTIVE'), raw['tags'].get('QUEST_PROGRESS_TOTAL'),
            raw['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')) != ('SPELL', 7, 1, 3, 42753):
        raise TargetValidationError('Lakkari lost its native three-turn objective or named child')
    def body(c):
        if c.player_effect is None or c.player_effect.spec_id != SPEC:
            raise ValueError('Lakkari end body requires its original captured objective instance')
        return (DiscardMatching(c.player_id, source_id=c.source_id),
                FillBoardWithCard(c.player_id, IMP, SummonCause.capture(c)))
    registry.register_behavior(BODY, body)
    registry.register_player_effect(PlayerEffectSpec(SPEC, CARD, kind='objective', duration=3,
        tick_event='turn_ended', triggers=(TriggerSpec('turn_ended', BODY, EndTurnSpec()),)))
    definition = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'],
        metadata=metadata_from_record(raw), ongoing_effect_id=SPEC)
    registry.register_card(definition)
    registry.register_pool_card(PoolCard.from_definition(definition))
