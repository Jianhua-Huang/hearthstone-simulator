"""Native stored Deathrattle facts, real bottom-deck cards and Kindred discard."""
from dataclasses import dataclass,replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone
from hs_sim.engine.deathrattles import InvokeDeathrattle,validate_context
from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,Destroy,Draw,Effect,GainArmor,InvokeBehavior,RequestChoice,Silence,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.stored_deathrattles import capture_group
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,DestroyStoredCard,DiscardCard,DiscardMatching

IMP='JAIL_398';STOOGE='JAIL_399';GRANDMA='JAIL_399t1';RAZIDIR='TLC_463';YETI='CORE_CS2_182'


@dataclass(frozen=True)
class BareBurn(Effect):
    target_id:int


def registry(wait=False):
    r=build_registry()
    def held(c,zone):
        return next(e for e in getattr(c.state.players[1],zone.value)if c.state.entities[e].card_id==IMP)
    scripts={
        'discard':lambda c:(DiscardCard(CardReference.capture(c.state.entities[held(c,Zone.HAND)]),c.source_id),),
        'discard_first':lambda c:(DiscardCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),c.source_id),),
        'destroy_hand':lambda c:(DestroyStoredCard(CardReference.capture(c.state.entities[held(c,Zone.HAND)]),c.source_id),),
        'destroy_deck':lambda c:(DestroyStoredCard(CardReference.capture(c.state.entities[held(c,Zone.DECK)]),c.source_id),),
        'draw':lambda c:(Draw(1,source_id=c.source_id),),
        'fill_burn':lambda c:(AddToHand(1,YETI,c.source_id),Draw(1,source_id=c.source_id)),
        'create_burn':lambda c:(AddToHand(1,YETI,c.source_id),AddToHand(1,IMP,c.source_id)),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'fail':lambda c:(AddToHand(1,'missing.s38'),),
        'late_failure':lambda c:(DiscardCard(CardReference.capture(c.state.entities[held(c,Zone.HAND)]),c.source_id),InvokeBehavior('s38.fail',c.source_id,1)),
        'bare':lambda c:(BareBurn(held(c,Zone.HAND)),),
        'summon_diabolus':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial('DINO_138'),),SummonCause.capture(c)),),
    }
    for key,body in scripts.items():
        r.register_behavior('s38.'+key,body)
        if key=='fail':continue
        r.register_card(CardDefinition('s38.'+key,key,CardType.SPELL,on_play='s38.'+key,requires_target=key in('kill','silence','trigger')))
    r.register_card(CardDefinition('s38.suppressor','Suppression fixture',CardType.MINION,health=8,keywords=(Keyword.DEATHRATTLE_SUPPRESSOR,)))
    r.register_card(CardDefinition('s38.big','Large endpoint fixture',CardType.MINION,attack=1,health=20))
    r.register_card(CardDefinition('s38.dormant','Dormant endpoint fixture',CardType.MINION,attack=1,health=20,dormant_turns=2))
    if wait:
        def watch(c):
            if c.event.kind!='card_discarded' or c.state.entities[c.event.target_id].card_id!=IMP:return ()
            return(RequestChoice(1,(
                ChoiceOption('ok','Continue stored Deathrattle',(GainArmor(1,1),)),
                ChoiceOption('bad','Rollback choice',(InvokeBehavior('s38.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('s38.watch',watch);r.register_card(CardDefinition('s38.watch','Observer fixture',CardType.MINION,health=8,
            triggers=(TriggerSpec('card_discarded','s38.watch'),)))
    return r


class StoredDeathrattleCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),deck=(YETI,)*8,enemy=(),enemy_hand=(),wait=False,mechanics=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=391),
            registry(True)if wait else self.registry,mechanics=mechanics)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def body(self,g,cid,p=1):return next(g.state.entities[e]for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def health(self,g,p):return g.state.entities[g.state.players[p].hero_id].health
    def portable(self,g,wait=False):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(wait))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(wait)).snapshot(),saved);return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def prepare_kindred(self,g,cid='CORE_ICC_023',clear_enemy_draw=False):
        self.play(g,cid);g.apply(EndTurn(1))
        if clear_enemy_draw:
            eid=next(e for e in g.state.players[2].hand if g.state.entities[e].card_id==YETI)
            g.apply(PlayCard(2,eid))
        g.apply(EndTurn(2))

    def test_complete_native_faces_token_and_only_explicit_stored_permission(self):
        for cid,stats,keywords in((IMP,(6,6,6),()),(STOOGE,(3,2,5),(Keyword.TAUNT,)),
                                  (GRANDMA,(8,8,8),(Keyword.TAUNT,Keyword.LIFESTEAL)),(RAZIDIR,(4,7,7),())):
            card=self.registry.card(cid);self.assertEqual((card.cost,card.attack,card.health),stats);self.assertEqual(card.keywords,keywords)
        self.assertTrue(self.registry.card(IMP).stored_deathrattle);self.assertIsNone(self.registry.card(IMP).on_discard)
        self.assertIsNone(self.registry.card(IMP).on_destroyed);self.assertFalse(self.registry.card(GRANDMA).metadata.collectible)
        card=self.registry.card('DINO_138');self.assertEqual((card.cost,card.attack,card.health),(6,6,5))
        self.assertIsNone(card.battlecry);self.assertTrue(card.on_play)

    def test_diabolus_kindred_physical_endpoints_single_twice_no_spell_damage(self):
        for enemy,expected in((('s38.big',),8),(('s38.dormant','s38.big'),14)):
            g=self.game(('CORE_ICC_023','DINO_138'),board=('CORE_EX1_012',),enemy=enemy);self.prepare_kindred(g)
            self.play(g,'DINO_138');self.assertEqual(self.body(g,'s38.big',2).health,expected)
            rows=[x.health_result for x in g.state.damage_history if x.health_result.source_card_id=='DINO_138']
            self.assertTrue(all(x.modified_amount==6 and x.spell_bonus==0 for x in rows))
            self.assertEqual(len({x.batch_id for x in rows}),1);self.portable(g)

    def test_diabolus_same_turn_and_direct_summon_do_not_run_kindred_body(self):
        g=self.game(('CORE_ICC_023','DINO_138'),enemy=('s38.big',));self.play(g,'CORE_ICC_023');self.play(g,'DINO_138')
        self.assertEqual(self.body(g,'s38.big',2).health,20);self.assertFalse(g.state.damage_history)
        g=self.game(('CORE_ICC_023','s38.summon_diabolus'),enemy=('s38.big',));self.prepare_kindred(g)
        self.play(g,'s38.summon_diabolus');self.assertEqual(self.body(g,'s38.big',2).health,20)
        self.assertFalse(g.state.damage_history);self.assertEqual(self.body(g,'DINO_138').health,5)

    def test_discard_real_deathrattle_not_a_fake_board_death_or_destroyer_spell(self):
        g=self.game(('s38.discard',IMP),board=(YETI,'CORE_EX1_012'),enemy=(YETI,));source=g.state.players[1].hand[1]
        self.play(g,'s38.discard');self.assertEqual([self.health(g,p)for p in(1,2)],[27,27])
        self.assertEqual(self.body(g,YETI).health,2);self.assertEqual(self.body(g,YETI,2).health,2)
        self.assertFalse(any(d.entity_id==source for d in g.state.death_history))
        self.assertEqual([r.capture.origin for r in g.state.deathrattle_history if r.capture.carrier_id==source],['stored'])
        rows=[x.health_result for x in g.state.damage_history]
        self.assertTrue(all(x.source_id==source and x.source_card_id==IMP and x.modified_amount==3 and x.spell_bonus==0 for x in rows))
        self.portable(g)

    def test_explicit_hand_and_deck_destructions_use_same_stored_protocol(self):
        for mode in('hand','deck'):
            g=self.game(('s38.destroy_'+mode,IMP)if mode=='hand'else('s38.destroy_deck',),deck=(IMP,YETI)if mode=='deck'else(YETI,))
            self.play(g,'s38.destroy_'+mode)
            self.assertEqual([self.health(g,p)for p in(1,2)],[27,27]);self.assertFalse(g.state.death_history)
            self.assertEqual([r.capture.origin for r in g.state.deathrattle_history],['stored']);self.portable(g)

    def test_draw_overflow_and_created_overflow_each_keep_actual_burn_fact(self):
        for script,deck in(('fill_burn',(IMP,)),('create_burn',())):
            g=self.game(('s38.'+script,)+(YETI,)*9,deck=deck);self.play(g,'s38.'+script)
            self.assertEqual([self.health(g,p)for p in(1,2)],[27,27])
            self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)
            self.assertEqual([x.capture.origin for x in g.state.deathrattle_history],['stored']);self.assertFalse(g.state.death_history)
            self.portable(g)

    def test_bare_unsupported_burn_of_flagged_card_is_rejected_atomically(self):
        mechanics=default_mechanics();mechanics.register(BareBurn,lambda r,e:r.emit('card_burned',target_id=e.target_id,player_id=1))
        g=self.game(('s38.bare',IMP),mechanics=mechanics);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'s38.bare')
        self.assertEqual(g.snapshot(),before)

    def test_natural_death_and_active_board_trigger_are_not_double_dispatched(self):
        g=self.game(('s38.kill',),board=(IMP,));source=self.body(g,IMP).id;self.play(g,'s38.kill',source)
        self.assertEqual([x.capture.origin for x in g.state.deathrattle_history],['death']);self.assertEqual(self.health(g,2),27)
        self.assertEqual(len(g.state.death_history),1)
        g=self.game(('s38.trigger',),board=(IMP,));source=self.body(g,IMP).id;self.play(g,'s38.trigger',source)
        self.assertEqual([x.capture.origin for x in g.state.deathrattle_history],['effect'])
        self.assertEqual(g.state.entities[source].health,6);self.assertFalse(g.state.death_history)

    def test_ordinary_native_deathrattle_does_not_gain_stored_permission(self):
        g=self.game(('s38.discard_first','TLC_621'));before=list(g.state.players[1].deck);self.play(g,'s38.discard_first')
        self.assertEqual(g.state.players[1].deck,before);self.assertFalse(g.state.deathrattle_history)

    def test_original_repeat_plan_and_prohibition_apply_to_stored_origin(self):
        g=self.game(('s38.discard',IMP),board=('FP1_031',));self.play(g,'s38.discard')
        self.assertEqual(self.health(g,2),24);self.assertEqual(len(g.state.deathrattle_history),2)
        self.assertTrue(all(x.capture.origin=='stored'for x in g.state.deathrattle_history));self.portable(g)
        g=self.game(('s38.discard',IMP),board=('s38.suppressor',));before=g.snapshot()['rng_state'];self.play(g,'s38.discard')
        self.assertEqual(self.health(g,2),30);self.assertFalse(g.state.deathrattle_history);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_waiting_before_stored_group_bad_choice_restoration_and_player_boundary(self):
        g=self.game(('s38.discard',IMP),board=('s38.watch',),wait=True);self.play(g,'s38.discard')
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,True)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([self.health(g,p)for p in(1,2)],[28,27])
        for p in(1,2):
            view=json.dumps(g.observe(p));self.assertNotIn('deathrattle_batches',view);self.assertNotIn('burn_destruction',view)

    def test_original_retirement_event_cannot_be_rebound_in_pending_capture(self):
        g=self.game(('s38.discard',IMP),board=('s38.watch',),wait=True);self.play(g,'s38.discard')
        work=next(x for x in(*g._frame.prefix,*g._frame.continuation)if type(x)is InvokeDeathrattle)
        bad=replace(work.context,event=replace(work.context.event,target_id=g.state.players[1].hero_id))
        with self.assertRaises(ValueError):validate_context(bad,g.registry)

    def test_late_error_rolls_back_stored_damage_history_and_discard(self):
        g=self.game(('s38.late_failure',IMP));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'s38.late_failure')
        self.assertEqual(g.snapshot(),before)

    def test_storage_permission_strict_declaration_and_previous_schema_rejected(self):
        for changes in({'stored_deathrattle':1},{'deathrattle':None},{'on_discard':'cards.demon_zones.impfernal'}):
            r=registry();card=replace(r.card(IMP),id='s38.invalid',**changes)
            with self.assertRaises(ValueError):r.register_card(card);r.validate()
        g=self.game();self.assertEqual(g.snapshot()['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        for version in(272,SNAPSHOT_SCHEMA_VERSION-1):
            saved=g.snapshot();saved['schema_version']=version
            with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_stooge_exact_two_original_bottom_cards_and_later_normal_play(self):
        g=self.game(('s38.kill','s38.draw',),board=(STOOGE,),deck=());source=self.body(g,STOOGE).id
        self.play(g,'s38.kill',source);ids=list(g.state.players[1].deck)
        self.assertEqual(len(ids),2);self.assertNotEqual(ids[0],ids[1]);self.assertTrue(all(g.state.entities[e].card_id==GRANDMA for e in ids))
        self.play(g,'s38.draw');self.assertEqual(g.state.players[1].hand,[ids[0]])
        self.play(g,GRANDMA);self.assertEqual(self.body(g,GRANDMA).id,ids[0]);self.portable(g)

    def test_stooge_keeps_prior_deck_order_and_empty_hand_is_irrelevant(self):
        g=self.game(('s38.kill',),board=(STOOGE,),deck=(YETI,'CORE_CS2_029'));old=list(g.state.players[1].deck)
        self.play(g,'s38.kill',self.body(g,STOOGE).id);self.assertEqual(g.state.players[1].deck[:2],old)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].deck[2:]],[GRANDMA,GRANDMA])

    def test_razidir_same_turn_minion_does_not_satisfy_previous_own_turn(self):
        g=self.game(('CORE_ICC_023',RAZIDIR,YETI),enemy_hand=(IMP,));self.play(g,'CORE_ICC_023');self.play(g,RAZIDIR)
        self.assertFalse(g.state.players[1].hand);self.assertEqual([g.state.entities[e].card_id for e in g.state.players[2].hand],[IMP])
        self.assertEqual(g.state.discard_history[-1].player_id,1);self.assertEqual(self.health(g,2),30)

    def test_razidir_previous_beast_or_demon_discards_enemy_hand_instead(self):
        for previous in('CORE_ICC_023','CORE_YOD_026'):
            g=self.game((previous,RAZIDIR,YETI),enemy_hand=(YETI,));self.prepare_kindred(g,previous)
            self.play(g,RAZIDIR);self.assertEqual(len(g.state.players[2].hand),1)
            self.assertEqual(g.state.discard_history[-1].player_id,2);self.assertTrue(g.state.players[1].hand)

    def test_razidir_kindred_empty_enemy_hand_has_no_own_fallback(self):
        r=self.registry;g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('CORE_ICC_023',RAZIDIR,YETI),deck=(YETI,)*5,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',mana=40,max_mana=40,mana_cap=40)),seed=392),r)
        self.prepare_kindred(g);before=g.snapshot()['rng_state'];self.play(g,RAZIDIR)
        self.assertFalse(g.state.discard_history);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_real_kindred_enemy_imp_discard_enters_opponent_stored_deathrattle(self):
        g=self.game(('CORE_ICC_023',RAZIDIR,YETI),enemy_hand=(IMP,));self.prepare_kindred(g,clear_enemy_draw=True)
        self.play(g,RAZIDIR)
        self.assertEqual(g.state.discard_history[-1].card_id,IMP)
        self.assertEqual([self.health(g,p)for p in(1,2)],[27,27])
        self.assertEqual(g.state.deathrattle_history[0].capture.player_id,2)
        self.assertEqual(g.state.deathrattle_history[0].capture.trigger_source_card_id,RAZIDIR)
        self.portable(g)
