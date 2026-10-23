"""The Forbidden Sequence and its full original offered-card weapon reward."""
import json
from pathlib import Path

from hs_sim.engine.discovery_delivery import COMPLETED, original_recipient
from hs_sim.engine.effects import AddToHand, ModifyWeapon
from hs_sim.engine.model import (CardDefinition, CardType, EquippedWeaponReference,
    Keyword, QuestSpec, QuestStageSpec, TriggerSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.whole_card_replays import PlayDiscoveredOptions
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, REWARD = 'TLC_460', 'TLC_460t'
PREFIX = 'cards.origin_stone.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-origin-stone-v1.json'
BATCH_HASH = 'da749622d4597d93c7bf1040d320850b128b6b0715b127948fec44549d9beb09'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [CARD]
            or [x['record']['id'] for x in data['dependencies']] != [REWARD]
            or any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards'] + data['dependencies'])):
        raise TargetValidationError('Origin Stone lost its complete reviewed source and reward')
    return data


def register_native_origin_stone_cards(registry):
    data = load_batch()
    def progress(c):
        if c.event.player_id != c.player_id: return ()
        original_recipient(c.state, c.event)
        old = c.source.quest_progress
        return (AdvanceQuest(c.source_id, old.id, old.stage,
            key='discovery:' + str(dict(c.event.data)['discovery_id'])),)
    def play_options(c):
        if c.event.player_id != c.player_id: return ()
        recipient = original_recipient(c.state, c.event)
        if recipient is not None and recipient.kind == CardType.HERO_POWER:
            return ()
        return (PlayDiscoveredOptions(c.player_id, c.source_id, dict(c.event.data)['discovery_id']),
            ModifyWeapon(EquippedWeaponReference.capture(c.source), durability=-1, source_id=c.source_id))
    registry.register_behavior(PREFIX + 'progress', progress)
    registry.register_behavior(PREFIX + 'reward', lambda c: (AddToHand(c.player_id, REWARD, c.source_id),))
    registry.register_behavior(PREFIX + 'play_options', play_options)
    quest = data['cards'][0]['record']; weapon = data['dependencies'][0]['record']
    if (quest['cost'], quest['tags']['QUEST_PROGRESS_TOTAL'], weapon['cost'], weapon['attack'], weapon['health']) != (1, 8, 3, None, 8):
        raise TargetValidationError('Unreviewed Forbidden Sequence goal or weapon stats')
    definitions = (
        CardDefinition(CARD, quest['name'], CardType.SPELL, cost=1, keywords=(Keyword.QUEST,),
            metadata=metadata_from_record(quest), quest=QuestSpec('quest', (
                QuestStageSpec(CARD, 8, (COMPLETED,), PREFIX + 'progress', PREFIX + 'reward'),))),
        CardDefinition(REWARD, weapon['name'], CardType.WEAPON, cost=3, durability=8,
            metadata=metadata_from_record(weapon), triggers=(TriggerSpec(COMPLETED, PREFIX + 'play_options'),)),
    )
    for definition in definitions:
        registry.register_card(definition)
        if definition.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(definition))
