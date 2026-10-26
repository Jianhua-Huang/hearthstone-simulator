"""Complete native cards reached by the reviewed Nefarius reference inventory."""
import json
from pathlib import Path

from hs_sim.engine.effects import GrantKeyword, Overload
from hs_sim.engine.model import (CardDefinition, CardType, CostAuraSpec, CostSpec,
    IntrinsicCostSpec, Keyword, MinionDeathCostSpec, StatRelationLayer,
    StatRelationOperand, StatRelationSpec)
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

ROOTS = ('BRM_025', 'BOT_066', 'DRG_211', 'SCH_711', 'TTN_924', 'DEEP_006',
    'ICC_700', 'ICC_913', 'ULD_275', 'ULD_185', 'JAM_007', 'JAM_021')
TOKEN = 'BOT_066t'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/nefarian-native-dependencies-v1.json'
BATCH_HASH = '0fd4550affc67d16efdf4933d5bd72e3e2b23ad1e882a2491c28fd8ac057b0ed'
PREFIX = 'cards.nefarian_native_dependencies.'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = value['cards'] + value['dependencies']
    if (canonical_digest(value) != BATCH_HASH or
            tuple(row['record']['id'] for row in rows) != (*ROOTS, TOKEN) or
            any(value[key] for key in ('existing_dependencies', 'evidence_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Nefarius generated dependencies lost their complete source')
    return value


def register_nefarian_native_dependencies(registry):
    def whelp(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),),
            SummonCause.capture(c), position=deathrattle_position(c)),)

    def proto(c):
        return (SummonFromPool(c.player_id, 'constructed.minions',
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=7, max_cost=7),
            source_id=c.source_id, cause=SummonCause.capture(c), position=deathrattle_position(c)),)

    for name, body in dict(whelp=whelp, proto=proto,
            overload=lambda c: (Overload(c.player_id, 2),),
            soloist=lambda c: (GrantKeyword(c.source_id, Keyword.POISONOUS, c.source_id),)).items():
        registry.register_behavior(PREFIX+name, body)
    declarations = {
        'BRM_025': dict(minion_death_cost=MinionDeathCostSpec('cost.minion-deaths-both-turn-v1')),
        'BOT_066': dict(deathrattle=PREFIX+'whelp'),
        'DRG_211': dict(spell_damage=2, on_play=PREFIX+'overload'),
        'SCH_711': dict(deathrattle=PREFIX+'proto'),
        'TTN_924': dict(cost_auras=(CostAuraSpec(CostSpec(minimum=2), 'all_cards_minimum'),)),
        'DEEP_006': dict(keywords=(Keyword.DIVINE_SHIELD, Keyword.TAUNT, Keyword.LIFESTEAL, Keyword.ELUSIVE)),
        'ICC_700': dict(intrinsic_costs=(IntrinsicCostSpec(set_to=0, condition='hero_healed_this_turn',
            history_profile_id='healing.hero-this-turn-v1'),)),
        'ICC_913': dict(keywords=(Keyword.DIVINE_SHIELD,), spell_damage=1),
        'ULD_275': dict(keywords=(Keyword.TAUNT, Keyword.REBORN)),
        'ULD_185': dict(keywords=(Keyword.REBORN,), stat_relations=(StatRelationSpec(
            operand=StatRelationOperand.SELF_DAMAGED, layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=2),)),
        'JAM_007': dict(keywords=(Keyword.DIVINE_SHIELD, Keyword.REBORN)),
        'JAM_021': dict(keywords=(Keyword.RUSH, Keyword.COMBO), combo=PREFIX+'soloist'),
        TOKEN: {},
    }
    data = load_batch()
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; cid = raw['id']
        if raw['type'] != 'MINION' or any(type(raw[k]) is not int for k in ('cost', 'attack', 'health')):
            raise TargetValidationError('Nefarius dependencies require complete original minion values')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], metadata=metadata_from_record(raw), **declarations[cid])
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
