"""Dissolving Ooze produces physical Bones carrying the original victim's stats."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.destruction_spell_values import DestroyMinionForStatSpell, SpellStatGrantProfile
from hs_sim.engine.effects import Buff
from hs_sim.engine.model import CardDefinition, CardType, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, BONES = 'TLC_252', 'TLC_829t'
PREFIX = 'cards.destruction_bones.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/destruction-bones-v1.json'
BATCH_HASH = '648fbe8ce0342ffdee9b094c8c6fe202fd552185f875e25a085646052b5575ff'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (BONES,)):
        raise TargetValidationError('Unreviewed complete destruction/Bones source')
    for row in data['cards'] + data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original destruction/Bones source')
    return data


def register_destruction_bones_card(registry):
    def dissolve(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION or
                not target.active or target.doomed or target.health <= 0): return ()
        return (DestroyMinionForStatSpell(c.player_id, c.source_id, MinionReference.capture(target), BONES),)

    def bones(c):
        ability = c.cast.native_spell_value if c.cast is not None else None
        if ability is None or ability.kind != 'spell_stat_value' or ability.spell_stat_value.card_id != BONES:
            raise UnsupportedDefinitionError('Bones lacks its original bound Attack and Health')
        value = ability.spell_stat_value
        return (Buff(c.target_id, value.attack, value.health, c.source_id),)

    registry.register_behavior(PREFIX+'dissolve', dissolve)
    registry.register_behavior(PREFIX+'bones', bones)
    data = load_batch()
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; root = raw['id'] == CARD
        card = CardDefinition(raw['id'], raw['name'], CardType.MINION if root else CardType.SPELL,
            cost=raw['cost'], attack=raw.get('attack') or 0, health=raw.get('health') or 0,
            metadata=replace(metadata_from_record(raw), deck_identity=raw['id']),
            battlecry=PREFIX+'dissolve' if root else None,
            on_play=None if root else PREFIX+'bones',
            targeting=TargetSpec(TargetMode.IF_AVAILABLE if root else TargetMode.REQUIRED,
                zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly' if root else 'any'))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_value_profile(SpellStatGrantProfile(BONES, CARD))
