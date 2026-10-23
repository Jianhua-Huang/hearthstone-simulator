"""Historical one-cost consumers of existing tribe, cost and summon effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import AddCostModifier, AddToHand, Buff, Draw, Freeze
from hs_sim.engine.model import (
    CardDefinition, CardType, CostSpec, Keyword, TargetMode, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position


KINDLING, SLAYER, OSCILLATOR, PEASANT, SPRINGPAW, SHARD, HELBOAR, CHUM, EGG, GUIDE = (
    'BAR_854', 'BT_142', 'ETC_106', 'SW_319', 'TRL_348',
    'UNG_205', 'BT_202', 'CFM_650', 'RLK_833', 'SCH_312')
LEAVES = (KINDLING, SLAYER, OSCILLATOR, PEASANT, SPRINGPAW, SHARD, HELBOAR, CHUM, EGG, GUIDE)
FOWL, LYNX = 'RLK_833t', 'TRL_348t'
DEPENDENCIES = LEAVES + (FOWL,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_tribal.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-tribal-v1.json'
BATCH_HASH = '907cbffaeb259b6ff0cfce29673cb1f1a72bcc8b1688a578c7cfc4412fd349fd'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != (LYNX,) or
            any(data[key] for key in ('cards', 'evidence_only', 'choice_only', 'skipped')) or
            data['numeric_normalizations'] != {EGG: {'attack': 0}} or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Historical tribe consumers lost their complete pinned sources')
    return data


def register_past_one_cost_tribal_cards(registry):
    data = load_batch()
    old = data['existing_dependencies'][0]
    if canonical_digest(asdict(registry.card(LYNX))) != old['definition_sha256']:
        raise TargetValidationError('Springpaw requires its unchanged complete named Lynx')

    def next_tribe(c, tribe):
        return (AddCostModifier(c.player_id, CostSpec(delta=-1, card_types=(CardType.MINION,)),
            uses_remaining=1, source_id=c.source_id, tribes_any=(tribe,)),)

    def hand_buff(c, tribe):
        return (RandomBuffStoredMinion(c.player_id, attack=1, health=1,
            query=PoolQuery(tribes_any=(tribe,)), source_id=c.source_id, tribe_basis='current'),)

    bodies = {
        KINDLING: lambda c: next_tribe(c, 'elemental'),
        OSCILLATOR: lambda c: next_tribe(c, 'mech'),
        GUIDE: lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=0,
            card_types=(CardType.HERO_POWER,)), uses_remaining=1, source_id=c.source_id),),
        SLAYER: lambda c: (Buff(c.state.players[c.player_id].hero_id, attack=1,
            source_id=c.source_id, expires_turn=c.state.turn),),
        PEASANT: lambda c: (Draw(c.player_id, 1, c.source_id),) if c.event.player_id == c.player_id else (),
        SPRINGPAW: lambda c: (AddToHand(c.player_id, LYNX, c.source_id),),
        SHARD: lambda c: () if c.target_id is None else (Freeze(c.target_id, c.source_id),),
        HELBOAR: lambda c: hand_buff(c, 'beast'),
        CHUM: lambda c: hand_buff(c, 'murloc'),
        EGG: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(FOWL),),
            SummonCause.capture(c), position=deathrattle_position(c)),),
    }
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid, body)
    for item in data['dependencies']:
        raw = item['record']
        cid = raw['id']
        if (raw['type'] != 'MINION' or type(raw['cost']) is not int or
                raw['cost'] != (3 if cid == FOWL else 1) or type(raw['health']) is not int or
                raw['collectible'] != (cid != FOWL) or
                cid != EGG and type(raw['attack']) is not int):
            raise TargetValidationError('Historical tribe consumer lost its actual printed body')
        fields = {}
        if cid == PEASANT:
            fields['triggers'] = (TriggerSpec('turn_started', PREFIX + cid),)
        elif cid != FOWL:
            fields['deathrattle' if cid in (HELBOAR, EGG) else 'battlecry'] = PREFIX + cid
        if cid == SPRINGPAW:
            fields['keywords'] = (Keyword.RUSH,)
        if cid == SHARD:
            fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.HERO, Zone.BOARD),
                (CardType.HERO, CardType.MINION), relation='enemy', exclude_source=True)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=0 if cid == EGG else raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
