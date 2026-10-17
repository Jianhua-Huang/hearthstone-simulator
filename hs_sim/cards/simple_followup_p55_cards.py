"""Original Osk continuations, exact followups and all-Mana location casting."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, Heal, HealBatch, InvokeBehavior, RandomDamage, SpendMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, DamageKind, Zone
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference, SetCapturedMinionStats
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.zones import CardReference, DrawMatching, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p55-v1.json'
BATCH_HASH = 'a34bf3b0c2397825f73306dc53f291fb47eefef601c8bb1d3c26d1c6158b1da4'
DISCOVER = 'TLC_452t4'
DISCOUNT = 'TLC_452t5'
SET = 'TLC_452t16'
SUMMON = 'TLC_452t20'
BURST = 'TLC_452t22'
SWEEP = 'TLC_452t27'
WEAPON = 'TLC_452t32'
SCOUT = 'CORE_EX1_506a'
TYRANT = 'CS3_002t'
DRAKE = 'EDR_846t5'
SHRINE = 'EDR_520'
ROOTS = (DISCOVER, DISCOUNT, SET, BURST, SWEEP, WEAPON, SCOUT, TYRANT, DRAKE, SHRINE)
SKIPPED = (SUMMON,)
PARENTS = ('TLC_452', 'CORE_EX1_506', 'CS3_002', 'EDR_846')
PREFIX = 'cards.simple_followup_p55.'
POOL_ID = 'constructed.cards'
DEATHRATTLES = PoolQuery(kinds=(CardType.MINION,), collectible=True, deathrattle=True)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['skipped']) != SKIPPED
            or tuple(x['record']['id'] for x in data['evidence_only']) != PARENTS
            or data['dependencies'] or data['existing_dependencies']):
        raise TargetValidationError('P55 complete original ten definitions and deferred pool entry changed')
    for section in ('cards', 'skipped', 'evidence_only'):
        for row in data[section]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P55 complete original source row changed')
    return data


def register_simple_followup_p55_cards(registry):
    def self_buff(c, attack, health):
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack, health, c.source_id),) if c.source.zone == Zone.BOARD else ()

    def discount(c):
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].hand
                     if c.state.entities[i].kind == CardType.MINION)
        return tuple(ModifyStoredCost(ref, CostSpec(delta=-2), c.source_id) for ref in refs)

    def set_enemies(c):
        return tuple(SetCapturedMinionStats(MinionReference.capture(c.state.entities[i]), 2, 2, c.source_id)
                     for i in minions(c, registry, 3 - c.player_id))

    def random_enemy(c):
        return (RandomDamage(characters(c, registry, 3 - c.player_id), 4, c.source_id, DamageKind.MINION_ABILITY),)

    def sweep(c):
        hits = tuple(Damage(i, 3, c.source_id, DamageKind.MINION_ABILITY)
                     for i in characters(c, registry, 3 - c.player_id))
        return (DamageBatch(hits), InvokeBehavior(PREFIX + 'heal_friends', c.source_id, c.player_id))

    def heal_friends(c):
        return (HealBatch(tuple(Heal(i, 6, c.source_id) for i in characters(c, registry, c.player_id))),)

    def shrine(c):
        return (SpendMana(c.player_id, None, c.source_id, PREFIX + 'mana_result'),)

    def mana_result(c):
        result = c.mana_result
        if result is None or (result.player_id, result.source_id, result.requested) != (c.player_id, c.source_id, None):
            raise ResolutionError('Shrine requires its complete original all-Mana debit result')
        query = PoolQuery(kinds=(CardType.SPELL,), collectible=True, min_cost=result.actual, max_cost=result.actual)
        return (CastFromPool(c.player_id, POOL_ID, query, source_id=c.source_id),)

    bodies = {
        DISCOVER: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, DEATHRATTLES, source_id=c.source_id, cost=CostSpec(delta=-3)),),
        DISCOUNT: discount, SET: set_enemies,
        BURST: lambda c: (*self_buff(c, 2, 1), InvokeBehavior(PREFIX + 'random_enemy', c.source_id, c.player_id)),
        SWEEP: sweep,
        WEAPON: lambda c: (*self_buff(c, 2, 2), DrawMatching(c.player_id, PoolQuery(kinds=(CardType.WEAPON,)), 'skip', source_id=c.source_id)),
        SHRINE: shrine, 'mana_result': mana_result, 'random_enemy': random_enemy, 'heal_friends': heal_friends,
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in load_batch()['cards']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        kwargs = {}
        if cid in (DISCOVER, DISCOUNT, SET, BURST, SWEEP, WEAPON):
            kwargs['battlecry'] = PREFIX + cid
        if cid == SHRINE:
            kwargs.update(on_use=PREFIX + cid, durability=raw['health'])
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
