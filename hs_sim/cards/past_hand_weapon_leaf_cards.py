"""Historical hand/equipment consumers of the original shared contracts."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, ModifyWeapon, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, EquippedWeaponReference,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .zone_cards import PREFIX as ZONES

SORCERESS, DEFILER, BUCCANEER = 'AV_114', 'AV_308', 'AT_029'
DEPENDENCIES = (SORCERESS, DEFILER, BUCCANEER)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_hand_weapon_leaves.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-hand-weapon-leaves-v1.json'
BATCH_HASH = 'e26ba6285e94d1bdd5ce8cafa31ec6b9f5a6b7a840d6fa839c3e6ae623950078'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['dependencies'])):
        raise TargetValidationError('Historical hand/equipment leaves require three complete original faces')
    return data


def register_past_hand_weapon_leaf_cards(registry):
    def discounted(ref, source):
        return (ModifyStoredCost(ref, CostSpec(delta=-1), source),)

    def sorceress(c):
        spells = tuple(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].kind == CardType.SPELL)
        if not spells: return ()
        prices = tuple(quote_unselected_cost(c.state, registry, entity).amount for entity in spells)
        highest = max(prices)
        tied = tuple(entity for entity, price in zip(spells, prices) if price == highest)
        if len(tied) == 1: return discounted(CardReference.capture(tied[0]), c.source_id)
        options = tuple(ChoiceOption(json.dumps(asdict(CardReference.capture(e)), sort_keys=True),
            registry.card(e.card_id).name, card_id=e.card_id, entity_id=e.id) for e in tied)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX+'discount_selected'),)

    def selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Sorceress requires its original automatically selected highest-cost spell')
        raw = json.loads(c.choice.choice.options[0].id); raw['zone'] = Zone(raw['zone'])
        return discounted(CardReference(**raw), c.source_id)

    def buccaneer(c):
        event = c.event
        if event is None or event.kind != 'weapon_equipped' or not living_source(c) or event.player_id != c.player_id:
            return ()
        weapon = c.state.entities.get(event.target_id)
        if (weapon is None or event.source_id != event.target_id or weapon.kind != CardType.WEAPON or
                weapon.zone != Zone.WEAPON or weapon.controller != c.player_id or not weapon.active or
                weapon.durability <= 0 or weapon.doomed or c.state.players[c.player_id].weapon_id != weapon.id):
            return ()
        return (ModifyWeapon(EquippedWeaponReference.capture(weapon), attack=1, source_id=c.source_id),)

    registry.register_behavior(PREFIX+'discount', sorceress)
    registry.register_behavior(PREFIX+'discount_selected', selected)
    registry.register_behavior(PREFIX+'equipped', buccaneer)
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Historical hand/equipment leaves lost their printed minion bodies')
        if cid == SORCERESS: fields['battlecry'] = PREFIX+'discount'
        elif cid == DEFILER:
            fields.update(battlecry=ZONES+'selected_hand_copy', target_rule=ZONES+'hand_fel',
                targeting=TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.HAND,),
                    kinds=(CardType.SPELL,), relation='friendly'))
        else: fields['triggers'] = (TriggerSpec('weapon_equipped', PREFIX+'equipped'),)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1,
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
