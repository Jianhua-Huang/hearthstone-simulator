"""Real original-offer, selected-copy, entry-boon and historical Arcane spells."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import TransformDefiningHandCardFromPool
from hs_sim.engine.effects import InvokeBehavior, RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardDefinition, CardType, DamageKind, HandProgressSpec, Keyword, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.spell_history import DiscoverSpellHistory, SpellHistoryQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-discovery-profiles-v1.json'
BATCH_HASH = 'ef33f3b1addde3379a75bfaa9ac64a8336b3858201436ce2c4652186531fde60'
LEAVES = ('BT_021','DAL_578','ETC_528','ETC_532','GDB_479','LOOT_104')
DEPENDENCIES = LEAVES
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_discovery_profiles.'
POOL = 'constructed.cards'
MAGE_MINIONS = PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
MAGE_SPELLS = PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
SIXES = PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',min_cost=6,max_cost=6)
EIGHTS = PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',min_cost=8,max_cost=8)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(v['record']['id']for v in data['dependencies']) != LEAVES or
            tuple(v['record']['id']for v in data['evidence_only']) != ('LOOT_104e',) or
            len(data['official_observations']) != 12 or data['numeric_normalizations'] != {'LOOT_104':{'cost':0}} or
            data['display_normalizations'] != {'ETC_528':{'@':''}} or
            any(data[k]for k in('cards','existing_dependencies','skipped','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            not set(LEAVES)<=set(reference['candidate_ids']) or
            any(canonical_digest(v['record']) != v['record_sha256']for v in data['dependencies']+data['evidence_only'])):
        raise TargetValidationError('Past Arcane discovery consumers changed their complete original source or finite policies')
    return data


def register_past_arcane_discovery_profiles(registry):
    prepared = []
    for row in load_batch()['dependencies']:
        raw = row['record'];cid = raw['id']
        if cid in registry.cards:
            raise TargetValidationError('Past Arcane discovery consumers cannot overwrite an original identity: '+cid)
        if raw['type']!='SPELL' or raw['tags'].get('SPELL_SCHOOL')!=1:
            raise TargetValidationError('Past Arcane discovery consumer changed its original Arcane face')
        fields = ({'manual_playable':False,'defining_hand_source':HandProgressSpec('event',event='turn_started',
            on_complete=PREFIX+'shift',repeat=True)}if cid=='LOOT_104'else {'on_play':PREFIX+cid})
        card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=0 if cid=='LOOT_104'else raw['cost'],
            spell_school=SpellSchool.ARCANE,metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Past Arcane discovery consumer differs from its original printed metadata: '+cid)
        prepared.append(card)

    def font(c):
        keep = not any(c.state.entities[i].kind==CardType.MINION for i in c.state.players[c.player_id].deck)
        if keep:
            return (GenerateFromPool(c.player_id,POOL,MAGE_MINIONS,count=3,replacement=False,source_id=c.source_id),)
        return (DiscoverFromPool(c.player_id,POOL,MAGE_MINIONS,source_id=c.source_id),)
    def lightshow(c):
        if c.cast is None or (c.cast.source_id,c.cast.player_id,c.cast.card_id)!=(c.source_id,c.player_id,'ETC_528'):
            raise ResolutionError('Lightshow requires its actual original CAST')
        identity = registry.pool_card('ETC_528').generation_identity
        count = sum(row.player_id==c.player_id and row.payload_started and row.failure is None and
            (row.card_id=='ETC_528' or row.card_id in registry.pool_cards and
                registry.pool_card(row.card_id).generation_identity==identity)for row in c.state.cast_history)
        return (InvokeBehavior(PREFIX+'beam',c.source_id,c.player_id)for _ in range(1+count))
    def shift(c):
        source = c.trigger
        if source is None or source.kind!='defining_hand_source' or source.defining_card_id!='LOOT_104':
            raise ResolutionError('Shifting Scroll lost its original defining hand source')
        return (TransformDefiningHandCardFromPool(CardReference.capture(c.source),'LOOT_104',source.id,POOL,
            query=MAGE_SPELLS),)
    bodies = {
        'BT_021':font,
        'DAL_578':lambda c:(DiscoverFromPool(c.player_id,POOL,SIXES,source_id=c.source_id,destination='board',
            cause=SummonCause.capture(c),summon_copies=2),),
        'GDB_479':lambda c:(DiscoverFromPool(c.player_id,POOL,EIGHTS,source_id=c.source_id,destination='board',
            cause=SummonCause.capture(c),discoveries=2,entry_keywords=(Keyword.TAUNT,Keyword.ELUSIVE)),),
        'ETC_528':lightshow,
        'beam':lambda c:(RandomDamage(characters(c,registry,3-c.player_id),2,c.source_id,DamageKind.SPELL),),
        'ETC_532':lambda c:(DiscoverSpellHistory(c.player_id,SpellHistoryQuery(cards=PoolQuery(exclude_source=True)),
            source_id=c.source_id,discovery=True),),
        'shift':shift,
    }
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
