"""Real recovery roots use immutable deaths and actual own-turn play facts."""
import json,unittest
from random import Random
from hs_sim.cards import build_registry
from hs_sim.cards.history_recovery_cards import load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,
    Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Destroy,Draw,GainArmor,
    InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_sources import DeathQuery,death_candidates
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.targets import canonical_digest

CALIA='CORE_CATA_002';KRAG='CORE_TRL_345';YETI='CORE_CS2_182'


def registry():
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_behavior('k31.native',lambda c:(GainArmor(c.state.players[c.player_id].hero_id,7),))
    for key,cost in(('small',2),('large',7),('twin',7)):
        r.register_card(CardDefinition('k31.'+key,key,CardType.MINION,cost=cost,attack=3,health=5,
            battlecry='k31.native',keywords=(Keyword.TAUNT,),metadata=meta))
    r.register_card(CardDefinition('k31.filler','Non-spell filler',CardType.MINION,health=1,metadata=meta))
    bodies=dict(s1=lambda c:(),s2=lambda c:(),blank=lambda c:(),refill=lambda c:(Draw(c.player_id,3,c.source_id),),
        kill=lambda c:(Destroy(c.target_id,c.source_id),),
        killall=lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board),
        lower=lambda c:(ModifyCost(c.target_id,CostSpec(set_to=0),c.source_id),),
        buff=lambda c:(Buff(c.target_id,6,6,c.source_id),Silence(c.target_id)),
        transform=lambda c:(Transform(c.target_id,'k31.small'),),
        steal=lambda c:(ChangeControl(c.target_id,c.player_id),),
        extra=lambda c:(QueueTurns((c.player_id,),c.source_id),),
        skip=lambda c:(SkipTurns(c.player_id,1,c.source_id),),
        discount=lambda c:(ModifyCost(next(i for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id=='k31.s2'),CostSpec(set_to=0),c.source_id),),
        fail=lambda c:(AddToHand(c.player_id,'unknown.k31'),))
    targeted={'kill','lower','buff','transform','steal'}
    for key,body in bodies.items():
        r.register_behavior('k31.'+key,body)
        if key=='fail':continue
        r.register_card(CardDefinition('k31.'+key,key,CardType.SPELL,cost={'s1':1,'s2':2}.get(key,0),
            on_play='k31.'+key,requires_target=key in targeted,metadata=meta,
            spell_school=SpellSchool.ARCANE if key=='s1'else None))
    r.register_behavior('k31.auto',lambda c:(CastSpell(c.player_id,'k31.s2',c.source_id),))
    r.register_card(CardDefinition('k31.auto','Automatic cast producer',CardType.MINION,health=1,battlecry='k31.auto',metadata=meta))
    def counter(c):
        return(CounterSpell(dict(c.event.data)['window_id']),)if c.play is not None and c.play.kind==CardType.SPELL else()
    r.register_behavior('k31.counter',counter)
    r.register_card(CardDefinition('k31.counter','Counter fixture',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_committed','k31.counter'),),metadata=meta))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if c.event.kind=='card_added_to_hand':
            if source is None or source.card_id!=KRAG:return()
        else:
            restored=next((row for row in c.state.resurrection_history if row.entity_id==c.event.target_id),None)
            if restored is None:return()
            source=c.state.entities[restored.source_id]
        retreat=()if source is None else(ReturnToHand(source.id),)
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),
            ChoiceOption('retreat','Return original source',retreat),
            ChoiceOption('fail','Fail',(InvokeBehavior('k31.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k31.watch',watch)
    for event,key in(('minion_summoned','reswatch'),('card_added_to_hand','handwatch')):
        r.register_card(CardDefinition('k31.'+key,key,CardType.MINION,health=8,
            triggers=(TriggerSpec(event,'k31.watch'),),metadata=meta))
    def faulty(c):
        source=c.state.entities.get(c.event.source_id)
        return(InvokeBehavior('k31.fail',c.source_id,c.player_id),)if source is not None and source.card_id==KRAG else()
    r.register_behavior('k31.fault',faulty)
    r.register_card(CardDefinition('k31.fault','Generation rollback fixture',CardType.MINION,health=8,
        triggers=(TriggerSpec('card_added_to_hand','k31.fault'),),metadata=meta))
    return r


class HistoryRecoveryCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=431),self.r)
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target,len(g.state.players[p].board)if g.registry.card(cid).kind==CardType.MINION else None))
        return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def round(self,g):self.end(g);self.end(g)
    def entity(self,g,cid,p=1):return next(i for i in g.state.players[p].board if g.state.entities[i].card_id==cid)
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('resurrection_summon_history','resurrection_history','owner_turn_history','played_face','face_replaced'):
                self.assertNotIn('"'+key+'"',visible)

    def test_complete_pinned_faces_and_explicit_identities(self):
        batch=load_batch()
        for row in batch['cards']+batch['historical_identity_evidence']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for cid,stats,tribe in((CALIA,(6,4,5),'undead'),(KRAG,(6,4,6),'beast')):
            c=self.r.card(cid);self.assertEqual((c.cost,c.attack,c.health),stats);self.assertEqual(c.metadata.tribes,(tribe,))
        self.assertEqual(self.r.card(KRAG).metadata.deck_identity,'TRL_345')
        self.assertEqual(self.r.card(CALIA).metadata.deck_identity,CALIA)

    def test_calia_pays_once_and_creates_a_new_body_from_highest_friendly_death(self):
        g=self.game(('k31.killall',CALIA),('k31.small','k31.large'),('k31.twin',));self.play(g,'k31.killall')
        old=self.entity_ids_in_grave(g);mana=g.state.players[1].mana;self.play(g,CALIA)
        row=g.state.resurrection_history[-1];self.assertEqual(g.state.entities[row.entity_id].card_id,'k31.large')
        self.assertNotIn(row.entity_id,old);self.assertEqual(g.state.players[1].mana,mana-6)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in old))
        self.assertEqual(len(g.state.resurrection_history),1);self.portable(g)

    def entity_ids_in_grave(self,g):return{i for i,e in g.state.entities.items()if e.zone==Zone.GRAVEYARD and e.kind==CardType.MINION}

    def test_calia_empty_or_only_enemy_deaths_do_not_sample(self):
        for enemy in((),('k31.large',)):
            g=self.game(('k31.kill',CALIA),enemy=enemy)
            if enemy:self.play(g,'k31.kill',self.entity(g,'k31.large',2))
            before=g.snapshot()['rng_state'];self.play(g,CALIA)
            self.assertFalse(g.state.resurrection_history);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_calia_uses_printed_extreme_even_with_local_zero_cost_at_death(self):
        g=self.game(('k31.lower','k31.killall',CALIA),('k31.small','k31.large'))
        self.play(g,'k31.lower',self.entity(g,'k31.large'));self.play(g,'k31.killall')
        self.assertEqual([d.card_id for d in death_candidates(g.state,self.r,1,DeathQuery(cost_extreme='highest',cost_basis='local_at_death'))],['k31.small'])
        self.play(g,CALIA);self.assertEqual(g.state.entities[g.state.resurrection_history[-1].entity_id].card_id,'k31.large')

    def test_calia_uses_transformed_face_frozen_at_death(self):
        g=self.game(('k31.transform','k31.killall',CALIA),('k31.large',YETI))
        self.play(g,'k31.transform',self.entity(g,'k31.large'));self.play(g,'k31.killall');self.play(g,CALIA)
        self.assertEqual(g.state.entities[g.state.resurrection_history[-1].entity_id].card_id,YETI)

    def test_calia_friendly_means_controller_at_death(self):
        g=self.game(('k31.steal','k31.kill',CALIA),enemy=('k31.large',));target=self.entity(g,'k31.large',2)
        self.play(g,'k31.steal',target);self.play(g,'k31.kill',target);self.play(g,CALIA)
        dead=g.state.death_history[-1];self.assertEqual((dead.owner,dead.controller),(2,1))
        new=g.state.entities[g.state.resurrection_history[-1].entity_id];self.assertEqual((new.card_id,new.owner,new.controller),('k31.large',1,1))

    def test_calia_ties_keep_one_weight_per_death_occurrence(self):
        g=self.game(('k31.killall',CALIA),('k31.large','k31.large','k31.twin'))
        self.play(g,'k31.killall');saved=g.snapshot()['rng_state'];rng=Random();rng.setstate((saved[0],tuple(saved[1]),saved[2]))
        candidates=[d.id for d in g.state.death_history];expected=rng.choice(candidates)
        self.play(g,CALIA);root=g.state.resurrection_summon_history[-1]
        self.assertEqual(root.candidates,tuple(candidates));self.assertEqual(root.picks[0].selected,expected)
        self.assertEqual(g.state.resurrection_history[-1].death_id,expected)

    def test_calia_full_board_does_not_select_or_consume_rng(self):
        g=self.game(('k31.kill',CALIA),('k31.large',)+('k31.filler',)*6)
        self.play(g,'k31.kill',self.entity(g,'k31.large'));before=g.snapshot()['rng_state'];self.play(g,CALIA)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(g.state.resurrection_history)
        self.assertEqual(g.state.resurrection_summon_history[-1].status,'board_full');self.assertEqual(g.snapshot()['rng_state'],before)

    def test_calia_restores_base_stats_and_native_keyword_without_replaying_battlecry(self):
        g=self.game(('k31.buff','k31.kill',CALIA),('k31.large',));target=self.entity(g,'k31.large')
        self.play(g,'k31.buff',target);self.assertNotIn(Keyword.TAUNT,g.state.entities[target].keywords)
        self.play(g,'k31.kill',target);self.play(g,CALIA);new=g.state.entities[g.state.resurrection_history[-1].entity_id]
        self.assertEqual((new.attack,new.max_health,new.health),(3,5,5));self.assertIn(Keyword.TAUNT,new.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def waiting_calia(self):
        g=self.game(('k31.kill',CALIA),('k31.large','k31.reswatch'));self.play(g,'k31.kill',self.entity(g,'k31.large'));self.play(g,CALIA)
        self.assertIsNotNone(g.state.pending_choice);return g

    def test_calia_wait_preserves_chosen_death_after_source_returns(self):
        g=self.waiting_calia();self.portable(g);entity=g.state.resurrection_history[-1].entity_id
        self.choose(g,'retreat');self.assertIn(CALIA,self.hand(g));self.assertIn(entity,g.state.players[1].board)
        self.assertEqual(len(g.state.resurrection_history),1);self.portable(g)

    def test_calia_failed_choice_restores_original_frame_rng_and_selected_body(self):
        g=self.waiting_calia();saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.portable(g)

    def test_kragwa_has_no_previous_own_turn_on_first_turn(self):
        g=self.game(('k31.s1',KRAG));self.play(g,'k31.s1');before=g.snapshot()['rng_state'];self.play(g,KRAG)
        self.assertFalse(self.hand(g));self.assertEqual(g.snapshot()['rng_state'],before)

    def test_kragwa_returns_each_play_occurrence_as_new_base_spell(self):
        g=self.game(('k31.s1','k31.s1','k31.s2',KRAG));ids=[self.play(g,c)for c in('k31.s1','k31.s1','k31.s2')]
        self.round(g);mana=g.state.players[1].mana;self.play(g,KRAG)
        self.assertEqual(self.hand(g),[YETI,'k31.s1','k31.s1','k31.s2'])
        self.assertEqual(g.state.players[1].mana,mana-6)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in ids))
        self.assertFalse(set(ids)&set(g.state.players[1].hand));self.portable(g)

    def test_kragwa_includes_unschooled_countered_paid_play_and_excludes_automatic_cast(self):
        g=self.game(('k31.blank','k31.auto',KRAG),enemy=('k31.counter',))
        self.play(g,'k31.blank');self.play(g,'k31.auto');self.assertTrue(g.state.play_history[0].countered)
        self.assertEqual(len(g.state.cast_history),2);self.round(g);self.play(g,KRAG)
        self.assertEqual(self.hand(g),[YETI,'k31.blank'])

    def test_kragwa_excludes_opponent_and_current_turn_spells(self):
        g=self.game(('k31.s1','k31.s2',KRAG),enemy_hand=('k31.blank',))
        self.play(g,'k31.s1');self.end(g);self.play(g,'k31.blank');self.end(g);self.play(g,'k31.s2');self.play(g,KRAG)
        self.assertEqual(self.hand(g),[YETI,'k31.s1'])

    def test_kragwa_does_not_search_past_an_empty_previous_own_turn(self):
        g=self.game(('k31.s1',KRAG));self.play(g,'k31.s1');self.round(g);self.round(g);self.play(g,KRAG)
        self.assertEqual(self.hand(g),[YETI,YETI])

    def test_kragwa_uses_actual_extra_own_interval(self):
        g=self.game(('k31.s1','k31.extra',KRAG));self.play(g,'k31.s1');self.play(g,'k31.extra');self.end(g)
        self.assertEqual(g.state.active_player,1);self.play(g,KRAG)
        self.assertEqual(self.hand(g),[YETI,'k31.s1','k31.extra'])

    def test_kragwa_skipped_slot_does_not_create_an_empty_previous_interval(self):
        g=self.game(('k31.s1','k31.skip',KRAG));self.play(g,'k31.s1');self.play(g,'k31.skip');self.end(g);self.end(g)
        self.assertEqual(g.state.active_player,2);self.end(g);self.assertEqual(g.state.active_player,1);self.play(g,KRAG)
        self.assertEqual(self.hand(g),[YETI,'k31.s1','k31.skip'])

    def test_kragwa_does_not_copy_original_spell_cost_enchantments(self):
        g=self.game(('k31.discount','k31.s2',KRAG));self.play(g,'k31.discount');old=self.play(g,'k31.s2')
        self.round(g);self.play(g,KRAG);new=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='k31.s2')
        self.assertNotEqual(old,new);self.assertEqual(quote_cost(g.state,self.r,g.state.entities[new]).amount,2)

    def test_kragwa_full_hand_burns_later_returns_in_original_order(self):
        g=self.game(('k31.s1','k31.refill',KRAG)+('k31.filler',)*7)
        self.play(g,'k31.s1');self.play(g,'k31.refill');self.round(g)
        self.assertEqual(len(self.hand(g)),10);previous=set(g.state.entities);self.play(g,KRAG)
        self.assertEqual(self.hand(g)[-1],'k31.s1');self.assertEqual(len(self.hand(g)),10)
        new=[e for i,e in g.state.entities.items()if i not in previous]
        self.assertEqual([(e.card_id,e.zone)for e in new],[('k31.s1',Zone.HAND),('k31.refill',Zone.GRAVEYARD)])

    def waiting_krag(self,watch='k31.handwatch'):
        g=self.game(('k31.s1','k31.s2',KRAG),(watch,));self.play(g,'k31.s1');self.play(g,'k31.s2');self.round(g)
        self.play(g,KRAG);return g

    def test_kragwa_waiting_tail_survives_source_return_and_independent_restore(self):
        g=self.waiting_krag();self.assertEqual(self.hand(g),[YETI,'k31.s1']);self.portable(g)
        self.choose(g,'retreat');self.assertEqual(self.hand(g),[YETI,'k31.s1',KRAG,'k31.s2'])
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_kragwa_failed_generation_reaction_rolls_back_whole_paid_action(self):
        g=self.game(('k31.s1','k31.s2',KRAG),('k31.fault',));self.play(g,'k31.s1');self.play(g,'k31.s2');self.round(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,KRAG)
        self.assertEqual(g.snapshot(),saved)

    def test_kragwa_failed_choice_preserves_original_history_and_tail(self):
        g=self.waiting_krag();saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        self.assertEqual(self.hand(g),[YETI,'k31.s1','k31.s2']);self.portable(g)

    def test_two_kragwas_do_not_consume_the_previous_turn_history(self):
        g=self.game(('k31.s1',KRAG,KRAG));self.play(g,'k31.s1');self.round(g);self.play(g,KRAG);self.play(g,KRAG)
        self.assertEqual(self.hand(g),[YETI,'k31.s1','k31.s1']);self.assertEqual(len(g.state.play_history),3)


if __name__=='__main__':unittest.main()
