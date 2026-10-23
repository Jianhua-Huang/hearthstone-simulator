"""Historical successful-entry, finite spell and original health consumers."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, RandomBuff, Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, LimitedTriggerSpec, SpellSchool, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion, DestroyCapturedMinion, MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.successful_summons import BuffSummonedMinion
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CopyMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .health_cards import HealthStep, health_body
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions


DEALER, DISTRIBUTOR, CHIRURGEON, ZEALOT, PIRANHA, HEALER, RACER, SUNFURY, BUBBLER, BANSHEE, CONJURER, ORACLE = (
    'RLK_824', 'TOY_518', 'WON_065', 'ULD_145', 'TSC_638', 'GDB_454', 'YOP_020',
    'RLK_609', 'TID_713', 'RLK_957', 'EX1_193', 'UNG_032')
LEAVES = (DEALER, DISTRIBUTOR, CHIRURGEON, ZEALOT, PIRANHA, HEALER, RACER, SUNFURY, BUBBLER, BANSHEE, CONJURER, ORACLE)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_summon_spell.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-summon-spell-v1.json'
BATCH_HASH = '3f52519cbeccf3fa0f0f5ed786353c74352b6de363cd0fadec5c1085e5a90004'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != LEAVES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped', 'numeric_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in data['dependencies'])):
        raise TargetValidationError('Historical summon/spell consumers lost their complete pinned sources')
    return data


def register_past_one_cost_summon_spell_cards(registry):
    data = load_batch()

    def entry(c):
        rows = [row for row in c.state.successful_summon_history if row.event_sequence == c.event.sequence]
        if len(rows) != 1 or (rows[0].entity_id, rows[0].player_id, rows[0].action) != (
                c.event.target_id, c.event.player_id, c.event.action):
            raise ResolutionError('Summon listener lost its original successful physical entry')
        row = rows[0]
        return row if row.player_id == c.player_id and row.entity_id != c.source_id and living_source(c) else None

    def reward(c, tribe=None, attack=0, health=0):
        row = entry(c)
        if row is None: return ()
        if tribe is not None:
            if row.tribes is None:
                raise UnsupportedDefinitionError('Summon reward requires known original current tribes: ' + row.card_id)
            if not row.tribes.matches_any((tribe,)): return ()
        return (BuffSummonedMinion(c.player_id, row.id, c.source_id, attack, health),)

    def grow(c, piranha=False):
        row = entry(c)
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack=1, source_id=c.source_id),) \
            if row is not None and (not piranha or row.card_id == PIRANHA) else ()

    def frozen(c):
        ids = tuple(i for i in characters(c, registry, 3-c.player_id) if c.state.entities[i].frozen)
        return (DamageBatch(tuple(Damage(i, 3, c.source_id, DamageKind.MINION_ABILITY) for i in ids)),)

    def sunfury(c):
        row = cast_record(c.state, dict(c.event.data)['cast_id'])
        if (row.source_id, row.player_id, row.target_id) != (c.event.source_id, c.event.player_id, c.event.target_id):
            raise ResolutionError('Sunfury Initiate lost its original completed spell')
        if (row.player_id != c.player_id or not living_source(c) or not row.completed or not row.payload_started or
                row.failure is not None or row.interrupted or registry.card(row.card_id).spell_school != SpellSchool.FIRE):
            return ()
        ids = minions(c, registry, 1) + minions(c, registry, 2)
        return (DamageBatch(tuple(Damage(i, 1, c.source_id, DamageKind.MINION_ABILITY) for i in ids)),)

    def bubbler(c):
        return (DestroyCapturedMinion(MinionReference.capture(c.source), c.source_id),) if (
            c.event.target_id == c.source_id and c.event.amount == 1 and living_source(c)) else ()

    def banshee(c):
        ids = tuple(i for i in minions(c, registry, c.player_id)
            if has_any_tribe(registry, c.state.entities[i], ('undead',)))
        return (RandomBuff(ids, 2, 1, c.source_id),)

    bodies = {
        DEALER: lambda c: reward(c, 'undead', attack=1),
        DISTRIBUTOR: lambda c: reward(c, 'pirate', attack=1),
        CHIRURGEON: lambda c: reward(c, health=1), ZEALOT: grow, PIRANHA: lambda c: grow(c, True),
        HEALER: lambda c: health_body(c, (HealthStep('heal', 'enemy_hero', 6),), False),
        'silence_healer': lambda c: (Silence(c.source_id),), RACER: frozen, SUNFURY: sunfury,
        BUBBLER: bubbler, BANSHEE: banshee,
        CONJURER: lambda c: (CopyMatching(c.player_id, 3-c.player_id, Zone.DECK, source_id=c.source_id),),
        ORACLE: lambda c: (CopyMatching(c.player_id, 3-c.player_id, Zone.DECK, source_id=c.source_id),),
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX + cid, body)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Historical summon/spell consumer lost its native minion face')
        if cid in (DEALER, DISTRIBUTOR, CHIRURGEON, ZEALOT, PIRANHA):
            fields['triggers'] = (TriggerSpec('minion_summoned', PREFIX + cid),)
        elif cid == SUNFURY:
            fields['triggers'] = (TriggerSpec('spell_cast_finished', PREFIX + cid),)
        elif cid == BUBBLER:
            fields['triggers'] = (TriggerSpec('damage_dealt', PREFIX + cid),)
        elif cid == CONJURER:
            fields['battlecry'] = PREFIX + cid
        if cid in (HEALER, BANSHEE, ORACLE): fields['deathrattle'] = PREFIX + cid
        if cid in (HEALER, RACER):
            fields.update(keywords=(Keyword.SPELLBURST,), limited_triggers=(LimitedTriggerSpec.spellburst(
                PREFIX + 'silence_healer' if cid == HEALER else PREFIX + RACER),))
        elif cid == PIRANHA: fields['keywords'] = (Keyword.RUSH,)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
