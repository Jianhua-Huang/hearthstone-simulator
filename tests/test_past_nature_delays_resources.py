"""Real six-card entries, frozen original operands, deadlines and privacy."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json, unittest
from pathlib import Path

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import build_registry, past_nature_delays_resources as native
from hs_sim.engine import (EndTurn, Game, IllegalAction, PlayCard, PlayerSetup, ResolutionError, Ruleset,
    Scenario, UseHandAction)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, DestroyBatch,
    GainArmor, GainTemporaryMana, InvokeBehavior, RandomDamage, RefreshMana, RequestChoice,
    Silence, Transform)
from hs_sim.engine.health_theft import StealMinionStats
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, CastWhenDrawnSpec,
    ChooseBranch, ChooseOneSpec, Keyword, PlayerEffectSpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.summon_quantities import ConvertManaCrystalsToMinions, SummonCause
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

P='k663.'
U,ALL,PLAIN,ZERO,ONE,BOTH,UNKNOWN=(P+x for x in ('undead','all','plain','zero','one','both','unknown'))
KILL,SILENCE,GIVE,REFRESH,COPY,AUTO,FAULT=(P+x for x in ('kill','silence','give','refresh','copy','auto','fault'))
BAD=P+'convert_unknown'
MCHOICE,SCHOICE,PORTAL=(P+x for x in ('choose_minion','choose_spell','choose_portal'))
CTX=GenerationContext('k663-explicit-bounded-test-domain','experimental')


@lru_cache(1)
def original():return build_registry()


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=opening_registry();full=original()
    c=full.card('EX1_154')
    r.register_card(c);r.register_pool_card(PoolCard.from_definition(c))
    for branch in (*c.choose_one.branches,c.choose_one.combined):
        r.register_behavior(branch.behavior_id,full.behavior(branch.behavior_id))
    native.register_past_nature_delays_resources(r)
    for cid,attack,health,tribes,extra in ((U,2,6,('undead',),{}),(ALL,2,6,('all',),{}),
            (PLAIN,4,8,(),{}),(ZERO,0,4,(),{}),(ONE,3,1,(),{}),(BOTH,0,6,(),dict(choose_both=True)),
            (UNKNOWN,1,5,None,{})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,
            metadata=metadata(CardClass.DRUID,tribes=tribes),**extra))
    for n in (1,2,3):r.register_behavior(P+'armor'+str(n),lambda c,n=n:(GainArmor(c.player_id,n),))
    spec=ChooseOneSpec((ChooseBranch('left','One',P+'armor1'),ChooseBranch('right','Two',P+'armor2')),
        ChooseBranch('both','Three',P+'armor3'))
    for cid,kind in ((MCHOICE,CardType.MINION),(SCHOICE,CardType.SPELL),(PORTAL,CardType.SPELL)):
        extra=dict(attack=1,health=4,on_play='engine.choose_one')if kind==CardType.MINION else dict(on_play='engine.choose_one')
        if cid==PORTAL:extra.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        r.register_card(CardDefinition(cid,cid,kind,cost=1,choose_one=spec,
            metadata=metadata(CardClass.DRUID,tribes=()),**extra))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(FAULT,lambda c:(_ for _ in ()).throw(ValueError('K663 deliberate rollback')))
    def copy(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if c.state.entities[i].choose_branch is not None)
        ref=CardReference.capture(e)
        return(CopyCard(ref,c.player_id,mode='current',source_id=c.source_id),
            CopyCard(ref,c.player_id,mode='base',source_id=c.source_id))
    def auto(c):
        if mode=='foreign_trail':return(CastSpell(2,'VAC_508',c.source_id),)
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id in(SCHOICE,'EX1_154'))
        return(CastStoredSpell(CardReference.capture(e),c.player_id,c.source_id),)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        SILENCE:lambda c:(Silence(c.target_id),),GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        REFRESH:lambda c:(RefreshMana(c.player_id,10),),COPY:copy,AUTO:auto,
        BAD:lambda c:(ConvertManaCrystalsToMinions(c.player_id,P+'unknown_named_token',SummonCause.capture(c)),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=metadata(collectible=False,tribes=()),
            **({'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if cid in(KILL,SILENCE,GIVE)else{})))
    for kind,event in (('stats','stats_changed'),('entry','minion_summoned'),('draw','card_drawn'),('commit','card_committed')):
        cid=P+'watch.'+kind
        def watch(c,kind=kind):
            target=c.state.entities.get(c.event.target_id)
            if kind=='commit':
                source=c.state.entities.get(c.event.source_id)
                return (AddToHand(c.player_id,PLAIN,c.source_id),)if source is not None and source.card_id=='TTN_951t'else()
            if kind=='stats'and(target is None or c.event.source_id is None or
                    c.state.entities[c.event.source_id].card_id!='RLK_655'):return()
            if kind=='entry'and(target is None or target.card_id not in('ETC_387bt','ETC_387ct','UNG_111t1')):return()
            opts=[ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAULT,c.source_id,c.player_id)))]
            if kind=='entry':opts.append(ChoiceOption('slay','Destroy entry',(Destroy(target.id,c.source_id),)))
            if kind=='stats':
                others=[c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==U]
                if others:
                    last=others[-1]
                    opts.extend((ChoiceOption('control','Transfer',(ChangeControl(last.id,3-c.player_id),)),
                        ChoiceOption('transform','Change donor',(Transform(c.event.target_id,ZERO),))))
            return(RequestChoice(c.player_id,tuple(opts),c.source_id),)
        r.register_behavior(cid,watch)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,triggers=(TriggerSpec(event,cid),),
            metadata=metadata(collectible=False,tribes=())))
    r.register_pool(PoolDefinition('constructed.cards','k663-complete-bounded-domain',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in('EX1_154',MCHOICE,SCHOICE,PORTAL)),complete=True))
    r.validate();return r


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


class NatureDelaysResourcesTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(mode,role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(PLAIN,)*20,other_hand=(),watch=None,
            mana=40,max_mana=40,temporary=0,cap=40,hand_cap=10,other_max_mana=10,mode='normal',rules=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,
            board=board+((P+'watch.'+watch,)if watch else()),deck=deck,mana=mana+temporary,max_mana=max_mana,
            temporary_mana=temporary,mana_cap=cap,hand_cap=hand_cap),
            PlayerSetup('mage.hero',hand=other_hand,board=enemy,deck=(PLAIN,)*20,mana=other_max_mana,max_mana=other_max_mana)),
            seed=663,generation_context=CTX),fixture(mode),ruleset=rules or Ruleset())

    def ids(self,g,zone='board',player=1):return[g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]

    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]

    def finish(self,g):
        for _ in range(100):
            if g.state.pending_choice is None:return g
            q=g.state.pending_choice;keys=[o.id for o in q.options]
            self.choose(g,'continue'if 'continue'in keys else keys[0])
        self.fail('Unbounded diagnostic continuation')

    def cycle(self,g):
        for _ in range(2):g.apply(EndTurn(g.state.active_player));self.finish(g)

    def branch(self,g,branch='ETC_387b'):
        g.apply(PlayCard(1,self.entity(g,'ETC_387').id,branch_id=branch))

    def selected(self,g,cid,target=None):
        e=self.entity(g,cid)
        g.apply(PlayCard(1,e.id,target,branch_id=e.choose_branch.branch_id))

    def test_full_source_inventory_and_thirteen_definitions(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),27)
        self.assertEqual((len(d['official_observations']),len(d['unconfirmed_primary_faces'])),(32,4))
        self.assertEqual(len(d['complete_druid_Nature_inventory']),85)
        self.assertEqual(d['original_missing_native_ids'],list(native.ROOTS))
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(cid in r.pool_cards,cid not in native.CHOICES)
        for cid in native.CHOICES:self.assertTrue(r.card(cid).choice_only)
        self.assertFalse(d['source_scope_bound']);self.assertFalse(d['cn_calibrated'])

    def test_hidden_deadline_shape_rejects_unreviewed_programs(self):
        good=PlayerEffectSpec('test.deadline','ETC_387',kind='secret_objective',duration=2,
            tick_event='turn_started',on_expire=native.PREFIX+'ancients')
        for patch in ({'duration':1},{'tick_event':'turn_ended'},{'tick_player':'opponent'},
                {'on_expire':None},{'spell_damage':1},{'next_turn_end':True}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):replace(good,**patch)

    def test_rhythm_two_owner_starts_and_private_events(self):
        g=self.game(('ETC_387',));self.branch(g)
        self.assertEqual(len(g.state.players[1].player_effects),1)
        self.assertIn(native.ANCIENTS,json.dumps(g.for_player(1).observe()))
        self.assertNotIn(native.ANCIENTS,json.dumps(g.for_player(2).observe()))
        g.apply(EndTurn(1));self.assertEqual(self.ids(g),[])
        g.apply(EndTurn(2));self.assertEqual(self.ids(g),[])
        self.cycle(g);self.assertEqual(self.ids(g),['ETC_387bt']*3)
        self.assertFalse(g.state.players[1].player_effects)
        self.assertNotIn(native.ANCIENTS,json.dumps(g.for_player(2).observe()))
        self.portable(g)

    def test_rhythm_four_owner_starts_and_independent_instances(self):
        g=self.game(('ETC_387','ETC_387'));self.branch(g,'ETC_387c');self.branch(g)
        self.portable(g)
        self.cycle(g);self.cycle(g);self.assertEqual(self.ids(g),['ETC_387bt']*3)
        self.assertEqual(len(g.state.players[1].player_effects),1)
        self.portable(g)
        self.cycle(g);self.assertEqual(self.ids(g),['ETC_387bt']*3)
        self.cycle(g);self.assertEqual(self.ids(g),['ETC_387bt']*3+['ETC_387ct']*3)

    def test_rhythm_opponent_cannot_distinguish_hidden_branch_before_due_turn(self):
        games=[]
        for branch in ('ETC_387b','ETC_387c'):
            g=self.game(('ETC_387',));self.branch(g,branch);games.append(g)
        self.assertEqual(games[0].for_player(2).observe(),games[1].for_player(2).observe())
        self.assertNotEqual(games[0].for_player(1).observe(),games[1].for_player(1).observe())
        for g in games:self.cycle(g)
        self.assertEqual(games[0].for_player(2).observe(),games[1].for_player(2).observe())

    def test_rhythm_combined_capacity_clips_and_consumes_both_deadlines(self):
        g=self.game(('ETC_387',),board=(BOTH,PLAIN));self.branch(g,'ETC_387:combined')
        for _ in range(4):self.cycle(g)
        self.assertEqual(self.ids(g),[BOTH,PLAIN]+['ETC_387bt']*3+['ETC_387ct']*2)
        self.assertFalse(g.state.players[1].player_effects)

    def test_rhythm_expiry_wait_restore_and_failed_choice_rollback(self):
        g=self.game(('ETC_387',),watch='entry');self.branch(g);self.cycle(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);before=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g)
        self.assertEqual(self.ids(g).count('ETC_387bt'),3)

    def test_lotus_three_holder_ends_not_opponent_ends_or_deck(self):
        g=self.game(('TTN_930',),deck=('TTN_930',)+(PLAIN,)*10)
        original=self.entity(g,'TTN_930').id
        for turn in range(3):
            g.apply(EndTurn(1))
            self.assertEqual(g.state.entities[original].card_id,'TTN_930t'if turn==2 else'TTN_930')
            if turn==1:self.portable(g)
            g.apply(EndTurn(2))
        deck_copy=next(e for e in g.state.entities.values()if e.card_id=='TTN_930'and e.id!=original)
        self.assertEqual(deck_copy.card_id,'TTN_930')
        self.portable(g)

    def test_lotus_both_real_faces_draw_and_armor(self):
        for cid,draws,armor in (('TTN_930',1,5),('TTN_930t',2,10)):
            with self.subTest(cid=cid):
                g=self.game((cid,));before=len(g.state.players[1].deck)
                self.play(g,cid)
                self.assertEqual((before-len(g.state.players[1].deck),self.hero(g).armor),(draws,armor))

    def test_lotus_draw_waiting_survives_before_armor_and_rolls_back(self):
        g=self.game(('TTN_930t',),watch='draw');self.play(g,'TTN_930t')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).armor,0)
        self.portable(g);self.finish(g);self.assertEqual(self.hero(g).armor,10)

    def test_trail_next_owner_start_temporary_over_cap_expires(self):
        g=self.game(('VAC_508',REFRESH,SCHOICE),mana=10,max_mana=10,cap=10)
        self.play(g,'VAC_508');g.apply(EndTurn(1));self.assertEqual(g.state.players[1].temporary_mana,0)
        g.apply(EndTurn(2));p=g.state.players[1]
        self.assertEqual((p.max_mana,p.mana,p.temporary_mana),(10,12,2))
        g.apply(PlayCard(1,self.entity(g,SCHOICE).id,branch_id='left'))
        self.play(g,REFRESH);self.assertEqual(g.state.players[1].temporary_mana,1)
        g.apply(EndTurn(1));self.assertEqual(g.state.players[1].temporary_mana,0)

    def test_trail_stacks_as_two_independent_rewards(self):
        g=self.game(('VAC_508','VAC_508'));self.play(g,'VAC_508');self.play(g,'VAC_508');self.cycle(g)
        self.assertEqual(g.state.players[1].temporary_mana,4)
        self.assertEqual(g.state.players[1].max_mana,40)
        self.portable(g)

    def test_trail_automatic_opponent_turn_uses_recipient_clock(self):
        g=self.game((AUTO,),mode='foreign_trail');self.play(g,AUTO)
        self.assertEqual(g.state.players[2].temporary_mana,0)
        g.apply(EndTurn(1));self.assertEqual(g.state.players[2].temporary_mana,2)
        self.assertFalse(g.state.players[2].player_effects)

    def test_living_mana_empty_first_cost_and_seven_original_entries(self):
        g=self.game(('UNG_111',),mana=10,max_mana=10,cap=10);self.play(g,'UNG_111')
        p=g.state.players[1];self.assertEqual((p.max_mana,p.mana,p.temporary_mana),(3,3,0))
        self.assertEqual(self.ids(g),['UNG_111t1']*7)
        self.portable(g)

    def test_living_mana_only_permanent_crystals_and_real_free_slots(self):
        for maximum,mana,temporary,board,count,remaining in (
                (7,7,0,(PLAIN,PLAIN),5,(2,2,0)),(4,4,6,(),4,(0,1,1)),
                (0,0,5,(),0,(0,0,0)),(10,10,0,(PLAIN,)*7,0,(10,5,0))):
            with self.subTest(maximum=maximum,board=len(board)):
                g=self.game(('UNG_111',),board=board,mana=mana,max_mana=maximum,temporary=temporary,cap=10)
                self.play(g,'UNG_111');p=g.state.players[1]
                self.assertEqual((p.max_mana,p.mana,p.temporary_mana),remaining)
                self.assertEqual(self.ids(g).count('UNG_111t1'),count)

    def test_living_mana_respects_ruleset_capacity(self):
        g=self.game(('UNG_111',),mana=10,max_mana=10,cap=10,rules=Ruleset(max_board=3))
        self.play(g,'UNG_111');self.assertEqual(self.ids(g),['UNG_111t1']*3)
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(7,5))

    def test_mana_conversion_unknown_fixed_material_rejects_even_with_no_capacity(self):
        for board,maximum in (((),0),((PLAIN,)*7,10)):
            g=self.game((BAD,),board=board,mana=maximum,max_mana=maximum,cap=10);before=deepcopy(g.snapshot())
            with self.assertRaises(ResolutionError):self.play(g,BAD)
            self.assertEqual(g.snapshot(),before)

    def test_living_mana_original_count_frozen_while_entry_deaths_refund(self):
        g=self.game(('UNG_111',),mana=3,max_mana=3,temporary=5,cap=10,watch='entry')
        self.play(g,'UNG_111');self.portable(g);self.assertEqual(g.state.players[1].max_mana,0)
        for _ in range(3):
            self.assertIsNotNone(g.state.pending_choice);self.choose(g,'slay')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.ids(g),[P+'watch.entry'])
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(3,0))

    def test_mana_treant_actual_death_controller_silence_and_cap(self):
        g=self.game((GIVE,KILL,SILENCE,KILL),board=('UNG_111t1','UNG_111t1'),mana=5,max_mana=5,cap=10,other_max_mana=6)
        first=g.state.players[1].board[0];self.play(g,GIVE,first);self.play(g,KILL,first)
        self.assertEqual(g.state.players[2].max_mana,7)
        self.assertEqual(g.state.players[1].max_mana,5)
        second=g.state.players[1].board[0];self.play(g,SILENCE,second);self.play(g,KILL,second)
        self.assertEqual(g.state.players[1].max_mana,5)
        g=self.game((KILL,),board=('UNG_111t1',),mana=5,max_mana=5,cap=10)
        self.play(g,KILL,g.state.players[1].board[0]);self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(6,5))

    def test_wither_each_original_friendly_undead_and_all_tribes(self):
        g=self.game(('RLK_655',),board=(U,ALL,PLAIN),enemy=(PLAIN,U))
        donor=g.state.players[2].board[0];other=g.state.players[2].board[1]
        self.play(g,'RLK_655',donor)
        self.assertEqual((g.state.entities[donor].attack,g.state.entities[donor].health),(2,6))
        self.assertEqual((g.state.entities[other].attack,g.state.entities[other].health),(2,6))
        for eid in g.state.players[1].board[:2]:self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(3,7))
        self.assertEqual(g.state.entities[g.state.players[1].board[2]].attack,4)
        self.assertFalse([e for e in g.events if e.kind in ('damage_dealt','healed','health_lost')])

    def test_wither_partial_attack_and_health_death_stops_later_recipients(self):
        for card,stats,recipients in ((ZERO,(0,2),((2,7),(2,7))),
                (ONE,(2,0),((3,7),(2,6)))):
            with self.subTest(card=card):
                g=self.game(('RLK_655',),board=(U,U),enemy=(card,));donor=g.state.players[2].board[0]
                self.play(g,'RLK_655',donor)
                self.assertEqual(tuple((g.state.entities[i].attack,g.state.entities[i].health)for i in g.state.players[1].board),recipients)
                self.assertEqual((g.state.entities[donor].attack,g.state.entities[donor].health),stats)
                if card==ONE:self.assertEqual(g.state.entities[donor].zone,Zone.GRAVEYARD)

    def test_wither_self_recipient_does_not_create_stats(self):
        g=self.game(('RLK_655',),board=(U,U));donor=g.state.players[1].board[0]
        self.play(g,'RLK_655',donor)
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health)for i in g.state.players[1].board],[(1,5),(3,7)])

    def test_wither_pair_commits_before_notice_and_remaining_refs_restore(self):
        g=self.game(('RLK_655',),board=(U,U),enemy=(PLAIN,),watch='stats')
        donor=g.state.players[2].board[0];first=g.state.players[1].board[0]
        self.play(g,'RLK_655',donor);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[donor].attack,g.state.entities[first].attack),(3,3))
        self.portable(g);before=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(before,g.snapshot());self.finish(g)
        self.assertEqual(g.state.entities[donor].attack,2)

    def test_wither_later_recipient_control_change_invalidates_original_reference(self):
        g=self.game(('RLK_655',),board=(U,U),enemy=(PLAIN,),watch='stats')
        donor=g.state.players[2].board[0];second=g.state.players[1].board[1]
        self.play(g,'RLK_655',donor);self.choose(g,'control');self.finish(g)
        self.assertEqual(g.state.entities[second].controller,2)
        self.assertEqual((g.state.entities[second].attack,g.state.entities[donor].attack),(2,3))

    def test_wither_original_donor_transformation_does_not_continue_from_new_face(self):
        g=self.game(('RLK_655',),board=(U,U),enemy=(PLAIN,),watch='stats')
        donor=g.state.players[2].board[0];second=g.state.players[1].board[1]
        self.play(g,'RLK_655',donor);self.choose(g,'transform');self.finish(g)
        self.assertEqual(g.state.entities[donor].card_id,ZERO)
        self.assertEqual((g.state.entities[second].attack,g.state.entities[second].health),(2,6))

    def test_wither_unknown_tribe_is_explicit_atomic_failure(self):
        g=self.game(('RLK_655',),board=(UNKNOWN,),enemy=(PLAIN,));before=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.play(g,'RLK_655',g.state.players[2].board[0])
        self.assertEqual(before,g.snapshot())

    def test_forge_actual_hand_payment_and_original_spell_combined(self):
        g=self.game(('TTN_951',),enemy=(PLAIN,),deck=('EX1_154',)+(PLAIN,)*10)
        eid=self.entity(g,'TTN_951').id;g.apply(UseHandAction(1,eid,'forge'))
        self.assertEqual(g.state.entities[eid].card_id,'TTN_951t');self.assertEqual(g.state.players[1].mana,38)
        self.play(g,'TTN_951t');e=self.entity(g,'EX1_154')
        self.assertEqual(e.choose_branch.branch_id,fixture().card('EX1_154').choose_one.combined.id)
        donor=g.state.players[2].board[0]
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,e.id,donor,branch_id='damage'))
        self.selected(g,'EX1_154',donor)
        self.assertEqual(g.state.entities[donor].health,4)
        self.assertEqual(g.state.players[1].mana,34)
        self.assertEqual(len(g.state.players[1].hand),1)

    def test_embrace_unforged_does_not_preselect_and_forged_accepts_minion(self):
        g=self.game(('TTN_951',),deck=(SCHOICE,));self.play(g,'TTN_951')
        self.assertIsNone(self.entity(g,SCHOICE).choose_branch)
        g=self.game(('TTN_951t',),deck=(MCHOICE,));self.play(g,'TTN_951t')
        self.assertEqual(self.entity(g,MCHOICE).choose_branch.branch_id,'both')
        self.selected(g,MCHOICE);self.assertEqual(self.hero(g).armor,3)

    def test_embrace_empty_matching_domain_does_not_draw_or_consume_rng(self):
        g=self.game(('TTN_951t',),deck=(PLAIN,)*3);rng=deepcopy(g._rng.getstate())
        self.play(g,'TTN_951t');self.assertEqual(len(g.state.players[1].deck),3)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.hero(g).health,30)

    def test_embrace_combined_preselection_current_copy_base_reset_and_effect_cast(self):
        g=self.game(('TTN_951t',COPY,AUTO),deck=(SCHOICE,));self.play(g,'TTN_951t');self.play(g,COPY)
        copies=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==SCHOICE]
        self.assertEqual([e.choose_branch is not None for e in copies],[True,True,False])
        self.play(g,AUTO);self.assertEqual(self.hero(g).armor,3)
        self.portable(g)

    def test_embrace_original_draw_waiting_restore_and_not_cwd_replacement(self):
        g=self.game(('TTN_951t',),deck=(SCHOICE,),watch='draw');self.play(g,'TTN_951t')
        self.portable(g);self.finish(g);self.assertEqual(self.entity(g,SCHOICE).choose_branch.branch_id,'both')
        g=self.game(('TTN_951t',),deck=(PORTAL,SCHOICE));self.play(g,'TTN_951t');self.finish(g)
        self.assertIsNone(self.entity(g,SCHOICE).choose_branch)

    def test_embrace_burned_original_has_no_replacement_reward(self):
        g=self.game(('TTN_951t',),deck=(SCHOICE,),hand_cap=1,watch='commit')
        self.play(g,'TTN_951t');self.assertNotIn(SCHOICE,self.ids(g,'hand'))
        self.assertTrue(all(e.choose_branch is None for e in g.state.entities.values()))

    def test_new_request_shapes_reject_unrelated_rewards_and_actors(self):
        for kwargs in ({'amount':1},{'repetitions':2}):
            with self.assertRaises(ValueError):DrawGroupReward('combine_original_choose_one',**kwargs)
        for slots in ((DrawGroupSlot(),),(DrawGroupSlot(PoolQuery(choose_one=True)),)*2):
            with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,slots,DrawGroupReward('combine_original_choose_one'))
        with self.assertRaises(ValueError):StealMinionStats(None,None,1)
        with self.assertRaises(ValueError):ConvertManaCrystalsToMinions(1,'UNG_111t1',None)

    def test_full_standard_host_actual_six_roots_and_all_executable_derivatives(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*30
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=('RLK_655','VAC_508','ETC_387','TTN_930'),
            board=('OG_044','ICC_085t'),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('ICC_832t4',),deck=deck)),seed=663,generation_context=h.context),h.registry)
        self.play(g,'RLK_655',g.state.players[2].board[0]);self.play(g,'VAC_508');self.branch(g,'ETC_387:combined')
        for _ in range(4):self.cycle(g)
        self.assertEqual(self.ids(g).count('ETC_387bt'),3);self.assertEqual(self.ids(g).count('ETC_387ct'),2)
        self.play(g,'TTN_930t');self.assertEqual(self.hero(g).armor,10);self.portable(g)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=('TTN_951','UNG_111'),
            deck=('EX1_154',)+deck,mana=10,max_mana=10),PlayerSetup('HERO_08',deck=deck)),seed=664,generation_context=h.context),h.registry)
        eid=self.entity(g,'TTN_951').id;g.apply(UseHandAction(1,eid,'forge'));self.play(g,'TTN_951t')
        self.play(g,'UNG_111');self.assertEqual(self.ids(g),['UNG_111t1']*7)
        self.cycle(g);self.selected(g,'EX1_154',g.state.players[1].board[0]);self.assertEqual(len(g.state.players[1].board),6)
        self.assertEqual(g.state.players[1].max_mana,5);self.portable(g)


if __name__=='__main__':unittest.main()
