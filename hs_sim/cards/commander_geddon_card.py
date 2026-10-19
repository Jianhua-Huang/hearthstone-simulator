"""Geddon's permanent player program replaces only the scheduled turn draw."""
import json
from pathlib import Path

from hs_sim.engine.effects import Draw
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, PlayerEffectSpec, Zone
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.turn_start_draws import TurnDrawReplacementProfile
from hs_sim.engine.zones import ChooseFromZone, HAND_TYPES
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_591'
PROGRAM = 'cards.commander_geddon.program'
INSTALL = 'cards.commander_geddon.install'
DRAW = 'cards.commander_geddon.draw'
PROMPT = '从你的牌库中发现一张牌；其余候选被摧毁'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/commander-geddon-v1.json'
BATCH_HASH = '7460360467b1550f647eef5c7e417e3bbcf5e9f4caf30fc6af30dc6dff93e1fc'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('CATA_591e', 'CATA_591e2') or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            (data['policy']['offered'], data['policy']['cost_delta']) != (3, -3)):
        raise TargetValidationError('Geddon lost its complete source and native draw recipe')
    for row in (*data['cards'], *data['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Geddon original source pin changed')
    return data


def register_commander_geddon_card(registry):
    raw = load_batch()['cards'][0]['record']
    registry.register_behavior(INSTALL, lambda c: (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),))
    def draw(c):
        instance = c.player_effect
        if (instance is None or instance.spec_id != PROGRAM or c.state.active_player != c.player_id or
                instance not in c.state.players[c.player_id].player_effects):
            raise ValueError('Geddon requires its captured scheduled owner-draw program')
        if not c.state.players[c.player_id].deck:
            return (Draw(c.player_id),)
        return (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, query=PoolQuery(kinds=HAND_TYPES),
            operation='take', sample_size=3, distinct='entity', source_id=c.source_id, prompt=PROMPT,
            discovery=True, cost=CostSpec(delta=-3), destroy_unchosen=True),)
    registry.register_behavior(DRAW, draw)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], battlecry=INSTALL, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, CARD))
    registry.register_turn_draw_replacement_profile(TurnDrawReplacementProfile(PROGRAM, DRAW))
