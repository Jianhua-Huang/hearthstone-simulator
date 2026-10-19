"""Chef Neth'rek uses the original opening, owner clock and mana accounts."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.deck_conditions import CheckDeckCondition, DeckCostCeilingCondition
from hs_sim.engine.effects import ChangeManaCrystals, InvokeBehavior, RefreshMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, OpeningHook, PlayerEffectSpec, TriggerSpec
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.player_effects import AddPlayerEffect, ConsumePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'JAIL_860'
PREFIX = 'cards.chef_nethrek.'
PROGRAM = PREFIX+'countdown'
CONDITION = DeckCostCeilingCondition(3, 'printed')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/chef-nethrek-v1.json'
BATCH_HASH = '89dbed5a7b2734f853ef5c5e9dac31435bb8eeeb61cc8eda6de6ed69ace26274'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ROOT,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('JAIL_860e',) or
            data['dependencies'] or data['existing_dependencies']):
        raise TargetValidationError('Chef Nethrek requires its complete original source')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Chef Nethrek row')
    return data


def register_chef_nethrek_card(registry):
    def opening(c):
        window = c.state.opening
        original = () if window is None else window.original_entities[c.player_id-1]
        if (window is None or window.stage != 'dealing' or c.source_id not in original or
                c.state.players[c.player_id].original_deck[original.index(c.source_id)] != ROOT):
            raise ResolutionError('Chef requires its actual original before-deal source')
        return (CheckDeckCondition(c.player_id, CONDITION, (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),)),)

    def deadline(c):
        if c.event is None or c.event.kind != 'turn_ended' or c.event.player_id != c.player_id: return ()
        if c.player_effect is None or c.player_effect.spec_id != PROGRAM:
            raise ResolutionError('Chef lost its original persistent start-of-game instance')
        if current_owner_turn(c.state).owner_index < 5: return ()
        # Consumption, rather than separate remove/execute requests, prevents
        # any later accepted work from repeating an already consumed instance.
        return (ConsumePlayerEffect(c.player_id, c.player_effect,
            (InvokeBehavior(PREFIX+'assign', c.source_id, c.player_id),)),)

    def assign(c):
        # Fresh continuation after original-instance consumption. Earlier end
        # subjects cannot leave an obsolete maximum in the assignment delta.
        player = c.state.players[c.player_id]
        return (ChangeManaCrystals(c.player_id, 10-player.max_mana, filled=True),
                RefreshMana(c.player_id, player.mana_spent))

    registry.register_behavior(PREFIX+'opening', opening)
    registry.register_behavior(PREFIX+'deadline', deadline)
    registry.register_behavior(PREFIX+'assign', assign)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, ROOT,
        triggers=(TriggerSpec('turn_ended', PREFIX+'deadline', EndTurnSpec()),)))
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CHEF_NETHREK_REQUIREMENT')) != ('MINION', 3, 3, 3, 4):
        raise TargetValidationError('Chef changed its real printed face or original internal requirement tag')
    card = CardDefinition(ROOT, raw['name'], CardType.MINION, cost=3, attack=3, health=3,
        opening_hooks=(OpeningHook('before_deal', PREFIX+'opening'),),
        metadata=replace(metadata_from_record(raw), deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
