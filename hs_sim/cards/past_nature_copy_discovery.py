"""Real Nature copies, discoveries, physical draw rewards and repeated summons."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.adapt import adapt, CHOICE_IDS, PLANT_ID
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import AddCostModifier, ChangeManaCrystals, CopyMinion, DestroyBatch, InvokeBehavior
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.jade import CLASSIC, SummonJadeGolem
from hs_sim.engine.model import (BoardPresenceReference, CardClass, CardDefinition, CardType,
    ChooseBranch, ChooseOneSpec, CostSpec, Keyword, SpellSchool, SummonStats, TargetSpec, Zone)
from hs_sim.engine.physical_draw_groups import DrawPhysicalGroup, DrawGroupSlot, DrawGroupReward
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-nature-copy-discovery-v1.json'
BATCH_HASH = 'beb6ffb56468ae7e49425ae0588b6e46a4a56660608cc4994c3a6316ac752f64'
POLICY = 'cn37-local-past-nature-copy-discovery-v1'
PREFIX = 'cards.past_nature_copy_discovery.'
ROOTS = ('BAR_549','BT_128','BT_129','CFM_713','DAL_352','DRG_315','FP1_019',
    'ICC_054','REV_313','SCH_333','TTN_955','UNG_103','WW_818')
TOKENS = ('FP1_019t', 'ICC_832t4')
CHOICES = ('TTN_955A', 'TTN_955B')
SHARED = (*CHOICE_IDS, PLANT_ID, 'CFM_712_t01', 'CFM_712_t04', 'CFM_712_t07', 'CFM_712_t20')
EVIDENCE = ('BAR_549e','BT_129e','DRG_315e','DRG_315e2','REV_313e','SCH_333e','SCH_333e2','TTN_955Be','WW_818e')
POOL = 'constructed.cards'
SPELLS = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current')
NATURE = PoolQuery(kinds=(CardType.SPELL,), collectible=True, spell_schools=(SpellSchool.NATURE,))
DRUID_MINIONS = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='specified',
    classes=(CardClass.DRUID,), include_neutral=False)
TWOS = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=2, max_cost=2, class_mode='current')


def make_definition(raw):
    cid = raw['id']; fields = {}
    if cid in TOKENS:
        return CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw),
            keywords=(Keyword.TAUNT,) if cid == 'ICC_832t4' else ())
    if cid in CHOICES:
        fields.update(choice_only=True)
    else:
        fields['on_play'] = PREFIX+cid
    if cid in ('BAR_549','BT_129'):
        fields['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,),
            relation='friendly' if cid == 'BT_129' else 'any')
    if cid == 'TTN_955':
        fields.update(on_play='engine.choose_one', choose_one=ChooseOneSpec(tuple(
            ChooseBranch(choice, label, PREFIX+choice) for choice, label in
                zip(CHOICES, ('获取两张随机自然法术','手牌法术减费'))),
            ChooseBranch('TTN_955:combined','两者兼得',PREFIX+'gift_combined')))
    return CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'] or 0,
        spell_school=SpellSchool.NATURE, metadata=metadata_from_record(raw), **fields)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            tuple(v['record']['id'] for v in d['cards']) != ROOTS or
            tuple(v['record']['id'] for v in d['dependencies']) != TOKENS+CHOICES or
            tuple(v['record']['id'] for v in d['existing_dependencies']) != SHARED or
            tuple(v['record']['id'] for v in d['evidence_only']) != EVIDENCE or
            len(d['official_observations']) != 30 or len(d['complete_druid_Nature_inventory']) != 85 or
            not set(ROOTS) <= set(d['original_missing_native_ids']) or
            any(d[k] for k in ('new_standard_roots','membership_uses_executable_coverage',
                'source_scope_bound','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Nature copy/discovery consumers require their complete original source')
    for row in d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Nature copy/discovery source lost a full original row')
    return d


def register_past_nature_copy_discovery(registry):
    d = load_batch()
    for row in d['existing_dependencies']:
        cid = row['record']['id']
        old_meta = registry.pool_cards.get(cid)
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                (canonical_digest(asdict(old_meta)) if old_meta is not None else None) != row['pool_card_sha256']):
            raise TargetValidationError('Nature consumers changed a complete shared Adapt/Jade identity')
    prepared = []
    for row in d['cards']+d['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Nature consumers cannot overwrite an existing identity: '+cid)
        card = make_definition(raw)
        if canonical_digest(asdict(card)) != row['definition_sha256']:
            raise TargetValidationError('Nature consumer differs from its complete reviewed native face')
        prepared.append(card)

    def spikeshell(c):
        return (BuffCapturedMinion(BoardPresenceReference.capture(c.state,c.target_id),2,2,c.source_id),
            CopyCard(MinionReference.capture(c.state.entities[c.target_id]),c.player_id,
                mode='base',source_id=c.source_id,required_keyword=Keyword.TAUNT))

    def embiggen(c):
        return tuple(BuffStoredCard(CardReference.capture(e),2,2,c.source_id,
            cost=CostSpec(delta=1) if local_cost(e)[0] < 10 else None)
            for i in c.state.players[c.player_id].deck for e in (c.state.entities[i],)
            if e.kind == CardType.MINION)

    def summon(c, player, token, count=1):
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(player,(SummonEntryMaterial(token),),cause) for _ in range(count))

    def seeds(c):
        sides = ((c.player_id,minions(c,registry,c.player_id)),(3-c.player_id,minions(c,registry,3-c.player_id)))
        targets = tuple(i for _,ids in sides for i in ids)
        return (DestroyBatch(targets,c.source_id),)+tuple(effect for player,ids in sides
            for effect in summon(c,player,'FP1_019t',len(ids)))

    def plague(c):
        return (SummonByCard(c.player_id,(SummonEntryMaterial('ICC_832t4',
            on_summon=PREFIX+'plague_repeat',followup_policy='original_delivery'),),SummonCause.capture(c)),)

    def plague_repeat(c):
        return plague(c) if len(minions(c,registry,3-c.player_id)) > len(minions(c,registry,c.player_id)) else ()

    def portal(c):
        keep = not any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].hand)
        return (GenerateFromPool(c.player_id,POOL,DRUID_MINIONS,count=3,replacement=False,source_id=c.source_id),) if keep else (
            DiscoverFromPool(c.player_id,POOL,DRUID_MINIONS,source_id=c.source_id),)

    def discount(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-1),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].kind == CardType.SPELL)

    def gifts(c):
        return (GenerateFromPool(c.player_id,POOL,NATURE,count=2,source_id=c.source_id),)

    bodies = {
        'BAR_549':spikeshell,
        'BT_128':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*3,
            DrawGroupReward('discard_drawn_minions')),),
        'BT_129':lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,
            cause=SummonCause.capture(c),minion_grant=CreatedMinionGrant(keywords=(Keyword.TAUNT,))),),
        'CFM_713':lambda c:(SummonJadeGolem(c.player_id,c.source_id,CLASSIC,cause=SummonCause.capture(c)),ChangeManaCrystals(c.player_id,1)),
        'DAL_352':portal,
        'DRG_315':embiggen,
        'FP1_019':seeds,
        'ICC_054':plague,
        'plague_repeat':plague_repeat,
        'REV_313':lambda c:(DiscoverFromPool(c.player_id,POOL,SPELLS,source_id=c.source_id,
            cost=CostSpec(delta=-2),expires_turn=c.state.turn),),
        'SCH_333':lambda c:(DiscoverFromPool(c.player_id,POOL,SPELLS,source_id=c.source_id),
            AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.SPELL,)),
                uses_remaining=1,source_id=c.source_id)),
        'TTN_955A':gifts,
        'TTN_955B':discount,
        'gift_combined':lambda c:(*gifts(c),InvokeBehavior(PREFIX+'discount',c.source_id,c.player_id)),
        'discount':discount,
        'UNG_103':lambda c:adapt(c,minions(c,registry,c.player_id),registry),
        'WW_818':lambda c:(DiscoverFromPool(c.player_id,POOL,TWOS,source_id=c.source_id,
            cause=SummonCause.capture(c),summon_copy_stats=SummonStats(1,2)),),
    }
    for key,body in bodies.items():
        registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only:
            registry.register_pool_card(PoolCard.from_definition(card))
