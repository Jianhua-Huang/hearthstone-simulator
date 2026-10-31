"""Original Joust, power, discovery/Deathrattle and exact named summon recipes."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.character_attacks import completed_attack,completed_minion_cost,completed_minion_types
from hs_sim.engine.death_hand_returns import ReturnDeadMinion
from hs_sim.engine.discovered_deathrattles import DiscoveredDeathrattleTarget,QUERY as DEATHRATTLES
from hs_sim.engine.effects import (ChoiceOption,Damage,DamageBatch,Draw,Freeze,ReplaceHeroPower,ReturnToHand,Transform)
from hs_sim.engine.fixed_card_discovery import POOL as FIXED_DISCOVERY
from hs_sim.engine.joust import Joust
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CastWhenDrawnSpec,DamageKind,HeroPowerReference,
    Keyword,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.play_history import played_outside_starting_deck,played_cards
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.random_split_damage import RandomSplitDamage,SplitDamageScope
from hs_sim.engine.sacrifice import FreezeCapturedMinion,GrantCapturedDeathrattle,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import AddToDeck,CardReference,MoveCard
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.targets import TargetValidationError,canonical_digest
from .basic_hero_roles import TOTEMS
from .core_secret_cards import event_play
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .upgraded_hero_power_cards import UPGRADES,DAGGER,GHOUL,RECRUIT

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-linked-discovery-summons-v1.json'
BATCH_HASH='b28204f77a0bf35f550e19e18e506674438a09095e83322f93344b425424b0ba'
KNIGHT,JUSTICAR,TAVISH,HANAR,MYRA,GREY,NITHOGG,MALYGOS,YSERA,ARCHIMONDE=ROOTS=(
    'AT_128','AT_132','BAR_038','BT_188','BOT_243','DMF_734','DRG_224','DRG_270','DRG_320','GDB_128')
EGG,WHELP,BOLT,MISSILES,NOVA,POLY,TOME,EXPLOSION,INTELLECT,FIREBALL,FLAMES,SHEEP,PORTAL=DEPENDENCIES=(
    'DRG_224t','DRG_224t2','DRG_270t8','DRG_270t11','DRG_270t5','DRG_270t6','DRG_270t2','DRG_270t4',
    'DRG_270t1','DRG_270t9','DRG_270t7','DRG_270t6t','DRG_320t')
UPGRADED_SPELLS=(BOLT,MISSILES,NOVA,POLY,TOME,EXPLOSION,INTELLECT,FIREBALL,FLAMES)
EXISTING=tuple(dict.fromkeys((*UPGRADES,*UPGRADES.values(),DAGGER,GHOUL,RECRUIT,*TOTEMS)))
EVIDENCE=('MIS_701','BOT_243e','DMF_734e','AT_132_SHAMANa','AT_132_SHAMANb','AT_132_SHAMANc','AT_132_SHAMANd')
PREFIX='cards.past_linked_discovery_summons.'
POOL='constructed.cards'
MAGE_SPELLS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
DRAGONS=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',))


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS+DEPENDENCIES or raw['type']not in('MINION','SPELL'):
        raise TargetValidationError('Linked consumers require complete original physical faces')
    kind=CardType(raw['type'].lower());cost=0 if cid==BOLT else raw['cost'];attack=0 if cid==EGG else raw['attack']
    if type(cost)is not int or kind==CardType.MINION and any(type(x)is not int for x in(attack,raw['health'])):
        raise TargetValidationError('Linked consumers lost their exact printed numeric body')
    fields={}
    if cid in(JUSTICAR,MYRA,NITHOGG,MALYGOS,YSERA,ARCHIMONDE):fields['battlecry']=PREFIX+cid
    if cid in(KNIGHT,GREY):fields['deathrattle']=PREFIX+cid
    if cid==GREY:fields['keywords']=(Keyword.TAUNT,)
    if cid==WHELP:fields['keywords']=(Keyword.RUSH,)
    if cid==TAVISH:fields['triggers']=(TriggerSpec('attack_finished',PREFIX+cid),)
    if cid==HANAR:fields['triggers']=(TriggerSpec('card_played',PREFIX+cid),)
    if cid==EGG:fields['triggers']=(TriggerSpec('turn_started',PREFIX+'hatch'),)
    if kind==CardType.SPELL:fields['on_play']=PREFIX+cid
    if cid==PORTAL:fields.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
    if cid in(BOLT,FIREBALL):fields['targeting']=TargetSpec()
    if cid==POLY:fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    return CardDefinition(cid,raw['name'],kind,cost=cost,attack=attack if kind==CardType.MINION else 0,
        health=raw['health']if kind==CardType.MINION else 0,spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))if kind==CardType.SPELL else None,
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=48 or
            tuple(d['fixed_upgraded_spell_ids'])!=UPGRADED_SPELLS or d['fixed_upgraded_spell_weights']!=[1]*9 or
            d['upgraded_power_map']!=UPGRADES or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Linked consumers lost complete source roles or open-domain boundaries')
    for row in d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Changed complete original linked source row')
    for entry in d['retained_documents'].values():
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Changed complete original linked reference')
    ref=json.loads((ROOT/d['retained_documents']['past']['path']).read_text(encoding='utf8'))
    rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):raise TargetValidationError('Cropped full original past source')
    return d


def register_past_linked_discovery_summons(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                (cid in registry.pool_cards)!=row['pool_card_present']or row['pool_card_present']and
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Linked consumer changed an original basic/upgraded power dependency')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Linked consumer cannot replace or alter a complete physical face')
        registry._validate_card(card);prepared.append(card)
    def knight(c):
        work=()
        if c.death is not None:
            origin=c.death.copy_source.origin
            if(c.source.zone,c.source.card_id,c.source.zone_epoch,c.source.entered_order)==(
                    Zone.GRAVEYARD,origin.card_id,origin.zone_epoch+1,origin.entered_order):
                fact=SourceAllocationFact.capture(c.state,c.source);work=(ReturnDeadMinion(c.death.id,fact,fact),)
        elif c.source.zone==Zone.BOARD:
            work=(ReturnToHand(c.source_id,recipient=MinionReference.capture(c.source)),)
        elif c.source.zone==Zone.DECK:
            work=(MoveCard(CardReference.capture(c.source),c.player_id,Zone.HAND,reset=True,source_id=c.source_id),)
        return(Joust(c.player_id,source_id=c.source_id,on_win=work),)
    def justicar(c):
        power_id=c.state.players[c.player_id].hero_power_id
        if power_id is None:return()
        power=c.state.entities[power_id]
        upgraded=UPGRADES.get(power.card_id)
        return()if upgraded is None else(ReplaceHeroPower(c.player_id,upgraded,HeroPowerReference.capture(power),source_id=c.source_id),)
    def tavish(c):
        row=completed_attack(c)
        if row is None or row.source_kind!=CardType.MINION or row.combat.player_id!=c.player_id:return()
        tribes=completed_minion_types(c,registry)
        if tribes is None or not tribes.matches_any(('beast',)):return()
        cost=completed_minion_cost(c,registry)-1
        if cost<0:return()
        return(SummonFromZone(c.player_id,query=PoolQuery(kinds=(CardType.MINION,),tribes_any=('beast',),
            min_cost=cost,max_cost=cost),cost_basis='local',source_id=c.source_id,cause=SummonCause.capture(c)),)
    def hanar(c):
        play=event_play(c)
        if play is None or play.player_id!=c.player_id or play.countered or registry.card(play.card_id).secret is None:return()
        meta=play.played_face.metadata
        if meta is None or meta.classes is None:raise TargetValidationError('Hanar requires the original played Secret class')
        classes=tuple(klass for klass in CardClass if klass!=CardClass.NEUTRAL and klass not in meta.classes)
        query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,keywords_all=(Keyword.SECRET,),
            class_mode='specified',classes=classes,include_neutral=False)
        return(DiscoverFromPool(c.player_id,POOL,query,source_id=c.source_id),)
    def myra(c):
        if c.battlecry is None:raise TargetValidationError('Myra requires her original actual Battlecry')
        ref=MinionReference.capture(c.source)if c.source.kind==CardType.MINION and c.source.zone==Zone.BOARD else None
        return(DiscoverFromPool(c.player_id,POOL,DEATHRATTLES,source_id=c.source_id,destination='memory',
            memory_target=DiscoveredDeathrattleTarget(c.battlecry.id,ref)),)
    def grey(c):
        options=tuple(ChoiceOption(str(i),registry.card(e.card_id).name,(
            GrantCapturedDeathrattle(MinionReference.capture(e),PREFIX+'grey_child',c.source_id),))
            for i in c.state.players[c.player_id].board for e in(c.state.entities[i],)
            if e.kind==CardType.MINION and e.active and e.health>0 and not e.doomed)
        return()if not options else(ChooseRandomEffects(c.player_id,c.source_id,options),)
    def hatch(c):
        if c.event.player_id!=c.player_id:return()
        return(Transform(c.source_id,WHELP,MinionReference.capture(c.source)),)
    def malygos(c):
        held=any(c.state.entities[i].kind==CardType.MINION and has_any_tribe(registry,c.state.entities[i],('dragon',))
            for i in c.state.players[c.player_id].hand)
        return()if not held else(DiscoverFromPool(c.player_id,FIXED_DISCOVERY,source_id=c.source_id,fixed_candidates=UPGRADED_SPELLS),)
    def archimonde(c):
        outside={p.id for p in played_outside_starting_deck(c.state,c.player_id)}
        rows=played_cards(c.state,c.player_id,kind=CardType.MINION,registry=registry,tribes_any=('demon',))
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(p.card_id),),cause)for p in rows if p.id in outside)
    def enemies(c):
        return tuple(c.state.entities[i]for i in c.state.players[3-c.player_id].board
            if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].active and
            c.state.entities[i].health>0 and not c.state.entities[i].doomed)
    def aoe(c,amount):return(DamageBatch(tuple(Damage(e.id,amount,c.source_id,DamageKind.SPELL)for e in enemies(c))),)
    def bolt(c):
        target=c.state.entities[c.target_id]
        freeze=FreezeCapturedMinion(MinionReference.capture(target),c.source_id)if target.kind==CardType.MINION else Freeze(target.id,c.source_id)
        return(Damage(target.id,3,c.source_id,DamageKind.SPELL),freeze)
    def missiles(c):
        if c.cast is None:raise TargetValidationError('Upgraded missiles require their actual original CAST')
        return(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,6,SplitDamageScope(),kind=DamageKind.SPELL),)
    bodies={KNIGHT:knight,JUSTICAR:justicar,TAVISH:tavish,HANAR:hanar,MYRA:myra,GREY:grey,
        NITHOGG:lambda c:tuple(SummonByCard(c.player_id,(SummonEntryMaterial(EGG),),SummonCause.capture(c))for _ in range(2)),
        MALYGOS:malygos,YSERA:lambda c:shuffled(c,tuple(AddToDeck(c.player_id,PORTAL,source_id=c.source_id)for _ in range(7))),
        ARCHIMONDE:archimonde,'hatch':hatch,
        'grey_child':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(GREY),),SummonCause.capture(c)),),
        BOLT:bolt,MISSILES:missiles,NOVA:lambda c:tuple(FreezeCapturedMinion(MinionReference.capture(e),c.source_id)for e in enemies(c)),
        POLY:lambda c:(Transform(c.target_id,SHEEP,MinionReference.capture(c.state.entities[c.target_id])),),
        TOME:lambda c:(GenerateFromPool(c.player_id,POOL,MAGE_SPELLS,count=3,source_id=c.source_id),),
        EXPLOSION:lambda c:aoe(c,2),INTELLECT:lambda c:(Draw(c.player_id,4,c.source_id),),
        FIREBALL:lambda c:(Damage(c.target_id,8,c.source_id,DamageKind.SPELL),),FLAMES:lambda c:aoe(c,8),
        PORTAL:lambda c:(GenerateFromPool(c.player_id,POOL,DRAGONS,source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),)}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
