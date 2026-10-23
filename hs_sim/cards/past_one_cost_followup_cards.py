"""Twelve historical one-cost leaf candidates, without inventing a past pool."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier, AddToHand, Damage, ModifyWeapon
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, DamageKind, EquippedWeaponReference, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import HealthStep, health_body
from .metadata import metadata_from_record


SPY, LEECH, PROTECTOR, KNIGHT, MURMY, BOMB, CHOW, GUITARIST, SPELLWING, FLYBOOTER, VENDOR, DECKHAND = (
    'BT_701', 'GIL_558', 'ICC_038', 'ICC_220', 'ULD_723', 'BOT_031',
    'FP1_001', 'ETC_102', 'DRG_107', 'DRG_035', 'DAL_544', 'CS3_008')
LEAVES = (SPY, LEECH, PROTECTOR, KNIGHT, MURMY, BOMB, CHOW, GUITARIST, SPELLWING, FLYBOOTER, VENDOR, DECKHAND)
PIRATE, MISSILES = 'DRG_035t', 'EX1_277'
DEPENDENCIES = LEAVES + (PIRATE,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_followups.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-followups-v1.json'
BATCH_HASH = '01e8d02c769bafa226236d4043f93210bdd01aa348304704a937f0cb34c42258'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(item['record']['id'] for item in data['dependencies']) != DEPENDENCIES or
            tuple(item['record']['id'] for item in data['existing_dependencies']) != (MISSILES,) or
            any(data[key] for key in ('cards', 'evidence_only', 'choice_only', 'skipped')) or
            data['numeric_normalizations'] != {BOMB: {'attack': 0}} or
            any(canonical_digest(item['record']) != item['record_sha256']
                for item in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Historical followups lost their complete fixed records and evidence')
    return data


def register_past_one_cost_followup_cards(registry):
    data = load_batch()
    old = data['existing_dependencies'][0]
    if canonical_digest(asdict(registry.card(MISSILES))) != old['definition_sha256']:
        raise TargetValidationError('Spellwing requires its unchanged complete retained Arcane Missiles definition')

    def guitarist(c):
        eid = c.state.players[c.player_id].weapon_id
        if eid is None:
            return ()
        return (ModifyWeapon(EquippedWeaponReference.capture(c.state.entities[eid]),
            durability=1, source_id=c.source_id),)

    bodies = {
        BOMB: lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 2, c.source_id,
            DamageKind.MINION_ABILITY),),
        CHOW: lambda c: health_body(c, (HealthStep('heal', 'enemy_hero', 5),), False),
        GUITARIST: guitarist,
        SPELLWING: lambda c: (AddToHand(c.player_id, MISSILES, c.source_id),),
        FLYBOOTER: lambda c: (AddToHand(c.player_id, PIRATE, c.source_id),
            AddToHand(c.player_id, PIRATE, c.source_id)),
        VENDOR: lambda c: health_body(c, (HealthStep('heal', 'friendly_characters', 2),), False),
        DECKHAND: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1,
            card_types=(CardType.WEAPON,)), uses_remaining=1, source_id=c.source_id),),
    }
    keywords = {SPY: (Keyword.STEALTH,), LEECH: (Keyword.LIFESTEAL,),
        PROTECTOR: (Keyword.TAUNT, Keyword.DIVINE_SHIELD), KNIGHT: (Keyword.LIFESTEAL,),
        MURMY: (Keyword.REBORN,)}
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid, body)
    for item in data['dependencies']:
        raw = item['record']
        cid = raw['id']
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or type(raw['health']) is not int or
                raw['collectible'] != (cid != PIRATE) or
                cid != BOMB and type(raw['attack']) is not int):
            raise TargetValidationError('Historical followup lost its original printed minion body')
        fields = {}
        if cid in bodies:
            fields['deathrattle' if cid in (BOMB, CHOW, SPELLWING) else 'battlecry'] = PREFIX + cid
        if cid in keywords:
            fields['keywords'] = keywords[cid]
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1,
            attack=0 if cid == BOMB else raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
