"""Actual Cultist board sacrifice, Boar histories and Sword account effects."""
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_death_count_sacrifice_cards import (CULTIST,BOAR,RA,SWORD,
    load_batch,register_past_death_count_sacrifice_cards)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,
    EndTurn,Game,Keyword,PlayerSetup,Registry,Scenario,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChangeManaCrystals,ChoiceOption,
    Destroy,DestroyAllManaCrystals,EquipWeapon,GainTemporaryMana,InvokeBehavior,Overload,
    RequestChoice,ReturnToHand,SetManaCap,Silence,Summon,Transform,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.model import RewindSpec
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.sacrifice import SacrificeFullNamedBoard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from tools import card_batch as batch

P='k491.'
HERO,POWER,A,WATCH=(P+x for x in ('hero','power','a','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_death_count_sacrifice_cards(r)
    r.register_behavior(P+'empty',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,initial_hero_power=POWER,metadata=META))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'empty',metadata=META))
    r.register_card(CardDefinition(A,A,CardType.MINION,attack=1,health=30,keywords=(Keyword.CHARGE,),metadata=META))
    def fail(c):raise ResolutionError('K491 deliberate late native failure')
    r.register_behavior(P+'fail',fail)
    r.register_behavior(P+'kill_entry',lambda c:(Destroy(c.target_id,c.source_id),))
    def one(c):return(SummonByCard(c.player_id,(SummonEntryMaterial(BOAR,on_summon=P+'kill_entry'),),SummonCause.capture(c)),)
    r.register_behavior(P+'one',one)
    for n in(8,9,10,11):
        key=P+'deaths'+str(n)
        r.register_behavior(key,lambda c,count=n:tuple(InvokeBehavior(P+'one',c.source_id,c.player_id)for _ in range(count)))
        r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,metadata=META))
    targeted=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),
        rewind=lambda c:(Destroy(c.target_id,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        transform=lambda c:(Transform(c.target_id,A),),
        give=lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        sleep=lambda c:(MakeDormant(c.target_id,2,c.source_id),),
        trigger=lambda c:(TriggerDeathrattles(c.target_id,c.source_id),))
    for key,body in targeted.items():
        r.register_behavior(P+key,body);extra=dict(keywords=(Keyword.REWIND,),rewind=RewindSpec())if key=='rewind'else{}
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),**extra))
    def queued_sacrifice(c):
        cause=SummonCause.capture(c)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('change','Change original',(Transform(c.state.players[c.player_id].board[0],A),))),c.source_id),
            SacrificeFullNamedBoard(c.player_id,CULTIST,RA,cause))
    def queued_crystals(c):
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('grow','Grow current account',(SetManaCap(2,60),ChangeManaCrystals(2,20,True)))),c.source_id),
            DestroyAllManaCrystals(2))
    scripts=dict(summon_cultist=lambda c:(Summon(c.player_id,CULTIST),),
        summon_ra=lambda c:(Summon(c.player_id,RA),),queue_sacrifice=queued_sacrifice,queue_crystals=queued_crystals,
        accounts=lambda c:(GainTemporaryMana(2,3),Overload(2,2)),
        equip_other=lambda c:(EquipWeapon(c.player_id,P+'other'),),
        equip_enemy=lambda c:(EquipWeapon(3-c.player_id,SWORD),))
    r.register_card(CardDefinition(P+'other','Other',CardType.WEAPON,attack=1,durability=3,metadata=META))
    for key,body in scripts.items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META))
    def watch(c):
        event=c.event;target=c.state.entities.get(event.target_id)
        relevant=(mode=='death_wait'and event.kind=='minion_died'and target.card_id==CULTIST or
            mode in('ra_wait','ra_fail')and event.kind=='minion_summoned'and target.card_id==RA or
            mode in('mana_wait','mana_fail')and event.kind=='mana_changed'and dict(event.data).get('operation')=='DestroyAllManaCrystals')
        if not relevant:return ()
        if mode.endswith('fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=50,metadata=META,
        triggers=tuple(TriggerSpec(e,WATCH)for e in('minion_died','minion_summoned','mana_changed'))))
    r.validate();return r


class PastDeathCountSacrificeTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),mode='normal',limit=7):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),deck=(A,)*20,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,hand=tuple(enemy_hand),board=tuple(enemy),deck=(A,)*20,
            mana=40,max_mana=40,mana_cap=40)),seed=491),fixture(mode),Ruleset(max_board=limit,max_hand=40))

    def board(self,g,cid,p=1):return self.entity(g,cid,p,zone='board')
    def count(self,g,cid,p=1):return sum(g.state.entities[i].card_id==cid for i in g.state.players[p].board)
    def weapon(self,g,p=1):return g.state.entities.get(g.state.players[p].weapon_id)
    def seed(self,g,n):self.play(g,P+'deaths'+str(n))

    def test_four_full_records_eight_primary_faces_and_explicit_counter_declaration(self):
        d=load_batch();rows={i['record']['id']:i['record']for i in d['dependencies']}
        self.assertEqual(tuple(rows),(CULTIST,BOAR,RA,SWORD));self.assertEqual(len(d['official_observations']),8)
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_actual_constructed_boundary_adds_exact_four_definitions(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.past_death_count_sacrifice_cards.register_past_death_count_sacrifice_cards',
            register_past_death_count_sacrifice_cards,after=True)
        self.assertEqual(len(r.cards),2692)
        for cid in(CULTIST,BOAR,RA,SWORD):self.assertEqual(r.card(cid),fixture().card(cid))

    def test_actual_seventh_cultist_destroys_one_complete_group_then_summons_ra(self):
        g=self.game((CULTIST,),board=(CULTIST,)*6);self.play(g,CULTIST)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[RA])
        self.assertEqual(len(g.state.death_history),7);self.assertEqual(len({d.batch for d in g.state.death_history}),1)
        self.assertEqual((self.board(g,RA).attack,self.board(g,RA).max_health),(20,20));self.portable(g)

    def test_actual_capacity_is_used_without_a_seven_slot_constant(self):
        g=self.game((CULTIST,),board=(CULTIST,)*2,limit=3);self.play(g,CULTIST)
        self.assertEqual(self.count(g,RA),1);self.assertEqual(len(g.state.death_history),3);self.portable(g)

    def test_incomplete_or_mixed_board_does_not_sacrifice(self):
        for board in((CULTIST,)*5,(CULTIST,)*5+(A,)):
            g=self.game((CULTIST,),board=board);self.play(g,CULTIST)
            self.assertFalse(g.state.death_history);self.assertEqual(self.count(g,RA),0);self.portable(g)

    def test_dormant_named_slot_does_not_satisfy_the_active_group(self):
        g=self.game((P+'sleep',CULTIST),board=(CULTIST,)*6)
        self.play(g,P+'sleep',self.board(g,CULTIST).id);self.play(g,CULTIST)
        self.assertFalse(g.state.death_history);self.assertEqual(self.count(g,RA),0);self.portable(g)

    def test_summon_without_play_does_not_activate_cultist_battlecry(self):
        g=self.game((P+'summon_cultist',),board=(CULTIST,)*6);self.play(g,P+'summon_cultist')
        self.assertEqual(self.count(g,CULTIST),7);self.assertFalse(g.state.death_history);self.portable(g)

    def test_queued_named_group_rechecks_original_actual_board_and_restores(self):
        g=self.game((P+'queue_sacrifice',),board=(CULTIST,)*7);self.play(g,P+'queue_sacrifice')
        other=self.portable(g);self.choose(g,'change');self.choose(other,'change')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(g.state.death_history);self.portable(g)

    def test_ra_only_ends_on_its_controllers_turn_and_hits_all_enemy_characters(self):
        g=self.game(board=(RA,A),enemy=(A,A));enemy_hero=g.state.players[2].hero_id
        own=self.board(g,A).id;targets=tuple(g.state.players[2].board);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[enemy_hero].health,80)
        self.assertEqual([g.state.entities[i].health for i in targets],[10,10]);self.assertEqual(g.state.entities[own].health,30)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[enemy_hero].health,80);self.portable(g)

    def test_silencing_ra_removes_end_body(self):
        g=self.game((P+'silence',),board=(RA,));self.play(g,P+'silence',self.board(g,RA).id)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,100);self.portable(g)

    def test_death_group_wait_restores_before_reward_and_continues_once(self):
        g=self.game((CULTIST,),board=(CULTIST,)*6,enemy=(WATCH,),mode='death_wait');self.play(g,CULTIST)
        self.assertEqual(len(g.state.death_history),7);self.assertEqual(self.count(g,RA),0);other=self.portable(g)
        while g.state.pending_choice:self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.count(g,RA),1);self.portable(g)

    def test_reward_summon_failure_rolls_back_all_original_deaths_and_payment(self):
        g=self.game((CULTIST,),board=(CULTIST,)*6,enemy=(WATCH,),mode='ra_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CULTIST)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_ninth_boar_death_has_no_weapon_and_tenth_includes_its_own_death(self):
        g=self.game((P+'deaths9',P+'kill'),board=(BOAR,));self.seed(g,9)
        self.assertEqual(len(g.state.death_history),9);self.assertIsNone(self.weapon(g))
        self.play(g,P+'kill',self.board(g,BOAR).id)
        self.assertEqual((self.weapon(g).card_id,self.weapon(g).attack,self.weapon(g).durability),(SWORD,15,3));self.portable(g)

    def test_more_than_ten_deaths_and_live_active_invocation_use_same_history(self):
        g=self.game((P+'deaths11',BOAR,P+'trigger'));self.seed(g,11)
        self.play(g,BOAR);old=self.weapon(g).id;self.play(g,P+'trigger',self.board(g,BOAR).id)
        self.assertNotEqual(self.weapon(g).id,old)
        self.assertEqual(sum(d.card_id==BOAR and d.zone==Zone.BOARD for d in g.state.death_history),11)
        self.assertGreater(len(g.state.death_history),11);self.portable(g)

    def test_weapon_deaths_do_not_fill_the_named_minion_threshold(self):
        g=self.game((P+'deaths8',P+'equip_other',SWORD,P+'equip_other',P+'trigger'),board=(BOAR,))
        self.seed(g,8);self.play(g,P+'equip_other');self.play(g,SWORD);self.play(g,P+'equip_other')
        self.assertEqual(len(g.state.death_history),10);weapon=self.weapon(g).id
        self.play(g,P+'trigger',self.board(g,BOAR).id)
        self.assertEqual(self.weapon(g).id,weapon);self.assertEqual(self.weapon(g).card_id,P+'other');self.portable(g)

    def test_stolen_boar_counts_by_its_controller_at_death(self):
        g=self.game((P+'deaths9',P+'give',P+'kill'),enemy=(BOAR,));self.seed(g,9)
        target=self.board(g,BOAR,2).id;self.play(g,P+'give',target);self.play(g,P+'kill',target)
        self.assertEqual((g.state.death_history[-1].owner,g.state.death_history[-1].controller),(2,1))
        self.assertEqual(self.weapon(g).card_id,SWORD);self.portable(g)

    def test_live_invocation_does_not_count_a_fake_death(self):
        g=self.game((P+'deaths9',P+'trigger'),board=(BOAR,));self.seed(g,9)
        self.play(g,P+'trigger',self.board(g,BOAR).id);self.assertIsNone(self.weapon(g))
        self.assertEqual(len(g.state.death_history),9);self.portable(g)

    def test_silenced_named_boar_counts_for_other_boars_but_cannot_trigger(self):
        g=self.game((P+'deaths9',P+'silence',P+'kill',BOAR,P+'trigger'),board=(BOAR,))
        self.seed(g,9);target=self.board(g,BOAR).id;self.play(g,P+'silence',target);self.play(g,P+'kill',target)
        self.assertIsNone(self.weapon(g));self.play(g,BOAR);self.play(g,P+'trigger',self.board(g,BOAR).id)
        self.assertEqual(self.weapon(g).card_id,SWORD);self.portable(g)

    def test_enemy_named_deaths_and_ordinary_bounce_are_excluded(self):
        g=self.game((P+'kill',P+'bounce'),board=(BOAR,),enemy=(BOAR,))
        self.play(g,P+'kill',self.board(g,BOAR,2).id);self.play(g,P+'bounce',self.board(g,BOAR).id)
        self.assertIsNone(self.weapon(g));self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_real_rewind_sparse_death_ids_still_supply_ten_distinct_records(self):
        g=self.game((P+'deaths9',P+'rewind'),board=(BOAR,));self.seed(g,9)
        self.play(g,P+'rewind',self.board(g,BOAR).id);self.choose(g,'retry')
        self.assertGreater(g.state.death_history[-1].id,len(g.state.death_history))
        self.assertEqual(self.weapon(g).card_id,SWORD);self.portable(g)

    def test_paid_sword_actual_hero_attack_destroys_all_crystals_but_preserves_cap(self):
        g=self.game((SWORD,));self.play(g,SWORD)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual((g.state.players[2].max_mana,g.state.players[2].mana_cap),(0,40))
        self.assertEqual(self.weapon(g).durability,2);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[2].max_mana,1);self.portable(g)

    def test_minion_attack_does_not_run_equipped_sword_reward(self):
        g=self.game((SWORD,),board=(A,),enemy=(A,));self.play(g,SWORD)
        g.apply(Attack(1,self.board(g,A).id,self.board(g,A,2).id))
        self.assertEqual(g.state.players[2].max_mana,40);self.assertEqual(self.weapon(g).durability,3);self.portable(g)

    def test_last_durability_attack_keeps_original_weapon_completion(self):
        g=self.game((SWORD,));self.play(g,SWORD)
        for step in range(3):
            g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
            self.assertEqual(g.state.players[2].max_mana,0)
            if step<2:g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIsNone(self.weapon(g));self.portable(g)

    def test_destroy_all_rechecks_current_account_after_wait_and_preserves_new_cap(self):
        g=self.game((P+'queue_crystals',));self.play(g,P+'queue_crystals');other=self.portable(g)
        self.choose(g,'grow');self.choose(other,'grow');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((g.state.players[2].max_mana,g.state.players[2].mana_cap),(0,60));self.portable(g)

    def test_destroy_crystals_preserves_temporary_mana_and_pending_overload_accounts(self):
        g=self.game((P+'accounts',P+'queue_crystals'));self.play(g,P+'accounts');self.play(g,P+'queue_crystals');self.choose(g)
        p=g.state.players[2];self.assertEqual((p.max_mana,p.temporary_mana,p.overload_owed,p.mana_cap),(0,3,2,40));self.portable(g)

    def test_weapon_mana_wait_restores_original_attack_and_bad_choice_rolls_back(self):
        g=self.game((SWORD,),board=(WATCH,),mode='mana_wait');self.play(g,SWORD)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[2].max_mana,0);self.portable(g)

    def test_late_mana_failure_rolls_back_combat_durability_and_accounts(self):
        g=self.game((SWORD,),board=(WATCH,),mode='mana_fail');self.play(g,SWORD);saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(),saved);self.portable(g)
