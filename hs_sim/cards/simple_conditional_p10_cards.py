"""Three P10 roots over native Combo, dormancy and current-tribe targets."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import Overload
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-conditional-p10-v1.json'
BATCH_HASH = '3446967643c4e44ab4e2f970682ba00b4fb6239fcaed468d8255385fb0401bfb'
ABERRATION = 'END_032'
CONFINEMENT = 'JAIL_997'
NATURE = 'MEND_305'
BLAZER = 'CATA_EVENT_002'
ROOTS = (ABERRATION, CONFINEMENT, NATURE)
PREFIX = 'cards.simple_conditional_p10.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P10 lost its complete reviewed source pin')
    if (tuple(x['record']['id'] for x in data['cards']) != ROOTS or data['dependencies'] or
            data['existing_dependencies'] or tuple(x['record']['id'] for x in data['skipped']) != (BLAZER,)):
        raise TargetValidationError('Unreviewed P10 roots or dependencies')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P10 complete source row changed')
    return data


def register_simple_conditional_p10_cards(registry):
    data = load_batch()
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'current_beast', current_tribes_any=('beast',)))

    def aberration(c):
        grants = ()
        if living_source(c):
            original = MinionReference.capture(c.source)
            grants = (GrantCapturedKeyword(original, Keyword.IMMUNE, c.source_id, expires_turn=c.state.turn),
                      GrantCapturedKeyword(original, Keyword.WINDFURY, c.source_id))
        return Overload(c.player_id, 2), *grants

    def confinement(c):
        target = c.state.entities[c.target_id]
        if (target.kind != CardType.MINION or target.zone != Zone.BOARD or not target.active or
                target.health <= 0 or target.doomed):return ()
        if target.controller == c.player_id and has_any_tribe(registry, target, ('demon',)):
            return (BuffCapturedMinion(MinionReference.capture(target), 3, 3, c.source_id),)
        return (MakeDormant(target.id, 2, c.source_id),)

    def nature(c):
        return (BuffCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]), 2, 2, c.source_id),
                RandomBuffStoredMinion(c.player_id, 2, 2, query=PoolQuery(tribes_any=('beast',)),
                                      source_id=c.source_id, tribe_basis='current'))

    for name, body in (('aberration',aberration),('confinement',confinement),('nature',nature)):
        registry.register_behavior(PREFIX+name, body)
    for row in data['cards']:
        raw = row['record'];cid = raw['id'];kind = CardType(raw['type'].lower());kwargs = {}
        if raw['collectible'] is not True:
            raise TargetValidationError('P10 requires complete collectible roots')
        if cid == ABERRATION:
            kwargs.update(attack=raw['attack'],health=raw['health'],keywords=(Keyword.RUSH,Keyword.COMBO),combo=PREFIX+'aberration')
        else:
            kwargs['targeting'] = TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly' if cid == NATURE else 'any')
            if cid == CONFINEMENT:
                if 'SPELL_SCHOOL' in raw['tags']:
                    raise TargetValidationError('Confinement must retain its absent printed school')
                kwargs['on_play'] = PREFIX+'confinement'
            else:
                if raw['tags'].get('SPELL_SCHOOL') != 4:
                    raise TargetValidationError('Nurturing Nature requires its original Nature school')
                kwargs.update(on_play=PREFIX+'nature',spell_school=SpellSchool.NATURE,target_rule=PREFIX+'current_beast')
        card = CardDefinition(cid,raw['name'],kind,cost=raw['cost'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
