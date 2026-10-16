"""Ravenous Devilsaur separates one destruction from its Kindred rewards."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.kindred import repeat_components
from hs_sim.engine.model import CardDefinition, CardType, KindredProfile, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import CompleteDestructionBuff, DestroyCapturedMinion, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

DEVILSAUR = 'TLC_829'
PREFIX = 'cards.native_kindred_destruction.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-kindred-destruction-v1.json'
BATCH_HASH = '06632b275eb1b8de99f5e8d0ba67af7616b2e8cf0777b218b4c24b753911a372'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['dependencies']
            or tuple(x['record']['id'] for x in data['cards']) != (DEVILSAUR,)):
        raise TargetValidationError('Unreviewed native Kindred destruction source')
    row = data['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Incomplete original Devilsaur source')
    return data


def original_live_minion(entity):
    return (entity is not None and entity.kind == CardType.MINION and entity.zone == Zone.BOARD
            and entity.active and entity.health > 0 and not entity.doomed)


def register_native_kindred_destruction_cards(registry):
    def victim(c):
        if c.kindred is None or c.kindred.card_id != DEVILSAUR:
            raise ValueError('Devilsaur requires its original Kindred acceptance')
        original = c.kindred.original
        target = original.state.entities.get(original.target_id)
        return (original, target) if original_live_minion(target) else (original, None)

    def prepare(c):
        _, target = victim(c)
        destruction = () if target is None else (DestroyCapturedMinion(MinionReference.capture(target), c.source_id),)
        return (*destruction, *repeat_components(c))

    def active(c):
        original, target = victim(c)
        if target is None or not original_live_minion(original.source):
            return ()
        return (CompleteDestructionBuff(MinionReference.capture(target), MinionReference.capture(original.source),
            original.state.next_death_id, target.attack, target.health, c.source_id),)

    registry.register_behavior(PREFIX+'wrapper', lambda c: ())
    registry.register_behavior(PREFIX+'prepare', prepare)
    registry.register_behavior(PREFIX+'active', active)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health'],
            raw['tags'].get('BATTLECRY'), raw['tags'].get('KINDRED')) != ('MINION', True, 7, 3, 3, 1, 1):
        raise TargetValidationError('Unreviewed original Devilsaur face')
    card = CardDefinition(DEVILSAUR, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=replace(metadata_from_record(raw), deck_identity=DEVILSAUR), battlecry=PREFIX+'wrapper',
        targeting=TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(DEVILSAUR, 'body', wrapper=PREFIX+'wrapper',
        prepare=PREFIX+'prepare', active=PREFIX+'active'))
