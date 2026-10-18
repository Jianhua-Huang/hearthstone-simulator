"""Seven real Leyline roots and three non-physical upgrade previews."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier, AddToHand, ChoiceOption, RequestChoice
from hs_sim.engine.excess_damage import RandomEnemyMinionExcessDamage
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, Keyword,
    PlayerEffectSpec, SpellEffectModifierSpec, SpellSchool)
from hs_sim.engine.player_effects import AddPlayerEffect, spell_effect_values
from hs_sim.engine.pools import GenerateFromCandidates, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.spell_sequences import DrawWithCostReduction
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BURST, WALKER, CRYSTAL, NEEDLE, NEXUS, MAP, CAT = ROOTS = tuple(f'MEND_{i}' for i in range(500, 507))
CHARGE, CHANNEL, ENHANCE = CHOICES = ('MEND_505t', 'MEND_505t2', 'MEND_505t3')
FAMILY = (BURST, CRYSTAL, NEXUS)
PREFIX = 'cards.leyline.'
POOL = 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/native-leyline-v1.json'
BATCH_HASH = 'be26fb7b553e8f5d976d1800d0df8dfc8319c5168f27c5b3558de086f4b759cf'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['dependencies']) != CHOICES or tuple(d['family']) != FAMILY or
            d['existing_dependencies'] or d['skipped']):
        raise TargetValidationError('Leylines require their complete native family and upgrades')
    rows = [x for k in ('cards', 'dependencies', 'evidence_only') for x in d[k]]
    if any(canonical_digest(x['record']) != x['record_sha256'] for x in rows):
        raise TargetValidationError('Leyline complete original record changed')
    by = {x['record']['id']: x['record'] for x in rows}
    if (any(by[c]['tags'].get('TAG_SCRIPT_DATA_NUM_1') != v for c, v in d['initial_primary_values'].items()) or
            by[BURST]['tags'].get('349') != 1 or
            d['numeric_normalizations'] != {c:{'cost':0} for c in CHOICES}):
        raise TargetValidationError('Original Leyline scalars/immunity or hidden-cost upgrade faces changed')
    return d


def register_native_leyline_cards(registry):
    d = load_batch()
    for cid, value, extra in ((NEEDLE, 0, 1), (CHARGE, 0, 1), (CAT, 1, 0), (ENHANCE, 2, 0)):
        registry.register_player_effect(PlayerEffectSpec(PREFIX+cid, MAP if cid in CHOICES else cid,
            spell_effects=(SpellEffectModifierSpec(FAMILY, value, extra),)))
    def discount(c, reduction):
        return (AddCostModifier(c.player_id, CostSpec(delta=-reduction,
            card_types=(CardType.SPELL,), card_ids=FAMILY), source_id=c.source_id),)
    def modifier(c, cid):
        return (AddPlayerEffect(c.player_id, PREFIX+cid, c.source_id),)
    def parameters(c, cid):
        if c.cast is None or c.cast.card_id != cid:
            raise ValueError('Leyline body requires its original native CAST')
        return spell_effect_values(c.state, registry, c.cast, d['initial_primary_values'][cid])
    def burst(c):
        value, count = parameters(c, BURST)
        return (RandomEnemyMinionExcessDamage(c.player_id, value, c.source_id, 0),)*count
    def crystal(c):
        value, count = parameters(c, CRYSTAL)
        request = GenerateFromPool(c.player_id, POOL,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=value, max_cost=value),
            source_id=c.source_id, destination='board', cause=SummonCause.capture(c))
        return (request,)*count
    def nexus(c):
        value, count = parameters(c, NEXUS)
        return (DrawWithCostReduction(c.player_id, value, c.source_id),)*count
    def map_body(c):
        options = (ChoiceOption('charge', '充能', modifier(c, CHARGE), card_id=CHARGE),
            ChoiceOption('channel', '导通', discount(c, 2), card_id=CHANNEL),
            ChoiceOption('enhance', '强化', modifier(c, ENHANCE), card_id=ENHANCE))
        return (*(AddToHand(c.player_id, cid, c.source_id) for cid in d['map_delivery_order']),
            RequestChoice(c.player_id, options, c.source_id, prompt='选择魔网升级'))
    bodies = {BURST:burst, CRYSTAL:crystal, NEXUS:nexus, MAP:map_body,
        WALKER:lambda c:discount(c, 1), WALKER+'.death':lambda c:(GenerateFromCandidates(c.player_id, FAMILY, c.source_id),),
        NEEDLE:lambda c:modifier(c, NEEDLE), CAT:lambda c:modifier(c, CAT)}
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    for item in d['cards']+d['dependencies']:
        raw = item['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        fields = dict(cost=0 if cid in CHOICES else raw['cost'], metadata=metadata_from_record(raw))
        if cid in CHOICES:
            fields['choice_only'] = True
        elif kind == CardType.MINION:
            fields.update(attack=raw['attack'], health=raw['health'], battlecry=PREFIX+cid)
            if cid == WALKER: fields['deathrattle'] = PREFIX+cid+'.death'
            if cid == CAT: fields['keywords'] = (Keyword.ELUSIVE,)
        else:
            fields.update(on_play=PREFIX+cid, spell_school=SpellSchool.ARCANE)
        card = CardDefinition(cid, raw['name'], kind, **fields)
        registry.register_card(card)
        if cid not in CHOICES and cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
