"""Complete named followups and native generation consumers for Black Empire."""
import json
from pathlib import Path

from hs_sim.engine.effects import (AddToHand, Buff, CopyMinion, Damage, DamageBatch,
    RandomDamage, RandomDestroy, RandomForceAttack)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    DamageKind, EndTurnSpec, Keyword, SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack, living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

DANCER, RECKONING, HALLS, RIFT, NEGOTIATOR, DEVOURER, HAMMER, TANK, BOARS, BLOOM, HUNTER, TIGER = (
    'BE_152', 'BE_153', 'BE_183', 'BE_220', 'BE_256', 'BE_264', 'BE_349',
    'BE_550', 'BE_730', 'BE_802', 'BE_998', 'BE_999')
BLESSING, FINAL, ELEMENTAL, BOAR, PLANT, BUG = (
    'BE_152t', 'BE_153t', 'BE_349t', 'BE_730t', 'BE_802t', 'BE_002')
ROOTS = COLLECTIBLE_ROOTS = (DANCER, RECKONING, HALLS, RIFT, NEGOTIATOR, DEVOURER,
    HAMMER, TANK, BOARS, BLOOM, HUNTER, TIGER)
DEPENDENCIES = (BLESSING, FINAL, ELEMENTAL, BOAR, PLANT, BUG)
PREFIX = 'cards.black_empire_followups.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/black-empire-followups-v1.json'
BATCH_HASH = '82b889a819ee3cd55caa40410a08a3b52c8a6263909cf72aca04917634667c04'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            tuple(r['record']['id'] for r in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards']+data['dependencies'])):
        raise TargetValidationError('Black Empire followups require twelve full roots and six original dependencies')
    return data


def register_black_empire_followup_cards(registry):
    data = load_batch()
    if next(r['record'] for r in data['cards'] if r['record']['id'] == HALLS)['tags'].get('349') != 1:
        raise TargetValidationError('Halls lost its original ImmuneToSpellpower declaration')
    def summon(c, cid):
        return SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c))

    def twice(c, cid):
        request = summon(c, cid)
        return (request, request)

    def damage_all(c, amount):
        return DamageBatch(tuple(Damage(eid, amount, c.source_id, DamageKind.SPELL)
            for eid in minions(c, registry, 3-c.player_id)))

    def halls(c):
        if c.cast is None:
            raise ResolutionError('Halls of Origination requires its actual original Spell cast')
        return (RandomSplitDamage(c.player_id, c.cast.id, c.source_id, 8, spell_bonus_multiplier=0),
            SummonFromPool(c.player_id, 'constructed.minions',
                PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=8, max_cost=8),
                source_id=c.source_id, cause=SummonCause.capture(c)))

    def outcast_card(c):
        return GenerateFromPool(c.player_id, 'constructed.cards',
            PoolQuery(collectible=True, keywords_all=(Keyword.OUTCAST,)), source_id=c.source_id)

    def outcast(c):
        if c.spell_conditions is None:
            raise ResolutionError('Blind Mindflayer requires original accepted Outcast conditions')
        return (outcast_card(c),) if c.spell_conditions.outcast else ()

    def hammer(c):
        row = completed_attack(c)
        if (row is None or row.source_kind != CardType.HERO or row.declaration.player_id != c.player_id or
                row.combat is None or row.combat.weapon_id != c.source_id): return ()
        return twice(c, ELEMENTAL)

    def tank(c):
        if not living_source(c): return ()
        copy = CopyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id,
            cause=SummonCause.capture(c))
        return (copy, copy)

    def hunter(c):
        event = c.event
        if event is None or event.kind != 'damage_dealt' or event.target_id != c.source_id or event.amount <= 0:
            return ()
        return (RandomDestroy(minions(c, registry, 3-c.player_id), c.source_id),)

    def tiger(c):
        if c.event is None or c.event.kind != 'turn_started' or not living_source(c): return ()
        return (RandomForceAttack((c.source_id,), characters(c, registry, 3-c.player_id), c.source_id),)

    bodies = dict(
        dancer=lambda c: (AddToHand(c.player_id, BLESSING, c.source_id),),
        blessing=lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        reckoning=lambda c: (damage_all(c, 1), AddToDeck(c.player_id, FINAL, source_id=c.source_id)),
        final=lambda c: (damage_all(c, 3),), halls=halls,
        rift=lambda c: (GenerateFromPool(c.player_id, 'constructed.cards',
            PoolQuery(kinds=(CardType.SPELL,), collectible=True, spell_schools=(SpellSchool.SHADOW,)),
            count=2, source_id=c.source_id),),
        negotiator=lambda c: (CastFromPool(c.player_id, 'constructed.cards',
            PoolQuery(kinds=(CardType.SPELL,), collectible=True, min_cost=3, max_cost=3), source_id=c.source_id),),
        outcast=outcast, devourer_death=lambda c: (outcast_card(c),), hammer=hammer, tank=tank,
        tank_death=lambda c: (RandomDamage(characters(c, registry, 3-c.player_id), 3, c.source_id, DamageKind.MINION_ABILITY),),
        boars=lambda c: twice(c, BOAR),
        bloom=lambda c: (AddToHand(c.player_id, PLANT, c.source_id), AddToHand(c.player_id, PLANT, c.source_id)),
        plant=lambda c: (summon(c, BUG),), hunter=hunter, tiger=tiger)
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    spell_bodies = {RECKONING: 'reckoning', HALLS: 'halls', RIFT: 'rift', BOARS: 'boars',
        BLOOM: 'bloom', BLESSING: 'blessing', FINAL: 'final'}
    keywords = {HALLS: (Keyword.LIFESTEAL,), FINAL: (Keyword.LIFESTEAL,), DEVOURER: (Keyword.OUTCAST,),
        ELEMENTAL: (Keyword.RUSH,), BOAR: (Keyword.CHARGE,), BUG: (Keyword.TAUNT,), HUNTER: (Keyword.ELUSIVE,)}
    for row in data['cards']+data['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); fields = {}
        if kind == CardType.MINION: fields.update(attack=raw['attack'], health=raw['health'])
        elif kind == CardType.WEAPON: fields.update(attack=raw['attack'], durability=raw['health'])
        else: fields.update(spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), on_play=PREFIX+spell_bodies[cid])
        if cid == BLESSING: fields['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if cid == DANCER: fields['triggers'] = (TriggerSpec('turn_ended', PREFIX+'dancer', EndTurnSpec()),)
        elif cid == NEGOTIATOR: fields.update(battlecry=PREFIX+'negotiator', deathrattle=PREFIX+'negotiator')
        elif cid == DEVOURER: fields.update(on_play=PREFIX+'outcast', deathrattle=PREFIX+'devourer_death')
        elif cid == HAMMER: fields['triggers'] = (TriggerSpec('attack_finished', PREFIX+'hammer'),)
        elif cid == TANK: fields.update(battlecry=PREFIX+'tank', deathrattle=PREFIX+'tank_death')
        elif cid == PLANT: fields['deathrattle'] = PREFIX+'plant'
        elif cid == HUNTER: fields['triggers'] = (TriggerSpec('damage_dealt', PREFIX+'hunter'),)
        elif cid == TIGER: fields['triggers'] = (TriggerSpec('turn_started', PREFIX+'tiger'),)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], keywords=keywords.get(cid, ()),
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
