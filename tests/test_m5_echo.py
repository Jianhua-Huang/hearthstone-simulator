"""Printed Echo and reusable temporary-hand lifetimes; no new real cards."""
from hs_sim.engine.model import CostAuraSpec
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BuffStoredCard, CardDefinition, CardType, CostSpec, CreateTemporaryCard,
    EndTurn, Game, HandLifetime, HandRepeatSpec, Keyword, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, ShatterSpec, SnapshotError, SpellRepeatSpec,
    TriggerSpec, UpgradeHandCard, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Draw, GainArmor, InvokeBehavior,
    ModifyCost, RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,CopyCard,DiscardCard,MoveCard


class EchoTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.spell('plain',lambda c:[])
        self.spell('echo',lambda c:[GainArmor(c.player_id,1)],cost=2,
                   keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        self.r.register_card(CardDefinition('echo_minion','Echo minion',CardType.MINION,cost=2,attack=2,health=3,
            keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec()))

    def spell(self,name,fn,**kw):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kw))

    def game(self,hand=(),board=(),enemy_hand=(),enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=('plain',)*12,max_mana=10,mana=10),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=('plain',)*12,max_mana=10,mana=10)),seed=186),self.r)

    def cards(self,g,player=1):
        s=g.state;return [s.entities[i] for i in s.players[player].hand]
    def find(self,g,name,player=1):return next(e.id for e in self.cards(g,player) if e.card_id==name)
    def play(self,g,name,player=1,target=None,position=None):
        i=self.find(g,name,player);g.apply(PlayCard(player,i,target,position));return i
    def ref(self,c,name):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id==name))
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor

    def test_each_hand_play_creates_one_new_physical_copy(self):
        g=self.game(('echo',));original=self.find(g,'echo');self.play(g,'echo');first=self.find(g,'echo')
        self.play(g,'echo');second=self.find(g,'echo')
        self.assertEqual(len({original,first,second}),3)
        self.assertEqual((g.state.players[1].mana,self.armor(g)),(6,2))
        self.assertEqual(g.state.entities[second].hand_lifetime,HandLifetime(first,1,1,1));self.check(g)

    def test_unplayed_original_does_not_expire(self):
        g=self.game(('echo',));original=self.find(g,'echo');g.apply(EndTurn(1))
        self.assertEqual(self.find(g,'echo'),original);self.assertIsNone(g.state.entities[original].hand_lifetime);self.check(g)

    def test_unused_echo_expires_without_discard_or_death(self):
        g=self.game(('echo',));self.play(g,'echo');copy=self.find(g,'echo');g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[copy].zone,Zone.GRAVEYARD)
        self.assertIsNone(g.state.entities[copy].hand_lifetime)
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind=='card_discarded' for e in g.events))
        self.assertEqual(len([e for e in g.events if e.kind=='card_expired']),1);self.check(g)

    def test_played_minion_survives_deadline(self):
        g=self.game(('echo_minion',));self.play(g,'echo_minion');played=self.play(g,'echo_minion');g.apply(EndTurn(1))
        self.assertIn(played,g.state.players[1].board)
        self.assertIsNone(g.state.entities[played].hand_lifetime);self.check(g)

    def test_echo_copies_are_base_stats_and_cost(self):
        self.spell('buff',lambda c:[BuffStoredCard(self.ref(c,'echo_minion'),4,5),
                                   ModifyCost(self.ref(c,'echo_minion').entity_id,CostSpec(delta=-2))])
        g=self.game(('buff','echo_minion'));self.play(g,'buff');original=self.play(g,'echo_minion')
        source=g.state.entities[original];copy=g.state.entities[self.find(g,'echo_minion')]
        self.assertEqual((source.attack,source.health),(6,8));self.assertEqual((copy.attack,copy.health,copy.cost),(2,3,2))
        self.assertEqual(g.state.players[1].mana,10);self.check(g)

    def test_global_reduction_can_zero_original_but_not_echo_copy(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-9))])
        g=self.game(('discount','echo'));self.play(g,'discount')
        self.assertEqual(g.quote_cost(self.find(g,'echo')).amount,0);self.play(g,'echo')
        self.assertEqual(g.quote_cost(self.find(g,'echo')).amount,1);self.play(g,'echo')
        self.assertEqual(g.state.players[1].mana,9);self.check(g)

    def test_local_set_zero_cannot_bypass_copy_floor(self):
        self.spell('discount',lambda c:[ModifyCost(self.ref(c,'echo').entity_id,CostSpec(set_to=0))])
        g=self.game(('echo','discount'));self.play(g,'echo');self.play(g,'discount')
        self.assertEqual(g.quote_cost(self.find(g,'echo')).amount,1)
        self.assertEqual(g.state.entities[self.find(g,'echo')].cost,1);self.check(g)

    def test_floor_is_applied_after_modifiers_not_before_increases(self):
        self.spell('local',lambda c:[ModifyCost(self.ref(c,'echo').entity_id,CostSpec(set_to=0)),AddCostModifier(1,CostSpec(delta=2))])
        g=self.game(('echo','local'));self.play(g,'echo');self.play(g,'local')
        self.assertEqual(g.quote_cost(self.find(g,'echo')).amount,2);self.check(g)

    def test_non_keyword_repeat_can_have_zero_cost_copies(self):
        self.spell('repeat',lambda c:[],hand_repeat=HandRepeatSpec(echo=False))
        g=self.game(('repeat',));self.play(g,'repeat');self.play(g,'repeat')
        self.assertEqual(g.quote_cost(self.find(g,'repeat')).amount,0)
        g.apply(EndTurn(1));self.assertFalse(self.cards(g));self.check(g)

    def test_base_copy_of_temporary_card_is_permanent(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'echo'),1,mode='base')])
        g=self.game(('echo','copy'));self.play(g,'echo');self.play(g,'copy');g.apply(EndTurn(1))
        self.assertEqual(len(self.cards(g)),1);self.assertIsNone(self.cards(g)[0].hand_lifetime);self.check(g)

    def test_current_copy_preserves_deadline(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'echo'),1)])
        g=self.game(('echo','copy'));self.play(g,'echo');self.play(g,'copy')
        self.assertTrue(all(e.hand_lifetime.expires_turn==1 for e in self.cards(g)))
        g.apply(EndTurn(1));self.assertFalse(self.cards(g));self.check(g)

    def test_shuffle_preserves_marker_until_deadline_without_destroying_deck_card(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c,'echo'),1,Zone.DECK,position='bottom')])
        g=self.game(('echo','move'));self.play(g,'echo');copy=self.find(g,'echo');self.play(g,'move');g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[copy].zone,Zone.DECK);self.assertIsNone(g.state.entities[copy].hand_lifetime);self.check(g)

    def test_reset_discards_temporary_state(self):
        self.spell('reset',lambda c:[MoveCard(self.ref(c,'echo'),1,Zone.DECK,position='top',reset=True),Draw(1)])
        g=self.game(('echo','reset'));self.play(g,'echo');self.play(g,'reset');g.apply(EndTurn(1))
        self.assertEqual(len(self.cards(g)),1);self.assertIsNone(self.cards(g)[0].hand_lifetime);self.check(g)

    def test_bounced_played_echo_copy_is_permanent_base(self):
        self.spell('bounce',lambda c:[ReturnToHand(c.state.players[1].board[-1])])
        g=self.game(('echo_minion','bounce'));self.play(g,'echo_minion');played=self.play(g,'echo_minion');self.play(g,'bounce')
        self.assertIsNone(g.state.entities[played].hand_lifetime);g.apply(EndTurn(1))
        self.assertIn(played,g.state.players[1].hand);self.check(g)

    def test_hand_upgrade_preserves_deadline(self):
        self.spell('upgrade',lambda c:[UpgradeHandCard(self.ref(c,'echo'),'plain')])
        g=self.game(('echo','upgrade'));self.play(g,'echo');self.play(g,'upgrade');g.apply(EndTurn(1))
        self.assertFalse(self.cards(g));self.check(g)

    def test_countered_echo_still_generated_at_commit(self):
        g=self.game(('echo',),enemy_hand=('EX1_287',));g.apply(EndTurn(1));self.play(g,'EX1_287',player=2);g.apply(EndTurn(2))
        self.play(g,'echo');self.assertEqual(self.armor(g),0)
        self.assertEqual(sum(e.card_id=='echo' for e in self.cards(g)),1)
        self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_effect_repetition_does_not_multiply_echo_copies(self):
        self.r.register_card(CardDefinition('repeat_source','repeat_source',CardType.MINION,health=3,spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        g=self.game(('echo',),board=('repeat_source',));self.play(g,'echo')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(self.cards(g)),1);self.check(g)

    def test_direct_summon_does_not_echo(self):
        self.spell('summon',lambda c:[Summon(1,'echo_minion')])
        g=self.game(('summon',));self.play(g,'summon');self.assertFalse(self.cards(g));self.check(g)

    def test_choice_sees_copy_and_restores_without_duplicate(self):
        self.spell('echo_choice',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',(GainArmor(1,2),)),),c.source_id)],
                   keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        g=self.game(('echo_choice',));self.play(g,'echo_choice');self.assertEqual(len(self.cards(g)),1);self.check(g)
        choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,choice.id,('yes',)))
        self.assertEqual(len(self.cards(g)),1);self.assertEqual(self.armor(g),2);self.check(g)

    def test_late_failure_rolls_back_echo_copy_and_all_counters(self):
        self.r.register_behavior('bad',lambda c:[GainArmor(1,-1)])
        self.spell('echo_fail',lambda c:[InvokeBehavior('bad',c.source_id,1)],keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        g=self.game(('echo_fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'echo_fail')
        self.assertEqual(g.snapshot(),before)

    def test_play_from_full_hand_has_room_for_echo_copy(self):
        g=self.game(('echo',)+('plain',)*9);self.play(g,'echo')
        self.assertEqual(len(self.cards(g)),10);self.assertFalse(any(e.kind=='card_burned' for e in g.events));self.check(g)

    def test_temporary_generation_full_hand_burns_normally(self):
        self.spell('get',lambda c:[AddToHand(1,'plain'),CreateTemporaryCard(1,'echo',c.state.turn,source_id=c.source_id)])
        g=self.game(('get',)+('plain',)*9);self.play(g,'get')
        self.assertTrue(any(e.kind=='card_burned' for e in g.events));g.apply(EndTurn(1))
        self.assertFalse(any(e.kind=='card_expired' for e in g.events));self.check(g)

    def test_generation_in_end_turn_reaction_is_also_expired(self):
        self.r.register_behavior('end',lambda c:[CreateTemporaryCard(1,'plain',c.state.turn,source_id=c.source_id)])
        self.r.register_card(CardDefinition('source','source',CardType.MINION,health=1,triggers=(TriggerSpec('turn_ended','end'),)))
        g=self.game(board=('source',));g.apply(EndTurn(1))
        self.assertFalse(self.cards(g));self.assertTrue(any(e.kind=='card_expired' for e in g.events));self.check(g)

    def test_expiry_reaction_new_copy_settles_before_next_turn(self):
        self.r.register_behavior('once',lambda c:[] if len([e for e in c.state.entities.values() if e.card_id=='plain'])>25 else
                                 [CreateTemporaryCard(1,'plain',c.state.turn,source_id=c.source_id)])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=1,triggers=(TriggerSpec('card_expired','once'),)))
        self.spell('get',lambda c:[CreateTemporaryCard(1,'plain',c.state.turn,source_id=c.source_id)])
        g=self.game(('get',),board=('watch',));self.play(g,'get');g.apply(EndTurn(1))
        self.assertFalse(self.cards(g));self.assertEqual(len([e for e in g.events if e.kind=='card_expired']),2);self.check(g)

    def test_lifetime_is_private_and_owner_can_see_deadline(self):
        g=self.game(('echo',));self.play(g,'echo')
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['temporary'],{'expires_turn':1,'minimum_cost':1})
        self.assertNotIn('temporary',json.dumps(g.observe(2)['players'][0]['hand']))
        g.apply(EndTurn(1));self.assertFalse(any(e['kind']=='card_expired' for e in g.player_events(2)));self.check(g)

    def test_player_command_pays_floor_and_returns_new_revision(self):
        g=self.game(('echo',));port=g.for_player(1)
        for _ in range(2):
            listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='play_card')
            self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(self.armor(g),2);self.check(g)

    def test_queued_temporary_effect_round_trips_in_choice_frame(self):
        self.spell('choose',lambda c:[RequestChoice(1,(ChoiceOption('make','Make',
            (CreateTemporaryCard(1,'plain',c.state.turn,source_id=c.source_id),)),),c.source_id)])
        g=self.game(('choose',));self.play(g,'choose');self.check(g)
        choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,choice.id,('make',)))
        self.assertEqual(len(self.cards(g)),1);g.apply(EndTurn(1));self.assertFalse(self.cards(g));self.check(g)

    def test_temporary_state_survives_shatter_and_recombination(self):
        self.r.register_card(CardDefinition('split','split',CardType.SPELL,keywords=(Keyword.SHATTER,),shatter=ShatterSpec('L','R')))
        for name in ('L','R'):self.r.register_card(CardDefinition(name,name,CardType.SPELL,keywords=(Keyword.SHATTERED,)))
        self.spell('get',lambda c:[CreateTemporaryCard(1,'split',c.state.turn,minimum_cost=1,source_id=c.source_id)])
        g=self.game(('get','plain'));self.play(g,'get')
        self.assertTrue(all(e.hand_lifetime is not None for e in self.cards(g) if e.card_id!='plain'))
        self.play(g,'plain');self.assertEqual(g.quote_cost(self.find(g,'split')).amount,1)
        g.apply(EndTurn(1));self.assertFalse(self.cards(g));self.check(g)

    def test_corrupt_lifetime_snapshot_rejected(self):
        g=self.game(('echo',));self.play(g,'echo');eid=str(self.find(g,'echo'))
        for key,value in (('source_id',999999),('created_turn',2),('expires_turn',0),('minimum_cost',-1),('minimum_cost',True)):
            snap=g.snapshot();snap['state']['entities'][eid]['hand_lifetime'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_missing_lifetime_field_rejected(self):
        g=self.game(('echo',));self.play(g,'echo');snap=g.snapshot()
        del snap['state']['entities'][str(self.find(g,'echo'))]['hand_lifetime']['expires_turn']
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_later_deadline_survives_one_turn_then_expires(self):
        self.spell('get',lambda c:[CreateTemporaryCard(1,'plain',c.state.turn+1,source_id=c.source_id)])
        g=self.game(('get',));self.play(g,'get');g.apply(EndTurn(1));self.assertEqual(len(self.cards(g)),1)
        self.check(g);g.apply(EndTurn(2));self.assertEqual([e.card_id for e in self.cards(g)],['plain'])
        self.assertIsNone(self.cards(g)[0].hand_lifetime) # Only the ordinary turn-three draw remains.
        self.assertEqual(len([e for e in g.events if e.kind=='card_expired']),1);self.check(g)

    def test_temporary_card_moved_to_other_hand_keeps_deadline(self):
        self.spell('give',lambda c:[MoveCard(self.ref(c,'echo'),2,Zone.HAND)])
        g=self.game(('echo','give'));self.play(g,'echo');copy=self.find(g,'echo');self.play(g,'give');g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[copy].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[copy].controller,2);self.check(g)

    def test_explicit_discard_does_not_emit_later_expiry(self):
        self.spell('discard',lambda c:[DiscardCard(self.ref(c,'echo'))])
        g=self.game(('echo','discard'));self.play(g,'echo');self.play(g,'discard');g.apply(EndTurn(1))
        self.assertEqual(len([e for e in g.events if e.kind=='card_discarded']),1)
        self.assertFalse(any(e.kind=='card_expired' for e in g.events));self.check(g)

    def test_expired_creation_and_unknown_source_roll_back(self):
        self.spell('bad_source',lambda c:[CreateTemporaryCard(1,'plain',c.state.turn,source_id=99999)])
        self.spell('old',lambda c:[CreateTemporaryCard(1,'plain',1)])
        g=self.game(('bad_source','old'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad_source')
        self.assertEqual(g.snapshot(),before);g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'old')
        self.assertEqual(g.snapshot(),before)

    def test_spell_cost_aura_cannot_bypass_floor(self):
        self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=2,
            cost_auras=(CostAuraSpec(CostSpec(delta=-10,card_types=(CardType.SPELL,))),)))
        g=self.game(('echo',),board=('aura',));self.play(g,'echo')
        self.assertEqual(g.quote_cost(self.find(g,'echo')).amount,1);self.check(g)

    def test_transforming_source_does_not_change_captured_copy_identity(self):
        self.r.register_behavior('change',lambda c:[Transform(c.source_id,'CS2_182')])
        self.r.register_card(CardDefinition('changing','changing',CardType.MINION,health=2,on_play='change',
            keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec()))
        g=self.game(('changing',));original=self.play(g,'changing')
        self.assertEqual(g.state.entities[original].card_id,'CS2_182')
        self.assertEqual(self.cards(g)[0].card_id,'changing');self.check(g)


