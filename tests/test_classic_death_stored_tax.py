"""Actual rewards/cycle, stored physical groups and one-turn spell tax."""
from dataclasses import asdict
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import classic_death_stored_tax as native
from hs_sim.cards.conditional_cards import register_conditional_cards
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,Draw,
    GainArmor,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,TriggerDeathrattles)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

RHON,ANUB,MIST,EADRIC,LOATHEB=native.ROOTS;NERUB=native.NERUBIAN;MISSILES=native.MISSILES
P='k692.';A=P+'plain';POWER=P+'power';IMMUNE=P+'immune';DORMANT=P+'dormant';LOC=P+'location';WEAPON=P+'weapon'
KILL=P+'kill';HUSH=P+'hush';OUT=P+'out';TAKE=P+'take';BOOST=P+'boost';HIT=P+'hit';DRAW=P+'draw'
ADD=P+'add';SPELL=P+'spell';EXTRA=P+'extra';SKIP=P+'skip';TRIGGER=P+'trigger';FAIL=P+'fail'
REWARD_WATCH=P+'reward_watch';SUMMON_WATCH=P+'summon_watch';STORED_WATCH=P+'stored_watch'
SET_WATCH=P+'set_watch';COST_WATCH=P+'cost_watch';WATCH=P+'watch'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();register_conditional_cards(r);native.register_classic_death_stored_tax(r)
    for cid,bonus,keywords in((A,0,()),(POWER,2,()),(IMMUNE,0,(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=3,attack=5,health=20,
            spell_damage=bonus,keywords=keywords,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,attack=5,health=20,dormant_turns=2,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=2,durability=2,metadata=metadata(collectible=False)))
    r.register_behavior(LOC,lambda c:());r.register_card(CardDefinition(LOC,LOC,CardType.LOCATION,durability=3,on_use=LOC,metadata=metadata(collectible=False)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        OUT:lambda c:(ReturnToHand(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,c.player_id),),
        BOOST:lambda c:(Buff(c.target_id,3,3,c.source_id),),HIT:lambda c:(Damage(c.target_id,3,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),ADD:lambda c:(AddToHand(c.player_id,SPELL,source_id=c.source_id),),
        SPELL:lambda c:(GainArmor(c.player_id,1),),EXTRA:lambda c:(QueueTurns((c.player_id,),c.source_id),),
        SKIP:lambda c:(SkipTurns(3-c.player_id,source_id=c.source_id),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=2 if cid==SPELL else 1,on_play=cid,
            targeting=board if cid in(KILL,HUSH,OUT,TAKE,BOOST,HIT,TRIGGER)else None,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K692 deliberate reward/stat/cost continuation rollback')))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id);extra=()
        if e.kind=='card_added_to_hand':
            if source is None or source.card_id!=RHON or target is None or target.card_id!=MISSILES:return()
        elif e.kind=='minion_summoned':
            if target is None or target.card_id!=NERUB:return()
        elif e.kind=='stored_card_buffed':
            if source is None or source.card_id!=MIST:return()
            extra=(Draw(c.player_id,1,c.source_id),)
        elif e.kind=='stats_changed':
            if source is None or source.card_id!=EADRIC:return()
            others=[i for i in c.state.players[3-c.player_id].board if i!=e.target_id and c.state.entities[i].kind==CardType.MINION]
            extra=()if not others else(ReturnToHand(others[0]),)
        elif source is None or source.card_id!=LOATHEB:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('move','Move original',extra),
            ChoiceOption('fault','Fail after random work',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((REWARD_WATCH,'card_added_to_hand'),(SUMMON_WATCH,'minion_summoned'),
            (STORED_WATCH,'stored_card_buffed'),(SET_WATCH,'stats_changed'),(COST_WATCH,'cost_modifier_added')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=40,triggers=(TriggerSpec(event,WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class ClassicDeathStoredTaxTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(A,)*8,enemy_deck=(A,)*8,player=1,seed=692):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=deck if p==player else enemy_deck,mana=20,max_mana=20,mana_cap=20)for p in(1,2)),active_player=player,seed=seed),fixture('writer'))
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def price(self,g,cid,p=1):
        e=self.entity(g,cid,p);return(g.quote_cost(e.id)if p==g.state.active_player else quote_cost(g.state,g.registry,e)).amount
    def pending(self,g,p=2):return[e for e in g.state.players[p].player_effects if e.spec_id==native.PROGRAM]
    def finish_choices(self,g):
        while g.state.pending_choice is not None:self.choose(g)

    def test_complete_faces_existing_actual_missiles_and_full_original_domain(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),18)
        for row in d['cards']+d['dependencies']+d['existing_dependencies'][:1]:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(fixture().card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(fixture().pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual((fixture().card(ANUB).attack,fixture().card(ANUB).health),(8,4));self.assertIsNone(fixture().card(ANUB).battlecry)

    def test_all_six_actual_paid_faces_preserve_real_printed_stats_and_one_payment(self):
        for cid in(*native.ROOTS,NERUB):
            g=self.game((cid,));source=self.play(g,cid);card=fixture().card(cid)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(card.attack,card.health))
            self.assertEqual(g.state.players[1].mana,20-card.cost);self.assertEqual(len(g.state.play_history),1)

    def test_rhonin_real_death_adds_three_actual_distinct_missiles_without_drawing(self):
        g=self.game((KILL,),board=(RHON,));self.play(g,KILL,self.unit(g,RHON).id)
        self.assertEqual(self.hand(g),[MISSILES]*3);self.assertEqual(len(set(g.state.players[1].hand)),3)
        self.assertEqual(g.state.draw_history,[]);self.assertEqual(self.hero(g).health,30)

    def test_rhonin_generated_missile_really_pays_and_uses_existing_split_damage_count(self):
        g=self.game((KILL,),board=(RHON,POWER));self.play(g,KILL,self.unit(g,RHON).id);self.play(g,MISSILES)
        self.assertEqual(self.hero(g,2).health,25);self.assertEqual(g.state.players[1].mana,18)
        self.assertEqual(self.hand(g),[MISSILES]*2);self.assertEqual([x.card_id for x in g.state.cast_history],[KILL,MISSILES])

    def test_rhonin_current_controller_receives_reward_and_full_hand_burns_excess(self):
        g=self.game((TAKE,KILL),enemy=(RHON,));source=self.unit(g,RHON,2).id;self.play(g,TAKE,source);self.play(g,KILL,source)
        self.assertEqual(self.hand(g),[MISSILES]*3);self.assertEqual(self.hand(g,2),[])
        g=self.game((KILL,)+(A,)*9,board=(RHON,));self.play(g,KILL,self.unit(g,RHON).id)
        self.assertEqual(self.hand(g).count(MISSILES),1)
        burned=[e for e in g.state.entities.values()if e.card_id==MISSILES and e.zone==Zone.GRAVEYARD];self.assertEqual(len(burned),2)

    def test_rhonin_silence_removes_reward_and_live_trigger_does_not_kill_source(self):
        g=self.game((HUSH,KILL),board=(RHON,));source=self.unit(g,RHON).id;self.play(g,HUSH,source);self.play(g,KILL,source)
        self.assertNotIn(MISSILES,self.hand(g))
        g=self.game((TRIGGER,),board=(RHON,));source=self.unit(g,RHON).id;self.play(g,TRIGGER,source)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(self.hand(g),[MISSILES]*3)

    def test_rhonin_three_reward_notifications_wait_restore_and_failure_do_not_duplicate(self):
        g=self.game((KILL,),board=(RHON,REWARD_WATCH));self.play(g,KILL,self.unit(g,RHON).id);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish_choices(g);self.assertEqual(self.hand(g),[MISSILES]*3);self.portable(g)

    def test_anubarak_actual_cycle_summons_fresh_full_eight_four_and_no_hand_return(self):
        g=self.game((KILL,KILL),board=(ANUB,));original=self.unit(g,ANUB).id;self.play(g,KILL,original)
        child=self.unit(g,NERUB);self.assertEqual((child.attack,child.health),(4,4));self.play(g,KILL,child.id)
        revived=self.unit(g,ANUB);self.assertNotEqual(revived.id,original);self.assertEqual((revived.attack,revived.health),(8,4))
        self.assertEqual(self.hand(g),[]);self.assertEqual(len(g.state.death_history),2)

    def test_anubarak_and_nerubian_use_actual_same_side_natural_death_slot(self):
        g=self.game((KILL,KILL),board=(A,ANUB,A));self.play(g,KILL,self.unit(g,ANUB).id)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[A,NERUB,A])
        self.play(g,KILL,self.unit(g,NERUB).id);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[A,ANUB,A])

    def test_anubarak_buffs_do_not_leak_into_fresh_named_child_or_cycle_body(self):
        g=self.game((BOOST,KILL,KILL),board=(ANUB,));self.play(g,BOOST,self.unit(g,ANUB).id);self.play(g,KILL,self.unit(g,ANUB).id)
        self.assertEqual((self.unit(g,NERUB).attack,self.unit(g,NERUB).health),(4,4));self.play(g,KILL,self.unit(g,NERUB).id)
        self.assertEqual((self.unit(g,ANUB).attack,self.unit(g,ANUB).health),(8,4))

    def test_anubarak_stolen_death_goes_to_current_controller_and_silence_breaks_cycle(self):
        g=self.game((TAKE,KILL),enemy=(ANUB,));source=self.unit(g,ANUB,2).id;self.play(g,TAKE,source);self.play(g,KILL,source)
        self.assertEqual(self.unit(g,NERUB).controller,1);self.assertEqual(g.state.players[2].board,[])
        for cid in(ANUB,NERUB):
            g=self.game((HUSH,KILL),board=(cid,));source=self.unit(g,cid).id;self.play(g,HUSH,source);self.play(g,KILL,source)
            self.assertEqual(g.state.players[1].board,[])

    def test_anubarak_live_trigger_respects_capacity_and_does_not_remove_original(self):
        g=self.game((TRIGGER,),board=(ANUB,)+(A,)*6);source=self.unit(g,ANUB).id;self.play(g,TRIGGER,source)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(any(e.card_id==NERUB for e in g.state.entities.values()))
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD)

    def test_named_child_wait_restore_and_failed_choice_preserve_original_death(self):
        g=self.game((KILL,),board=(ANUB,SUMMON_WATCH));source=self.unit(g,ANUB).id;self.play(g,KILL,source);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.unit(g,NERUB).health,4)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_mistcaller_buffs_all_original_hand_deck_minions_but_not_other_kinds_or_board(self):
        g=self.game((MIST,A,SPELL,WEAPON),board=(A,),enemy_hand=(A,),deck=(A,SPELL,WEAPON),enemy_deck=(A,))
        hand=self.entity(g,A).id;deck=g.state.players[1].deck[0];board=self.unit(g,A).id;self.play(g,MIST)
        for eid in(hand,deck):self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(6,21))
        self.assertEqual((g.state.entities[board].attack,g.state.entities[board].health),(5,20))
        self.assertEqual(g.state.entities[g.state.players[2].hand[0]].attack,5)
        self.assertEqual((self.entity(g,WEAPON).attack,self.entity(g,WEAPON).durability),(2,2));self.assertEqual(self.price(g,SPELL),2)
        self.assertEqual((self.unit(g,MIST).attack,self.unit(g,MIST).health),(4,4))

    def test_mistcaller_buffed_physical_draw_and_play_keep_growth_and_source_can_leave(self):
        g=self.game((MIST,DRAW,KILL),deck=(A,));source=self.play(g,MIST);self.play(g,KILL,source);self.play(g,DRAW)
        source=self.play(g,A);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(6,21));self.portable(g)

    def test_two_mistcaller_battlecries_stack_original_stored_growth_only(self):
        g=self.game((MIST,MIST,A));self.play(g,MIST);self.assertEqual((self.entity(g,MIST).attack,self.entity(g,MIST).health),(5,5))
        second=self.play(g,MIST);self.assertEqual((g.state.entities[second].attack,g.state.entities[second].health),(5,5))
        self.assertEqual((self.entity(g,A).attack,self.entity(g,A).health),(7,22))

    def test_mistcaller_captured_deck_reference_does_not_follow_card_moved_by_earlier_notice(self):
        g=self.game((MIST,A),board=(STORED_WATCH,),deck=(A,));deck=g.state.players[1].deck[0];self.play(g,MIST);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'move');self.finish_choices(g)
        self.assertEqual(g.state.entities[deck].zone,Zone.HAND);self.assertEqual((g.state.entities[deck].attack,g.state.entities[deck].health),(5,20));self.portable(g)

    def test_eadric_sets_current_enemy_attack_only_and_preserves_damage_and_identity(self):
        g=self.game((BOOST,HIT,EADRIC),board=(A,),enemy=(A,));target=self.unit(g,A,2).id;self.play(g,BOOST,target);self.play(g,HIT,target)
        before=(g.state.entities[target].health,g.state.entities[target].max_health,g.state.entities[target].damage);self.play(g,EADRIC)
        self.assertEqual(g.state.entities[target].attack,1);self.assertEqual((g.state.entities[target].health,g.state.entities[target].max_health,g.state.entities[target].damage),before)
        self.assertEqual(self.unit(g,A).attack,5);self.assertEqual(g.state.entities[target].zone,Zone.BOARD)

    def test_eadric_current_set_later_add_and_silence_use_original_stat_layer(self):
        g=self.game((EADRIC,BOOST,HUSH),enemy=(A,));target=self.unit(g,A,2).id;self.play(g,EADRIC);self.play(g,BOOST,target)
        self.assertEqual(g.state.entities[target].attack,4);self.play(g,HUSH,target);self.assertEqual(g.state.entities[target].attack,5)

    def test_eadric_group_includes_immune_but_excludes_dormant_and_locations(self):
        g=self.game((EADRIC,),enemy=(IMMUNE,DORMANT,LOC));self.play(g,EADRIC)
        self.assertEqual(self.unit(g,IMMUNE,2).attack,1);self.assertEqual(self.unit(g,DORMANT,2).attack,5)
        self.assertEqual(self.unit(g,LOC,2).durability,3)

    def test_eadric_empty_group_has_no_rng_and_no_required_arrow(self):
        g=self.game((EADRIC,));rng=g._rng.getstate();self.play(g,EADRIC);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.players[1].mana,13)

    def test_eadric_wait_restores_then_skips_original_later_target_that_left(self):
        g=self.game((EADRIC,),board=(SET_WATCH,),enemy=(A,A));later=g.state.players[2].board[1];self.play(g,EADRIC)
        before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'move');self.finish_choices(g)
        self.assertEqual(g.state.entities[later].zone,Zone.HAND);self.assertEqual(g.state.entities[later].attack,5);self.portable(g)

    def test_loatheb_does_not_tax_current_turn_or_caster_and_installs_exact_opponent_instance(self):
        g=self.game((LOATHEB,SPELL),enemy_hand=(SPELL,));source=self.play(g,LOATHEB)
        self.assertEqual(len(self.pending(g)),1);self.assertEqual(self.pending(g)[0].source_id,source)
        self.assertEqual(self.price(g,SPELL),2);self.assertEqual(self.price(g,SPELL,2),2)

    def test_loatheb_taxes_all_existing_drawn_and_generated_spells_for_actual_turn(self):
        g=self.game((LOATHEB,),enemy_hand=(SPELL,DRAW,ADD),enemy_deck=(SPELL,)*10);self.play(g,LOATHEB);self.end(g)
        self.assertEqual(self.pending(g),[]);self.assertEqual(self.price(g,SPELL,2),7)
        self.play(g,DRAW,player=2);self.play(g,ADD,player=2);self.assertEqual(self.price(g,SPELL,2),7)
        spell_ids=[eid for eid in g.state.players[2].hand if g.state.entities[eid].card_id==SPELL]
        self.assertEqual([g.quote_cost(eid).amount for eid in spell_ids],[7]*len(spell_ids))
        mana=g.state.players[2].mana;self.play(g,SPELL,player=2);self.assertEqual(g.state.players[2].mana,mana-7)

    def test_loatheb_tax_affordability_rejects_before_payment_and_does_not_discount_minions(self):
        g=self.game((LOATHEB,),enemy_hand=(SPELL,SPELL,SPELL,A));self.play(g,LOATHEB);self.end(g)
        self.assertEqual(self.price(g,A,2),3);self.play(g,SPELL,player=2);self.play(g,SPELL,player=2);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,SPELL,player=2)
        self.assertEqual(g.snapshot(),before)

    def test_loatheb_source_death_silence_return_do_not_cancel_and_tax_expires(self):
        for action in(KILL,HUSH,OUT):
            g=self.game((LOATHEB,action),enemy_hand=(SPELL,));source=self.play(g,LOATHEB);self.play(g,action,source);self.end(g)
            self.assertEqual(self.price(g,SPELL,2),7);self.end(g);self.assertEqual(self.price(g,SPELL,2),2)

    def test_two_actual_loathebs_keep_distinct_consumption_and_additive_tax(self):
        g=self.game((LOATHEB,LOATHEB),enemy_hand=(SPELL,));self.play(g,LOATHEB);self.play(g,LOATHEB)
        self.assertEqual(len({x.id for x in self.pending(g)}),2);self.assertEqual(g.state.players[1].mana,10)
        self.end(g);self.assertEqual(self.price(g,SPELL,2),12);self.assertEqual(len(g.state.players[2].cost_modifiers),2)

    def test_loatheb_waits_through_caster_extra_turn_and_skipped_enemy_slot(self):
        for action in(EXTRA,SKIP):
            g=self.game((LOATHEB,action),enemy_hand=(SPELL,));self.play(g,LOATHEB);self.play(g,action);self.end(g)
            self.assertEqual(g.state.active_player,1);self.assertEqual(len(self.pending(g)),1);self.assertEqual(self.price(g,SPELL,2),2)
            self.end(g);self.assertEqual(self.price(g,SPELL,2),7)

    def test_second_player_native_death_and_spell_tax_use_actual_controller(self):
        g=self.game((KILL,LOATHEB),board=(ANUB,),enemy_hand=(SPELL,),player=2);self.play(g,KILL,self.unit(g,ANUB,2).id,player=2)
        self.assertEqual(self.unit(g,NERUB,2).controller,2);self.play(g,LOATHEB,player=2);self.end(g)
        self.assertEqual(self.price(g,SPELL),7);self.portable(g)

    def test_loatheb_pending_and_cost_install_wait_restore_exact_once_and_rollback(self):
        g=self.game((LOATHEB,),enemy=(COST_WATCH,),enemy_hand=(SPELL,));self.play(g,LOATHEB);g=self.portable(g);self.end(g)
        self.assertEqual(self.pending(g),[]);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.price(g,SPELL,2),7)
        self.end(g);self.assertEqual(self.price(g,SPELL,2),2);self.portable(g)

    def test_standard_host_real_anubarak_child_cycle_uses_normal_paid_fireballs(self):
        self.mode='host';h=host('writer');fireball='CORE_CS2_029'
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(ANUB,fireball,fireball),deck=('CORE_CS2_182',)*8,
            mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8)),generation_context=h.context,seed=692),h.registry)
        old=self.play(g,ANUB);self.play(g,fireball,old);child=self.unit(g,NERUB);self.play(g,fireball,child.id)
        self.assertEqual((self.unit(g,ANUB).attack,self.unit(g,ANUB).health),(8,4));self.assertNotEqual(self.unit(g,ANUB).id,old)
        self.assertEqual(g.state.players[1].mana,4);self.assertEqual(len(g.state.death_history),2);self.portable(g)
