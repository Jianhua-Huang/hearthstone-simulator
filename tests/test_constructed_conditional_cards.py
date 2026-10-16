"""Actual K05 card bodies, fixed dependencies and private choice continuations."""
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.conditional_cards import load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Ruleset,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,FillBoardWithCopies,
    GainArmor,InvokeBehavior,RequestChoice,ReturnToHand)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,Zone
from hs_sim.engine.replay import build_replay,replay


def registry(wait=None):
    r=build_registry()
    r.register_behavior('k05.kill',lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_card(CardDefinition('k05.kill','Remove',CardType.SPELL,on_play='k05.kill',requires_target=True))
    r.register_card(CardDefinition('k05.zero_weapon','Zero',CardType.WEAPON,durability=2))
    if wait:
        def watch(c):
            cid=c.state.entities[c.event.source_id].card_id
            if cid not in ('DINO_402','CORE_BRM_013'):return ()
            effects=(ReturnToHand(c.event.target_id),) if wait=='return' else (AddToHand(c.player_id,'CORE_CS2_182',c.source_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue',effects),),c.source_id),)
        r.register_behavior('k05.watch',watch)
        r.register_card(CardDefinition('k05.watch','Observer',CardType.MINION,health=5,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=()),
            triggers=(TriggerSpec('stats_changed' if wait=='return' else 'damage_dealt','k05.watch'),)))
    return r


class ConstructedConditionalCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry();cls.batch=load_batch()

    def game(self,hand=(),board=(),enemy=(),deck=('CORE_CS2_182',)*12,weapon=None,custom=None,rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('test.hero',hand=hand,board=board,deck=deck,mana=30,max_mana=30,
                mana_cap=30,weapon_card_id=weapon),
            PlayerSetup('test.hero',board=enemy),),seed=41),custom or self.registry,ruleset=rules)

    def card(self,g,cid):return next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
    def play(self,g,cid,target=None,branch=None):
        eid=self.card(g,cid);g.apply(PlayCard(1,eid,target_id=target,branch_id=branch));return eid
    def names(self,g,zone='board',player=1):return [g.state.entities[e].card_id for e in getattr(g.state.players[player],zone)]
    def portable(self,g,custom=None):
        make=custom or registry
        for other in (g.clone(),Game.from_snapshot(g.snapshot(),make()),replay(build_replay(g),make())):
            self.assertEqual(other.snapshot(),g.snapshot())

    def test_all_33_roots_pay_and_execute_their_complete_entries(self):
        roots=[row for row in self.batch['cards'] if row['recipe']['root']]
        self.assertEqual(len(roots),33)
        for row in roots:
            cid=row['record']['id'];spec=row['recipe']
            branches=(None,) if spec['choices'] is None else ('first','second','both')
            for branch in branches:
                with self.subTest(card=cid,branch=branch):
                    g=self.game((cid,'JAIL_941t','CORE_EX1_043','CORE_CS2_029'),
                        board=('CORE_CS2_182',)+(('OG_044',) if branch=='both' else ()),
                        enemy=('CORE_CS2_182',),weapon='k05.zero_weapon')
                    if spec.get('target_condition')=='combo':self.play(g,'CORE_CS2_029',g.state.players[2].hero_id)
                    eid=self.card(g,cid)
                    action=next(a for a in g.legal_actions() if isinstance(a,PlayCard) and a.entity_id==eid and a.branch_id==branch)
                    mana=g.state.players[1].mana;g.apply(action)
                    while g.state.pending_choice:
                        p=g.state.pending_choice;g.apply(SelectChoice(p.player_id,p.id,(p.options[0].id,)))
                    self.assertEqual(g.state.play_history[-1].mana_before,mana)
                    self.assertEqual(g.state.play_history[-1].mana_after,mana-row['record']['cost'])
                    if spec['entry']=='deathrattle':
                        self.play(g,'k05.kill',eid) if 'k05.kill' in self.names(g,'hand') else self.kill_in_combat(g,eid)
                    elif spec.get('trigger')=='own_turn_end':g.apply(EndTurn(1))

    def kill_in_combat(self,g,eid):
        # A legitimate root corpse invokes its actual deathrattle once.
        g.apply(EndTurn(1));enemy=g.state.players[2].board[0]
        g.apply(Attack(2,enemy,eid))

    def test_poison_requires_own_weapon_and_exposes_no_target_prompt(self):
        g=self.game(('CORE_CS2_074',))
        with self.assertRaises(IllegalAction):self.play(g,'CORE_CS2_074')
        g=self.game(('CORE_CS2_074',),weapon='k05.zero_weapon');eid=self.card(g,'CORE_CS2_074')
        choices=[a for a in g.legal_actions() if isinstance(a,PlayCard) and a.entity_id==eid]
        self.assertEqual(len(choices),1);self.assertIsNone(choices[0].target_id)
        g.apply(choices[0]);self.assertEqual(g.state.entities[g.state.players[1].weapon_id].attack,2)

    def test_real_choose_one_branches_and_combined_wrath_have_correct_packets(self):
        for branch,damage,draw in [('first',3,0),('second',1,1),('both',4,1)]:
            with self.subTest(branch=branch):
                g=self.game(('CORE_EX1_154',),board=('OG_044',) if branch=='both' else (),enemy=('CORE_CS2_182',))
                target=g.state.players[2].board[0];before=len(g.state.players[1].hand)
                self.play(g,'CORE_EX1_154',target,branch)
                self.assertEqual(g.state.entities[target].damage,damage)
                self.assertEqual(len(g.state.players[1].hand),before-1+draw)
                packets=[e for e in g.events if e.kind=='damage_dealt' and e.target_id==target]
                self.assertEqual(len(packets),1)

    def test_no_target_summon_branch_and_full_board_failure_do_not_reselect(self):
        g=self.game(('CORE_AT_037',));self.play(g,'CORE_AT_037',branch='second')
        self.assertEqual(self.names(g),['AT_037t']*2)
        g=self.game(('CORE_TSC_650',),board=('CORE_CS2_182',)*6)
        self.play(g,'CORE_TSC_650',branch='second');self.assertEqual(len(g.state.players[1].board),7)
        e=g.state.entities[g.state.players[1].board[-1]];self.assertEqual(e.card_id,'TSC_650t4');self.assertIn(Keyword.RUSH,e.keywords)

    def test_combined_buffs_and_summon_use_execution_order(self):
        g=self.game(('CORE_EX1_160',),board=('OG_044','CORE_CS2_182'))
        self.play(g,'CORE_EX1_160',branch='both')
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].attack,3)
        self.assertEqual(g.state.entities[g.state.players[1].board[1]].attack,5)
        g=self.game(('EDR_257',),board=('OG_044',));eid=self.play(g,'EDR_257',branch='both')
        e=g.state.entities[eid];self.assertEqual((e.attack,e.health),(6,6))
        self.assertTrue({Keyword.TAUNT,Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL}<=e.keywords)

    def test_tracking_takes_one_actual_deck_entity_keeps_other_cards_and_hides_options(self):
        g=self.game(('CORE_DS1_184',),deck=('CORE_CS2_182','CORE_CS2_029','CORE_EX1_043','CORE_CS2_182'))
        originals=set(g.state.players[1].deck);self.play(g,'CORE_DS1_184')
        p=g.state.pending_choice;self.assertEqual(len(p.options),3)
        self.assertEqual(g.for_player(2).legal_actions()['observation']['pending_choice'],{'player_id':1})
        self.portable(g)
        g.apply(SelectChoice(1,p.id,(p.options[0].id,)))
        self.assertEqual(len(g.state.players[1].hand),1);chosen=g.state.players[1].hand[0]
        self.assertIn(chosen,originals);self.assertEqual(set(g.state.players[1].deck),originals-{chosen})
        self.assertEqual(len(g.state.draw_history),0);self.portable(g)

    def test_empty_tracking_does_not_create_choice_or_consume_rng(self):
        g=self.game(('CORE_DS1_184',),deck=());before=g.snapshot()['rng_state']
        self.play(g,'CORE_DS1_184');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_named_generation_has_full_secondary_spells_and_private_recipient(self):
        g=self.game(('CORE_UNG_809','CORE_EX1_014','CORE_SW_108'),enemy=('CORE_CS2_182',))
        self.play(g,'CORE_UNG_809');self.assertIn('UNG_809t1',self.names(g,'hand'))
        self.play(g,'CORE_EX1_014');self.assertEqual(self.names(g,'hand',2),['EX1_014t']*2)
        target=g.state.players[2].board[0];self.play(g,'CORE_SW_108',target)
        self.assertIn('SW_108t',self.names(g,'hand'));self.play(g,'SW_108t',target)
        self.assertEqual(g.state.entities[target].damage,4)

    def test_twilight_drake_counts_remaining_physical_hand(self):
        g=self.game(('CORE_EX1_043','CORE_CS2_182','CORE_CS2_182'))
        eid=self.play(g,'CORE_EX1_043');self.assertEqual(g.state.entities[eid].max_health,3)

    def test_hand_shadow_and_dragon_conditions_have_positive_and_negative_paths(self):
        for present in (False,True):
            with self.subTest(present=present):
                g=self.game(('CORE_RLK_814',)+(('JAIL_941t',) if present else ()))
                eid=self.play(g,'CORE_RLK_814');self.assertEqual(g.state.entities[eid].attack,2 if present else 1)
                g=self.game(('CATA_111','CORE_CS2_029')+(('CORE_EX1_043',) if present else ()))
                self.play(g,'CORE_CS2_029',g.state.players[2].hero_id);before=g.state.players[1].mana
                self.play(g,'CATA_111');self.assertEqual(g.state.players[1].mana,before-3+(2 if present else 0))

    def test_beast_axe_uses_live_board_tribes_not_hand(self):
        for on_board in (False,True):
            g=self.game(('CORE_TRL_111','CORE_EX1_014'),board=('CORE_EX1_014',) if on_board else ())
            eid=self.play(g,'CORE_TRL_111');self.assertEqual(g.state.entities[eid].durability,3 if on_board else 2)

    def test_conditional_battlecry_targets_vanish_without_weapon(self):
        g=self.game(('CS3_022',),enemy=('CORE_CS2_182',));eid=self.card(g,'CS3_022')
        actions=[a for a in g.legal_actions() if isinstance(a,PlayCard) and a.entity_id==eid]
        self.assertTrue(actions);self.assertTrue(all(a.target_id is None for a in actions))
        g.apply(actions[0]);self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage,0)

    def test_quick_shot_rechecks_hand_after_a_real_damage_choice(self):
        r=registry('add');g=self.game(('CORE_BRM_013',),board=('k05.watch',),enemy=('CORE_CS2_182',),custom=r)
        self.play(g,'CORE_BRM_013',g.state.players[2].board[0]);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g,lambda:registry('add'))
        before=len(g.state.players[1].deck);p=g.state.pending_choice;g.apply(SelectChoice(1,p.id,('continue',)))
        self.assertEqual(len(g.state.players[1].deck),before);self.assertEqual(self.names(g,'hand'),['CORE_CS2_182'])

    def test_copy_battlecry_does_not_recursively_invoke_new_battlecries(self):
        g=self.game(('CORE_RLK_062',));eid=self.play(g,'CORE_RLK_062')
        self.assertEqual(self.names(g),['CORE_RLK_062']*3)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.battlecry_history),1)
        self.assertEqual(len(set(g.state.players[1].board)),3)

    def test_reborn_expert_grants_once_or_copies_an_already_reborn_target(self):
        g=self.game(('CAP_804','CAP_804'),board=('CORE_CS2_182',));target=g.state.players[1].board[0]
        self.play(g,'CAP_804',target);self.assertIn(Keyword.REBORN,g.state.entities[target].keywords)
        self.play(g,'CAP_804',target);self.assertEqual(self.names(g).count('CORE_CS2_182'),2)

    def test_bat_mask_obeys_actual_board_capacity_and_copies_current_stats(self):
        for cap in (3,10):
            with self.subTest(cap=cap):
                g=self.game(('DINO_402',),board=('CORE_CS2_182',),rules=Ruleset(max_board=cap))
                self.play(g,'DINO_402',g.state.players[1].board[0]);self.assertEqual(len(g.state.players[1].board),cap)
                self.assertTrue(all((g.state.entities[e].attack,g.state.entities[e].health)==(1,1) for e in g.state.players[1].board))

    def test_queued_fill_instruction_restore_and_departed_target_are_safe(self):
        r=registry('return');g=self.game(('DINO_402',),board=('CORE_CS2_182','k05.watch'),custom=r)
        self.play(g,'DINO_402',g.state.players[1].board[0]);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g,lambda:registry('return'))
        p=g.state.pending_choice;g.apply(SelectChoice(1,p.id,('continue',)))
        self.assertEqual(self.names(g),['k05.watch']);self.assertEqual(self.names(g,'hand'),['CORE_CS2_182'])
        self.portable(g,lambda:registry('return'))

    def test_masks_set_stats_grant_keyword_and_keep_followup_draw(self):
        for cid,stats,keyword,draws in [('DINO_403',(8,8),Keyword.CHARGE,0),('DINO_432',(5,4),Keyword.STEALTH,2)]:
            g=self.game((cid,),board=('CORE_CS2_182',));target=g.state.players[1].board[0]
            self.play(g,cid,target);e=g.state.entities[target]
            self.assertEqual((e.attack,e.health),stats);self.assertIn(keyword,e.keywords)
            self.assertEqual(len(g.state.players[1].hand),draws)

    def test_keyword_choices_restore_and_granted_plant_deathrattle_executes(self):
        g=self.game(('TLC_245','k05.kill'));eid=self.play(g,'TLC_245');self.portable(g)
        p=g.state.pending_choice;g.apply(SelectChoice(1,p.id,('plants',)))
        self.play(g,'k05.kill',eid);self.assertEqual(self.names(g),['UNG_999t2t1']*2);self.portable(g)
        g=self.game(('TLC_242',));eid=self.play(g,'TLC_242');p=g.state.pending_choice
        g.apply(SelectChoice(1,p.id,('stats',)));self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(2,6))

    def test_named_raptors_shuffle_and_each_real_battlecry_draws_once(self):
        g=self.game(('TLC_826','UNG_920t2'));before=len(g.state.players[1].deck)
        self.play(g,'TLC_826');self.assertEqual(self.names(g,'deck').count('UNG_920t2'),10)
        self.assertEqual(len(g.state.players[1].deck),before+10)
        self.play(g,'UNG_920t2');self.assertEqual(len(g.state.players[1].deck),before+9);self.portable(g)

    def test_missile_dependency_uses_spell_bonus_once_over_whole_random_budget(self):
        g=self.game(('JAIL_312',),board=('EX1_012',));self.play(g,'JAIL_312')
        self.assertEqual(self.names(g,'hand'),['EX1_277']*3);self.play(g,'EX1_277')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26);self.portable(g)

    def test_spider_chain_has_all_three_spells_and_temporary_attack(self):
        g=self.game(('JAIL_436',));hero=g.state.players[1].hero_id
        for cid in ('JAIL_436','JAIL_436t','JAIL_436t2'):self.play(g,cid)
        self.assertEqual(g.state.entities[hero].attack,7);self.assertEqual(g.state.entities[hero].armor,7)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[hero].attack,0)

    def test_deathrattle_gifts_and_embrace_dependency_are_complete(self):
        g=self.game(('JAIL_447','k05.kill'));eid=self.play(g,'JAIL_447');self.play(g,'k05.kill',eid)
        self.assertEqual(self.names(g,'hand'),['JAIL_447t'])
        g=self.game(('JAIL_941',),enemy=('CORE_CS2_182',));self.play(g,'JAIL_941',g.state.players[1].hero_id)
        self.assertEqual(self.names(g,'hand'),['JAIL_941t']);self.play(g,'JAIL_941t',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)

