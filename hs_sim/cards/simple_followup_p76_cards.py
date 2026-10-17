"""Actual Rune consumers and complete ordinary older five-cost dependencies."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, GainArmor, Heal, SpendResource
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HealingKind, Keyword,
    Resource, TargetSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import DeathQuery, death_candidates
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .original_material_cards import direct_death

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p76-v1.json'
BATCH_HASH = 'bd1559022bf0dbf5c36099e6a158e69291f46cf0ca413ebaa80ba1fee8a98d77'
HEMATURGE, MORTICIAN, STRIKE = 'CORE_RLK_066', 'CORE_RLK_116', 'RLK_025'
PIT, DOG, BODYGUARD, KNIGHT, MAIDEN, HEALBOT, NIGHTBLADE, COMMANDO, SQUIRE = (
    'AT_101', 'GVG_070', 'CS2_187', 'CS2_151', 'GVG_053', 'GVG_069', 'EX1_593', 'CS2_150', 'CS2_152')
COLLECTIBLE_ROOTS = (HEMATURGE, MORTICIAN, STRIKE)
DEPENDENCIES = (PIT, DOG, BODYGUARD, KNIGHT, MAIDEN, HEALBOT, NIGHTBLADE, COMMANDO, SQUIRE)
ROOTS = (*COLLECTIBLE_ROOTS, *DEPENDENCIES)
PREFIX = 'cards.simple_followup_p76.'
POOL_ID = 'constructed.cards'
QUERIES = {rune: PoolQuery(collectible=True, runes_any=(rune,)) for rune in ('blood', 'unholy', 'frost')}


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['existing_dependencies'] or d['skipped']
            or tuple(x['record']['id'] for x in d['cards']) != COLLECTIBLE_ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES):
        raise TargetValidationError('P76 complete reviewed source scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for key in ('cards', 'dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P76 complete original row changed')
    return d


def register_simple_followup_p76_cards(registry):
    d = load_batch()

    def discover(c, rune):
        return DiscoverFromPool(c.player_id, POOL_ID, QUERIES[rune], source_id=c.source_id)

    def hematurge(c):
        return (SpendResource(c.player_id, Resource.CORPSES, 1, on_success=(discover(c, 'blood'),)),)

    def mortician(c):
        previous = next((row for row in reversed(c.state.owner_turn_history)
            if row.player_id == c.player_id and row.closed), None)
        first_turn = 1 if previous is None else previous.turn+1
        rows = death_candidates(c.state, registry, c.player_id, DeathQuery(min_turn=first_turn))
        # Validate every frozen fact in the original window before aggregating.
        matches = tuple(has_any_tribe(registry, row, ('undead',)) for row in rows)
        return (discover(c, 'unholy'),) if any(matches) else ()

    def strike(c):
        return (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL, PREFIX+'strike_result'),)

    def strike_result(c):
        return (InvokeHealthResult(PREFIX+'strike_after', c.event),)

    def strike_after(c):
        return (discover(c, 'frost'),) if direct_death(c) is not None else ()

    bodies = dict(hematurge=hematurge, mortician=mortician, strike=strike,
        strike_result=strike_result, strike_after=strike_after,
        knight=lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(SQUIRE),), SummonCause.capture(c)),),
        maiden=lambda c: (GainArmor(c.player_id, 5),),
        healbot=lambda c: (Heal(c.state.players[c.player_id].hero_id, 8, c.source_id, HealingKind.EFFECT),),
        nightblade=lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 3, c.source_id, DamageKind.MINION_ABILITY),),
        commando=lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.MINION_ABILITY),))
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    battlecries = {HEMATURGE:'hematurge', MORTICIAN:'mortician', KNIGHT:'knight', MAIDEN:'maiden',
        HEALBOT:'healbot', NIGHTBLADE:'nightblade', COMMANDO:'commando'}
    for item in (*d['cards'], *d['dependencies']):
        raw = item['record']; cid = raw['id']; kw = {}
        if cid in battlecries: kw['battlecry'] = PREFIX+battlecries[cid]
        if cid == BODYGUARD: kw['keywords'] = (Keyword.TAUNT,)
        if cid == COMMANDO: kw['targeting'] = TargetSpec()
        if cid == STRIKE:
            kw.update(on_play=PREFIX+'strike', targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
                spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
        minion = raw['type'] == 'MINION'
        definition = CardDefinition(cid, raw['name'], CardType.MINION if minion else CardType.SPELL,
            cost=raw['cost'], attack=raw['attack'] if minion else 0, health=raw['health'] if minion else 0,
            metadata=metadata_from_record(raw), **kw)
        registry.register_card(definition)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(definition))
