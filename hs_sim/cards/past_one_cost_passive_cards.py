"""Historical passive consumers of existing health, cost and attribute rules."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier, Damage, Draw, ModifyWeapon, RandomBuff
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import is_overheal
from hs_sim.engine.model import (
    CardDefinition, CardType, CostSpec, DamageKind, EndTurnSpec, EquippedWeaponReference,
    HealthFlow, Keyword, StatRelationLayer, StatRelationOperand, StatRelationSpec, TriggerSpec,
)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions


BLOOD_IMP, CHICKEN, WITCH_IMP, SEEKER, TOTEM, SPACE_PIRATE, NORTHSHIRE, CLERGY, WYRM, TIME_WYRM, MASSAGER, CORSAIR = (
    'CS2_059', 'EX1_009', 'GIL_608', 'LOE_116', 'REV_839', 'GDB_333',
    'CS2_235', 'CS3_014', 'NEW1_012', 'WON_031', 'VAC_512', 'NEW1_025')
LEAVES = (BLOOD_IMP, CHICKEN, WITCH_IMP, SEEKER, TOTEM, SPACE_PIRATE,
    NORTHSHIRE, CLERGY, WYRM, TIME_WYRM, MASSAGER, CORSAIR)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_passive.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-passive-v1.json'
BATCH_HASH = 'a09fd3f46c3cac47e13803ddb1e0e8aa3e07bfbfa2ce835c2eea3e14f757cb75'
CHICKEN_ATTACK = StatRelationSpec(operand=StatRelationOperand.SELF_DAMAGED,
    layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=5)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != LEAVES or
            any(data[key] for key in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            data['numeric_normalizations'] != {BLOOD_IMP: {'attack': 0}, TOTEM: {'attack': 0}} or
            canonical_digest(data['native_stat_relations']) != canonical_digest({CHICKEN: asdict(CHICKEN_ATTACK)}) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in data['dependencies'])):
        raise TargetValidationError('Historical passives lost their complete pinned bodies and native relation')
    return data


def register_past_one_cost_passive_cards(registry):
    def random_health(c, amount, exclude_source=False):
        candidates = tuple(i for i in minions(c, registry, c.player_id)
            if not exclude_source or i != c.source_id)
        return (RandomBuff(candidates, health=amount, source_id=c.source_id),)

    def seeker(c):
        others = tuple(i for i in c.state.players[c.player_id].board if i != c.source_id and
            (e := c.state.entities[i]).kind == CardType.MINION and e.health > 0 and not e.doomed and
            registry.card(e.card_id).interactable is None)
        return (BuffCapturedMinion(MinionReference.capture(c.source), 4, 4, c.source_id),) if len(others) == 6 else ()

    def northshire(c):
        result = c.health_result
        if result is None:
            raise ResolutionError('Northshire Cleric requires its original settled health result')
        return (Draw(c.player_id, 1, c.source_id),) if (
            result.flow == HealthFlow.HEALING.value and result.target_kind == CardType.MINION.value and result.healed > 0) else ()

    def wyrm(c):
        cast = cast_record(c.state, dict(c.event.data)['cast_id'])
        if (cast.source_id, cast.player_id, cast.target_id) != (c.event.source_id, c.event.player_id, c.event.target_id):
            raise ResolutionError('Mana Wyrm lost its original completed spell')
        if (cast.player_id != c.player_id or not living_source(c) or not cast.completed or
                not cast.payload_started or cast.failure is not None or cast.interrupted):
            return ()
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack=1, source_id=c.source_id),)

    def massager(c):
        if c.event.target_id != c.source_id or c.event.amount <= 0:
            return ()
        return (Damage(c.state.players[c.player_id].hero_id, c.event.amount,
            c.source_id, DamageKind.MINION_ABILITY),)

    def corsair(c):
        weapon_id = c.state.players[3-c.player_id].weapon_id
        return () if weapon_id is None else (ModifyWeapon(
            EquippedWeaponReference.capture(c.state.entities[weapon_id]), durability=-1, source_id=c.source_id),)

    bodies = {
        BLOOD_IMP: lambda c: random_health(c, 1, True),
        WITCH_IMP: lambda c: random_health(c, 2), SEEKER: seeker,
        TOTEM: lambda c: (BuffCapturedMinion(MinionReference.capture(c.source), health=1, source_id=c.source_id),),
        SPACE_PIRATE: lambda c: (AddCostModifier(c.player_id,
            CostSpec(delta=-1, card_types=(CardType.WEAPON,)), uses_remaining=1, source_id=c.source_id),),
        NORTHSHIRE: northshire,
        CLERGY: lambda c: (Draw(c.player_id, 1, c.source_id),) if is_overheal(c.event, c.source_id) else (),
        WYRM: wyrm, TIME_WYRM: wyrm, MASSAGER: massager, CORSAIR: corsair,
    }
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid, body)
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(raw['health']) is not int or cid not in (BLOOD_IMP, TOTEM) and type(raw['attack']) is not int):
            raise TargetValidationError('Historical passive lost its actual printed minion body')
        fields = {}
        if cid in (BLOOD_IMP, WITCH_IMP):
            fields['keywords'] = (Keyword.STEALTH,)
        if cid in (BLOOD_IMP, TOTEM):
            fields['triggers'] = (TriggerSpec('turn_ended', PREFIX + cid, EndTurnSpec()),)
        elif cid == CHICKEN:
            fields['stat_relations'] = (CHICKEN_ATTACK,)
        elif cid in (WITCH_IMP, SPACE_PIRATE):
            fields['deathrattle'] = PREFIX + cid
        elif cid in (SEEKER, CORSAIR):
            fields['battlecry'] = PREFIX + cid
        else:
            event = ('health_resolved' if cid in (NORTHSHIRE, CLERGY) else
                'spell_cast_finished' if cid in (WYRM, TIME_WYRM) else 'damage_dealt')
            fields['triggers'] = (TriggerSpec(event, PREFIX + cid),)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1,
            attack=0 if cid in (BLOOD_IMP, TOTEM) else raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
