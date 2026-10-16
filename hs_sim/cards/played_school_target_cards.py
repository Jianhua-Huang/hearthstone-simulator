"""A real conditional Battlecry using the player's original played-school input."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Destroy
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool, TargetMode, TargetSpec, Zone
from hs_sim.engine.play_history import played_cards, spell_schools_from_plays
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/played-school-targets-v1.json'
BATCH_HASH = 'c9a1a8e840b46054b4043d26c772c2d44e2dca8520437d31913dfd5bcbe40137'
BLAZER = 'CATA_EVENT_002'
PREFIX = 'cards.played_school_targets.'
FIELD = 'spell_schools_played_this_turn'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Played-school target lost its complete reviewed source pin')
    if tuple(row['record']['id'] for row in data['cards']) != (BLAZER,) or data['dependencies']:
        raise TargetValidationError('Unreviewed played-school target roots or dependencies')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Played-school target complete source row changed')
    return data


def register_played_school_target_cards(registry):
    data = load_batch()

    def fire_input(c):
        return SpellSchool.FIRE.value in c.observation['players'][c.player_id - 1][FIELD]

    def blazer(c):
        schools = spell_schools_from_plays(played_cards(c.state, c.player_id, turn=c.state.turn))
        return (Destroy(c.target_id, c.source_id),) if c.target_id is not None and SpellSchool.FIRE in schools else ()

    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'fire_this_turn', 'v1'), fire_input)
    registry.register_behavior(PREFIX+'blazer', blazer)
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'], raw['tags'].get('BATTLECRY')) != (
            'MINION', 3, 4, 3, True, 1):
        raise TargetValidationError('Unreviewed Baleful Blazer face')
    card = CardDefinition(BLAZER, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=PREFIX+'blazer',
        targeting=TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,), exclude_source=False),
        target_rule=PREFIX+'fire_this_turn', metadata=replace(metadata_from_record(raw), deck_identity=BLAZER))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
