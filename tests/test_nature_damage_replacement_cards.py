"""Real Nature replacements preserve packet timing and ordinary summon identity."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.nature_damage_replacement_cards import load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DamageKind,EndTurn,Game,
    Keyword,PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,SnapshotError,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,DamageBatch,GainArmor,
    GrantHealthRule,GrantKeyword,Heal,InvokeBehavior,RequestChoice,Silence)
from hs_sim.engine.model import HealthLayer,HealthOp
from hs_sim.engine.nature_damage_replacements import POOL,QUERY,RULES
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

P='nature.replacement.test.';FLUX='TIME_214';ROOK='TIME_217'
A,B,FILL,WATCH,POWER=(P+x for x in ('a','b','fill','watch','power'))
CTX=GenerationContext('K227.complete-explicit-fixture','experimental')


@lru_cache(maxsize=None)
def registry(role,mode='complete'):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,99),))
    for cid,cost in ((A,5),(B,5),(FILL,0)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=3,health=4,battlecry=P+'bc',metadata=replace(meta,collectible=cid!=FILL))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=6,spell_damage=2,metadata=meta))
    def spell(name,body,school=None,target=True):
        cid=P+name;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=target,spell_school=school,metadata=meta))
    for name,school,kind,amount in (('nature',SpellSchool.NATURE,DamageKind.SPELL,2),('fire',SpellSchool.FIRE,DamageKind.SPELL,2),
            ('untyped',None,DamageKind.SPELL,2),('effect',SpellSchool.NATURE,DamageKind.EFFECT,2),
            ('zero',SpellSchool.NATURE,DamageKind.SPELL,0),('lethal',SpellSchool.NATURE,DamageKind.SPELL,20)):
        spell(name,lambda c,k=kind,a=amount:(Damage(c.target_id,a,c.source_id,k),),school)
    spell('two',lambda c:(DamageBatch(tuple(Damage(c.target_id,2,c.source_id,DamageKind.SPELL)for _ in range(2))),),SpellSchool.NATURE)
    spell('mixed',lambda c:(DamageBatch((Damage(c.target_id,20,c.source_id,DamageKind.SPELL),Damage(c.target_id,4,c.source_id,DamageKind.EFFECT))),),SpellSchool.NATURE)
    spell('heal',lambda c:(Heal(c.target_id,2,c.source_id),),SpellSchool.NATURE)
    spell('silence',lambda c:(Silence(c.target_id),))
    spell('steal',lambda c:(ChangeControl(c.target_id,2),))
    spell('copy',lambda c:(CopyMinion(c.target_id,c.player_id),))
    spell('shield',lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),))
    spell('grant',lambda c:(GrantHealthRule(999999,RULES[HealthOp.NATURE_GROWTH],c.source_id),),target=False)
    def fail(c):raise ResolutionError('K227 deliberately failing reaction')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        eid=c.event.target_id if c.event.kind=='stats_changed'else c.event.source_id
        entity=c.state.entities.get(eid)
        if entity is None or (entity.card_id!=FLUX if c.event.kind=='stats_changed'else entity.card_id not in (A,B)):return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=meta,
        triggers=(TriggerSpec('stats_changed',WATCH),TriggerSpec('minion_summoned',WATCH))))
    unknown=P+'unimplemented_five'
    if mode=='unknown':
        # The real candidate formerly used here has since been implemented.
        # Keep an explicitly unimplemented eligible fixture, never a stale
        # assertion that a currently registered production card is unknown.
        r.register_pool_card(PoolCard.from_definition(replace(r.card(A),id=unknown,name=unknown)))
    members=((A,B)if mode=='complete'else(A,unknown)if mode=='unknown'else
        ('JAIL_397',)if mode=='beatrix'else(A,'CORE_CFM_670')if mode=='outside'else(FILL,))
    r.register_pool(PoolDefinition(POOL,'K227-'+mode,CTX.target_id,CTX.mode,tuple(PoolMember(x)for x in members),complete=True))
    r.validate();r.freeze();return r


class NatureDamageReplacementTests(unittest.TestCase):
    def game(self,hand=(P+'nature',),board=(FLUX,),enemy=(),enemy_hand=(),mode='complete'):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*5,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(FILL,)*5,mana=50,max_mana=50,mana_cap=50)),seed=227214,generation_context=CTX),registry('writer',mode))
    def entity(self,g,cid,zone='board',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=P+'nature',target=None,pid=1):
        e=self.entity(g,cid,'hand',pid);g.apply(PlayCard(pid,e.id,target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader',self.mode);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint())
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','SourceAllocationFact','nature_growth','nature_summon'):
                self.assertNotIn(key,public)
        return other
    def test_a00_flux_replaces_even_lethal_nature_damage_with_one_fixed_growth(self):
        g=self.game(hand=(P+'lethal',),board=(FLUX,POWER));eid=self.entity(g,FLUX).id;self.play(g,P+'lethal',eid)
        e=g.state.entities[eid];self.assertEqual((e.attack,e.health,e.max_health),(3,5,5))
        rows=[dict(dict(x.data)['result'])for x in g.events if x.kind=='health_resolved']
        self.assertEqual([(x['health_before'],x['health_after'],x['damage_dealt'],x['prevention'])for x in rows],[(4,4,0,'rule_prevention')])
        self.assertFalse(any(x.kind=='damage_dealt'for x in g.events));self.portable(g)
    def test_a01_stormrook_summons_one_full_five_cost_body_without_its_battlecry(self):
        g=self.game(board=(ROOK,));eid=self.entity(g,ROOK).id;self.play(g,target=eid)
        self.assertEqual(g.state.entities[eid].health,5);new=[g.state.entities[i]for i in g.state.players[1].board if i!=eid]
        self.assertEqual(len(new),1);self.assertIn(new[0].card_id,(A,B));self.assertEqual(new[0].health,4)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,eid);self.portable(g)

    def test_a02_generated_commander_has_taunt_without_construction_or_opening_copies(self):
        g=self.game(board=(ROOK,),mode='beatrix');before=len(g.state.players[1].deck)
        self.play(g,target=self.entity(g,ROOK).id)
        new=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='JAIL_397']
        self.assertEqual(len(new),1);self.assertEqual((new[0].attack,new[0].health),(5,6))
        self.assertIn(Keyword.TAUNT,new[0].keywords);self.assertEqual(len(g.state.players[1].deck),before)
        self.assertFalse(g.state.players[1].sideboards);self.portable(g)
    def test_a02_complete_raw_roots_four_primary_faces_and_evidence_only_enchantment(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['cards']],[FLUX,ROOK])
        for row in (*d['cards'],*d['evidence_only']):self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(d['official_observations']),4);self.assertFalse(d['policy']['cn_calibrated']);self.assertFalse(d['policy']['formal_pool_complete'])
        self.assertIn(Keyword.TAUNT,registry('writer').card(FLUX).keywords)
    def test_b00_enemy_nature_spell_deals_normal_damage(self):
        g=self.game(hand=(),enemy_hand=(P+'nature',));eid=self.entity(g,FLUX).id;g.apply(EndTurn(1));self.play(g,target=eid,pid=2)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,2))
    def test_b01_fire_untyped_and_nonspell_damage_do_not_replace(self):
        for key in ('fire','untyped','effect'):
            with self.subTest(key=key):
                g=self.game(hand=(P+key,));eid=self.entity(g,FLUX).id;self.play(g,P+key,eid)
                self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,2))
    def test_b02_nature_healing_is_ordinary_healing(self):
        g=self.game(hand=(P+'fire',P+'heal'));eid=self.entity(g,FLUX).id;self.play(g,P+'fire',eid);self.play(g,P+'heal',eid)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,4))
    def test_b03_zero_packet_requires_a_positive_actual_spell_budget(self):
        for board,expected in (((FLUX,),(1,4)),((FLUX,POWER),(3,5))):
            with self.subTest(board=board):
                g=self.game(hand=(P+'zero',),board=board);eid=self.entity(g,FLUX).id;self.play(g,P+'zero',eid)
                self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),expected)
    def test_b04_each_packet_grows_before_the_next_packet_without_damage(self):
        g=self.game(hand=(P+'two',));eid=self.entity(g,FLUX).id;self.play(g,P+'two',eid)
        e=g.state.entities[eid];self.assertEqual((e.attack,e.health,e.max_health),(5,6,6))
        rows=[dict(dict(x.data)['result'])for x in g.events if x.kind=='health_resolved']
        self.assertEqual([(x['health_before'],x['health_after'])for x in rows],[(4,4),(5,5)])
    def test_b05_growth_is_committed_before_a_later_nonmatching_packet(self):
        g=self.game(hand=(P+'mixed',));eid=self.entity(g,FLUX).id;self.play(g,P+'mixed',eid)
        e=g.state.entities[eid];self.assertEqual((e.zone,e.attack,e.health,e.max_health),(Zone.BOARD,3,1,5))
    def test_c00_real_static_shock_keeps_its_hero_attack_and_one_actual_spell(self):
        g=self.game(hand=('TIME_218',));eid=self.entity(g,FLUX).id;self.play(g,'TIME_218',eid)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(3,5))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,1);self.assertEqual(len(g.state.cast_history),1)
    def test_c01_real_thunderquake_accepts_both_replacements_before_the_new_summon(self):
        g=self.game(hand=('TIME_215',),board=(FLUX,ROOK),enemy=(FLUX,));self.play(g,'TIME_215')
        self.assertEqual((self.entity(g,FLUX).attack,self.entity(g,FLUX).health),(3,5));self.assertEqual(self.entity(g,ROOK).health,5)
        self.assertEqual(self.entity(g,FLUX,pid=2).health,3)
        spawned=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id in (A,B)]
        self.assertEqual(len(spawned),1);self.assertEqual(spawned[0].health,4)
        self.assertIn('TIME_218',[g.state.entities[i].card_id for i in g.state.players[1].hand]);self.assertEqual(g.state.players[1].mana,48)
    def test_d00_full_board_keeps_prevention_without_rng_or_extra_summons(self):
        g=self.game(board=(ROOK,)+(FILL,)*6);rng=g._rng.getstate();eid=self.entity(g,ROOK).id;self.play(g,target=eid)
        self.assertEqual(g.state.entities[eid].health,5);self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g._rng.getstate(),rng)
    def test_d01_empty_eligible_pool_keeps_prevention_without_rng(self):
        g=self.game(board=(ROOK,),mode='empty');rng=g._rng.getstate();eid=self.entity(g,ROOK).id;self.play(g,target=eid)
        self.assertEqual((g.state.entities[eid].health,len(g.state.players[1].board)),(5,1));self.assertEqual(g._rng.getstate(),rng)
    def test_d02_unknown_eligible_five_cost_candidate_rejects_the_whole_action_even_when_full(self):
        for fill in (0,6):
            with self.subTest(fill=fill):
                g=self.game(board=(ROOK,)+(FILL,)*fill,mode='unknown');snap=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,target=self.entity(g,ROOK).id)
                self.assertEqual(g.snapshot(),snap)
    def test_d03_unknown_nonmatching_content_is_not_an_eligible_candidate(self):
        g=self.game(board=(ROOK,),mode='outside');self.play(g,target=self.entity(g,ROOK).id)
        self.assertEqual(self.entity(g,A).health,4)
    def test_e00_silence_removes_both_native_replacements(self):
        for cid,health in ((FLUX,2),(ROOK,3)):
            with self.subTest(cid=cid):
                g=self.game(hand=(P+'silence',P+'nature'),board=(cid,));eid=self.entity(g,cid).id
                self.play(g,P+'silence',eid);self.play(g,target=eid);self.assertEqual(g.state.entities[eid].health,health);self.assertEqual(len(g.state.players[1].board),1)
    def test_e01_current_controller_is_the_owner_of_the_nature_replacement(self):
        g=self.game(hand=(P+'steal',),enemy_hand=(P+'nature',));eid=self.entity(g,FLUX).id;self.play(g,P+'steal',eid)
        g.apply(EndTurn(1));self.play(g,target=eid,pid=2);self.assertEqual((g.state.entities[eid].controller,g.state.entities[eid].attack,g.state.entities[eid].health),(2,3,5))
    def test_e02_current_copy_keeps_the_printed_rule_and_its_own_growth(self):
        g=self.game(hand=(P+'nature',P+'copy',P+'nature'));old=self.entity(g,FLUX).id;self.play(g,target=old);self.play(g,P+'copy',old)
        new=next(i for i in g.state.players[1].board if i!=old);self.play(g,target=new)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(3,5));self.assertEqual((g.state.entities[new].attack,g.state.entities[new].health),(5,6));self.portable(g)
    def test_f00_two_growth_notifications_wait_after_the_whole_batch_and_roll_back_failed_choice(self):
        g=self.game(hand=(P+'two',),board=(FLUX,WATCH));self.play(g,P+'two',self.entity(g,FLUX).id)
        self.assertEqual((self.entity(g,FLUX).attack,self.entity(g,FLUX).health),(5,6));other=self.portable(g);snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),snap)
        for game in (g,other):self.select(game);self.assertIsNotNone(game.state.pending_choice);self.select(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)
    def test_f01_real_summon_reaction_waits_with_original_source_and_portable_rng(self):
        g=self.game(board=(ROOK,WATCH));self.play(g,target=self.entity(g,ROOK).id);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g);snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),snap)
        self.select(g);self.select(other);self.assertEqual(g.snapshot(),other.snapshot())
    def test_g00_unreviewed_profiles_carriers_and_dynamic_grants_are_rejected(self):
        rule=RULES[HealthOp.NATURE_GROWTH]
        for delta in (dict(source_relation='any'),dict(layer=HealthLayer.SOURCE),dict(amount=1),dict(schools=())):
            with self.assertRaises(ValueError):replace(rule,**delta)
        r=build_registry()
        with self.assertRaises(ValueError):r.register_card(CardDefinition(P+'invalid','Invalid hero',CardType.HERO,health=30,health_rules=(rule,)))
        g=self.game(hand=(P+'grant',));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'grant')
        self.assertEqual(g.snapshot(),snap)
    def test_g01_old_schema_is_explicitly_rejected(self):
        g=self.game();snap=g.snapshot();snap['schema_version']=413
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry('reader'))
