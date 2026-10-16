"""Reviewed finite damage sequences, original draws and class-resource spells."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage, DamageBatch, Draw, Heal, InvokeBehavior
from hs_sim.engine.herald import Herald
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HealingKind,
                                Keyword, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_sequences import (DamageMinionsDrawDeaths, DecreasingMinionDamage,
                                          DrawWithCostReduction)
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/spell-sequence-effects-v1.json'
BATCH_HASH = '6844da85c563298a08f7d29b6d4f0a6ad6d5cbaf072a4e676b4ee39a7c44275b'
PREFIX = 'cards.spell_sequence.'
SCRIPTS = {'CATA_491': 'tentacles', 'CATA_526': 'last_stand', 'CATA_533': 'flood',
    'CORE_CS2_053': 'far_sight', 'EDR_231': 'embrace', 'CATA_785': 'rite', 'CATA_156': 'animation'}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Spell sequence cards differ from their reviewed full source pin')
    return data


def register_spell_sequence_cards(registry):
    def cast_sequence(c, kind, amount):
        if c.cast is None or c.cast.source_id != c.source_id:
            raise ValueError('Damage sequence requires its actual current SPELL cast')
        return (kind(c.player_id, c.cast.id, c.source_id, amount),)

    def invoke(c, name):
        return InvokeBehavior(PREFIX+name, c.source_id, c.player_id,
                              play_id=None if c.play is None else c.play.id)

    def flood_wave(c):
        # Position uses physical minions, including dormant ends; a dormant end
        # cannot be hit and does not make its inner neighbour become the edge.
        ids = tuple(eid for eid in c.state.players[3-c.player_id].board
            if c.state.entities[eid].kind == CardType.MINION
            and registry.card(c.state.entities[eid].card_id).interactable is None)
        return (DamageBatch(tuple(Damage(eid, 5, c.source_id, DamageKind.SPELL)
            for eid in (ids[0], ids[-1]))),) if ids else ()

    def flood(c):
        return (invoke(c, 'flood_wave'),) * (2 if c.spell_conditions.outcast else 1)

    def rite(c):
        return (Herald(c.player_id, c.source_id),) + ((Damage(c.target_id, 3, c.source_id,
            DamageKind.SPELL),) if c.spell_conditions.combo and c.target_id is not None else ())

    bodies = {
        'tentacles': lambda c: cast_sequence(c, DecreasingMinionDamage, 3),
        'last_stand': lambda c: cast_sequence(c, DamageMinionsDrawDeaths, 1),
        'flood': flood, 'flood_wave': flood_wave,
        'far_sight': lambda c: (DrawWithCostReduction(c.player_id, 3, c.source_id),),
        'embrace': lambda c: (Heal(c.target_id, 4, c.source_id, HealingKind.SPELL),
            Draw(c.player_id, source_id=c.source_id), Imbue(c.player_id, c.source_id)),
        'rite': rite,
        'animation': lambda c: (Herald(c.player_id, c.source_id), invoke(c, 'animation_damage')),
        'animation_damage': lambda c: (DamageBatch(tuple(Damage(eid, 4, c.source_id, DamageKind.SPELL)
            for eid in minions(c, registry, 3-c.player_id))),),
    }
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if (canonical_digest(raw) != row['record_sha256'] or SCRIPTS.get(raw['id']) != recipe['script']
                or raw['type'] != 'SPELL' or not raw['collectible'] or raw['cost'] != recipe['cost']):
            raise TargetValidationError('Spell sequence lost its reviewed complete face')
        kwargs = {}
        if recipe['target'] is not None:
            kwargs['targeting'] = TargetSpec(TargetMode.REQUIRED, zones=(Zone.HERO, Zone.BOARD),
                kinds=(CardType.HERO, CardType.MINION))
        if recipe['target'] == 'combo_character': kwargs['target_condition'] = 'combo'
        definition = CardDefinition(raw['id'], raw['name'], CardType.SPELL, cost=recipe['cost'],
            keywords=tuple(Keyword(value) for value in recipe['keywords']),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']),
            on_play=PREFIX+recipe['script'], **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
