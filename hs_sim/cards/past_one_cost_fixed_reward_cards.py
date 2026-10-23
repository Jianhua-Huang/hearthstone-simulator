"""Historical native destruction, named rewards and completed-attack consumers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import AddToHand, Damage, DamageBatch
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, TargetMode, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import DestroyForBuff, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position


CRAB, REVELER, WYRM, ACORN, GUEST, CHEF, ZOMBIE, SOLDIER, BOMBER, SKELETON, VRYKUL = (
    'NEW1_017', 'ICC_903', 'RLK_548', 'DAL_354', 'REV_356', 'REV_952',
    'NX2_024', 'RLK_921', 'WON_062', 'NX2_006', 'TTN_812')
LEAVES = (CRAB, REVELER, WYRM, ACORN, GUEST, CHEF, ZOMBIE, SOLDIER, BOMBER, SKELETON, VRYKUL)
SQUIRREL, BAT, PIRATE, VALKYR, BOLT, RECRUIT = (
    'DAL_354t', 'REV_350t', 'NX2_006t', 'TTN_812t', 'RLK_843', 'CS2_101t')
DEPENDENCIES = LEAVES + (SQUIRREL, BAT, PIRATE, VALKYR)
EXISTING = (BOLT, RECRUIT)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_fixed_rewards.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-fixed-rewards-v1.json'
BATCH_HASH = '8b24eb7e894aba73e3a1e047ab863f81439ead51ed046275d18e9438f8496239'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != EXISTING or
            any(data[k] for k in ('cards', 'evidence_only', 'choice_only', 'skipped', 'numeric_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Historical fixed rewards lost complete native sources')
    return data


def register_past_one_cost_fixed_reward_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Historical rewards require their unchanged named Bolt and Recruit')
    registry.register_target_predicate(TargetPredicateSpec(PREFIX + 'murloc', current_tribes_any=('murloc',)))

    def destroy_reward(c, murloc=False):
        if c.target_id is None or not living_source(c):
            return ()
        target = c.state.entities[c.target_id]
        if (target.kind != CardType.MINION or target.zone != Zone.BOARD or not target.active or
                target.health <= 0 or target.doomed or
                (not murloc and target.controller != c.player_id) or
                (murloc and not has_any_tribe(registry, target, ('murloc',)))):
            return ()
        return (DestroyForBuff(MinionReference.capture(target), MinionReference.capture(c.source),
            2, 2, c.source_id),)

    def hand_pair(c, card_id):
        return (AddToHand(c.player_id, card_id, c.source_id), AddToHand(c.player_id, card_id, c.source_id))

    def guest(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(BAT),), SummonCause.capture(c),
            position=deathrattle_position(c)),)

    def skeleton(c):
        row = completed_attack(c)
        if row is None or not living_source(c) or row.source_kind != CardType.HERO or row.combat.player_id != c.player_id:
            return ()
        return (SummonByCard(c.player_id, (SummonEntryMaterial(PIRATE),), SummonCause.capture(c)),)

    def vrykul(c):
        row = completed_attack(c)
        if (row is None or not living_source(c) or row.source_kind != CardType.MINION or
                row.declaration.source_id != c.source_id or row.combat.player_id != c.player_id or
                (row.combat.source_zone_epoch, row.combat.source_entered_order) !=
                (c.source.zone_epoch, c.source.entered_order)):
            return ()
        return (AddToHand(c.player_id, VALKYR, c.source_id),)

    bodies = {
        CRAB: lambda c: destroy_reward(c, True), REVELER: destroy_reward,
        WYRM: lambda c: (AddToHand(c.player_id, BOLT, c.source_id),),
        ACORN: lambda c: hand_pair(c, SQUIRREL), CHEF: lambda c: hand_pair(c, RECRUIT), GUEST: guest,
        ZOMBIE: lambda c: (Damage(c.state.players[c.player_id].hero_id, 4, c.source_id, DamageKind.MINION_ABILITY),),
        SOLDIER: lambda c: (Damage(c.state.players[c.player_id].hero_id, 2, c.source_id, DamageKind.MINION_ABILITY),),
        BOMBER: lambda c: (DamageBatch(tuple(Damage(c.state.players[pid].hero_id, 3,
            c.source_id, DamageKind.MINION_ABILITY) for pid in (1, 2))),),
        SKELETON: skeleton, VRYKUL: vrykul,
    }
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid, body)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] != (cid in LEAVES) or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Historical fixed reward lost its native minion body')
        fields = {}
        if cid in (CRAB, REVELER):
            fields.update(battlecry=PREFIX + cid, targeting=TargetSpec(TargetMode.IF_AVAILABLE,
                (Zone.BOARD,), (CardType.MINION,), relation='any' if cid == CRAB else 'friendly'))
            if cid == CRAB:
                fields['target_rule'] = PREFIX + 'murloc'
        elif cid in (WYRM, SOLDIER, BOMBER):
            fields['battlecry'] = PREFIX + cid
        elif cid in (ACORN, GUEST, CHEF, ZOMBIE):
            fields['deathrattle'] = PREFIX + cid
        elif cid in (SKELETON, VRYKUL):
            fields['triggers'] = (TriggerSpec('attack_finished', PREFIX + cid),)
        if cid == ZOMBIE:
            fields['keywords'] = (Keyword.RUSH,)
        elif cid == SOLDIER:
            fields['keywords'] = (Keyword.DIVINE_SHIELD,)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
