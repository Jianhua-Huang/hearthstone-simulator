"""Whole K06 card behaviors over real private zones and original health outcomes."""
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.zone_cards import load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TriggerSpec,UseLocation)
from hs_sim.engine.effects import Buff,ChoiceOption,Damage,Destroy,RequestChoice,ReturnToHand
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.model import CardClass,CardMetadata,Resource,SpellSchool,Zone
from hs_sim.engine.replay import build_replay,replay


def registry(wait=False):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('dragon',))
    r.register_card(CardDefinition('k06.small','Small dragon',CardType.MINION,attack=1,health=1,metadata=meta))
    r.register_card(CardDefinition('k06.fel','Fel',CardType.SPELL,spell_school=SpellSchool.FEL))
    for name,body in {'kill':lambda c:(Destroy(c.target_id,c.source_id),),
                      'buff':lambda c:(Buff(c.target_id,1,1,c.source_id),),
                      'wound':lambda c:(Damage(c.target_id,1,c.source_id),)}.items():
        r.register_behavior('k06.'+name,body)
        r.register_card(CardDefinition('k06.'+name,name,CardType.MINION if name=='kill' else CardType.SPELL,
            health=1 if name=='kill' else 0,metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=()),
            battlecry='k06.'+name if name=='kill' else None,on_play=None if name=='kill' else 'k06.'+name,
            requires_target=True))
    if wait:
        def watch(c):
            if c.state.entities[c.event.source_id].card_id!='CORE_EX1_391':return ()
            return (RequestChoice(1,(ChoiceOption('return','Return survivor',(
                ReturnToHand(c.event.target_id),)),),c.source_id),)
        r.register_behavior('k06.watch',watch)
        r.register_card(CardDefinition('k06.watch','Observer',CardType.MINION,health=5,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=()),
            triggers=(TriggerSpec('damage_dealt','k06.watch'),)))
    return r


class ConstructedZoneCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry();cls.batch=load_batch()
    def game(self,hand=(),board=(),enemy=(),deck=('CORE_CS2_182',)*5,
             enemy_hand=(),enemy_deck=(),corpses=0,custom=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('test.hero',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30,corpses=corpses),
            PlayerSetup('test.hero',hand=enemy_hand,board=enemy,deck=enemy_deck),),seed=31),custom or self.registry)
    def card(self,g,cid):return next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.card(g,cid);g.apply(PlayCard(1,eid,target_id=target));return eid
    def names(self,g,zone='hand',player=1):return [g.state.entities[e].card_id for e in getattr(g.state.players[player],zone)]
    def portable(self,g,wait=False):
        for other in (g.clone(),Game.from_snapshot(g.snapshot(),registry(wait)),replay(build_replay(g),registry(wait))):
            self.assertEqual(other.snapshot(),g.snapshot())

    def test_all_19_roots_pay_and_run_complete_bodies_and_required_triggers(self):
        self.assertEqual(len(self.batch['cards']),19)
        for row in self.batch['cards']:
            cid=row['record']['id'];spec=row['recipe']
            with self.subTest(card=cid):
                g=self.game((cid,'k06.fel','CORE_EX1_043','k06.kill'),board=('CORE_CS2_182',),
                    enemy=('k06.small',),enemy_hand=('CORE_CS2_182',),enemy_deck=('CORE_CS2_182',)*6,corpses=4)
                eid=self.card(g,cid);action=next(a for a in g.legal_actions() if isinstance(a,PlayCard) and a.entity_id==eid)
                g.apply(action);self.assertEqual(g.state.play_history[-1].mana_after,30-row['record']['cost'])
                if spec['entry']=='deathrattle':self.play(g,'k06.kill',eid)
                elif spec['trigger']=='own_turn_end':g.apply(EndTurn(1))
                elif spec['trigger']=='self_attack':g.apply(Attack(1,eid,g.state.players[2].board[0]))
                elif spec['entry']=='on_use':
                    use=next(a for a in g.legal_actions() if isinstance(a,UseLocation) and a.entity_id==eid);g.apply(use)
                if spec['deathrattle'] is not None:
                    # Native weapon loss through the ordinary final two attacks.
                    g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
                    g.apply(EndTurn(1));g.apply(EndTurn(2))
                    g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))

    def test_enemy_deck_copy_leaves_original_and_never_requests_a_choice(self):
        g=self.game(('CORE_EX1_193',),enemy_deck=('CORE_CS2_182',));original=g.state.players[2].deck[0]
        self.play(g,'CORE_EX1_193');copy=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual(copy.origin_entity_id,original);self.assertNotEqual(copy.id,original)
        self.assertEqual(g.state.players[2].deck,[original]);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_cloud_serpent_is_automatic_and_does_not_copy_unrelated_cards(self):
        g=self.game(('TLC_888','CORE_CS2_182','CORE_EX1_043'))
        self.play(g,'TLC_888');self.assertEqual(self.names(g).count('CORE_EX1_043'),2)
        self.assertEqual(self.names(g).count('CORE_CS2_182'),1);self.assertIsNone(g.state.pending_choice)

    def test_selected_fel_copy_rejects_other_school_enemy_and_self_before_payment(self):
        g=self.game(('CATA_697','k06.fel','CORE_CS2_029'),enemy_hand=('k06.fel',))
        source=self.card(g,'CATA_697');before=g.snapshot()
        for target in (self.card(g,'CORE_CS2_029'),source,g.state.players[2].hand[0]):
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,target_id=target))
            self.assertEqual(g.snapshot(),before)
        target=self.card(g,'k06.fel');self.play(g,'CATA_697',target)
        self.assertEqual(self.names(g),['k06.fel','CORE_CS2_029','k06.fel']);self.portable(g)

    def test_hand_shuffle_moves_original_then_draws_and_self_is_not_a_target(self):
        g=self.game(('CATA_721','CORE_EX1_043'),deck=('CORE_CS2_182',));source=self.card(g,'CATA_721')
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,target_id=source))
        target=self.card(g,'CORE_EX1_043');self.play(g,'CATA_721',target)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertIn(target,g.state.players[1].deck+g.state.players[1].hand);self.portable(g)

    def test_no_other_hand_target_minion_can_still_draw(self):
        g=self.game(('CATA_721',));self.play(g,'CATA_721')
        self.assertEqual(self.names(g),['CORE_CS2_182'])

    def test_weapon_shuffles_actual_leftmost_and_real_deathrattle_draws_two(self):
        g=self.game(('CORE_EX1_043','DINO_408','CORE_CS2_182'),deck=('CORE_CS2_182',)*3)
        target=self.card(g,'CORE_EX1_043');eid=self.play(g,'DINO_408')
        self.assertNotIn(target,g.state.players[1].hand);self.assertIn(target,g.state.players[1].deck)
        for turn in range(2):
            g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
            if turn==0:g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.draw_history),4);self.portable(g)

    def test_corpse_end_copy_spends_only_if_available_and_new_copy_does_not_repeat_body(self):
        for corpses,count in [(3,1),(4,2)]:
            g=self.game(('CORE_RLK_745',),corpses=corpses);self.play(g,'CORE_RLK_745');g.apply(EndTurn(1))
            self.assertEqual(self.names(g,'board').count('CORE_RLK_745'),count)
            self.assertEqual(g.state.players[1].resources[Resource.CORPSES],corpses-(4 if count==2 else 0));self.portable(g)

    def test_coil_draws_only_on_its_original_minion_kill(self):
        for cid,draw in [('k06.small',1),('CORE_CS2_182',0)]:
            g=self.game(('CORE_EX1_302',),enemy=(cid,));self.play(g,'CORE_EX1_302',g.state.players[2].board[0])
            self.assertEqual(len(g.state.draw_history),draw)

    def test_slam_draws_for_survivor_including_prevented_damage_not_lethal(self):
        for cid,draw in [('k06.small',0),('CORE_CS2_182',1),('CORE_EX1_008',1)]:
            g=self.game(('CORE_EX1_391',),enemy=(cid,));self.play(g,'CORE_EX1_391',g.state.players[2].board[0])
            self.assertEqual(len(g.state.draw_history),draw)

    def test_pupil_summons_new_printed_copy_without_repeating_battlecry(self):
        g=self.game(('CORE_SCH_512',),enemy=('CORE_RLK_062',));target=g.state.players[2].board[0]
        self.play(g,'CORE_SCH_512',target);self.assertEqual(self.names(g,'board'),['CORE_RLK_062'])
        clone=g.state.entities[g.state.players[1].board[0]];self.assertNotEqual(clone.id,target)
        self.assertEqual((clone.attack,clone.health),(1,3));self.assertEqual(len(g.state.battlecry_history),0)

    def test_original_health_outcome_survives_waiting_and_target_departure(self):
        g=self.game(('CORE_EX1_391',),board=('k06.watch',),enemy=('CORE_CS2_182',),custom=registry(True))
        self.play(g,'CORE_EX1_391',g.state.players[2].board[0]);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g,True);p=g.state.pending_choice;g.apply(SelectChoice(1,p.id,('return',)))
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(self.names(g,'hand',2),['CORE_CS2_182']);self.portable(g,True)

    def test_top_three_minion_buff_does_not_reorder_deck_or_touch_spells(self):
        deck=('CORE_CS2_029','CORE_CS2_182','CORE_CS2_182','CORE_CS2_029','CORE_CS2_182','CORE_CS2_182')
        g=self.game(('EDR_230',),deck=deck);ids=list(g.state.players[1].deck);self.play(g,'EDR_230')
        self.assertEqual(g.state.players[1].deck,ids)
        self.assertEqual([g.state.entities[e].attack for e in ids if g.state.entities[e].kind==CardType.MINION],[8,8,8,4])

    def test_all_stored_minion_deathrattle_buffs_hand_and_deck_without_buffing_board(self):
        g=self.game(('DINO_421','CORE_CS2_182','k06.kill'),board=('CORE_CS2_182',),deck=('CORE_CS2_182','CORE_CS2_029'))
        eid=self.play(g,'DINO_421');self.play(g,'k06.kill',eid)
        self.assertEqual(g.state.entities[self.card(g,'CORE_CS2_182')].attack,7)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].attack,7)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,4)

    def test_current_attack_threshold_copy_checks_after_buffs(self):
        for buffed,count in [(False,1),(True,2)]:
            r=self.registry
            g=self.game(('EDR_481',),custom=r)
            if buffed:
                # A real stored-card buff from an existing card body.
                g=self.game(('CORE_CFM_753','EDR_481'));self.play(g,'CORE_CFM_753')
            self.play(g,'EDR_481');self.assertEqual(self.names(g,'board').count('EDR_481'),count)

    def test_kindred_all_race_uses_previous_owner_turn_not_current_play(self):
        g=self.game(('k06.small','DINO_435'),deck=())
        self.play(g,'k06.small');g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'DINO_435')
        self.assertEqual(self.names(g,'board').count('DINO_435'),2)
        g=self.game(('DINO_435',),deck=());self.play(g,'DINO_435')
        self.assertEqual(self.names(g,'board'),['DINO_435'])

    def test_selected_discard_is_not_board_death_or_source_self(self):
        g=self.game(('CATA_490','CORE_CS2_182'));source=self.card(g,'CATA_490')
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,target_id=source))
        target=self.card(g,'CORE_CS2_182');self.play(g,'CATA_490',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.death_history),0);self.assertEqual(len(g.state.discard_history),1)

    def test_location_targets_own_minion_hand_and_consumes_original_use(self):
        g=self.game(('CATA_477','CORE_CS2_182'));eid=self.play(g,'CATA_477');target=self.card(g,'CORE_CS2_182')
        g.apply(UseLocation(1,eid,target));e=g.state.entities[target]
        self.assertEqual((e.attack,e.health),(6,7));self.assertEqual(g.state.entities[eid].durability,1);self.portable(g)

    def test_self_attack_only_buffs_stored_minions(self):
        g=self.game(('CS3_025','CORE_CS2_182','CORE_CS2_029'),enemy=('k06.small',))
        eid=self.play(g,'CS3_025');g.apply(Attack(1,eid,g.state.players[2].board[0]))
        self.assertEqual(g.state.entities[self.card(g,'CORE_CS2_182')].attack,5)
        self.assertEqual(g.state.entities[self.card(g,'CORE_CS2_029')].kind,CardType.SPELL)

    def test_remove_and_empty_deck_destroy_have_distinct_original_lifecycles(self):
        g=self.game(('CORE_ICC_407',),enemy_deck=('CORE_CS2_182','CORE_CS2_029'));top=g.state.players[2].deck[0]
        self.play(g,'CORE_ICC_407');self.assertEqual(g.state.entities[top].zone,Zone.SETASIDE)
        self.assertEqual(len([e for e in g.events if e.kind=='card_destroyed_in_deck']),0)
        g=self.game(('END_035',),deck=(),enemy_deck=('CORE_CS2_182',)*6)
        self.play(g,'END_035');self.assertEqual(len(g.state.players[2].deck),1)
