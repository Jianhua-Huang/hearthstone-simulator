"""Historical qualified physical discovery, prices and native providers."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier, AddToHand, Buff
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.healing_history import restored_health
from hs_sim.engine.model import CardAbilityCondition, CardDefinition, CardType, CostSpec, Keyword, KeywordAuraSpec, SpellSchool, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedDeathrattle, MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import ChooseFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record


FLOWRIDER, CLERIC, PRIEST, KNIGHT, SCARAB, ATTENDANT, COLLECTOR, OUTSIDER, SUBJUGATOR, VIRTUOSO = (
    'ETC_359', 'WC_803', 'YOD_013', 'LOOT_154', 'TOY_006', 'BT_020', 'GDB_875', 'RLK_207', 'EX1_196', 'ETC_081')
LEAVES = (FLOWRIDER, CLERIC, PRIEST, KNIGHT, SCARAB, ATTENDANT, COLLECTOR, OUTSIDER, SUBJUGATOR, VIRTUOSO)
WISDOM = 'BT_025'
DEPENDENCIES = LEAVES + (WISDOM,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_qualified_prices.'
POOL = 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-qualified-prices-v1.json'
BATCH_HASH = 'd74bda1c5b263c93ef11b4e8421e570c21103511ab0324154d6cfc968c14fd38'
ONE_MINION = PoolQuery(kinds=(CardType.MINION,), min_cost=1, max_cost=1, collectible=True)
TWO_CARD = PoolQuery(min_cost=2, max_cost=2, collectible=True, class_mode='current')
OUTCAST_PRICE = CostSpec(delta=-1, ability=CardAbilityCondition('outcast', basis='printed'))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    facts = [row for row in data['dependencies'] + data['evidence_only']
        if type(row['record']['tags'].get('LIBRAM')) is int and row['record']['tags']['LIBRAM'] > 0]
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'choice_only', 'skipped', 'numeric_normalizations')) or
            len(facts) != 12 or {row['record']['id'] for row in facts} != set(data['printed_libram_ids']) or
            len(data['evidence_only']) != 11 or
            len(set(data['printed_libram_ids'])) != 12 or
            any(row['record']['type'] not in ('SPELL', 'WEAPON') or type(row['record']['tags'].get('LIBRAM')) is not int or
                row['record']['tags']['LIBRAM'] <= 0 for row in facts) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in data['dependencies'] + facts)):
        raise TargetValidationError('Historical qualified consumers lost roots or complete printed Libram facts')
    return data


def register_past_one_cost_qualified_price_cards(registry):
    data = load_batch()

    def discover(c, condition):
        return (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, PoolQuery(kinds=(CardType.SPELL,)),
            operation='take', distinct='entity', source_id=c.source_id, discovery=True),) if condition else ()

    def flowrider(c):
        player = c.state.players[c.player_id]
        return discover(c, player.overload_owed > 0 or player.overload_locked > 0)

    def priest(c):
        holding = any(c.state.entities[i].kind == CardType.MINION and
            has_any_tribe(registry, c.state.entities[i], ('dragon',)) for i in c.state.players[c.player_id].hand)
        return discover(c, holding)

    def outsider(c):
        if c.spell_conditions is None:
            raise ResolutionError('Fierce Outsider requires original accepted hand-position conditions')
        return (AddCostModifier(c.player_id, OUTCAST_PRICE, uses_remaining=1, source_id=c.source_id),) \
            if c.spell_conditions.outcast else ()

    def wisdom(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.kind != CardType.MINION or target.zone != Zone.BOARD or
                not target.active or target.health <= 0 or target.doomed): return ()
        original = MinionReference.capture(target)
        return (BuffCapturedMinion(original, 1, 1, c.source_id),
            GrantCapturedDeathrattle(original, PREFIX + 'return_wisdom', c.source_id))

    bodies = {
        FLOWRIDER: flowrider,
        CLERIC: lambda c: discover(c, restored_health(c.state, c.player_id, turn=c.state.turn) > 0),
        PRIEST: priest,
        KNIGHT: lambda c: (SummonFromPool(3-c.player_id, POOL, ONE_MINION, source_id=c.source_id, cause=SummonCause.capture(c)),),
        SCARAB: lambda c: (DiscoverFromPool(c.player_id, POOL, TWO_CARD, source_id=c.source_id),),
        ATTENDANT: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1,
            card_ids=tuple(data['printed_libram_ids'])), source_id=c.source_id),),
        COLLECTOR: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1), uses_remaining=1,
            source_id=c.source_id, combo_only=True),),
        OUTSIDER: outsider,
        SUBJUGATOR: lambda c: (Buff(c.target_id, attack=-2, source_id=c.source_id,
            until_owner_turn_start=c.player_id),) if c.target_id is not None else (),
        WISDOM: wisdom,
        'return_wisdom': lambda c: (AddToHand(c.player_id, WISDOM, c.source_id),),
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX + cid, body)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if cid == WISDOM:
            if (raw['type'], raw['cost'], raw['collectible'], raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 2, True, 5):
                raise TargetValidationError('Wisdom requires its complete original Holy spell')
            card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=2, on_play=PREFIX + cid,
                targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)),
                spell_school=SpellSchool.HOLY, metadata=metadata_from_record(raw))
            registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
            continue
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Qualified historical consumer lost its complete native minion')
        if cid == OUTSIDER:
            fields.update(on_play=PREFIX + cid, keywords=(Keyword.RUSH, Keyword.OUTCAST))
        elif cid == VIRTUOSO:
            fields['keyword_auras'] = (KeywordAuraSpec(Keyword.IMMUNE, target='friendly_hero', condition='controller_turn'),)
        else:
            fields['battlecry'] = PREFIX + cid
        if cid == SUBJUGATOR:
            fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,), relation='enemy')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
