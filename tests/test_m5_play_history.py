"""Pre-play provenance, conditional targets, history and interrupted resolution."""
from dataclasses import FrozenInstanceError, replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PaymentType, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TargetMode, TargetSpec, TriggerSpec, UseHeroPower, UseHandAction, Zone, played_cards,
    preplay_conditions)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, Draw,
    GainArmor, GrantKeyword, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand,
    Summon, Transform)
from hs_sim.engine import CostSpec
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class PlayHistoryTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=2,health=8))
        self.spell('noop',lambda c:[])

    def spell(self,name,callback,**kwargs):
        self.r.register_behavior(name,callback)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kwargs))

    def game(self,hand=(),enemy_hand=(),board=(),enemy_board=(),deck=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=tuple(deck or ('plain',)*12),max_mana=10,mana=10,
                hero_power_card_id='HERO_01bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('plain',)*12,max_mana=10,mana=10)),seed=103),self.r)

    def entity(self,g,card,player=None):
        state=g.state;player=player or state.active_player
        return next(i for i in state.players[player].hand if state.entities[i].card_id==card)

    def play(self,g,card,target=None):
        g.apply(PlayCard(g.state.active_player,self.entity(g,card),target))

    def hero(self,g,player=2):return g.state.entities[g.state.players[player].hero_id]

    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_first_card_does_not_enable_its_own_combo(self):
        g=self.game(hand=('EX1_124',));self.play(g,'EX1_124',self.hero(g).id)
        self.assertEqual(self.hero(g).health,28);p=g.state.play_history[0]
        self.assertFalse(p.combo);self.assertTrue(p.completed);self.assertEqual(p.prior_game_plays,0);self.check(g)

    def test_coin_enables_combo_and_is_itself_recorded(self):
        g=self.game(hand=('GAME_005','EX1_124'));self.play(g,'GAME_005');self.play(g,'EX1_124',self.hero(g).id)
        self.assertEqual(self.hero(g).health,26);self.assertTrue(g.state.play_history[-1].combo)
        self.assertEqual([p.card_id for p in g.state.play_history],['GAME_005','EX1_124']);self.check(g)

    def test_hero_power_does_not_enable_combo(self):
        g=self.game(hand=('EX1_124',));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(len(g.state.play_history),0);self.play(g,'EX1_124',self.hero(g).id)
        self.assertEqual(self.hero(g).health,28)

    def test_summon_and_generate_do_not_create_extra_plays(self):
        self.spell('make',lambda c:[Summon(c.player_id,'plain'),AddToHand(c.player_id,'noop')])
        g=self.game(hand=('make',));self.play(g,'make')
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.observe(2)['players'][0]['cards_played_total'],1)

    def test_trade_and_forge_are_not_card_plays(self):
        g=self.game(hand=('SW_094','TTN_042'))
        for name,action in (('SW_094','trade'),('TTN_042','forge')):
            g.apply(UseHandAction(1,self.entity(g,name),action))
        self.assertFalse(g.state.play_history);self.check(g)

    def test_turn_count_resets_but_game_history_persists(self):
        g=self.game(hand=('noop','EX1_124'),enemy_hand=('noop',));self.play(g,'noop');g.apply(EndTurn(1))
        self.play(g,'noop');g.apply(EndTurn(2));self.play(g,'EX1_124',self.hero(g).id)
        p=g.state.play_history[-1];self.assertFalse(p.combo);self.assertEqual(p.prior_game_plays,1)
        self.assertEqual(len(played_cards(g.state,1)),2);self.assertEqual(len(played_cards(g.state,2)),1);self.check(g)

    def test_countered_spell_counts_for_later_combo(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('noop','EX1_124'));self.play(g,'EX1_287');g.apply(EndTurn(1))
        self.play(g,'noop');self.play(g,'EX1_124',self.hero(g,1).id)
        p=g.state.play_history[1];self.assertTrue(p.countered and p.completed);self.assertTrue(g.state.play_history[-1].combo)
        self.assertEqual(self.hero(g,1).health,26);self.check(g)

    def test_countered_outcast_keeps_position_but_does_not_draw(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('BT_491','plain'));self.play(g,'EX1_287');g.apply(EndTurn(1))
        before=len(g.state.players[2].deck);self.play(g,'BT_491')
        self.assertEqual(len(g.state.players[2].deck),before);p=g.state.play_history[-1]
        self.assertTrue(p.outcast and p.countered and p.completed)

    def test_edwin_counts_prior_plays_not_current_play(self):
        g=self.game(hand=('noop','noop','EX1_613'));self.play(g,'noop');self.play(g,'noop');source=self.entity(g,'EX1_613');self.play(g,'EX1_613')
        e=g.state.entities[source];self.assertEqual((e.attack,e.health),(6,6));self.check(g)

    def test_si7_without_combo_has_no_target(self):
        g=self.game(hand=('EX1_134',));source=self.entity(g,'EX1_134')
        self.assertFalse(g.legal_targets(source))
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,self.hero(g).id))
        self.play(g,'EX1_134');self.assertEqual(self.hero(g).health,30)

    def test_si7_combo_requires_target_and_uses_pinned_three_damage(self):
        g=self.game(hand=('noop','EX1_134'));self.play(g,'noop');source=self.entity(g,'EX1_134')
        self.assertIn(self.hero(g).id,g.legal_targets(source))
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source))
        self.play(g,'EX1_134',self.hero(g).id);self.assertEqual(self.hero(g).health,27);self.check(g)

    def test_conditional_targets_match_player_command_enumeration(self):
        g=self.game(hand=('noop','EX1_134'));port=g.for_player(1)
        def options():
            listing=port.legal_actions();ref=next(c['ref'] for c in listing['observation']['players'][0]['hand'] if c['card_id']=='EX1_134')
            return listing,[a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref]
        _,actions=options();self.assertTrue(all(a['target'] is None for a in actions))
        self.play(g,'noop');listing,actions=options();self.assertTrue(all(a['target'] is not None for a in actions))
        self.assertTrue(port.submit({'revision':listing['revision'],'action':actions[0]})['accepted']);self.check(g)

    def test_conditional_minion_without_available_target_still_plays(self):
        self.r.register_behavior('conditional',lambda c:[])
        self.r.register_card(CardDefinition('conditional','Conditional',CardType.MINION,health=1,keywords=(Keyword.COMBO,),
            on_play='conditional',target_condition='combo',targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
        g=self.game(hand=('noop','conditional'));self.play(g,'noop');self.play(g,'conditional');self.check(g)

    def test_runner_draws_from_left_or_right_or_only_slot(self):
        for hand in (('BT_480',),('BT_480','plain'),('plain','BT_480')):
            with self.subTest(hand=hand):
                g=self.game(hand=hand);before=len(g.state.players[1].deck);self.play(g,'BT_480')
                self.assertEqual(len(g.state.players[1].deck),before-1);self.assertTrue(g.state.play_history[-1].outcast)

    def test_middle_runner_does_not_draw(self):
        g=self.game(hand=('plain','BT_480','plain'));self.play(g,'BT_480')
        self.assertEqual(len(g.state.players[1].deck),12);p=g.state.play_history[0]
        self.assertEqual((p.hand_index,p.hand_size),(1,3));self.assertFalse(p.outcast);self.check(g)

    def test_spectral_sight_normal_and_outcast_draw_counts(self):
        for hand,count in ((('plain','BT_491','plain'),1),(('BT_491','plain'),2)):
            g=self.game(hand=hand);self.play(g,'BT_491');self.assertEqual(len(g.state.players[1].deck),12-count);self.check(g)

    def test_consume_magic_silences_and_outcast_draws(self):
        g=self.game(hand=('BT_490',),enemy_board=('CS2_179',));target=g.state.players[2].board[0]
        self.play(g,'BT_490',target);self.assertTrue(g.state.entities[target].silenced)
        self.assertEqual(len(g.state.players[1].deck),11);self.check(g)

    def test_outcast_does_not_override_base_target_requirement(self):
        g=self.game(hand=('BT_490',))
        with self.assertRaises(IllegalAction):self.play(g,'BT_490')
        self.assertFalse(g.state.play_history)

    def test_outcast_is_frozen_before_committed_trigger_draws(self):
        self.r.register_behavior('draw',lambda c:[Draw(c.player_id)] if c.event.player_id==c.player_id else [])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=2,triggers=(TriggerSpec('card_committed','draw'),)))
        g=self.game(hand=('plain','BT_491'),board=('watcher',));self.play(g,'BT_491')
        self.assertEqual(len(g.state.players[1].deck),9);self.assertTrue(g.state.play_history[0].outcast)

    def test_middle_outcast_does_not_become_active_after_hand_changes(self):
        from hs_sim.engine.zones import DiscardCard, CardReference
        self.r.register_behavior('discard',lambda c:[DiscardCard(CardReference.capture(c.state.entities[c.state.players[c.player_id].hand[-1]]))])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=2,triggers=(TriggerSpec('card_committed','discard'),)))
        g=self.game(hand=('plain','BT_491','plain'),board=('watcher',));self.play(g,'BT_491')
        self.assertEqual(len(g.state.players[1].deck),11);self.assertFalse(g.state.play_history[0].outcast)

    def test_record_cost_captures_quote_before_discount_consumption(self):
        self.spell('discount',lambda c:[ModifyCost(c.state.players[c.player_id].hand[0],CostSpec(delta=-1))])
        g=self.game(hand=('discount','EX1_124'));self.play(g,'discount');self.play(g,'EX1_124',self.hero(g).id)
        self.assertEqual(g.state.play_history[-1].cost,1);self.assertEqual(g.state.play_history[-1].payment,PaymentType.MANA);self.check(g)

    def test_record_keeps_alternative_payment_type(self):
        self.spell('health_cost',lambda c:[ModifyCost(c.state.players[c.player_id].hand[0],CostSpec(payment=PaymentType.HEALTH))])
        g=self.game(hand=('health_cost','EX1_124'));self.play(g,'health_cost');self.play(g,'EX1_124',self.hero(g).id)
        p=g.state.play_history[-1];self.assertEqual((p.cost,p.payment),(2,PaymentType.HEALTH));self.check(g)

    def test_record_keeps_original_target_after_spellbender(self):
        g=self.game(hand=('tt_010',),enemy_hand=('EX1_124',),board=('plain',));target=g.state.players[1].board[0]
        self.play(g,'tt_010');g.apply(EndTurn(1));self.play(g,'EX1_124',target)
        self.assertEqual(g.state.play_history[-1].target_id,target);self.assertEqual(g.state.entities[target].health,8);self.check(g)

    def test_history_survives_source_transform_and_death(self):
        self.spell('change',lambda c:[Transform(c.state.players[c.player_id].board[0],'plain'),Destroy(c.state.players[c.player_id].board[0])])
        g=self.game(hand=('BT_480','change'));self.play(g,'BT_480');source=g.state.play_history[0].source_id;self.play(g,'change')
        self.assertEqual(g.state.entities[source].card_id,'plain');self.assertEqual(g.state.play_history[0].card_id,'BT_480');self.check(g)

    def test_same_entity_replayed_creates_distinct_records(self):
        self.spell('bounce',lambda c:[ReturnToHand(c.state.players[c.player_id].board[0])])
        g=self.game(hand=('BT_480','bounce'));self.play(g,'BT_480');self.play(g,'bounce');self.play(g,'BT_480')
        a,b=g.state.play_history[0],g.state.play_history[-1]
        self.assertEqual(a.source_id,b.source_id);self.assertNotEqual(a.id,b.id);self.assertEqual(b.prior_turn_plays,2);self.check(g)

    def test_history_filter_uses_frozen_kind_and_explicit_bounds(self):
        g=self.game(hand=('noop','BT_480','noop'));self.play(g,'noop');self.play(g,'BT_480');self.play(g,'noop')
        self.assertEqual([p.id for p in played_cards(g.state,1,kind=CardType.SPELL,before_id=3,completed=True)],[1])
        for kw in ({'turn':True},{'before_id':0},{'kind':'spell'},{'completed':1}):
            with self.assertRaises(ValueError):played_cards(g.state,1,**kw)

    def test_illegal_play_does_not_append_history(self):
        g=self.game(hand=('CS2_029',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'CS2_029')
        self.assertEqual(g.snapshot(),before)

    def test_exception_rolls_back_history_payment_and_observations(self):
        def fail(c):raise RuntimeError('failed')
        self.spell('fail',fail,cost=3);g=self.game(hand=('fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_lethal_play_retains_interrupted_record(self):
        self.spell('lethal',lambda c:[Damage(c.state.players[2].hero_id,99,c.source_id)])
        g=self.game(hand=('lethal',));self.play(g,'lethal');p=g.state.play_history[0]
        self.assertTrue(p.interrupted);self.assertFalse(p.completed);self.check(g)

    def test_trigger_context_sees_current_play_and_inclusive_counts(self):
        self.r.register_behavior('count',lambda c:[GainArmor(c.player_id,c.play.prior_turn_plays+1)] if c.event.player_id==c.player_id else [])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=2,triggers=(TriggerSpec('card_committed','count'),)))
        g=self.game(hand=('noop','noop'),board=('watcher',));self.play(g,'noop');self.play(g,'noop')
        self.assertEqual(self.hero(g,1).armor,3);self.check(g)

    def test_after_trigger_sees_completed_record_even_when_countered(self):
        self.r.register_behavior('after',lambda c:[GainArmor(c.player_id,2 if c.play.countered and c.play.completed else 1)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=2,triggers=(TriggerSpec('card_played','after'),)))
        g=self.game(hand=('EX1_287',),enemy_hand=('noop',),enemy_board=('watcher',));self.play(g,'EX1_287');g.apply(EndTurn(1));self.play(g,'noop')
        self.assertEqual(self.hero(g,2).armor,3)

    def test_history_record_is_frozen_and_context_state_detached(self):
        def read(c):
            self.assertIsNotNone(c.play)
            with self.assertRaises(FrozenInstanceError):c.play.card_id='bad'
            c.state.play_history.clear()
            return []
        self.spell('read',read);g=self.game(hand=('read',));self.play(g,'read')
        self.assertEqual(len(g.state.play_history),1);self.check(g)

    def test_choice_continuation_preserves_explicit_play_identity(self):
        self.r.register_behavior('resume',lambda c:[Draw(c.player_id,2 if c.play.outcast else 1)])
        self.spell('choice',lambda c:[RequestChoice(c.player_id,(ChoiceOption('go','Go',(
            InvokeBehavior('resume',c.source_id,c.player_id,play_id=c.play.id),)),),c.source_id)])
        g=self.game(hand=('plain','choice'));self.play(g,'choice');self.assertFalse(g.state.play_history[0].completed);self.check(g)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('go',)));self.assertTrue(g.state.play_history[0].completed)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.players[1].deck),10);self.check(g)

    def test_invalid_choice_preserves_committed_history(self):
        self.spell('choice',lambda c:[RequestChoice(c.player_id,(ChoiceOption('go','Go',()),),c.source_id)])
        g=self.game(hand=('choice',));self.play(g,'choice');before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),before)

    def test_wrong_play_reference_in_continuation_rolls_back(self):
        self.spell('wrong',lambda c:[InvokeBehavior('noop',c.source_id,c.player_id,play_id=9999)])
        g=self.game(hand=('wrong',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'wrong')
        self.assertEqual(g.snapshot(),before)

    def test_public_counts_do_not_reveal_secret_identity(self):
        games=[self.game(hand=(card,)) for card in ('EX1_287','EX1_289')]
        for g,card in zip(games,('EX1_287','EX1_289')):self.play(g,card)
        self.assertEqual(games[0].observe(2),games[1].observe(2));self.assertEqual(games[0].player_events(2),games[1].player_events(2))
        self.assertNotIn('play_history',json.dumps(games[0].observe(2)))

    def test_preplay_preview_requires_current_hand_entity(self):
        g=self.game(hand=('noop',));source=self.entity(g,'noop');self.assertTrue(preplay_conditions(g.state,g.state.entities[source])['outcast'])
        self.play(g,'noop')
        with self.assertRaises(ValueError):preplay_conditions(g.state,g.state.entities[source])

    def test_corrupt_history_with_recomputed_hash_is_rejected(self):
        g=self.game(hand=('noop',));self.play(g,'noop')
        for key,value in (('id',2),('card_id','missing'),('source_id',9999),('player_id',True),('hand_index',1),
                ('prior_turn_plays',1),('prior_game_plays',1),('turn',100),('action',99),('kind','minion'),('completed',False),('cost',-1)):
            with self.subTest(key=key):
                data=g.snapshot();data['state']['play_history'][0][key]=value
                data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_pending_history_requires_matching_finisher(self):
        self.spell('choice',lambda c:[RequestChoice(c.player_id,(ChoiceOption('go','Go',()),),c.source_id)])
        g=self.game(hand=('choice',));self.play(g,'choice');data=g.snapshot();data['state']['play_history'][0]['completed']=True
        data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_target_condition_registration_is_strict(self):
        for kwargs in ({'target_condition':'bad'}, {'target_condition':'combo','requires_target':True},
                {'target_condition':'outcast','keywords':(Keyword.OUTCAST,)}):
            with self.assertRaises(ValueError):self.r.register_card(CardDefinition('invalid','Invalid',CardType.MINION,health=1,**kwargs))

    def test_granting_condition_keyword_without_behavior_is_rejected(self):
        self.spell('grant',lambda c:[GrantKeyword(c.state.players[c.player_id].board[0],Keyword.COMBO)])
        g=self.game(hand=('grant',),board=('plain',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'grant')
        self.assertEqual(g.snapshot(),before)

    def test_old_snapshot_schema_is_rejected(self):
        g=self.game();data=g.snapshot();self.assertEqual(data['schema_version'],266);data['schema_version']=26
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_real_player_example_restores_and_replays(self):
        from examples.play_conditions import run
        game,snapshot=run()
        self.assertEqual(len(game.history),5);self.assertEqual(len(game.state.play_history),5)
        self.assertEqual(snapshot['schema_version'],266)


if __name__=='__main__':unittest.main()
