"""Four actual Dragon dependencies consume ordinary shared effect pipelines."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.dark_gifts import public_gifts
from hs_sim.engine.effects import Buff, Destroy, GainArmor, InvokeBehavior, RandomBuff, RandomDamage, RandomDestroy
from hs_sim.engine.locations import RandomDestroyLocation
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, EndTurnSpec, Keyword, RewindSpec, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/dragon-native-effects-v1.json'
BATCH_HASH = 'feda1b93e515d89c84541be2dd471fc07a94ba23e892dbaa9d75ff78b83123d0'
FLOWER = 'EDR_889'; TURTLE = 'FIR_956'; CRUMBLE = 'END_034'; CONFLUX = 'TIME_004'
ROOTS = (FLOWER, TURTLE, CRUMBLE, CONFLUX)
PREFIX = 'cards.dragon_native.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Dragon native effects lost their complete reviewed source pin')
    return data


def register_dragon_native_effect_cards(registry):
    def follow(c, name):
        return InvokeBehavior(PREFIX + name, c.source_id, c.player_id, c.target_id,
                              None if c.play is None else c.play.id)
    def flower(c):
        ids = tuple(i for i in minions(c, registry, c.player_id)
                    if i != c.source_id and has_any_tribe(registry, c.state.entities[i], ('dragon',)))
        return (RandomBuff(ids, 1, 1, c.source_id),)
    def turtle(c):
        if not any(c.state.entities[i].kind == CardType.MINION and public_gifts(c.state.entities[i])
                   for i in c.state.players[c.player_id].hand): return ()
        hero = c.state.players[c.player_id].hero_id
        return (Buff(hero, attack=3, source_id=c.source_id, expires_turn=c.state.turn), GainArmor(c.player_id, 6))
    def locations(c):
        ids = tuple(i for i in c.state.players[3-c.player_id].board for e in (c.state.entities[i],)
                    if e.kind == CardType.LOCATION and e.active and e.durability > 0 and not e.doomed)
        return (RandomDestroyLocation(ids, c.source_id),)
    def weapon(c):
        identity = c.state.players[3-c.player_id].weapon_id
        if identity is None: return ()
        entity = c.state.entities[identity]
        return (Destroy(identity, c.source_id),) if entity.active and entity.durability > 0 and not entity.doomed else ()
    bodies = dict(flower=flower, turtle=turtle, locations=locations, weapon=weapon,
        crumble=lambda c: (RandomDestroy(minions(c, registry, 3-c.player_id), c.source_id), follow(c, 'locations'), follow(c, 'weapon')),
        conflux=lambda c: (RandomDamage(characters(c, registry, 3-c.player_id), 7, c.source_id, DamageKind.MINION_ABILITY),))
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    data = load_batch()
    if tuple(row['record']['id'] for row in data['cards']) != ROOTS or data['dependencies']:
        raise TargetValidationError('Unreviewed Dragon native root/dependency set')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Dragon native full source row changed')
    for row in data['cards']:
        raw = row['record']; cid = raw['id']
        if raw['type'] != 'MINION' or raw['collectible'] is not True:
            raise TargetValidationError('Dragon native roots require complete collectible minions')
        kwargs = ({'triggers': (TriggerSpec('turn_ended', PREFIX + 'flower', EndTurnSpec()),)} if cid == FLOWER else
                  {'battlecry': PREFIX + {TURTLE:'turtle', CRUMBLE:'crumble', CONFLUX:'conflux'}[cid]})
        if cid == CONFLUX: kwargs.update(keywords=(Keyword.REWIND,), rewind=RewindSpec())
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
                              metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
