"""Toreth consumes one original shield over three positive damage packets."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.divine_shield_hit_provider_card import CARD,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DamageKind,Game,Keyword,
    PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,CopyMinion,Damage,DamageBatch,Destroy,GainArmor,GrantHealthRule,
    GrantKeyword,Heal,InvokeBehavior,RequestChoice,Silence,Transform)
from hs_sim.engine.dormancy import MakeDormant,AwakenMinion
from hs_sim.engine.shield_durability import RULE,shields,validate_public
from hs_sim.engine.summon_sources import Resurrect
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

P='shield.hits.test.';BODY,PLAIN,FILL,WATCH=(P+x for x in ('body','plain','fill','watch'))
HIT,ZERO,BATCH=(P+x for x in ('hit','zero','batch'))


@lru_cache(maxsize=None)
def registry(role,mode=None):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    for cid,keywords in ((BODY,(Keyword.DIVINE_SHIELD,)),(PLAIN,()),(FILL,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=5,keywords=keywords,metadata=meta))
    def spell(cid,body,target=True):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=target,metadata=meta))
    spell(HIT,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))
    spell(ZERO,lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.SPELL),))
    spell(BATCH,lambda c:(DamageBatch(tuple(Damage(c.target_id,1,c.source_id,DamageKind.SPELL)for _ in range(4))),))
    for key,body in (('shield',lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),)),
        ('immune',lambda c:(GrantKeyword(c.target_id,Keyword.IMMUNE,c.source_id),)),('heal',lambda c:(Heal(c.target_id,1,c.source_id),)),
        ('silence',lambda c:(Silence(c.target_id),)),('kill',lambda c:(Destroy(c.target_id,c.source_id),)),
        ('copy',lambda c:(CopyMinion(c.target_id,c.player_id),)),('basecopy',lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),)),
        ('transform',lambda c:(Transform(c.target_id,BODY),)),('sleep',lambda c:(MakeDormant(c.target_id,None),)),
        ('wake',lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].dormancy is not None)),))):
        spell(P+key,body,key!='wake')
    spell(P+'resurrect',lambda c:(Resurrect(c.player_id,1,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)),),False)
    spell(P+'grant',lambda c:(GrantHealthRule(999999,RULE,c.source_id),),False)
    def fail(c):raise ResolutionError('Toreth deliberate reaction failure')
    r.register_behavior(P+'fail',fail)
    if mode:
        def watch(c):
            entity=c.state.entities.get(c.event.target_id)
            if entity is None or entity.card_id!=BODY:return ()
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=meta,
            triggers=(TriggerSpec('shield_lost'if mode=='lost'else'damage_prevented',WATCH),)))
    r.validate();r.freeze();return r


class DivineShieldHitProviderTests(unittest.TestCase):
    def game(self,hand=(HIT,)*4,board=(CARD,BODY),enemy=(),mode=None,armor=0):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*5,mana=50,max_mana=50,mana_cap=50,armor=armor),
            PlayerSetup('HERO_08',board=enemy,deck=(FILL,)*5,mana=50,max_mana=50,mana_cap=50)),seed=229258),registry('writer',mode))
    def entity(self,g,cid=BODY,zone='board',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=HIT,target=None):
        e=self.entity(g,cid,'hand');g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def used(self,g,eid):return max((a.divine_shield_hits for a in shields(g.state.entities[eid])),default=None)
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader',self.mode);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint())
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','divine_shield_hits','rule_ids','SourceAllocationFact'):self.assertNotIn(key,public)
        return other
    def test_a00_real_paid_toreth_keeps_its_own_shield_for_three_hits(self):
        g=self.game(hand=(CARD,)+(HIT,)*4,board=());eid=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,45)
        for expected in (1,2):self.play(g,target=eid);self.assertEqual(self.used(g,eid),expected);self.assertEqual(g.state.entities[eid].health,4)
        self.play(g,target=eid);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.assertEqual(g.state.entities[eid].health,4)
        self.play(g,target=eid);self.assertEqual(g.state.entities[eid].health,3);self.portable(g)
    def test_a01_four_simultaneous_packets_prevent_three_and_lose_one_shield(self):
        g=self.game(hand=(BATCH,));eid=self.entity(g).id;self.play(g,BATCH,eid)
        self.assertEqual(g.state.entities[eid].health,4)
        results=[dict(dict(e.data)['result'])for e in g.events if e.kind=='health_resolved']
        self.assertEqual([x['damage_dealt']for x in results],[0,0,0,1]);self.assertEqual(len([e for e in g.events if e.kind=='shield_lost'and e.target_id==eid]),1)
        self.portable(g)
    def test_a02_complete_original_source_and_two_primary_faces(self):
        d=load_batch();row,=d['cards'];self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(d['official_observations']),2);self.assertFalse(d['policy']['formal_pool_complete']);self.assertFalse(d['policy']['cn_calibrated'])
    def test_b00_ordinary_shield_still_blocks_only_one_hit(self):
        g=self.game(hand=(BATCH,),board=(BODY,));eid=self.entity(g).id;self.play(g,BATCH,eid)
        self.assertEqual(g.state.entities[eid].health,2);self.assertEqual([a.divine_shield_hits for a in g.state.entities[eid].abilities if a.keyword==Keyword.DIVINE_SHIELD],[0])
    def test_b01_enemy_provider_does_not_protect_friendly_shield(self):
        g=self.game(board=(BODY,),enemy=(CARD,));eid=self.entity(g).id;self.play(g,target=eid)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
    def test_b02_two_providers_use_three_hits_without_multiplication(self):
        g=self.game(board=(CARD,CARD,BODY));eid=self.entity(g).id
        for _ in range(3):self.play(g,target=eid)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.assertEqual(g.state.entities[eid].health,5)
    def test_b03_friendly_hero_shield_protects_before_armor(self):
        g=self.game(hand=(P+'shield',BATCH),board=(CARD,),armor=5);eid=g.state.players[1].hero_id
        self.play(g,P+'shield',eid);self.play(g,BATCH,eid)
        e=g.state.entities[eid];self.assertEqual((e.health,e.armor),(30,4));self.assertNotIn(Keyword.DIVINE_SHIELD,e.keywords)
    def test_b04_zero_healing_and_immunity_do_not_consume_shield_hits(self):
        g=self.game(hand=(ZERO,P+'heal',P+'immune',HIT));eid=self.entity(g).id
        self.play(g,ZERO,eid);self.play(g,P+'heal',eid);self.play(g,P+'immune',eid);self.play(g,target=eid)
        self.assertEqual(self.used(g,eid),0);self.assertEqual(g.state.entities[eid].health,5)
    def test_b05_provider_does_not_create_a_shield_on_unshielded_minions(self):
        g=self.game(board=(CARD,PLAIN));eid=self.entity(g,PLAIN).id;self.play(g,target=eid)
        self.assertEqual(g.state.entities[eid].health,4);self.assertFalse(shields(g.state.entities[eid]))
    def test_c00_source_loss_uses_one_hit_at_the_next_packet_without_early_shield_loss(self):
        g=self.game(hand=(HIT,P+'silence',HIT,HIT));eid=self.entity(g).id;self.play(g,target=eid)
        self.play(g,P+'silence',self.entity(g,CARD).id);self.assertEqual(self.used(g,eid),1)
        self.play(g,target=eid);self.assertIsNone(self.used(g,eid));self.assertEqual(g.state.entities[eid].health,5)
        self.play(g,target=eid);self.assertEqual(g.state.entities[eid].health,4)
    def test_c01_target_silence_then_fresh_grant_starts_a_new_shield(self):
        g=self.game(hand=(HIT,P+'silence',P+'shield'));eid=self.entity(g).id;self.play(g,target=eid)
        self.play(g,P+'silence',eid);self.assertIsNone(self.used(g,eid));self.play(g,P+'shield',eid);self.assertEqual(self.used(g,eid),0)
    def test_c02_regranting_an_existing_shield_does_not_reset_its_hit_count(self):
        g=self.game(hand=(HIT,P+'shield',HIT,HIT));eid=self.entity(g).id;self.play(g,target=eid);self.play(g,P+'shield',eid)
        self.assertEqual([a.divine_shield_hits for a in shields(g.state.entities[eid])],[1,1])
        self.play(g,target=eid);self.assertEqual(self.used(g,eid),2);self.play(g,target=eid);self.assertIsNone(self.used(g,eid))
    def test_c03_current_copy_keeps_partial_shield_and_base_copy_starts_fresh(self):
        g=self.game(hand=(HIT,P+'copy',P+'basecopy'));eid=self.entity(g).id;self.play(g,target=eid);self.play(g,P+'copy',eid)
        copied=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==BODY and i!=eid);self.assertEqual(self.used(g,copied),1)
        self.play(g,P+'basecopy',eid);fresh=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==BODY and i not in(eid,copied));self.assertEqual(self.used(g,fresh),0);self.portable(g)
    def test_c04_transform_creates_fresh_keyword_identity(self):
        g=self.game(hand=(HIT,P+'transform'));eid=self.entity(g).id;self.play(g,target=eid);old=shields(g.state.entities[eid])[0].id
        self.play(g,P+'transform',eid);self.assertEqual(self.used(g,eid),0);self.assertNotEqual(shields(g.state.entities[eid])[0].id,old)
    def test_c05_resurrection_uses_a_new_body_and_fresh_printed_shield(self):
        g=self.game(hand=(HIT,P+'kill',P+'resurrect'));eid=self.entity(g).id;self.play(g,target=eid);self.play(g,P+'kill',eid);self.play(g,P+'resurrect')
        new=self.entity(g).id;self.assertNotEqual(new,eid);self.assertEqual(self.used(g,new),0);self.portable(g)
    def test_c06_dormancy_and_awaken_preserve_the_original_shield(self):
        g=self.game(hand=(HIT,P+'sleep',P+'wake'));eid=self.entity(g).id;self.play(g,target=eid);self.play(g,P+'sleep',eid)
        self.assertEqual(self.used(g,eid),1);self.play(g,P+'wake');self.assertEqual(self.used(g,eid),1)
    def test_d00_shield_lost_reaction_waits_only_after_third_hit_with_portable_batch(self):
        g=self.game(hand=(BATCH,),board=(CARD,BODY,WATCH),mode='lost');eid=self.entity(g).id;self.play(g,BATCH,eid)
        self.assertEqual(g.state.entities[eid].health,4);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.select(g);self.select(other);self.assertEqual(g.snapshot(),other.snapshot())
    def test_d01_partial_shield_wait_restore_clone_and_replay_keep_remaining_hits(self):
        g=self.game(hand=(HIT,),board=(CARD,BODY,WATCH),mode='prevent');eid=self.entity(g).id;self.play(g,target=eid)
        self.assertEqual(self.used(g,eid),1);other=self.portable(g);self.select(g);self.select(other);self.assertEqual(g.snapshot(),other.snapshot())
    def test_e00_public_shield_durability_is_exact_and_private_material_stays_hidden(self):
        g=self.game();eid=self.entity(g).id;self.play(g,target=eid)
        for pid in(1,2):
            dto=g.for_player(pid).observe()['observation'];self.assertEqual(dto['version'],'player-view-v96')
            row=next(e for e in dto['players'][0]['board']if e['card_id']==BODY)
            self.assertEqual(row['divine_shield'],dict(hits_taken=1,hits_to_break=3,remaining_hits=2,active=True));validate_public(row['divine_shield'])
        self.portable(g)
    def test_e01_invalid_counter_states_declarations_and_snapshot_edits_are_rejected(self):
        g=self.game();a=shields(self.entity(g))[0]
        for value in(-1,3,4,True):
            with self.assertRaises(ValueError):replace(a,divine_shield_hits=value)
        for delta in(dict(amount=2),dict(target_relation='self'),dict(source_relation='friendly')):
            with self.assertRaises(ValueError):replace(RULE,**delta)
        with self.assertRaises(ValueError):validate_public(dict(hits_taken=1,hits_to_break=3,remaining_hits=3,active=True))
        snap=g.snapshot();sid=str(self.entity(g).id);row=next(a for a in snap['state']['entities'][sid]['abilities']if a['keyword']=='divine_shield');row['divine_shield_hits']=3
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry('reader'))
        g=self.game(hand=(P+'grant',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'grant')
        self.assertEqual(g.snapshot(),saved)
