"""Seven real C'Thun family roots, fixed client rules and explicit CN conflicts."""
import json
from pathlib import Path

from hs_sim.engine.ability_families import (AbilityFamilyProfile, ChooseFamilyAbilities,
    TriggerFamilyAbility, context_record, request_from_context)
from hs_sim.engine.effects import Damage, RandomBuff, SplitDamage, Summon, AddCostModifier
from hs_sim.engine.held_spells import SHADOW_CASTS, shadow_casts, satisfied
from hs_sim.engine.model import (ActivatedAbilitySpec, CardDefinition, CardType, CostSpec,
    DamageKind, HandProgressSpec, Keyword, PlayerEffectSpec, SpellSchool, SummonStats,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.rituals import from_expiry
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

GOD, DEACON, SPAWN, RUMBLER, RITUAL, LASH, LESSON = (
    'BE_013', 'BE_012', 'BE_014', 'BE_204', 'BE_726', 'BE_771', 'BE_778')
ROOTS = (GOD, DEACON, SPAWN, RUMBLER, RITUAL, LASH, LESSON)
SKILLS = tuple('BE_013t'+str(n) for n in range(1,5))
FANATIC = 'BE_013t5'
FAMILY = 'cthun.empire'
PREFIX = 'cards.empire_cthun.'
PROGRAM = PREFIX+'ritual'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/support/empire-cthun-primary-audit.json'
BATCH_HASH = '3665100e08073502055858d57f09cfc98c0bb0a9ae3f055630f16472697f1d33'
PROGRESS = HandProgressSpec('spell_cast', goal=2, condition_id=SHADOW_CASTS)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['roots']) != ROOTS or
            tuple(data['dependencies']) != (*SKILLS, FANATIC) or
            set(data['records']) != set((*ROOTS, *SKILLS, FANATIC)) or
            any(canonical_digest(v['record']) != v['record_sha256'] for v in data['records'].values()) or
            data['all_primary_faces_verified'] is not False or data['cn_calibrated'] is not False):
        raise TargetValidationError('Cthun requires complete fixed records and preserves unresolved CN primary conflicts')
    return data


def register_empire_cthun_cards(registry):
    records = {cid: value['record'] for cid, value in load_batch()['records'].items()}
    registry.register_trigger_condition(SHADOW_CASTS, lambda c: shadow_casts(c, registry))
    def choose(c, count=1):
        return (ChooseFamilyAbilities(request_from_context(c, FAMILY, SKILLS[0]), count=count),)
    def ritual_expire(c):
        from_expiry(c)
        return choose(c)
    def deacon(c):
        return choose(c) if satisfied(c) else ()
    def spawn(c):
        return choose(c) if GOD in c.state.players[c.player_id].original_deck else ()
    def lash(c):
        if c.event is None or c.event.source_id != c.state.players[c.player_id].hero_id:
            return ()
        return (AddCostModifier(c.player_id, CostSpec(delta=-1, card_ids=(GOD,)),
                source_id=c.source_id), *choose(c))
    def wrath(c):
        row = context_record(c)
        kind = DamageKind.MINION_ABILITY if row.request.source.kind == CardType.MINION else DamageKind.EFFECT
        return (SplitDamage(3-c.player_id, 7*row.multiplier, c.source_id, kind=kind,
                            ability_trigger_id=row.id),)
    def domain(c):
        row = context_record(c)
        ids = tuple(i for i in c.state.players[c.player_id].board if i != c.source_id)
        return (RandomBuff(ids, 2*row.multiplier, 3*row.multiplier, c.source_id, count=2),)
    def gaze(c):
        row = context_record(c)
        if c.target_id is None: return ()
        kind = DamageKind.MINION_ABILITY if row.request.source.kind == CardType.MINION else DamageKind.EFFECT
        return (Damage(c.target_id, 5*row.multiplier, c.source_id, kind, ability_trigger_id=row.id),)
    def servants(c):
        row = context_record(c)
        return tuple(Summon(c.player_id, FANATIC,
            stats=SummonStats(2*row.multiplier, 3*row.multiplier)) for _ in range(2))
    bodies = (wrath, domain, gaze, servants)
    for cid, body in zip(SKILLS, bodies):
        registry.register_behavior(PREFIX+cid, body)
        registry.register_behavior(PREFIX+'native.'+cid, lambda c, cid=cid:
            (TriggerFamilyAbility(request_from_context(c, FAMILY, cid, native=True)),))
    for suffix, body in (('choose', choose), ('deacon', deacon), ('spawn', spawn), ('lash', lash),
            ('lesson', lambda c: choose(c, 2)),
            ('ritual_expire', ritual_expire)):
        registry.register_behavior(PREFIX+suffix, body)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, RITUAL, kind='ritual', duration=2,
        tick_event='turn_started', on_expire=PREFIX+'ritual_expire'))
    for cid in (*ROOTS, *SKILLS, FANATIC):
        raw = records[cid]; kind = CardType(raw['type'].lower())
        kwargs = dict(cost=raw['cost'] if raw['cost'] is not None else 0,
                      metadata=metadata_from_record(raw))
        if kind == CardType.MINION: kwargs.update(attack=raw['attack'], health=raw['health'])
        if cid == GOD:
            kwargs.update(keywords=(Keyword.OLD_GOD,), activated_abilities=tuple(
                ActivatedAbilitySpec(skill, PREFIX+'native.'+skill, card_id=skill,
                    targeting=TargetSpec(TargetMode.REQUIRED, kinds=(CardType.MINION,), relation='enemy')
                    if skill == SKILLS[2] else None) for skill in SKILLS))
        elif cid == DEACON: kwargs.update(hand_progress=PROGRESS, battlecry=PREFIX+'deacon')
        elif cid == SPAWN: kwargs.update(battlecry=PREFIX+'spawn')
        elif cid == RUMBLER: kwargs.update(keywords=(Keyword.TAUNT,), battlecry=PREFIX+'choose')
        elif cid == RITUAL: kwargs.update(ongoing_effect_id=PROGRAM, spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']])
        elif cid == LASH: kwargs.update(attack=raw['attack'], durability=raw['health'],
            triggers=(TriggerSpec('attack_finished', PREFIX+'lash'),))
        elif cid == LESSON: kwargs.update(on_play=PREFIX+'lesson', spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']])
        elif cid == FANATIC: kwargs.update(keywords=(Keyword.TAUNT,))
        elif cid in SKILLS:
            kwargs.update(choice_only=True)
        card = CardDefinition(cid, raw['name'], kind, **kwargs)
        registry.register_card(card)
        if cid not in SKILLS: registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_ability_family_profile(AbilityFamilyProfile(FAMILY, GOD, SKILLS,
        tuple(PREFIX+cid for cid in SKILLS), ROOTS[1:], ((), (), (Keyword.LIFESTEAL,), ())))
