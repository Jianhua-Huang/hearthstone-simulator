"""Spirit of the Mountain: six distinct physical plays, existing Ashalon reward."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.minion_type_history import AdvanceQuestFromPlayedTypes
from hs_sim.engine.model import CardDefinition, CardType, Keyword, QuestSpec, QuestStageSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import RACES, metadata_from_record, validate_race_pin

CARD, REWARD = 'TLC_229', 'TLC_229t14'
PREFIX = 'cards.spirit_of_the_mountain.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-menagerie-quest-v1.json'
BATCH_HASH = '31ab8c3241e2f0a1c977c2cd3238a4d699bb3b2e6eda704412b96c27b20c8436'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [CARD] or
            [x['record']['id'] for x in data['existing_dependencies']] != [REWARD] or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'] + data['existing_dependencies'])):
        raise TargetValidationError('Spirit of the Mountain lost complete fixed source materials')
    validate_race_pin()
    if (tuple(data['types']) != tuple(sorted(set(RACES.values()) - {'all'})) or
            data['race_source']['mapping'] != {str(k): v for k, v in RACES.items()}):
        raise TargetValidationError('Spirit of the Mountain lost its complete reviewed type universe')
    return data


def register_native_menagerie_quest_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Spirit of the Mountain changed its complete Ashalon dependency')
    types = tuple(data['types'])
    def progress(c):
        if c.event is None or c.event.kind != 'card_played' or c.event.player_id != c.player_id: return ()
        record = play_record(c.state, dict(c.event.data)['play_id'])
        if (record.source_id, record.player_id, record.completed) != (c.event.source_id, c.player_id, True):
            raise ResolutionError('Spirit of the Mountain lost its original completed play')
        if record.kind != CardType.MINION: return ()
        old = c.source.quest_progress
        return (AdvanceQuestFromPlayedTypes(c.source_id, old.id, old.stage, types),)
    registry.register_behavior(PREFIX + 'progress', progress)
    registry.register_behavior(PREFIX + 'reward', lambda c: (AddToHand(c.player_id, REWARD, c.source_id),))
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags']['QUEST_PROGRESS_TOTAL']) != ('SPELL', 1, 6):
        raise TargetValidationError('Unreviewed Spirit of the Mountain goal')
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=1, keywords=(Keyword.QUEST,),
        spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw),
        quest=QuestSpec('quest', (QuestStageSpec(CARD, 6, ('card_played',), PREFIX + 'progress', PREFIX + 'reward'),)))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
