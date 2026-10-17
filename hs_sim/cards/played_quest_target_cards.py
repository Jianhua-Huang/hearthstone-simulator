"""A real conditional Battlecry using complete own committed Quest plays."""
import json
from pathlib import Path
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, TargetMode, TargetSpec, Zone
from hs_sim.engine.play_history import played_cards, quests_from_plays
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/played-quest-targets-v1.json'
BATCH_HASH = '5b295486ff6178ac7c7b3e02e6d96c005f11c5d763c2b7fd34d62604d2b0b8dd'
ASSISTANT = 'TLC_987'
FIELD = 'quests_played_total'
PREFIX = 'cards.played_quest_targets.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ASSISTANT,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Played-Quest target lost its full reviewed source')
    if canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']:
        raise TargetValidationError('Played-Quest target full raw row changed')
    return data


def register_played_quest_target_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != (
            'MINION', 2, 3, 2, 1):
        raise TargetValidationError('Questing Assistant lost its native conditional Battlecry face')

    def condition(c):
        return c.observation['players'][c.player_id - 1][FIELD] > 0

    def assistant(c):
        if c.target_id is None or not quests_from_plays(played_cards(c.state, c.player_id), registry):
            return ()
        return (Damage(c.target_id, 3, c.source_id, DamageKind.MINION_ABILITY),)

    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'played_quest', 'v1'), condition)
    registry.register_behavior(PREFIX+'assistant', assistant)
    card = CardDefinition(ASSISTANT, raw['name'], CardType.MINION, cost=2, attack=3, health=2,
        metadata=metadata_from_record(raw), battlecry=PREFIX+'assistant',
        target_rule=PREFIX+'played_quest', targeting=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
