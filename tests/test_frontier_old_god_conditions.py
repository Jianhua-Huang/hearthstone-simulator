"""Real empty-zone hero destruction and occurrence-based Corrupted returns."""
from dataclasses import replace
from functools import lru_cache
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.frontier_old_god_conditions import ROOTS, EXISTING, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayerSetup, ResolutionError, Scenario, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy,
    DestroyBatch, InvokeBehavior, RequestChoice, Transform, TriggerDeathrattles)
from hs_sim.engine.model import KeywordAuraSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from tools import card_batch as batch

S='k557.'
WATCH, IMMUNE, CREATOR=S+'watch',S+'immune',S+'creator'
MECHA, YSHAARJ=ROOTS
GRYPHON, CORRUPTED=EXISTING
CTX=GenerationContext('k557-two-old-god-conditions-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','two-old-god-conditions-test-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in ROOTS),complete=True))
    def fail(c):raise ResolutionError('k557 deliberate card delivery failure')
    def wait(c):
        return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('spoil','Add a card',(AddToHand(c.player_id,FILLER,c.source_id),)),
            ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id)
    def observe(c):
        e=c.state.entities.get(c.event.target_id)
        if mode=='death_wait' and c.event.kind=='minion_died' and e is not None and e.card_id==MECHA:
            return (wait(c),)
        source=c.state.entities.get(c.event.source_id)
        if c.event.kind=='card_added_to_hand' and source is not None and source.card_id==YSHAARJ:
            if mode=='copy_wait':return (wait(c),)
            if mode=='copy_fail' and sum(c.state.entities[i].card_id==CORRUPTED
                    for i in c.state.players[c.player_id].hand)==2:
                return (InvokeBehavior(S+'fail',c.source_id,c.player_id),)
        return ()
    scripts={
        'fail':fail,'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'steal':lambda c:(ChangeControl(c.target_id,2),),
        'transform':lambda c:(Transform(c.target_id,FILLER),),
        'sweep':lambda c:(DestroyBatch(tuple(i for p in c.state.players.values()for i in p.board
            if c.state.entities[i].kind==CardType.MINION),c.source_id),),
        'fill':lambda c:tuple(AddToHand(c.player_id,FILLER,c.source_id)for _ in range(12)),
        'create':lambda c:(AddToHand(c.player_id,FILLER,c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior(S+name,body)
        r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name,
            requires_target=name in ('trigger','steal','transform')))
    r.register_card(CardDefinition(IMMUNE,'Diagnostic immune hero provider',CardType.MINION,health=5,
        keyword_auras=(KeywordAuraSpec(Keyword.IMMUNE),)))
    r.register_card(CardDefinition(CREATOR,'Diagnostic hand creator',CardType.MINION,health=1,deathrattle=S+'create'))
    r.register_behavior(S+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Diagnostic Old God observer',CardType.WEAPON,attack=0,durability=30,
        triggers=tuple(TriggerSpec(k,S+'observe')for k in ('minion_died','card_added_to_hand'))))
    r.validate();return replace(fmt,context=CTX)


class FrontierOldGodConditionTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand=(),*,board=(),deck=(),enemy=(),enemy_hand=(),enemy_deck=(FILLER,)*6,
            mode='normal',seed=1,weapon=None):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,max_mana=10,mana=10,
                hero_power_card_id='HERO_06bp',weapon_card_id=WATCH if mode!='normal'else weapon),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,max_mana=10,mana=10,armor=100)),
            seed=seed,generation_context=CTX),fmt.registry)

    def next_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def copies(self,g):return [g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==CORRUPTED]
    def cost(self,g,e):return quote_unselected_cost(g.state,g.registry,g.state.entities[e.id]).amount

    def test_full_roots_and_existing_corrupt_rows_four_primary_faces_are_preserved(self):
        data=load_batch();original={x['id']:x for x in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256']);rows={x['record']['id']:x['record']
            for key in ('cards','existing_dependencies')for x in data[key]}
        self.assertEqual(set(rows),{*ROOTS,*EXISTING})
        for cid,raw in rows.items():self.assertEqual(raw,original[cid])
        for face in data['official_faces']:batch.check_face(rows[face['card_id']],face['face'],face['locale'])
        r=fixture().registry
        self.assertEqual((r.card(MECHA).cost,r.card(MECHA).attack,r.card(MECHA).health),(10,10,10))
        self.assertIsNotNone(r.card(MECHA).deathrattle);self.assertIsNotNone(r.card(YSHAARJ).battlecry)
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_real_death_destroys_the_immune_armored_hero_without_any_damage(self):
        g=self.game((P+'kill',),board=(MECHA,),enemy=(IMMUNE,),weapon=WATCH)
        mecha=self.entity(g,MECHA,zone='board').id;hero=g.state.players[2].hero_id
        self.assertIn(Keyword.IMMUNE,g.state.entities[hero].aura_keywords)
        self.play(g,P+'kill',mecha)
        self.assertEqual((g.state.winner,g.state.entities[hero].health,g.state.entities[hero].armor),(1,30,100))
        self.assertFalse(g.state.damage_history)
        self.assertTrue(any(e.kind=='destroyed' and e.target_id==hero for e in g.events));self.portable(g)

    def test_each_real_own_zone_including_dormant_minion_and_location_prevents_win(self):
        for extra_hand,deck,board in (((FILLER,),(),()),((),(FILLER,),()),
                ((),(),(FILLER,)),((),(),('BT_004',)),((),(),('CORE_REV_990',))):
            with self.subTest(hand=extra_hand,deck=deck,board=board):
                g=self.game((P+'kill',)+extra_hand,board=(MECHA,)+board,deck=deck)
                self.play(g,P+'kill',self.entity(g,MECHA,zone='board').id)
                self.assertIsNone(g.state.winner);self.assertEqual(g.state.status,'playing')

    def test_active_deathrattle_counts_itself_and_silence_removes_natural_body(self):
        g=self.game((S+'trigger',),board=(MECHA,));mecha=self.entity(g,MECHA,zone='board').id
        self.play(g,S+'trigger',mecha);self.assertIsNone(g.state.winner)
        g=self.game((P+'quiet',P+'kill'),board=(MECHA,));mecha=self.entity(g,MECHA,zone='board').id
        self.play(g,P+'quiet',mecha);self.play(g,P+'kill',mecha);self.assertIsNone(g.state.winner)

    def test_whole_death_batch_clears_the_board_but_earlier_deathrattle_can_spoil_hand(self):
        g=self.game((S+'sweep',),board=(MECHA,FILLER));self.play(g,S+'sweep');self.assertEqual(g.state.winner,1)
        g=self.game((S+'sweep',),board=(CREATOR,MECHA));self.play(g,S+'sweep')
        self.assertIsNone(g.state.winner);self.assertEqual(self.entity(g,FILLER).card_id,FILLER)

    def test_last_controller_not_printed_owner_gets_the_deathrattle_condition(self):
        g=self.game((S+'steal',P+'kill'),board=(MECHA,),enemy_deck=())
        mecha=self.entity(g,MECHA,zone='board').id;self.play(g,S+'steal',mecha)
        self.play(g,P+'kill',mecha);self.assertEqual(g.state.winner,2)
        self.assertEqual((g.state.entities[mecha].owner,g.state.entities[mecha].controller),(1,2))

    def test_death_wait_restores_rolls_back_and_checks_the_new_hand_at_actual_body(self):
        g=self.game((P+'kill',),board=(MECHA,),mode='death_wait')
        self.play(g,P+'kill',self.entity(g,MECHA,zone='board').id);saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game,'spoil')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIsNone(g.state.winner)
        g=self.game((P+'kill',),board=(MECHA,),mode='death_wait')
        self.play(g,P+'kill',self.entity(g,MECHA,zone='board').id);self.choose(g);self.assertEqual(g.state.winner,1)

    def test_real_corrupt_transforms_after_first_yshaarj_then_played_copy_is_free(self):
        g=self.game((GRYPHON,YSHAARJ,YSHAARJ));first=self.play(g,YSHAARJ)
        self.assertEqual(len(self.copies(g)),1);self.assertEqual(self.cost(g,self.copies(g)[0]),5)
        self.next_turn(g);original=self.play(g,CORRUPTED);self.next_turn(g);second=self.play(g,YSHAARJ)
        copy,=self.copies(g);self.assertNotIn(copy.id,(original,first,second));self.assertEqual(self.cost(g,copy),0)
        source=self.play(g,CORRUPTED);self.assertEqual(g.state.play_history[-1].cost,0)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(8,8));self.portable(g)

    def test_each_same_name_occurrence_returns_separately_and_only_discount_expires(self):
        g=self.game((CORRUPTED,CORRUPTED,YSHAARJ));self.play(g,CORRUPTED);self.play(g,CORRUPTED)
        self.next_turn(g);self.play(g,YSHAARJ);copies=self.copies(g)
        self.assertEqual(len(copies),2);self.assertEqual([self.cost(g,e)for e in copies],[0,0])
        ids={e.id for e in copies};g.apply(EndTurn(1));self.assertEqual({e.id for e in self.copies(g)},ids)
        self.assertEqual([self.cost(g,e)for e in self.copies(g)],[5,5])

    def test_return_uses_original_played_face_even_after_body_transformation(self):
        g=self.game((CORRUPTED,S+'transform',YSHAARJ));source=self.play(g,CORRUPTED)
        self.play(g,S+'transform',source);self.next_turn(g);self.play(g,YSHAARJ)
        copy,=self.copies(g);self.assertEqual((copy.attack,copy.health),(8,8))
        self.assertEqual(g.state.entities[source].card_id,FILLER)

    def test_unplayed_corrupted_corrupt_base_name_only_blood_and_enemy_plays_do_not_qualify(self):
        g=self.game((GRYPHON,'TRL_541t',CORRUPTED,YSHAARJ));self.play(g,GRYPHON);self.play(g,'TRL_541t')
        original=self.copies(g)[0].id;self.next_turn(g);self.play(g,YSHAARJ)
        self.assertEqual([e.id for e in self.copies(g)],[original]);self.assertEqual(self.cost(g,self.copies(g)[0]),5)
        g=self.game((YSHAARJ,),enemy_hand=(CORRUPTED,));g.apply(EndTurn(1))
        self.play(g,CORRUPTED,player=2);g.apply(EndTurn(2));self.play(g,YSHAARJ);self.assertFalse(self.copies(g))

    def test_full_hand_burns_the_extra_original_occurrence_without_pruning(self):
        g=self.game((CORRUPTED,CORRUPTED,YSHAARJ,S+'fill'));self.play(g,CORRUPTED);self.play(g,CORRUPTED)
        self.next_turn(g);self.play(g,S+'fill');self.assertEqual(len(g.state.players[1].hand),10)
        source=self.play(g,YSHAARJ);self.assertEqual(len(self.copies(g)),1)
        created=[e for e in g.events if e.kind=='card_created' and e.source_id==source]
        self.assertEqual(len(created),2)
        self.assertEqual([g.state.entities[e.target_id].zone for e in created],[Zone.HAND,Zone.GRAVEYARD])

    def test_return_waits_restore_replay_and_failed_resume_without_duplicate_copies(self):
        g=self.game((CORRUPTED,CORRUPTED,YSHAARJ),mode='copy_wait')
        self.play(g,CORRUPTED);self.play(g,CORRUPTED);self.next_turn(g);self.play(g,YSHAARJ)
        self.assertEqual(len(self.copies(g)),1);saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):
            while game.state.pending_choice is not None:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.copies(g)),2)

    def test_second_return_failure_rolls_back_the_whole_payment_and_battlecry(self):
        g=self.game((CORRUPTED,CORRUPTED,YSHAARJ),mode='copy_fail')
        self.play(g,CORRUPTED);self.play(g,CORRUPTED);self.next_turn(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,YSHAARJ)
        self.assertEqual(g.snapshot(),saved)

    def test_both_roots_really_pass_frontier_discovery_and_one_mana_hand_play(self):
        r=fixture().registry;candidates=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual({x.card_id for x in candidates},set(ROOTS))
        for cid in ROOTS:
            seed=next(n for n in range(100)if cid in sample_candidates(Random(n),candidates,3,replacement=False))
            g=self.game(('GDB_857',),seed=seed);self.play(g,'GDB_857')
            self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid));source=self.play(g,cid)
            self.assertEqual((g.state.entities[source].card_id,g.state.play_history[-1].cost),(cid,1))


if __name__=='__main__':unittest.main()
