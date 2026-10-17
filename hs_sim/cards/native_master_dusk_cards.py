"""Five real shuffle operations and the original Ninja's direct death return."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.dead_minion_shuffles import ShuffleDeadMinion
from hs_sim.engine.deck_shuffles import INSERT_EVENTS, shuffled
from hs_sim.engine.effects import AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, Keyword, PlayerEffectSpec,
    QuestSpec, QuestStageSpec, TriggerSpec)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-master-dusk-v1.json'
BATCH_HASH = '6b5328f98d4514c72d67f10fa3dab63967b29a210386e80e3fe207d86005672f'
QUEST, DUSK, POWER, NINJA = 'TLC_513', 'TLC_513t', 'TLC_513hp', 'TLC_513t2'
PREFIX = 'cards.master_dusk.'
PROGRAM = PREFIX + 'ninjas'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (QUEST, DUSK) or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (POWER, NINJA)):
        raise TargetValidationError('Master Dusk lost its complete reviewed source scope')
    if any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'] + data['existing_dependencies']):
        raise TargetValidationError('Master Dusk complete original face changed')
    return data


def register_native_master_dusk_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin['sha256']:
            raise TargetValidationError('Master Dusk requires its complete original dependency: ' + cid)

    def progress(c):
        if c.event is None or c.event.kind not in INSERT_EVENTS or c.event.player_id != c.player_id:
            return ()
        marker = dict(c.event.data).get('deck_insertion')
        if marker is None or marker[0] != 'random':
            return ()
        row = c.state.deck_shuffle_history[marker[1] - 1]
        if row.actor_id is None:
            raise UnsupportedDefinitionError('Lie in Wait requires the original issuer of this shuffle')
        if row.actor_id != c.player_id or row.player_id != c.player_id or row.event_sequence != c.event.sequence:
            return ()
        q = c.source.quest_progress
        return (AdvanceQuest(c.source_id, q.id, q.stage, key='shuffle-' + str(row.id)),)

    def battlecry(c):
        request = SummonByCard(c.player_id, (SummonEntryMaterial(NINJA),), SummonCause.capture(c))
        return request, request, AddPlayerEffect(c.player_id, PROGRAM, c.source_id)

    def return_ninja(c):
        if c.player_effect is None:
            raise ResolutionError('Ninja death return lost its original player program')
        if c.event is None or c.event.kind != 'minion_died' or c.event.player_id != c.player_id:
            return ()
        death_id = dict(c.event.data).get('death_id')
        death = next((d for d in c.state.death_history if type(death_id) is int and d.id == death_id), None)
        if death is None:
            raise ResolutionError('Ninja death return lost its original physical death')
        if death.card_id != NINJA or death.controller != c.player_id:
            return ()
        if death.entity_id != c.event.target_id:
            raise ResolutionError('Ninja death return changed its original recipient')
        card = SourceAllocationFact.capture(c.state, c.state.entities[death.entity_id])
        return shuffled(c, (ShuffleDeadMinion(card, death, c.player_id, c.source_id),))

    registry.register_behavior(PREFIX + 'progress', progress)
    registry.register_behavior(PREFIX + 'reward', lambda c: (AddToHand(c.player_id, DUSK, c.source_id),))
    registry.register_behavior(PREFIX + 'battlecry', battlecry)
    registry.register_behavior(PREFIX + 'return_ninja', return_ninja)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, DUSK,
        triggers=(TriggerSpec('minion_died', PREFIX + 'return_ninja'),)))
    for row in data['cards']:
        raw = row['record']; cid = raw['id']
        if cid == QUEST:
            if (raw['type'], raw['cost'], raw['tags'].get('QUEST_PROGRESS_TOTAL')) != ('SPELL', 1, 5):
                raise TargetValidationError('Unreviewed Lie in Wait printed face')
            card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=1,
                metadata=metadata_from_record(raw), keywords=(Keyword.QUEST,),
                quest=QuestSpec('quest', (QuestStageSpec(cid, 5, tuple(sorted(INSERT_EVENTS)),
                    PREFIX + 'progress', PREFIX + 'reward'),)))
        else:
            if (raw['type'], raw['cost'], raw['health'], raw['tags'].get('ARMOR'),
                    raw['tags'].get('HERO_POWER')) != ('HERO', 3, 30, 8, 119197):
                raise TargetValidationError('Unreviewed Master Dusk printed face')
            card = CardDefinition(cid, raw['name'], CardType.HERO, cost=3, health=30,
                metadata=metadata_from_record(raw), hero_card=True, hero_armor=8,
                initial_hero_power=POWER, battlecry=PREFIX + 'battlecry')
        registry.register_card(card)
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
