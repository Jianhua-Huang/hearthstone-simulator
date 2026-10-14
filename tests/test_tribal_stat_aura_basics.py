"""Native Captain aura selects current Pirates using the original numeric layer."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardDefinition, CardType, ChangeMinionTribes,
    EndTurn, Game, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TribeChangeSpec, TriggerSpec, Zone, has_any_tribe)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, GainArmor, GrantAura, Heal, InvokeBehavior, RequestChoice,
    ReturnToHand, SetStats, Silence, Summon, Transform)
from hs_sim.engine.model import AbilityInstance, Keyword
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_auras import validate_carrier
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

CAPTAIN='NEW1_027'
PATH=Path(__file__).resolve().parents[1]/'data/support/tribal-stat-aura-basics.json'
PIN='07db12bcb2ca9d3c41974c1a9590ffc88e33fb839417bf5434f8fe287765a103'
AURA=AuraSpec(attack=1,health=1,tribes_any=('pirate',))

def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Tribal stat evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw card evidence changed')
    return support['records'][0]['data']

def registry():
    r=Registry('isolated-tribal-stat-aura-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition(CAPTAIN,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],auras=(AURA,),
        metadata=metadata(tribes=('pirate',),rarity=Rarity.EPIC)))
    for cid,tribes in (('pirate',('pirate',)),('plain',()),('dual',('pirate','undead')),
        ('all',('all',)),('unknown',None)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=5,metadata=metadata(tribes=tribes)))
    r.register_behavior('noop',lambda c:())
    r.register_card(CardDefinition('site','Site',CardType.LOCATION,durability=2,on_use='noop',metadata=metadata()))
    r.register_card(CardDefinition('dormant','Dormant',CardType.MINION,attack=2,health=5,
        dormant_turns=None,metadata=metadata(tribes=('pirate',))))
    def wait(c):
        src=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==CAPTAIN)
        return (RequestChoice(1,(
            ChoiceOption('silence','Silence source',(Silence(src),)),
            ChoiceOption('fault','Remove and fail',(Silence(src),InvokeBehavior('late-fault',source_id=c.source_id,player_id=1))),
        ),c.source_id),)
    def declared(c):return wait(c) if c.event.player_id==1 else ()
    def quote(c):return (GainArmor(1,c.state.entities[c.event.target_id].attack),)
    def fail(c):raise ValueError('Fixture late failure')
    r.register_behavior('wait',wait);r.register_behavior('declared',declared)
    r.register_behavior('quote',quote);r.register_behavior('late-fault',fail)
    r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=5,
        triggers=(TriggerSpec('attack_declared','declared'),),metadata=metadata(tribes=())))
    r.register_card(CardDefinition('observer','Observer',CardType.MINION,health=5,
        triggers=(TriggerSpec('tribes_changed','quote'),),metadata=metadata(tribes=())))
    targeted={
        'silence':lambda c:(Silence(c.target_id),),
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'plain-face':lambda c:(Transform(c.target_id,'plain'),),
        'captain-face':lambda c:(Transform(c.target_id,CAPTAIN),),
        'steal':lambda c:(ChangeControl(c.target_id,2),),
        'return':lambda c:(ChangeControl(c.target_id,1),),
        'copy':lambda c:(CopyMinion(c.target_id,1),),
        'base-copy':lambda c:(CopyMinion(c.target_id,1,mode='base'),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'hurt':lambda c:(Damage(c.target_id,4,c.source_id),),
        'heal':lambda c:(Heal(c.target_id,99,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,2,2,c.source_id),),
        'set':lambda c:(SetStats(c.target_id,attack=1,health=3,source_id=c.source_id),),
        'zero':lambda c:(Buff(c.target_id,-9,0,c.source_id),),
        'grant':lambda c:(GrantAura(c.target_id,attack=1,health=1,source_id=c.source_id),),
        'fault':lambda c:(Silence(c.target_id),InvokeBehavior('late-fault',source_id=c.source_id,player_id=1)),
    }
    for name,op,tribes in (('add-pirate','add',('pirate',)),('remove-pirate','remove',('pirate',)),
        ('set-pirate','set',('pirate',)),('set-plain','set',())):
        def work(c,op=op,tribes=tribes):
            return (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec(op,tribes),c.source_id),)
        targeted[name]=work
    scripts={
        'wait':wait,
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[1].board if c.state.entities[i].dormancy is not None)),),
        'summon-captain':lambda c:(Summon(1,CAPTAIN),),
        'summon-pirate':lambda c:(Summon(1,'pirate'),),
        'summon-unknown':lambda c:(Summon(1,'unknown'),),
        'kill-all':lambda c:(DamageBatch(tuple(Damage(i,100,c.source_id) for i in c.state.players[1].board)),),
    }
    for name,body in {**scripts,**targeted}.items():
        if name!='wait':r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=name in targeted,metadata=metadata()))
    return r

class TribalStatAuraBasicsTests(unittest.TestCase):
    def game(self,hand=(),board=(CAPTAIN,'pirate','plain'),enemy=('plain',),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*4,mana=10,max_mana=10),
        ),seed=38),registry())
    def source(self,g):return g.state.players[1].board[0]
    def recipient(self,g):return g.state.players[1].board[1]
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target if g.registry.card(cid).requires_target else None));return eid
    def stats(self,g,eid,attack=3,max_health=6,health=None):
        e=g.state.entities[eid];self.assertEqual((e.attack,e.max_health),(attack,max_health))
        if health is not None:self.assertEqual(e.health,health)
    def choose(self,g,key):c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def roundtrip(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def rehash(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')});return snap

    def test_complete_raw_and_single_native_aura_pin(self):
        raw=evidence();self.assertEqual((raw['id'],raw['cost'],raw['attack'],raw['health']),(CAPTAIN,3,3,3))
        self.assertEqual(raw['text_en'],'Your other Pirates have +1/+1.')
        self.assertEqual((raw['tags']['CLASS'],raw['tags']['CARDRACE'],raw['tags']['RARITY']),(12,23,4))
        card=registry().card(CAPTAIN);self.assertEqual(card.auras,(AURA,));self.assertEqual(card.metadata.rarity,Rarity.EPIC)

    def test_selector_is_immutable_typed_and_board_only(self):
        self.assertEqual(AuraSpec(1,health=1).tribes_any,())
        with self.assertRaises(FrozenInstanceError):AURA.tribes_any=()
        for tribes in (None,['pirate'],('pirate','pirate'),(True,),('',)):
            with self.subTest(tribes=tribes),self.assertRaises((ValueError,TypeError)):replace(AURA,tribes_any=tribes)
        for kw in ({'target':'friendly_weapon'},{'condition':'self_damaged'},{'adjacent_only':True},
            {'attack':True},{'health':-1},{'health':1.0},{'include_self':1}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(AURA,**kw)
        self.assertEqual(replace(AURA,attack=-2,health=0).attack,-2)

    def test_native_source_and_duplicate_definition_guards(self):
        card=registry().card(CAPTAIN)
        for kw in ({'kind':CardType.HERO},{'keywords':(Keyword.MAGNETIC,)},{'keywords':(Keyword.STARSHIP_PIECE,)},{'auras':(AURA,AURA)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):Registry('bad').register_card(replace(card,**kw))
        with self.assertRaises(TypeError):GrantAura(3,tribes_any=('pirate',))

    def test_other_current_pirates_only_exclude_source_enemy_hand_deck_hero(self):
        g=self.game(hand=('pirate',),enemy=('pirate',));self.stats(g,self.source(g),3,3)
        self.stats(g,self.recipient(g));self.stats(g,g.state.players[1].board[2],2,5)
        for eid in (*g.state.players[2].board,*g.state.players[1].hand,*g.state.players[1].deck):self.stats(g,eid,2,5)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].aura_attack,0)
        e=g.state.entities[self.recipient(g)];self.assertEqual(e.enchantments,[]);self.assertEqual(e.abilities,[]);self.roundtrip(g)

    def test_dual_and_all_tribes_and_exclusions_use_shared_query(self):
        g=self.game(board=(CAPTAIN,'dual','all'),hand=('remove-pirate','add-pirate'))
        self.stats(g,self.recipient(g));eid=g.state.players[1].board[2];self.stats(g,eid)
        self.play(g,'remove-pirate',eid);self.stats(g,eid,2,5)
        self.play(g,'add-pirate',eid);self.stats(g,eid);self.roundtrip(g)

    def test_current_identity_add_and_remove_preserve_printed_metadata(self):
        g=self.game(board=(CAPTAIN,'plain'),hand=('add-pirate','remove-pirate'));eid=self.recipient(g)
        self.play(g,'add-pirate',eid);self.stats(g,eid)
        self.assertFalse(has_any_tribe(g.registry,g.state.entities[eid],('pirate',),basis='printed'))
        self.play(g,'remove-pirate',eid);self.stats(g,eid,2,5)

    def test_source_tribe_does_not_condition_its_aura(self):
        g=self.game(hand=('set-plain',));self.play(g,'set-plain',self.source(g));self.stats(g,self.recipient(g));self.roundtrip(g)

    def test_unknown_recipient_is_error_and_unknown_summon_rolls_back(self):
        with self.assertRaises(UnsupportedDefinitionError):self.game(board=(CAPTAIN,'unknown'))
        g=self.game(hand=('summon-unknown',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'summon-unknown')
        self.assertEqual(g.snapshot(),before)
        g=self.game(board=('unknown',));self.stats(g,self.source(g),2,5);self.roundtrip(g)

    def test_manual_and_summoned_source_use_same_native_attachment(self):
        for cid in (CAPTAIN,'summon-captain'):
            g=self.game(board=('pirate',),hand=(cid,));self.play(g,cid)
            self.stats(g,self.source(g));e=g.state.entities[g.state.players[1].board[-1]]
            a=next(a for a in e.abilities if a.kind=='aura');self.assertEqual(a.aura_spec,AURA);self.roundtrip(g)

    def test_newly_summoned_pirate_gets_shared_numeric_contribution(self):
        g=self.game(board=(CAPTAIN,),hand=('summon-pirate',));self.play(g,'summon-pirate');self.stats(g,self.recipient(g));self.roundtrip(g)

    def test_two_sources_add_once_per_physical_carrier_and_support_each_other(self):
        g=self.game(board=(CAPTAIN,'pirate',CAPTAIN),hand=('silence','destroy'));src=self.source(g);eid=self.recipient(g);second=g.state.players[1].board[2]
        self.stats(g,src,4,4);self.stats(g,second,4,4);self.stats(g,eid,4,7)
        self.play(g,'silence',src);self.stats(g,eid);self.play(g,'destroy',second);self.stats(g,eid,2,5);self.roundtrip(g)

    def test_repeated_refresh_does_not_accumulate_or_allocate(self):
        from hs_sim.engine.resolver import Resolution
        g=self.game();copy=g.clone();before=deepcopy(copy._state);next_id=before.next_attachment_id
        for _ in range(3):Resolution(copy).refresh_auras()
        self.assertEqual(copy._state.next_attachment_id,next_id);self.assertEqual(copy.state,before)

    def test_old_local_buff_set_and_zero_floor_remain_before_aura(self):
        g=self.game(hand=('buff','set','zero'));eid=self.recipient(g)
        self.play(g,'buff',eid);self.stats(g,eid,5,8)
        self.play(g,'set',eid);self.stats(g,eid,2,4)
        self.play(g,'zero',eid);self.stats(g,eid,0,4);self.roundtrip(g)

    def test_health_removal_clamps_remaining_health_with_original_policy(self):
        g=self.game(hand=('hurt','silence'));eid=self.recipient(g)
        self.play(g,'hurt',eid);self.stats(g,eid,health=2)
        self.play(g,'silence',self.source(g));self.stats(g,eid,2,5,2);self.roundtrip(g)

    def test_real_combat_reads_current_attack_and_preserves_spent_opportunity(self):
        g=self.game();eid=self.recipient(g);g.apply(Attack(1,eid,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,77)
        self.assertEqual(g.state.entities[eid].attacks_this_turn,1);self.roundtrip(g)

    def test_unhurt_health_removal_clamps_to_original_maximum(self):
        g=self.game(hand=('destroy',));eid=self.recipient(g)
        self.play(g,'destroy',self.source(g));self.stats(g,eid,2,5,5)

    def test_current_tribe_loss_and_gain_preserve_original_health_clamp(self):
        g=self.game(hand=('hurt','remove-pirate','add-pirate'));eid=self.recipient(g)
        self.play(g,'hurt',eid);self.play(g,'remove-pirate',eid);self.stats(g,eid,2,5,2)
        self.play(g,'add-pirate',eid);self.stats(g,eid,3,6,3);self.roundtrip(g)

    def test_silencing_recipient_keeps_external_aura(self):
        g=self.game(hand=('buff','silence'));eid=self.recipient(g)
        self.play(g,'buff',eid);self.play(g,'silence',eid);self.stats(g,eid);self.roundtrip(g)

    def test_silencing_dynamic_recipient_restores_printed_nonpirate(self):
        g=self.game(board=(CAPTAIN,'plain'),hand=('add-pirate','silence'));eid=self.recipient(g)
        self.play(g,'add-pirate',eid);self.play(g,'silence',eid);self.stats(g,eid,2,5)

    def test_current_source_copy_has_independent_attachment_and_old_provenance(self):
        g=self.game(hand=('copy','silence'));src=self.source(g);eid=self.recipient(g)
        old=next(a for a in g.state.entities[src].abilities if a.kind=='aura')
        self.play(g,'copy',src);new=next(a for a in g.state.entities[g.state.players[1].board[-1]].abilities if a.kind=='aura')
        self.assertNotEqual(new.id,old.id);self.assertEqual(new.source_id,old.source_id)
        self.play(g,'silence',src);self.stats(g,eid);self.roundtrip(g)

    def test_recipient_copy_does_not_make_external_stats_permanent(self):
        g=self.game(hand=('copy','destroy'));self.play(g,'copy',self.recipient(g));eid=g.state.players[1].board[-1]
        self.play(g,'destroy',self.source(g));self.stats(g,eid,2,5);self.roundtrip(g)

    def test_current_and_base_copies_keep_distinct_current_tribes(self):
        g=self.game(board=(CAPTAIN,'plain'),hand=('add-pirate','copy','base-copy'));eid=self.recipient(g)
        self.play(g,'add-pirate',eid);self.play(g,'copy',eid);current=g.state.players[1].board[-1]
        self.play(g,'base-copy',eid);base=g.state.players[1].board[-1]
        self.stats(g,current);self.stats(g,base,2,5);self.roundtrip(g)

    def test_source_bounce_and_replay_replace_native_attachment(self):
        g=self.game(hand=('bounce',));src=self.source(g);eid=self.recipient(g)
        old=next(a for a in g.state.entities[src].abilities if a.kind=='aura')
        self.play(g,'bounce',src);self.stats(g,eid,2,5);self.play(g,CAPTAIN)
        new=next(a for a in g.state.entities[src].abilities if a.kind=='aura');self.assertNotEqual(new.id,old.id);self.stats(g,eid);self.roundtrip(g)

    def test_source_transform_away_and_into_captain(self):
        g=self.game(hand=('plain-face','captain-face'));src=self.source(g);eid=self.recipient(g)
        self.play(g,'plain-face',src);self.stats(g,eid,2,5)
        self.play(g,'captain-face',src);self.stats(g,eid);self.roundtrip(g)

    def test_source_and_recipient_control_use_current_board(self):
        g=self.game(hand=('steal','return'),enemy=('pirate',));src=self.source(g);eid=self.recipient(g)
        self.play(g,'steal',src);self.stats(g,eid,2,5);self.stats(g,g.state.players[2].board[0])
        self.play(g,'return',src);self.stats(g,eid);self.stats(g,g.state.players[2].board[0],2,5);self.roundtrip(g)

    def test_recipient_control_into_destination_source_reprices_only_current_aura(self):
        g=self.game(hand=('steal',),enemy=(CAPTAIN,));eid=self.recipient(g)
        self.play(g,'steal',eid);self.stats(g,eid);self.roundtrip(g)

    def test_source_dormancy_and_recipient_wake_use_old_active_policy(self):
        g=self.game(hand=('sleep','wake'));src=self.source(g);eid=self.recipient(g)
        self.play(g,'sleep',src);self.stats(g,eid,2,5);self.play(g,'wake');self.stats(g,eid);self.roundtrip(g)
        g=self.game(board=(CAPTAIN,'dormant','site'),hand=('wake',));eid=self.recipient(g)
        self.stats(g,eid,2,5);self.play(g,'wake');self.stats(g,eid);self.assertEqual(g.state.entities[g.state.players[1].board[2]].aura_health,0)

    def test_simultaneous_death_records_freeze_original_stat_contributions(self):
        g=self.game(board=(CAPTAIN,'pirate'),hand=('kill-all',));self.play(g,'kill-all')
        d=next(d for d in g.state.death_history if d.card_id=='pirate');self.assertEqual((d.attack,d.max_health),(3,6));self.roundtrip(g)

    def test_tribe_change_event_context_has_current_numeric_aura(self):
        g=self.game(board=(CAPTAIN,'plain','observer'),hand=('add-pirate','remove-pirate'));eid=self.recipient(g)
        self.play(g,'add-pirate',eid);self.play(g,'remove-pirate',eid)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5);self.roundtrip(g)

    def test_actual_declared_attack_wait_uses_current_delivery_and_recovers(self):
        g=self.game(board=(CAPTAIN,'pirate','watcher'));eid=self.recipient(g)
        g.apply(Attack(1,eid,g.state.players[2].hero_id));self.assertIsNotNone(g.state.pending_choice);self.roundtrip(g)
        matches=(g,Game.from_snapshot(g.snapshot(),registry()),g.clone(),replay(build_replay(g),registry()))
        for match in matches:
            self.choose(match,'silence');self.stats(match,eid,2,5)
            self.assertEqual(match.state.entities[match.state.players[2].hero_id].health,78)
            self.assertEqual(match.state.entities[eid].attacks_this_turn,1)
        self.assertTrue(all(m.snapshot()==g.snapshot() for m in matches));self.roundtrip(g)

    def test_immediate_and_choice_failures_roll_back_numeric_and_information_state(self):
        g=self.game(hand=('fault','wait'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fault',self.source(g))
        self.assertEqual(g.snapshot(),before);self.play(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.roundtrip(g)

    def test_player_views_queries_hide_internal_selector_and_are_pure(self):
        g=self.game();before=g.snapshot()
        for _ in range(3):
            text=json.dumps((g.observe(1),g.legal_actions(),g.player_events(1)),default=str)
            for hidden in ('aura_tribes_any','attachment_id','registry_fingerprint','resolution_frame'):self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)

    def test_native_flattened_ability_provenance_and_exact_declaration_guards(self):
        g=self.game();a=next(a for a in g.state.entities[self.source(g)].abilities if a.kind=='aura')
        self.assertEqual(a.aura_spec,AURA)
        for kw in ({'origin':'granted'},{'consumed':True},{'expires_turn':1},{'remove_on_silence':False},{'magnetic_id':1}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(a,**kw)
        for kw in ({'aura_tribes_any':()},{'aura_tribes_any':('beast',)},{'include_self':True},{'attack':2}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):validate_carrier(g.registry,CAPTAIN,CardType.MINION,[replace(a,**kw)])
        with self.assertRaises(ValueError):validate_carrier(g.registry,CAPTAIN,CardType.MINION,[a,replace(a,id=999)])
        with self.assertRaises(ValueError):AbilityInstance(1,'keyword',keyword=Keyword.CHARGE,aura_tribes_any=('pirate',))
        with self.assertRaises(ValueError):AbilityInstance(1,'keyword',keyword=Keyword.CHARGE,aura_tribes_any=[])

    def test_rehashed_wire_requires_full_selector_and_rejects_stale_cache(self):
        g=self.game();src=self.source(g)
        for value in (None,'pirate',[True],['pirate','pirate'],[],['beast']):
            s=g.snapshot();a=next(a for a in s['state']['entities'][str(src)]['abilities'] if a['kind']=='aura');a['aura_tribes_any']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())
        s=g.snapshot();del next(a for a in s['state']['entities'][str(src)]['abilities'] if a['kind']=='aura')['aura_tribes_any']
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())
        for field in ('aura_attack','aura_health'):
            s=g.snapshot();s['state']['entities'][str(self.recipient(g))][field]=0
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())

    def test_original_captured_context_checks_its_own_native_tribe_selector(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);ctx=RuleContext(g.state,self.source(g),1)
        self.assertEqual(codec.decode(codec.encode(ctx)).state.entities[self.recipient(g)].aura_attack,1)
        state=deepcopy(g.state);src=state.entities[self.source(g)]
        src.abilities=[replace(a,aura_tribes_any=()) if a.kind=='aura' else a for a in src.abilities]
        with self.assertRaises(ValueError):codec.decode(codec.encode(replace(ctx,state=state)))

    def test_schema_versions_strictly_reject_all_old_and_nonstrict(self):
        g=self.game();s=g.snapshot();self.assertEqual(s['schema_version'],266)
        self.assertEqual(s['ruleset']['id'],'prototype-v302');self.assertEqual(s['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for value in (*range(1,218),True,186.0,217):
            bad=deepcopy(s);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

if __name__=='__main__':unittest.main()
