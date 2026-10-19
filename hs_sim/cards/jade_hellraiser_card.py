"""Lotus Troublemaker composes stored progress and ordinary split packets."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind,
    HandProgressSpec, PaymentType, Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'JAIL_470'
PREFIX = 'cards.lotus_troublemaker.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/jade-hellraiser-v1.json'
BATCH_HASH = '092d29eb8e4c3d4763bc48082b1bf2660f687f0ad127407101a61f3a98d036a3'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ROOT,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Lotus Troublemaker requires its complete original source')
    return data


def register_jade_hellraiser_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'],
            raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'), raw['tags'].get('BATTLECRY')) != ('MINION', 3, 2, 2, 1, 1):
        raise TargetValidationError('Lotus Troublemaker changed its original native shot count')
    progress = HandProgressSpec('event', 1, on_complete=PREFIX+'counted', repeat=True,
        event='card_played', condition_id=PREFIX+'two_mana', zone=(Zone.HAND, Zone.DECK))

    def two_mana(c):
        event = c.event
        if event is None or event.kind != 'card_played': return False
        play_id = dict(event.data).get('play_id')
        if play_id is None: return False
        play = play_record(c.state, play_id)
        return (play.completed and play.player_id == c.player_id and play.source_id == event.source_id
                and play.payment == PaymentType.MANA and play.cost == 2)

    def body(c):
        if c.battlecry is None or c.battlecry.payload.card_id != ROOT:
            raise ResolutionError('Lotus shots require their actual accepted Battlecry')
        a = progress_ability(c.source)
        count = raw['tags']['TAG_SCRIPT_DATA_NUM_1']
        if a is not None and a.hand_progress == progress:
            count += a.progress_completions
        # c.source belongs to the original detached Battlecry context. The
        # complete amount is fixed before the first packet and its reactions.
        return (RandomSplitDamage(c.player_id, None, c.source_id, count,
            profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),)

    registry.register_trigger_condition(PREFIX+'two_mana', two_mana)
    registry.register_behavior(PREFIX+'counted', lambda c: ())
    registry.register_behavior(PREFIX+'body', body)
    card = CardDefinition(ROOT, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=PREFIX+'body',
        hand_progress=progress, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if ROOT not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
