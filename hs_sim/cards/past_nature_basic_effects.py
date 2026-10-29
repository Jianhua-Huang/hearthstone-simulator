"""Fourteen real past Nature spells over the existing public effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import (AddToHand, Buff, ChangeManaCrystals, Damage,
    Destroy, Draw, GainArmor, InvokeBehavior, Overload, RefreshMana)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind,
    Keyword, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/past-nature-basic-effects-v1.json'
BATCH_HASH = 'c9b4ee313b0e1c6e86bd2cb73012f76943e0fe962070248b244c7430e7210b6e'
POLICY = 'cn37-local-past-nature-basic-effects-v1'
SPELLS = ('BOT_054', 'BT_130', 'CS2_013', 'SCH_427', 'LOOT_047', 'UNG_108',
    'TOY_805', 'EX1_161', 'BAR_533', 'BOT_420', 'EX1_571', 'GIL_663', 'YOP_026', 'REV_307')
TOKENS = ('BAR_533t', 'EX1_tk9', 'GIL_663t', 'DMF_061t2', 'REV_336t2')
OVERFLOW = 'CS2_013t'
PREFIX = 'cards.past_nature_basic.'
TOKEN_BINDINGS = {'BAR_533': 'BAR_533t', 'BOT_420': 'EX1_tk9', 'EX1_571': 'EX1_tk9',
    'GIL_663': 'GIL_663t', 'YOP_026': 'DMF_061t2', 'REV_307': 'REV_336t2'}


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            tuple(v['record']['id'] for v in d['cards']) != SPELLS or
            tuple(v['record']['id'] for v in d['dependencies']) != TOKENS or
            [v['record']['id'] for v in d['existing_dependencies']] != [OVERFLOW] or
            d['token_bindings'] != TOKEN_BINDINGS or len(d['official_observations']) != 28 or
            len(d['complete_druid_Nature_inventory']) != 85 or
            not set(SPELLS) <= set(d['complete_druid_Nature_inventory']) or
            not set(SPELLS) <= set(d['original_missing_native_ids']) or
            d['numeric_normalizations'] != {'SCH_427': {'cost': 0}} or
            any(d[k] for k in ('new_standard_roots', 'membership_uses_executable_coverage',
                'source_scope_bound', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Past Nature effects require complete original records and the full declared source')
    rows = {v['record']['id']: v['record'] for v in d['cards'] + d['dependencies']}
    for row in d['cards'] + d['dependencies'] + d['existing_dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Past Nature effects lost a complete original row')
    for source, token in TOKEN_BINDINGS.items():
        if rows[source]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'] != rows[token]['dbf_id']:
            raise TargetValidationError('Past Nature source changed its original named token identity')
    return d


def register_past_nature_basic_effects(registry):
    d = load_batch()
    old, = d['existing_dependencies']
    if (canonical_digest(asdict(registry.card(OVERFLOW))) != old['definition_sha256'] or
            canonical_digest(asdict(registry.pool_card(OVERFLOW))) != old['pool_card_sha256']):
        raise TargetValidationError('Past Nature effects changed their complete existing Excess Mana')
    prepared = []
    for row in d['cards'] + d['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Past Nature effects cannot replace an existing identity: ' + cid)
        if cid in SPELLS:
            if raw['type'] != 'SPELL' or not raw['collectible'] or raw['tags'].get('SPELL_SCHOOL') != 4:
                raise TargetValidationError('Past Nature spell lost its original kind, school or collectible face')
            fields = dict(on_play=PREFIX + cid)
            if cid in ('EX1_161', 'LOOT_047', 'UNG_108'):
                fields['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,),
                    relation='friendly' if cid == 'UNG_108' else 'any')
            if cid == 'REV_307':
                fields['targeting'] = TargetSpec()
            card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'] or 0,
                spell_school=SpellSchool.NATURE, metadata=metadata_from_record(raw), **fields)
        else:
            if raw['type'] != 'MINION' or raw['collectible'] or raw['text_en'] != ('<b>Taunt</b>' if cid == 'BAR_533t' else ''):
                raise TargetValidationError('Past Nature token requires its complete original plain body')
            card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
                attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw),
                keywords=(Keyword.TAUNT,) if cid == 'BAR_533t' else ())
        if canonical_digest(asdict(card)) != row['definition_sha256']:
            raise TargetValidationError('Past Nature native definition differs from its complete reviewed face')
        prepared.append(card)

    def growth(c, amount):
        player = c.state.players[c.player_id]
        if player.max_mana >= player.mana_cap:
            return (AddToHand(c.player_id, OVERFLOW, c.source_id),)
        return (ChangeManaCrystals(c.player_id, amount),)

    def summon(c, card_id, count):
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(card_id),), cause) for _ in range(count))

    def scale_armor(c):
        target = c.state.entities.get(c.target_id)
        return () if target is None else (GainArmor(c.player_id, max(0, target.attack)),)

    def shrink(c):
        refs = tuple(CardReference.capture(c.state.entities[eid]) for eid in c.state.players[c.player_id].deck
            if c.state.entities[eid].kind == CardType.MINION)
        return tuple(BuffStoredCard(ref, attack=-1, cost=CostSpec(delta=-1), source_id=c.source_id) for ref in refs)

    def arbor_buff(c):
        return tuple(Buff(eid, 2, 1, c.source_id) for eid in minions(c, registry, c.player_id))

    bodies = {
        'BOT_054': lambda c: (ChangeManaCrystals(c.player_id, 2, filled=True),
            ChangeManaCrystals(3-c.player_id, 2, filled=True)),
        'BT_130': lambda c: growth(c, 2),
        'CS2_013': lambda c: growth(c, 1),
        'SCH_427': lambda c: (RefreshMana(c.player_id, 2), Overload(c.player_id, 2)),
        'LOOT_047': lambda c: (Buff(c.target_id, health=3, source_id=c.source_id), GainArmor(c.player_id, 3)),
        'UNG_108': lambda c: (Buff(c.target_id, 1, 1, c.source_id),
            InvokeBehavior(PREFIX + 'scale_armor', c.source_id, c.player_id, c.target_id)),
        'TOY_805': shrink,
        'EX1_161': lambda c: (Destroy(c.target_id, c.source_id), Draw(3-c.player_id, 2, c.source_id)),
        'BAR_533': lambda c: summon(c, 'BAR_533t', 2),
        'BOT_420': lambda c: summon(c, 'EX1_tk9', 2),
        'EX1_571': lambda c: summon(c, 'EX1_tk9', 3),
        'GIL_663': lambda c: (AddToHand(c.player_id, 'GIL_663t', c.source_id),) * 2,
        'YOP_026': lambda c: (*summon(c, 'DMF_061t2', 2),
            InvokeBehavior(PREFIX + 'arbor_buff', c.source_id, c.player_id)),
        'REV_307': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),
            *summon(c, 'REV_336t2', 1)),
        'scale_armor': scale_armor,
        'arbor_buff': arbor_buff,
    }
    for key, body in bodies.items():
        registry.register_behavior(PREFIX + key, body)
    for card in prepared:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
