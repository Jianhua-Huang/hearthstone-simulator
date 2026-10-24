"""Real reported tech faces, without asserting a complete Mimiron offer pool."""
import json
import unittest
from dataclasses import replace
from functools import lru_cache

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.mimiron_reported_tech_cards import (BOUNTY,GLUTTON,RENOVATOR,STARFISH,
    TECH,HORROR,DRAGON,CARDS,load_batch,register_mimiron_reported_tech_cards)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Game,Registry,CardDefinition,CardMetadata,CardClass,Rarity,CardType,
    PlayerSetup,Scenario,Keyword,TriggerSpec,TargetSpec,TargetMode,IllegalAction,ResolutionError)
from hs_sim.engine.actions import PlayCard,UseHeroPower,UseHandAction,EndTurn
from hs_sim.engine.effects import (Buff,Freeze,Silence,Transform,Destroy,ReturnToHand,
    ChoiceOption,RequestChoice,InvokeBehavior)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.sacrifice import MinionReference,DestroyForBuff
from tools import card_batch as batch

P='k503.'
HERO,POWER,UNIT,BIG,LEGEND,BEAST,ALL,DORM,LOCATION,WATCH=(P+s for s in
    ('hero','power','unit','big','legend','beast','all','dormant','location','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_mimiron_reported_tech_cards(r)
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=1000,metadata=META))
    def prepare(c):
        if mode=='up':return (Buff(c.target_id,3,source_id=c.source_id),)
        if mode=='down':return (Buff(c.target_id,-3,source_id=c.source_id),)
        if mode=='freeze':return (Freeze(c.target_id,c.source_id),)
        if mode=='silence':return (Silence(c.target_id),)
        if mode=='return':return (ReturnToHand(c.target_id),)
        if mode=='transform':return (Transform(c.target_id,LEGEND),)
        if mode=='indirect':return (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),)
        return ()
    r.register_behavior(P+'prepare',prepare)
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'prepare',metadata=META,
        targeting=TargetSpec(TargetMode.REQUIRED,kinds=(CardType.MINION,),relation='any')))
    for cid,attack,health,metadata in (
            (UNIT,1,3,META),(BIG,5,5,META),(LEGEND,4,5,replace(META,rarity=Rarity.LEGENDARY)),
            (BEAST,1,3,replace(META,tribes=('beast',))),(ALL,1,3,replace(META,tribes=('all',)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,metadata=metadata))
    r.register_card(CardDefinition(DORM,DORM,CardType.MINION,attack=1,health=3,dormant_turns=2,metadata=META))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=P+'noop',metadata=META))
    def fail(c):raise RuntimeError('k503-late-callback-failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if c.event.kind=='battlecry_started' and source is not None and source.card_id==GLUTTON and mode=='before_body':
            return (Destroy(source.id,c.source_id),)
        if c.event.kind=='destroyed' and c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==BEAST:
            if mode=='leave_reward':
                crab=next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==GLUTTON)
                return (ReturnToHand(crab.id),)
            if mode=='reward_wait':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),source_id=c.source_id),)
        if c.event.kind=='minion_summoned' and source is not None and source.card_id==STARFISH and mode=='source_buff':
            return (Buff(source.id,5,5,c.source_id),)
        if c.event.kind=='battlecry_finished' and source is not None and source.card_id in CARDS:
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode in ('wait','fail_choice'):
                return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),source_id=c.source_id,
                    on_select=P+'fail' if mode=='fail_choice' else None),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,attack=3,health=8,metadata=META,
        triggers=tuple(TriggerSpec(event,P+'watch') for event in
            ('battlecry_started','destroyed','minion_summoned','battlecry_finished'))))
    return r


class ReportedTechTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)
    mode='normal'

    def game(self,card,mode='normal',player=1,own=(),enemy=(),deck=(UNIT,)*8):
        self.mode=mode
        if mode in ('before_body','leave_reward','reward_wait','source_buff','fail','wait','fail_choice'):
            own=(*own,WATCH)
        players=tuple(PlayerSetup(HERO,hero_power_card_id=POWER,board=own if p==player else enemy,
            hand=(card,) if p==player else (),deck=deck,mana=10,max_mana=10) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=503),fixture(mode))

    def power(self,g,target,player=1):
        g.apply(UseHeroPower(player,g.state.players[player].hero_power_id,target))

    def test_full_original_rows_primary_faces_and_pending_producer_are_distinct(self):
        data=load_batch();rows={v['record']['id']:v for section in ('cards','evidence_only') for v in data[section]}
        self.assertEqual((len(data['cards']),len(rows),len(data['official_observations'])),(7,10,20))
        for o in data['official_observations']:batch.check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        r=build_registry()
        for v in data['cards']:
            raw=v['record'];d=r.card(raw['id'])
            self.assertEqual((d.cost,d.attack,d.health,d.metadata),(raw['cost'],raw['attack'],raw['health'],metadata_from_record(raw)))
        for cid in ('BE_588','REV_378','AV_135'):
            with self.assertRaises(UnsupportedDefinitionError):r.card(cid)
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['mimiron_root_implemented'])

    def test_bounty_actual_enemy_legendary_destruction_and_single_payment_both_players(self):
        for p in (1,2):
            with self.subTest(player=p):
                g=self.game(BOUNTY,player=p,enemy=(LEGEND,UNIT))
                victim=self.entity(g,LEGEND,3-p,'board').id;other=self.entity(g,UNIT,3-p,'board').id
                self.play(g,BOUNTY,victim,p)
                self.assertNotIn(victim,g.state.players[3-p].board);self.assertIn(other,g.state.players[3-p].board)
                self.assertEqual(g.state.players[p].mana,7)

    def test_bounty_rejects_common_or_friendly_legendary_without_mutation(self):
        g=self.game(BOUNTY,own=(LEGEND,),enemy=(UNIT,));before=g.snapshot()
        for cid,p in ((LEGEND,1),(UNIT,2)):
            with self.assertRaises(IllegalAction):self.play(g,BOUNTY,self.entity(g,cid,p,'board').id)
            self.assertEqual(g.snapshot(),before)

    def test_bounty_uses_current_face_rarity_after_transform(self):
        g=self.game(BOUNTY,'transform',enemy=(UNIT,));victim=self.entity(g,UNIT,2,'board').id
        self.power(g,victim);self.play(g,BOUNTY,victim)
        self.assertNotIn(victim,g.state.players[2].board)

    def test_targeted_cards_without_eligible_target_still_play_and_pay(self):
        for card,cost in ((BOUNTY,3),(GLUTTON,3),(RENOVATOR,3),(TECH,5)):
            with self.subTest(card=card):
                g=self.game(card,enemy=(UNIT,));source=self.play(g,card)
                self.assertIn(source,g.state.players[1].board);self.assertEqual(g.state.players[1].mana,10-cost)

    def test_glutton_destroys_friendly_or_enemy_current_beast_and_buffs_original_source(self):
        for owner in (1,2):
            with self.subTest(victim_owner=owner):
                g=self.game(GLUTTON,own=(BEAST,) if owner==1 else (),enemy=(BEAST,) if owner==2 else ())
                victim=self.entity(g,BEAST,owner,'board').id;source=self.play(g,GLUTTON,victim)
                self.assertNotIn(victim,g.state.players[owner].board)
                self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,4))

    def test_glutton_all_tribes_recipient_is_a_real_beast_target(self):
        g=self.game(GLUTTON,enemy=(ALL,));victim=self.entity(g,ALL,2,'board').id
        self.play(g,GLUTTON,victim);self.assertNotIn(victim,g.state.players[2].board)

    def test_glutton_source_death_before_body_does_not_prevent_victim_destruction(self):
        g=self.game(GLUTTON,'before_body',enemy=(BEAST,));victim=self.entity(g,BEAST,2,'board').id
        source=self.play(g,GLUTTON,victim)
        self.assertNotIn(source,g.state.players[1].board);self.assertNotIn(victim,g.state.players[2].board)

    def test_glutton_original_beneficiary_does_not_follow_source_to_hand(self):
        g=self.game(GLUTTON,'leave_reward',enemy=(BEAST,));victim=self.entity(g,BEAST,2,'board').id
        source=self.play(g,GLUTTON,victim)
        self.assertIn(source,g.state.players[1].hand)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(2,3))

    def test_glutton_wait_restores_original_destruction_reward_once(self):
        g=self.game(GLUTTON,'reward_wait',enemy=(BEAST,));victim=self.entity(g,BEAST,2,'board').id
        source=self.play(g,GLUTTON,victim);self.assertIsNotNone(g.state.pending_choice)
        restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,4))

    def test_renovator_destroys_only_enemy_location_and_pays_three(self):
        g=self.game(RENOVATOR,own=(LOCATION,),enemy=(LOCATION,UNIT))
        friendly=self.entity(g,LOCATION,1,'board').id;enemy=self.entity(g,LOCATION,2,'board').id
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,RENOVATOR,friendly)
        self.assertEqual(g.snapshot(),before)
        self.play(g,RENOVATOR,enemy)
        self.assertNotIn(enemy,g.state.players[2].board);self.assertIn(friendly,g.state.players[1].board)
        self.assertEqual(g.state.players[1].mana,7)

    def test_renovator_keeps_real_trade_action_and_ordinary_draw(self):
        g=self.game(RENOVATOR);source=self.entity(g,RENOVATOR).id
        g.apply(UseHandAction(1,source,'trade'))
        self.assertIn(source,g.state.players[1].deck)
        self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,UNIT)

    def test_starfish_silences_both_boards_current_material_and_excludes_itself(self):
        g=self.game(STARFISH,'source_buff',own=(DRAGON,),enemy=(DRAGON,))
        source=self.play(g,STARFISH)
        for p in (1,2):self.assertTrue(self.entity(g,DRAGON,p,'board').silenced)
        self.assertFalse(g.state.entities[source].silenced)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(7,9))

    def test_starfish_does_not_touch_dormant_minion_or_location(self):
        g=self.game(STARFISH,enemy=(DORM,LOCATION,UNIT));self.play(g,STARFISH)
        self.assertFalse(self.entity(g,DORM,2,'board').silenced)
        self.assertEqual(self.entity(g,LOCATION,2,'board').durability,2)
        self.assertTrue(self.entity(g,UNIT,2,'board').silenced)

    def test_targeted_post_body_choice_restore_clone_and_replay(self):
        g=self.game(BOUNTY,'wait',enemy=(LEGEND,));self.play(g,BOUNTY,self.entity(g,LEGEND,2,'board').id)
        restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_tech_four_minion_target_and_public_player_submission(self):
        g=self.game(TECH,enemy=(UNIT,UNIT,UNIT,LEGEND));victim=self.entity(g,LEGEND,2,'board').id
        port=g.for_player(1);message=port.legal_actions()
        target=next(v['ref'] for p in message['observation']['players'] if p['id']==2 for v in p['board'] if v.get('card_id')==LEGEND)
        command=next(a for a in message['actions'] if a['type']=='play_card' and a.get('target')==target)
        result=port.submit(dict(revision=message['revision'],action=command));self.assertIsNone(result['error'])
        self.assertIn(victim,g.state.players[1].board);self.assertNotIn(victim,g.state.players[2].board)
        self.assertEqual(g.state.players[1].mana,5)

    def test_tech_counts_minions_not_location_slots(self):
        g=self.game(TECH,enemy=(UNIT,UNIT,UNIT,LOCATION));self.play(g,TECH)
        self.assertEqual(len(g.state.players[2].board),4)

    def test_tech_counts_dormant_minions_but_cannot_target_them(self):
        g=self.game(TECH,enemy=(UNIT,UNIT,UNIT,DORM));dorm=self.entity(g,DORM,2,'board').id
        with self.assertRaises(IllegalAction):self.play(g,TECH,dorm)
        victim=self.entity(g,UNIT,2,'board').id;self.play(g,TECH,victim)
        self.assertIn(victim,g.state.players[1].board)

    def test_tech_second_player_and_full_friendly_board_obey_original_control_capacity(self):
        g=self.game(TECH,player=2,own=(UNIT,)*6,enemy=(UNIT,)*4);victim=self.entity(g,UNIT,1,'board').id
        self.play(g,TECH,victim,2)
        self.assertEqual(len(g.state.players[2].board),7)
        self.assertNotIn(victim,g.state.players[2].board)
        self.assertEqual(g.state.players[2].mana,5)

    def test_horror_destroys_all_other_small_minions_both_sides(self):
        g=self.game(HORROR,own=(UNIT,BIG),enemy=(UNIT,BIG));source=self.play(g,HORROR)
        self.assertIn(source,g.state.players[1].board)
        for p in (1,2):
            self.assertFalse(any(g.state.entities[i].card_id==UNIT for i in g.state.players[p].board))
            self.assertTrue(any(g.state.entities[i].card_id==BIG for i in g.state.players[p].board))

    def test_horror_uses_current_attack_with_both_buff_and_reduction(self):
        for mode,cid,destroyed in (('up',UNIT,False),('down',BIG,True)):
            with self.subTest(mode=mode):
                g=self.game(HORROR,mode,enemy=(cid,));victim=self.entity(g,cid,2,'board').id
                self.power(g,victim);self.play(g,HORROR)
                self.assertEqual(victim not in g.state.players[2].board,destroyed)

    def test_horror_preserves_dormant_small_minion_and_locations(self):
        g=self.game(HORROR,enemy=(DORM,LOCATION));self.play(g,HORROR)
        self.assertEqual(len(g.state.players[2].board),2)

    def test_dragon_prevents_freeze_for_friendly_including_self_and_thaws_existing(self):
        g=self.game(DRAGON,'freeze',own=(UNIT,));friend=self.entity(g,UNIT,1,'board').id
        self.power(g,friend);self.assertTrue(g.state.entities[friend].frozen)
        source=self.play(g,DRAGON);self.assertFalse(g.state.entities[friend].frozen)
        self.assertIn(Keyword.CANT_BE_FROZEN,g.state.entities[source].keywords)
        g.apply(EndTurn(1));self.power(g,friend,2);self.assertFalse(g.state.entities[friend].frozen)

    def test_dragon_does_not_thaw_or_protect_enemy_minions(self):
        g=self.game(DRAGON,'freeze',enemy=(UNIT,));enemy=self.entity(g,UNIT,2,'board').id
        self.power(g,enemy);self.play(g,DRAGON)
        self.assertTrue(g.state.entities[enemy].frozen)

    def test_dragon_aura_retires_on_silence_or_source_return(self):
        for mode in ('silence','return'):
            with self.subTest(mode=mode):
                g=self.game(UNIT,mode,own=(DRAGON,UNIT));source=self.entity(g,DRAGON,1,'board').id
                friend=self.entity(g,UNIT,1,'board').id
                self.power(g,source);self.assertNotIn(Keyword.CANT_BE_FROZEN,g.state.entities[friend].keywords)

    def test_late_control_failure_rolls_back_payment_ownership_and_information(self):
        g=self.game(TECH,'fail',enemy=(UNIT,)*4);victim=self.entity(g,UNIT,2,'board').id;before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'k503-late-callback-failure'):self.play(g,TECH,victim)
        self.assertEqual(g.snapshot(),before)

    def test_failed_post_body_choice_keeps_original_paid_wait(self):
        g=self.game(BOUNTY,'fail_choice',enemy=(LEGEND,));self.play(g,BOUNTY,self.entity(g,LEGEND,2,'board').id);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'k503-late-callback-failure'):self.choose(g)
        self.assertEqual(g.snapshot(),before)

    def test_tech_indirect_battlecry_reuses_observation_condition_and_original_target_selector(self):
        g=self.game(UNIT,'indirect',own=(TECH,),enemy=(UNIT,)*4)
        source=self.entity(g,TECH,1,'board').id;self.power(g,source)
        self.assertEqual(len(g.state.players[2].board),3)
        self.assertEqual(g.state.battlecry_history[-1].origin,'effect')

    def test_independent_destruction_flag_rejects_non_boolean_declarations(self):
        victim=MinionReference(1,1,UNIT,0,1);beneficiary=MinionReference(2,1,GLUTTON,0,2)
        for value in (0,1,None,'false'):
            with self.assertRaises(ValueError):DestroyForBuff(victim,beneficiary,1,1,2,require_live_beneficiary=value)
