"""Escape the Underfel combines original Temporary plays and the existing Rift."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interactables import InstallInteractable
from hs_sim.engine.model import CardDefinition, CardType, InteractableSpec, Keyword, QuestSpec, QuestStageSpec, Rarity
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard, SummonFromCandidates
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT, REWARD, OBJECT = 'TLC_446', 'TLC_446t', 'TLC_446t1'
BEASTS = ('TLC_446t2', 'TLC_446t3', 'TLC_446t4')
PREFIX = 'cards.underfel_rift.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/underfel-rift-v1.json'
BATCH_HASH = '8ae95e7ef19ab1f16b3fb3bf08491b39c406093ff634525c06304fe302ea4e91'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    expected = {'cards': (ROOT,), 'dependencies': (REWARD, OBJECT),
        'existing_dependencies': BEASTS, 'evidence_only': ('TLC_446e',), 'skipped': ()}
    if (canonical_digest(data) != BATCH_HASH or any(
            tuple(x['record']['id'] for x in data[k]) != ids for k, ids in expected.items())):
        raise TargetValidationError('Underfel requires its complete quest, spell, object and Fel Beasts')
    for key in expected:
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Underfel complete original row changed')
    quest = data['cards'][0]['record']
    spell, obj = (x['record'] for x in data['dependencies'])
    if ((quest['type'], quest['cost'], quest['tags'].get('QUEST_PROGRESS_TOTAL'),
         quest['tags'].get('QUEST_REWARD_DATABASE_ID')) != ('SPELL', 1, 6, spell['dbf_id']) or
            (spell['type'], spell['cost'], spell['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')) !=
                ('SPELL', 5, obj['dbf_id']) or
            (obj['type'], obj['cost'], obj['attack'], obj['health']) != ('MINION', 5, None, 1) or
            data['task']['numeric_normalizations'] != {OBJECT: {'attack': 0}} or
            data['metadata_overrides'] != {OBJECT: {'rarity': 'legendary'}} or obj['tags'].get('ELITE') != 1 or
            any(obj['tags'].get(k) != 1 for k in ('UNTOUCHABLE', 'INTERACTABLE_OBJECT', 'CAN_TARGET_CARDS_IN_HAND'))):
        raise TargetValidationError('Underfel lost its original six-play quest and five-mana inert reward')
    return data


def register_underfel_rift_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Underfel changed an existing complete Fel Beast dependency')
    def progress(c):
        if c.event is None or c.event.kind != 'card_played' or c.event.player_id != c.player_id:
            return ()
        played = play_record(c.state, dict(c.event.data)['play_id'])
        if (played.source_id, played.player_id, played.completed) != (c.event.source_id, c.player_id, True):
            raise ResolutionError('Underfel lost its original completed physical hand play')
        if played.submitted_cost is None:
            raise ResolutionError('Underfel requires the original submitted hand qualification')
        if played.submitted_cost.quote.quote_input.hand_lifetime is None:
            return ()
        q = c.source.quest_progress
        return (AdvanceQuest(c.source_id, q.id, q.stage),)
    def summon(c):
        cause = SummonCause.capture(c)
        return tuple(SummonFromCandidates(c.player_id, BEASTS, c.source_id, cause=cause) for _ in range(2))
    registry.register_behavior(PREFIX+'progress', progress)
    registry.register_behavior(PREFIX+'reward', lambda c: (AddToHand(c.player_id, REWARD, c.source_id),))
    registry.register_behavior(PREFIX+'open', lambda c: (InstallInteractable(c.player_id, OBJECT, c.source_id),))
    registry.register_behavior(PREFIX+'summon', summon)
    raw = data['cards'][0]['record']; spell, obj = (x['record'] for x in data['dependencies'])
    cards = (
        CardDefinition(ROOT, raw['name'], CardType.SPELL, cost=1, keywords=(Keyword.QUEST,),
            metadata=metadata_from_record(raw), quest=QuestSpec('quest', (
                QuestStageSpec(ROOT, 6, ('card_played',), PREFIX+'progress', PREFIX+'reward'),))),
        CardDefinition(REWARD, spell['name'], CardType.SPELL, cost=5, on_play=PREFIX+'open',
            metadata=metadata_from_record(spell)),
        CardDefinition(OBJECT, obj['name'], CardType.MINION, cost=5, health=1, corpse_value=0,
            interactable=InteractableSpec(PREFIX+'summon'),
            # Its ELITE characteristic is confirmed by the official35.6
            # Medivh's Triumph fix; absent crafting rarity is not this rule.
            metadata=replace(metadata_from_record(obj), rarity=Rarity.LEGENDARY)),
    )
    for card in cards:
        registry.register_card(card)
        if card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
