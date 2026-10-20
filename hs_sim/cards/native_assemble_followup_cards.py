"""Named summons, actual assembled delivery grants, and the fixed Mech reward."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_offers import Assemble
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.effects import AddToHand, Buff, Destroy, GrantKeyword, GrantTrigger
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, EndTurnSpec,
    Keyword, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_assemble_entry_cards import POOL_ID

DEPTHS, PATCH, SCULPT, CHISEL = 'BE_087', 'BE_553', 'BE_114', 'BE_740'
GUARD, OVERDRIVE, MECH_FRAGMENT = 'BE_087t', 'BE_553t', 'CORE_REV_946'
ROOTS = COLLECTIBLE_ROOTS = (DEPTHS, PATCH, SCULPT, CHISEL)
DEPENDENCIES = (GUARD, OVERDRIVE)
PREFIX = 'cards.native_assemble_followups.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/native-assemble-followups-v1.json'
BATCH_HASH = 'eedb942c5ddeab381937ea48d743723e0a06ea8f6bdfd511056fcdf6a3c0bf56'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            tuple(r['record']['id'] for r in data['dependencies']) != DEPENDENCIES or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != (MECH_FRAGMENT,) or
            any(data[k] for k in ('evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256']
                for r in data['cards']+data['dependencies']+data['existing_dependencies'])):
        raise TargetValidationError('Native Assemble followups require four full roots and two fixed dependencies')
    return data


def register_native_assemble_followup_cards(registry):
    data = load_batch(); original = registry.card(MECH_FRAGMENT)
    if canonical_digest(asdict(original)) != data['existing_dependencies'][0]['definition_sha256']:
        raise TargetValidationError('Assemble Mech fragment changed its complete original definition')
    declaration = data['reviewed_template']
    registry.register_assemble_template(AssembleTemplate(MECH_FRAGMENT,
        AssemblePrefix(declaration['timing'], tuple(Keyword(k) for k in declaration['keywords'])),
        AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings']))))
    policy = data['experimental_source_policy']
    if policy != dict(pool_id=POOL_ID, empty_policy='error', small_policy='error',
            keep_policy='forbid', formal_pool_installed=False, not_cn_calibrated=True):
        raise TargetValidationError('Native Assemble followups changed the experimental pool policy')

    def request(c, **kwargs):
        return Assemble(c.player_id, POOL_ID, c.source_id, empty_policy=policy['empty_policy'],
            small_policy=policy['small_policy'], keep_policy=policy['keep_policy'], **kwargs)

    def depths(c):
        summon = SummonByCard(c.player_id, (SummonEntryMaterial(GUARD),), SummonCause.capture(c))
        return (summon, summon, request(c))

    def overdrive(c):
        if c.target_id is None: raise ResolutionError('Overdrive requires its actual friendly Mech target')
        return (Buff(c.target_id, 2, 0, c.source_id), GrantKeyword(c.target_id, Keyword.RUSH, c.source_id),
            GrantTrigger(c.target_id, 'turn_ended', PREFIX+'die', c.source_id, end_turn=EndTurnSpec('either')))

    bodies = {
        DEPTHS: depths,
        PATCH: lambda c: (request(c, primary_query=PoolQuery(tribes_any=('mech',))),
            AddToHand(c.player_id, OVERDRIVE, c.source_id)),
        SCULPT: lambda c: (request(c, cost=CostSpec(delta=-2)),),
        CHISEL: lambda c: (request(c, primary_trait='taunt', minion_grant=CreatedMinionGrant(2, 3)),),
        OVERDRIVE: overdrive,
        'die': lambda c: (Destroy(c.source_id, c.source_id),),
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    rule = PREFIX+'friendly_mech'
    registry.register_target_predicate(TargetPredicateSpec(rule, current_tribes_any=('mech',)))
    for row in data['cards']+data['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        numbers = data['numeric_normalizations'].get(cid, {})
        cost = numbers['cost'] if raw.get('cost') is None and 'cost' in numbers else raw.get('cost')
        if type(cost) is not int: raise TargetValidationError('Native Assemble card lacks an explicit printed cost')
        if kind == CardType.MINION:
            attack = numbers['attack'] if raw.get('attack') is None and 'attack' in numbers else raw.get('attack')
            if cid != GUARD or type(attack) is not int or raw['tags'].get('TAUNT') != 1:
                raise TargetValidationError('Deepholm Guard lost its original whole printed face')
            fields = dict(attack=attack, health=raw['health'], keywords=(Keyword.TAUNT,))
        else:
            fields = dict(on_play=PREFIX+cid, spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
            if cid == OVERDRIVE:
                fields.update(targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,),
                    relation='friendly'), target_rule=rule)
        card = CardDefinition(cid, raw['name'], kind, cost=cost, metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
