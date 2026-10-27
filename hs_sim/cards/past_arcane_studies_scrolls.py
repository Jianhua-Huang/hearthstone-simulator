"""Primordial Studies uses complete printed facts and physical next-minion prices."""
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.model import (CardAbilityCondition, CardDefinition, CardType, CastWhenDrawnSpec,
    CostSpec, Keyword, SpellSchool)
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-studies-scrolls-v1.json'
BATCH_HASH = '8fcf3d64eef6110ffab3343355aa38795a5d7fe95470e44ad02b401201f89d76'
DECK, STUDIES, SCROLL = 'LOOT_106', 'SCH_270', 'LOOT_106t'
LEAVES = (DECK,STUDIES)
DEPENDENCIES = (*LEAVES,SCROLL)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_studies_scrolls.'
POOL = 'constructed.cards'
NEXT_COST = CostSpec(delta=-1,card_types=(CardType.MINION,),ability=CardAbilityCondition('spell_damage'))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    facts = data['spell_damage_eligibility_records']
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(x['record']['id']for x in data['dependencies']) != DEPENDENCIES or
            len(data['official_observations']) != 6 or not set(LEAVES) <= set(reference['candidate_ids']) or
            len(facts) != 86 or len(data['printed_spell_damage_ids']) != 66 or
            sorted(x['record']['id']for x in facts if x['eligible']) != data['printed_spell_damage_ids'] or
            len({x['record']['id']for x in facts}) != 86 or
            any(type(x['eligible']) is not bool or x['record']['type'] != 'MINION' or
                x['record']['collectible'] is not True for x in facts) or
            any(data[k]for k in ('cards','existing_dependencies','evidence_only','skipped','numeric_normalizations',
                'display_normalizations','eligibility_uses_executable_coverage','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record']) != x['record_sha256']for x in [*data['dependencies'],*facts])):
        raise TargetValidationError('Studies or Scrolls changed complete original sources or independent printed identities')
    return data


def register_past_arcane_studies_scrolls(registry):
    data = load_batch(); prepared = []
    for row in data['dependencies']:
        raw = row['record'];cid = raw['id']
        expected = ('SPELL',5,True,1) if cid == DECK else ('SPELL',1,True,1) if cid == STUDIES else ('SPELL',5,False,None)
        if (raw['type'],raw['cost'],raw['collectible'],raw['tags'].get('SPELL_SCHOOL')) != expected:
            raise TargetValidationError('Studies or Scrolls changed an original printed face')
        if cid in registry.cards:raise TargetValidationError('Studies or Scrolls cannot overwrite '+cid)
        if cid == DECK and raw['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID') != data['dependencies'][-1]['record']['dbf_id']:
            raise TargetValidationError('Deck of Wonders lost its exact physical scroll dependency')
        fields = {'spell_school':SpellSchool.ARCANE} if cid != SCROLL else {
            'keywords':(Keyword.CASTS_WHEN_DRAWN,),'cast_when_drawn':CastWhenDrawnSpec()}
        if cid == SCROLL and raw['tags'].get('CASTS_WHEN_DRAWN') != 1:
            raise TargetValidationError('Scroll of Wonder lost its native drawn-cast declaration')
        card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
            metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Studies or Scrolls differs from original printed metadata: '+cid)
        prepared.append(card)
    query = PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',
        card_ids=tuple(data['printed_spell_damage_ids']))
    registry.register_behavior(PREFIX+DECK,lambda c:shuffled(c,tuple(AddToDeck(c.player_id,SCROLL,'random',c.source_id)for _ in range(5))))
    registry.register_behavior(PREFIX+STUDIES,lambda c:(DiscoverFromPool(c.player_id,POOL,query,source_id=c.source_id),
        AddCostModifier(c.player_id,NEXT_COST,uses_remaining=1,source_id=c.source_id)))
    registry.register_behavior(PREFIX+SCROLL,lambda c:(CastFromPool(c.player_id,POOL,
        PoolQuery(kinds=(CardType.SPELL,),collectible=True),source_id=c.source_id),))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