class EchoDefinitionTests(unittest.TestCase):
    def test_marker_and_declaration_must_agree(self):
        for kw,spec in (((Keyword.ECHO,),None),((),HandRepeatSpec()),((Keyword.ECHO,),HandRepeatSpec(False))):
            r=build_registry();r.register_card(CardDefinition('bad','bad',CardType.SPELL,keywords=kw,hand_repeat=spec))
            with self.subTest(spec=spec),self.assertRaises(ValueError):r.freeze()

    def test_only_physical_minions_and_spells_supported(self):
        r=build_registry();r.register_card(CardDefinition('bad','bad',CardType.HERO,health=30,hand_repeat=HandRepeatSpec(False)))
        with self.assertRaises(ValueError):r.freeze()

    def test_repeat_flag_and_lifetime_scalars_are_strict(self):
        with self.assertRaises(ValueError):HandRepeatSpec(echo=1)
        for life in ((None,2,1,0),(None,1,1,-1),(False,1,1,0)):
            with self.subTest(life=life),self.assertRaises(ValueError):HandLifetime(*life)

    def test_temporary_effect_requires_valid_values(self):
        for fields in ((1,'',1),(1,'plain',0),(3,'plain',1)):
            with self.subTest(fields=fields),self.assertRaises(ValueError):CreateTemporaryCard(*fields)
