"""Original completed-attack copy and the complete eight-form Vortex producer."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.copy_followups import decode,original_copy_reference
from hs_sim.engine.effects import ChoiceOption,CopyMinion,ForceAttack
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,Zone
from hs_sim.engine.player_spell_count_costs import count_distinct_cast_schools
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import live_minion
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/visage-vortex-v1.json'
BATCH_HASH='b44714c016b2e3950d47f70a6abede3a32ccacf280ae12cc8a583b486c8e5f33'
POLICY='cn37-local-visage-vortex-v1'
VISAGE,INSPIRATION=LEAVES=('REV_516','TTN_480')
VORTICES=('TTN_480t','TTN_480t6','TTN_480t5','TTN_480t7','TTN_480t2','TTN_480t4','TTN_480t1','TTN_480t3')
BONUSES=(Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL,Keyword.POISONOUS,Keyword.REBORN,
    Keyword.RUSH,Keyword.ELUSIVE,Keyword.TAUNT,Keyword.WINDFURY)
DEPENDENCIES=(*LEAVES,*VORTICES)
COLLECTIBLE_ROOTS=()
PREFIX='cards.visage_vortex.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=POLICY or
            tuple(data['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in data['dependencies'])!=DEPENDENCIES or
            tuple(data['vortex_ids'])!=VORTICES or data['vortex_weights']!=[1]*8 or
            len(data['official_observations'])!=4 or any(data[k] for k in ('cards','existing_dependencies',
                'new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Visage/Vortex requires two full roots and all eight original token faces')
    children=[x['record']['dbf_id'] for x in data['dependencies'][2:]]
    parents=[x for x in data['official_observations'] if x['card_id']==INSPIRATION]
    if (data['vortex_child_dbf_ids']!=children or {x['locale'] for x in parents}!={'en_US','zh_CN'} or
            any(x['face']['childIds']!=children for x in parents)):
        raise TargetValidationError('Vortex faces lost full bilingual primary parent membership/order')
    path=ROOT/data['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=data['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Visage/Vortex roots lost their complete past-Mage reference scope')
    return data


def attacked_hero_source(c,registry):
    if c.event is None or c.event.kind!='attack_finished':return None
    row=completed_attack(c)
    if (row is None or row.source_kind!=CardType.MINION or row.combat.player_id==c.player_id or
            row.combat.target_player_id!=c.player_id or registry.card(row.combat.target_card_id).kind!=CardType.HERO):
        return None
    unit=c.state.entities.get(row.declaration.source_id)
    if (unit is None or unit.zone!=Zone.BOARD or unit.kind!=CardType.MINION or unit.controller==c.player_id or
            not unit.active or unit.health<=0 or unit.doomed or unit.entered_order!=row.combat.source_entered_order):
        return None
    return unit


def register_visage_vortex_cards(registry):
    from hs_sim.engine.random_effect_choices import ChooseRandomEffects
    def visage(c):
        unit=attacked_hero_source(c,registry)
        return () if unit is None else (CopyMinion(capture_board_presence(c.state,unit.id),c.player_id,
            cause=SummonCause.capture(c),on_summon=PREFIX+'attack'),)
    def attack(c):
        original_copy_reference(c)
        beneficiary=decode(dict(c.event.data)['followup']).beneficiary
        unit=live_minion(c.state,beneficiary)
        return () if unit is None else (ForceAttack(capture_board_presence(c.state,unit.id),
            c.state.players[3-c.player_id].hero_id),)
    def inspiration(c):
        count=count_distinct_cast_schools(c.state,registry,c.player_id)
        cause=SummonCause.capture(c)
        options=tuple(ChoiceOption(cid,cid,(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),cause),)) for cid in VORTICES)
        return tuple(ChooseRandomEffects(c.player_id,c.source_id,options) for _ in range(count))
    prepared=[]
    for index,item in enumerate(load_batch()['dependencies']):
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Visage/Vortex face already registered')
        if index<2:
            extra={'keywords':(Keyword.SECRET,), 'secret':SecretSpec(cid,('attack_finished',),PREFIX+'visage',
                PREFIX+'visage',requires_board_space=True)} if cid==VISAGE else {'on_play':PREFIX+'inspiration'}
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],
                spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**extra)
        else:
            if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'])!=('MINION',False,4,4,5):
                raise TargetValidationError('Vortex lost its actual noncollectible 4/5 face')
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
                keywords=(BONUSES[index-2],),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for key,body in (('visage',visage),('attack',attack),('inspiration',inspiration)):
        registry.register_behavior(PREFIX+key,body)
    registry.register_secret_condition(PREFIX+'visage',lambda c:attacked_hero_source(c,registry) is not None)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
