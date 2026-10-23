"""Real historical reaction and continuous-stat consumers; no inferred Past pool."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.cross_zone import MinionScope, minion_references
from hs_sim.engine.effects import Damage, Destroy, EquipWeapon, GainArmor
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (
    AuraSpec, CardDefinition, CardType, DamageKind, Keyword, StatRelationLayer,
    StatRelationOperand, StatRelationSpec, TriggerSpec, Zone,
)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_minion_keywords import RandomGrantMinionKeywords
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record


ANOMALY, TILLER, SELFLESS, MATE, ORACLE, TIDECALLER, BUCCANEER, COGMASTER, OFFERING, ROVER = (
    'KAR_036', 'ICC_468', 'OG_221', 'OG_312', 'EX1_508',
    'EX1_509', 'CFM_325', 'GVG_013', 'TRL_516', 'BOT_059')
LEAVES = (ANOMALY, TILLER, SELFLESS, MATE, ORACLE, TIDECALLER, BUCCANEER, COGMASTER, OFFERING, ROVER)
HOOK = 'OG_058'
DEPENDENCIES = LEAVES + (HOOK,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_reactive.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-reactive-v1.json'
BATCH_HASH = 'fd6711fd71150ce2dc5e799493b546f2fae0eeda7d00dd83e796d0c43e0f2266'
RELATIONS = {
    BUCCANEER: StatRelationSpec(operand=StatRelationOperand.CONTROLLER_HAS_WEAPON,
        layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=2),
    COGMASTER: StatRelationSpec(operand=StatRelationOperand.CONTROLLER_HAS_MECH,
        layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=2),
}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            any(data[key] for key in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            data['numeric_normalizations'] != {OFFERING: {'attack': 0}} or
            canonical_digest(data['native_stat_relations']) != canonical_digest({k: asdict(v) for k, v in RELATIONS.items()}) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in data['dependencies'])):
        raise TargetValidationError('Historical reactions lost their complete sources and native relations')
    return data


def register_past_one_cost_reactive_cards(registry):
    data = load_batch()

    def anomaly(c):
        cast = cast_record(c.state, dict(c.event.data)['cast_id'])
        if (cast.source_id, cast.player_id, cast.target_id) != (c.event.source_id, c.event.player_id, c.event.target_id):
            raise ResolutionError('Arcane Anomaly lost its original completed spell linkage')
        if (cast.player_id != c.player_id or not living_source(c) or not cast.completed or
                not cast.payload_started or cast.failure is not None or cast.interrupted):
            return ()
        return (BuffCapturedMinion(MinionReference.capture(c.source), health=1, source_id=c.source_id),)

    def tiller(c):
        if c.event.source_id != c.source_id:
            return ()
        window = dict(c.event.data)['window_id']
        rows = [row for row in c.state.character_attack_history if row.declaration.id == window]
        if len(rows) != 1:
            raise ResolutionError('Wretched Tiller lost its original attack declaration')
        row = rows[0]
        if (row.declaration.source_id, row.declaration.target_id, row.declaration.player_id,
                row.declaration_event_cursor + 1) != (c.source_id, c.event.target_id, c.player_id, c.event.sequence):
            raise ResolutionError('Wretched Tiller borrowed another attack window')
        return (Damage(c.state.players[3-c.player_id].hero_id, 2, c.source_id, DamageKind.MINION_ABILITY),)

    def selfless(c):
        # Constructed policy follows the native friendly domain. The historical
        # Battlegrounds-only exclusion is not silently imported into this mode.
        refs = minion_references(c.state, registry, c.player_id, MinionScope(zones=(Zone.BOARD,)), c.source_id)
        return (RandomGrantMinionKeywords(refs, (Keyword.DIVINE_SHIELD,), c.source_id),)

    def tidecaller(c):
        if (c.event.player_id != c.player_id or c.event.target_id == c.source_id or not living_source(c)):
            return ()
        target = c.state.entities[c.event.target_id]
        if not has_any_tribe(registry, target, ('murloc',), basis='current'):
            return ()
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack=1, source_id=c.source_id),)

    def offering(c):
        if c.event.player_id != c.player_id or not living_source(c):
            return ()
        return (Destroy(c.source_id, c.source_id), GainArmor(c.player_id, 8))

    def rover(c):
        if c.event.target_id != c.source_id or c.event.amount <= 0:
            return ()
        return (GainArmor(c.player_id, 2),)

    bodies = {ANOMALY: anomaly, TILLER: tiller, SELFLESS: selfless,
        MATE: lambda c: (EquipWeapon(c.player_id, HOOK),),
        TIDECALLER: tidecaller, OFFERING: offering, ROVER: rover}
    events = {ANOMALY: 'spell_cast_finished', TILLER: 'attack_declared',
        TIDECALLER: 'minion_summoned', OFFERING: 'turn_started', ROVER: 'damage_dealt'}
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid, body)
    for row in data['dependencies']:
        raw = row['record']
        cid = raw['id']
        if (raw['type'] != ('WEAPON' if cid == HOOK else 'MINION') or raw['cost'] != 1 or
                raw['collectible'] != (cid != HOOK) or type(raw['health']) is not int or
                cid != OFFERING and type(raw['attack']) is not int):
            raise TargetValidationError('Historical reaction lost its complete printed body')
        fields = {}
        if cid in events:
            fields['triggers'] = (TriggerSpec(events[cid], PREFIX + cid),)
        elif cid == SELFLESS:
            fields['deathrattle'] = PREFIX + cid
        elif cid == MATE:
            fields['battlecry'] = PREFIX + cid
        elif cid == ORACLE:
            fields['auras'] = (AuraSpec(attack=1, tribes_any=('murloc',)),)
        elif cid in RELATIONS:
            fields['stat_relations'] = (RELATIONS[cid],)
        if cid == HOOK:
            fields['durability'] = raw['health']
        card = CardDefinition(cid, raw['name'], CardType(raw['type'].lower()), cost=1,
            attack=0 if cid == OFFERING else raw['attack'],
            health=raw['health'] if cid != HOOK else 0, metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
