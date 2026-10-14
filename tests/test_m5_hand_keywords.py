"""Dynamic Echo, live hand contributions and persistent stored-card grants."""
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game,
    GrantStoredKeyword, HandDerivativeSpec, HandRepeatSpec, Keyword, KeywordAuraSpec,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SpellRepeatSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption,
    Damage, Destroy, Draw, GainArmor, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.keyword_auras import GrantKeywordAura
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard


ECHO_HAND = KeywordAuraSpec(Keyword.ECHO, 'friendly_hand_minions')


class HandKeywordTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.minion('plain',cost=2,attack=2,health=3)
        self.minion('aura',cost=2,health=5,keyword_auras=(ECHO_HAND,))
        self.minion('printed',cost=2,attack=2,health=3,keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        self.spell('nothing',lambda c:[])
        for name,fn in (
            ('silence',lambda c:[Silence(c.target_id)]),
            ('kill',lambda c:[Destroy(c.target_id)]),
            ('bounce',lambda c:[ReturnToHand(c.target_id)]),
            ('transform',lambda c:[Transform(c.target_id,'plain')]),
            ('steal',lambda c:[ChangeControl(c.target_id,2)]),
            ('ping',lambda c:[Damage(c.target_id,1)]),
        ):self.spell(name,fn,requires_target=True)

    def minion(self,name,**kw):
        self.r.register_card(CardDefinition(name,name,CardType.MINION,**kw))
    def spell(self,name,fn,**kw):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kw))
    def game(self,hand=(),board=('aura',),enemy_hand=(),enemy_board=(),deck=('plain',)*12):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=deck,max_mana=10,mana=10),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('nothing',)*12,max_mana=10,mana=10)),seed=196),self.r)
    def cards(self,g,player=1):
        s=g.state;return [s.entities[i] for i in s.players[player].hand]
    def find(self,g,name,player=1,zone='hand'):
        s=g.state;return next(i for i in getattr(s.players[player],zone) if s.entities[i].card_id==name)
    def play(self,g,name,target=None,player=1,position=None):
        eid=self.find(g,name,player);g.apply(PlayCard(player,eid,target,position));return eid
    def ref(self,c,name='plain',zone=Zone.HAND,player=1):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[player],zone.value)
                                         if c.state.entities[i].card_id==name))
    def has_echo(self,g,name='plain',expected=True,player=1):
        self.assertEqual(Keyword.ECHO in g.state.entities[self.find(g,name,player)].keywords,expected)
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)
    def grant(self,name='grant',keyword=Keyword.ECHO,**kw):
        self.spell(name,lambda c:[GrantStoredKeyword(self.ref(c),keyword,c.source_id,**kw)])
    def watcher(self,event,fn):
        self.r.register_behavior('watch',fn)
        self.minion('watch',health=2,triggers=(TriggerSpec(event,'watch'),))

    def test_existing_hand_minions_have_echo_without_printed_spec(self):
        g=self.game(('plain','nothing'),enemy_hand=('plain',))
        self.has_echo(g);self.has_echo(g,player=2,expected=False)
        self.has_echo(g,'nothing',False);self.check(g)

    def test_played_minion_loses_aura_but_copy_gains_it(self):
        g=self.game(('plain',));original=self.play(g,'plain')
        self.assertNotIn(Keyword.ECHO,g.state.entities[original].keywords)
        self.has_echo(g);copy=self.cards(g)[0]
        self.assertEqual((copy.origin_entity_id,copy.hand_lifetime.minimum_cost),(original,1))
        self.play(g,'plain');self.assertEqual(len(self.cards(g)),1);self.check(g)

    def test_generated_copy_floor_survives_aura_removal(self):
        self.spell('reduce',lambda c:[AddCostModifier(1,CostSpec(delta=-9))])
        g=self.game(('plain','reduce','kill'));self.play(g,'reduce')
        self.assertEqual(g.quote_cost(self.find(g,'plain')).amount,0);self.play(g,'plain')
        self.play(g,'kill',self.find(g,'aura',zone='board'));self.has_echo(g,expected=False)
        self.assertEqual(g.quote_cost(self.find(g,'plain')).amount,1)
        self.play(g,'plain');self.assertFalse(self.cards(g));self.assertEqual(g.state.players[1].mana,9);self.check(g)

    def test_generated_copy_expires_even_after_source_removed(self):
        g=self.game(('plain','kill'));self.play(g,'plain');copy=self.find(g,'plain')
        self.play(g,'kill',self.find(g,'aura',zone='board'));g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[copy].zone,Zone.GRAVEYARD);self.check(g)

    def test_playing_first_aura_does_not_echo_itself(self):
        g=self.game(('aura','plain'),board=());self.play(g,'aura')
        self.assertEqual([e.card_id for e in self.cards(g)],['plain']);self.has_echo(g);self.check(g)

    def test_playing_second_aura_is_eligible(self):
        g=self.game(('aura',));self.play(g,'aura')
        self.assertEqual([e.card_id for e in self.cards(g)],['aura']);self.has_echo(g,'aura');self.check(g)

    def test_multiple_sources_do_not_duplicate_copies(self):
        g=self.game(('plain',),board=('aura','aura'));self.play(g,'plain')
        self.assertEqual(len(self.cards(g)),1);self.check(g)

    def test_one_source_removed_other_still_contributes(self):
        g=self.game(('plain','kill','kill'),board=('aura','aura'))
        self.play(g,'kill',self.find(g,'aura',zone='board'));self.has_echo(g)
        self.play(g,'kill',self.find(g,'aura',zone='board'));self.has_echo(g,expected=False);self.check(g)

    def test_silence_removes_source_aura(self):
        g=self.game(('plain','silence'));self.play(g,'silence',self.find(g,'aura',zone='board'))
        self.has_echo(g,expected=False);self.check(g)

    def test_transform_removes_source_aura(self):
        g=self.game(('plain','transform'));self.play(g,'transform',self.find(g,'aura',zone='board'))
        self.has_echo(g,expected=False);self.check(g)

    def test_bounced_source_does_not_contribute_from_hand(self):
        g=self.game(('plain','bounce'));self.play(g,'bounce',self.find(g,'aura',zone='board'))
        self.has_echo(g,expected=False);self.has_echo(g,'aura',False);self.check(g)

    def test_control_change_moves_aura_to_new_controllers_hand(self):
        g=self.game(('plain','steal'),enemy_hand=('plain',))
        self.play(g,'steal',self.find(g,'aura',zone='board'))
        self.has_echo(g,expected=False);self.has_echo(g,player=2);self.check(g)

    def test_dormant_source_does_not_contribute(self):
        self.minion('sleep',health=5,dormant_turns=None,keyword_auras=(ECHO_HAND,))
        g=self.game(('plain',),board=('sleep',));self.has_echo(g,expected=False);self.check(g)

    def test_new_draw_has_aura_in_frozen_acquisition_context(self):
        self.spell('draw',lambda c:[Draw(1)])
        self.watcher('card_drawn',lambda c:[GainArmor(1,int(Keyword.ECHO in c.state.entities[c.event.target_id].keywords))])
        g=self.game(('draw',),board=('aura','watch'));self.play(g,'draw')
        self.assertEqual(self.armor(g),1);self.has_echo(g);self.check(g)

    def test_generated_echo_has_aura_in_frozen_acquisition_context(self):
        self.watcher('card_added_to_hand',lambda c:[GainArmor(1,int(Keyword.ECHO in c.state.entities[c.event.target_id].keywords))])
        g=self.game(('plain',),board=('aura','watch'));self.play(g,'plain')
        self.assertEqual(self.armor(g),1);self.check(g)

    def test_play_that_kills_source_keeps_captured_echo_once(self):
        self.r.register_behavior('kill_aura',lambda c:[Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='aura'))])
        self.minion('killer',cost=2,health=2,on_play='kill_aura')
        g=self.game(('killer',));self.play(g,'killer')
        self.assertEqual([e.card_id for e in self.cards(g)],['killer']);self.has_echo(g,'killer',False);self.check(g)

    def test_printed_echo_survives_removal_of_aura_source(self):
        g=self.game(('printed','kill'));self.play(g,'kill',self.find(g,'aura',zone='board'))
        self.has_echo(g,'printed');self.play(g,'printed');self.assertEqual(len(self.cards(g)),1);self.check(g)

    def test_spell_hand_scope_echoes_only_spells(self):
        self.minion('spells',health=2,keyword_auras=(KeywordAuraSpec(Keyword.ECHO,'friendly_hand_spells'),))
        g=self.game(('nothing','plain'),board=('spells',));self.has_echo(g,'nothing');self.has_echo(g,expected=False)
        self.play(g,'nothing');self.assertEqual(len(self.cards(g)),2);self.check(g)

    def test_all_hand_scope_excludes_weapons(self):
        self.minion('all',health=2,keyword_auras=(KeywordAuraSpec(Keyword.ECHO,'friendly_hand'),))
        g=self.game(('nothing','plain','CS2_106'),board=('all',))
        self.has_echo(g,'nothing');self.has_echo(g);self.has_echo(g,'CS2_106',False);self.check(g)

    def test_hand_only_combat_keyword_does_not_follow_card_to_board(self):
        self.minion('wind',health=2,keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY,'friendly_hand_minions'),))
        g=self.game(('plain',),board=('wind',));eid=self.find(g,'plain')
        self.assertIn(Keyword.WINDFURY,g.state.entities[eid].keywords);self.play(g,'plain')
        self.assertNotIn(Keyword.WINDFURY,g.state.entities[eid].keywords);self.check(g)

    def test_aura_is_not_baked_into_current_copy_to_opponent(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c),2)])
        g=self.game(('plain','copy'));self.play(g,'copy');self.has_echo(g);self.has_echo(g,player=2,expected=False);self.check(g)

    def test_move_to_opponent_recomputes_instead_of_carrying_aura(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c),2,Zone.HAND)])
        g=self.game(('plain','move'));self.play(g,'move');self.has_echo(g,player=2,expected=False);self.check(g)

    def test_shuffle_and_redraw_recalculate_aura(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top')])
        self.spell('draw',lambda c:[Draw(1)])
        g=self.game(('plain','move','draw'));eid=self.find(g,'plain');self.play(g,'move')
        self.assertFalse(g.state.entities[eid].hand_aura_keywords);self.play(g,'draw');self.has_echo(g);self.check(g)

    def test_dynamic_aura_grant_can_expire(self):
        self.spell('grant_aura',lambda c:[GrantKeywordAura(c.state.players[1].board[0],ECHO_HAND,c.source_id,c.state.turn)])
        g=self.game(('plain','grant_aura'),board=('plain',));self.play(g,'grant_aura');self.has_echo(g)
        g.apply(EndTurn(1));self.has_echo(g,expected=False);self.check(g)

    def test_source_copy_has_its_own_live_aura(self):
        from hs_sim.engine.effects import CopyMinion
        self.spell('copy_source',lambda c:[CopyMinion(c.state.players[1].board[0],2)])
        g=self.game(('plain','copy_source'),enemy_hand=('plain',));self.play(g,'copy_source')
        self.has_echo(g);self.has_echo(g,player=2);self.check(g)

    def test_magnetic_uses_captured_hand_echo_without_giving_host_echo(self):
        self.minion('mag',cost=2,attack=1,health=2,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',))
        self.minion('mech',attack=2,health=3,metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',)))
        g=self.game(('mag',),board=('aura','mech'));source=self.play(g,'mag',position=1)
        self.assertEqual(self.cards(g)[0].origin_entity_id,source)
        self.assertNotIn(Keyword.ECHO,g.state.entities[self.find(g,'mech',zone='board')].keywords);self.check(g)

    def test_dynamic_echo_and_miniaturize_generate_different_forms(self):
        self.minion('mini',cost=1,attack=1,health=1,keywords=(Keyword.MINI,))
        self.minion('small',cost=2,health=2,keywords=(Keyword.MINIATURIZE,),
            hand_derivatives=(HandDerivativeSpec(Keyword.MINIATURIZE,'mini'),))
        g=self.game(('small',));self.play(g,'small')
        self.assertEqual([e.card_id for e in self.cards(g)],['small','mini'])
        self.assertIsNotNone(self.cards(g)[0].hand_lifetime);self.assertIsNone(self.cards(g)[1].hand_lifetime)
        self.has_echo(g,'small');self.has_echo(g,'mini');self.check(g)

    def test_persistent_grant_echo_works_without_aura(self):
        self.grant();g=self.game(('plain','grant'),board=());self.play(g,'grant');self.has_echo(g)
        self.play(g,'plain');self.has_echo(g,expected=False)
        self.assertEqual(self.cards(g)[0].hand_lifetime.minimum_cost,1);self.check(g)

    def test_persistent_spell_grant_uses_same_repeat_path(self):
        self.spell('grant_spell',lambda c:[GrantStoredKeyword(self.ref(c,'nothing'),Keyword.ECHO)])
        g=self.game(('nothing','grant_spell'),board=());self.play(g,'grant_spell');self.play(g,'nothing')
        self.assertEqual(len(self.cards(g)),1);self.assertEqual(self.cards(g)[0].hand_lifetime.minimum_cost,1);self.check(g)

    def test_persistent_and_aura_echo_do_not_double_generate(self):
        self.grant();g=self.game(('plain','grant'));self.play(g,'grant');self.play(g,'plain')
        self.assertEqual(len(self.cards(g)),1);self.check(g)

    def test_persistent_grant_survives_aura_source_removal(self):
        self.grant();g=self.game(('plain','grant','kill'));self.play(g,'grant')
        self.play(g,'kill',self.find(g,'aura',zone='board'));self.has_echo(g);self.check(g)

    def test_current_copy_preserves_grant_but_base_copy_does_not(self):
        self.grant();self.spell('copy',lambda c:[CopyCard(self.ref(c),2),CopyCard(self.ref(c),2,mode='base')])
        g=self.game(('plain','grant','copy'),board=());self.play(g,'grant');self.play(g,'copy')
        self.assertEqual([Keyword.ECHO in e.keywords for e in self.cards(g,2)],[True,False]);self.check(g)

    def test_grant_survives_shuffle_and_draw(self):
        self.grant();self.spell('move',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top'),Draw(1)])
        g=self.game(('plain','grant','move'),board=());self.play(g,'grant');self.play(g,'move');self.has_echo(g);self.check(g)

    def test_reset_discards_persistent_grant(self):
        self.grant();self.spell('reset',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top',reset=True),Draw(1)])
        g=self.game(('plain','grant','reset'),board=());self.play(g,'grant');self.play(g,'reset');self.has_echo(g,expected=False);self.check(g)

    def test_grant_to_deck_card_applies_when_drawn(self):
        self.spell('grant_deck',lambda c:[GrantStoredKeyword(self.ref(c,zone=Zone.DECK),Keyword.ECHO),Draw(1)])
        g=self.game(('grant_deck',),board=());self.play(g,'grant_deck');self.has_echo(g);self.check(g)

    def test_grant_expiry_removes_ability_without_discarding_original(self):
        self.grant(expires_turn=1);g=self.game(('plain','grant'),board=());self.play(g,'grant')
        original=self.find(g,'plain');g.apply(EndTurn(1));self.has_echo(g,expected=False)
        self.assertEqual(self.find(g,'plain'),original);self.check(g)

    def test_stored_shield_is_carried_to_board_and_consumed_normally(self):
        self.grant(keyword=Keyword.DIVINE_SHIELD)
        g=self.game(('plain','grant','ping','ping'),board=());self.play(g,'grant');eid=self.play(g,'plain')
        self.play(g,'ping',eid);self.assertEqual(g.state.entities[eid].health,3)
        self.play(g,'ping',eid);self.assertEqual(g.state.entities[eid].health,2);self.check(g)

    def test_stale_reference_does_not_grant_to_returned_entity(self):
        self.spell('stale',lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top'),Draw(1),
                                  GrantStoredKeyword(self.ref(c),Keyword.ECHO)])
        g=self.game(('plain','stale'),board=());self.play(g,'stale');self.has_echo(g,expected=False)
        self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events));self.check(g)

    def test_grant_choice_round_trips_typed_reference(self):
        self.spell('choose',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',(
            GrantStoredKeyword(self.ref(c),Keyword.ECHO,c.source_id),)),),c.source_id)])
        g=self.game(('plain','choose'),board=());self.play(g,'choose');self.check(g)
        choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,choice.id,('yes',)));self.has_echo(g);self.check(g)

    def test_acquisition_choice_can_restore_live_aura_and_lifetime(self):
        self.watcher('card_added_to_hand',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',()),),c.source_id)])
        g=self.game(('plain',),board=('aura','watch'));self.play(g,'plain');self.has_echo(g);self.check(g)
        choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,choice.id,('yes',)));self.assertEqual(len(self.cards(g)),1);self.check(g)

    def test_private_grant_event_and_aura_details_are_owner_only(self):
        self.grant();g=self.game(('plain','grant'),board=());self.play(g,'grant')
        self.assertIn('echo',g.observe(1)['players'][0]['hand'][0]['keywords'])
        self.assertNotIn('keywords',g.observe(2)['players'][0]['hand'][0])
        self.assertTrue(any(e['kind']=='stored_keyword_granted' for e in g.player_events(1)))
        self.assertFalse(any(e['kind']=='stored_keyword_granted' for e in g.player_events(2)))
        self.assertNotIn('hand_aura_keywords',json.dumps(g.observe(1)));self.check(g)

    def test_player_port_respects_live_aura_and_copy_floor(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-10))])
        g=self.game(('plain','discount'));self.play(g,'discount');port=g.for_player(1)
        for _ in range(2):
            listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='play_card')
            self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(g.state.players[1].mana,9);self.check(g)

    def test_bad_source_or_expiry_roll_back_grant(self):
        self.spell('bad_source',lambda c:[GrantStoredKeyword(self.ref(c),Keyword.ECHO,999999)])
        self.grant('old',expires_turn=1)
        g=self.game(('plain','bad_source','old'),board=());g.apply(EndTurn(1));g.apply(EndTurn(2))
        for name in ('bad_source','old'):
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,name)
            self.assertEqual(g.snapshot(),before)

    def test_incompatible_card_kind_rejected_without_partial_mutation(self):
        self.spell('bad',lambda c:[GrantStoredKeyword(self.ref(c,'nothing'),Keyword.TAUNT)])
        g=self.game(('nothing','bad'),board=());before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_forged_hand_aura_cache_rejected(self):
        g=self.game(('plain',));eid=str(self.find(g,'plain'))
        for value in ([],['taunt'],['unknown']):
            snap=g.snapshot();snap['state']['entities'][eid]['hand_aura_keywords']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_missing_hand_aura_field_rejected(self):
        g=self.game(('plain',));snap=g.snapshot();del snap['state']['entities'][str(self.find(g,'plain'))]['hand_aura_keywords']
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_countered_spell_keeps_dynamic_echo_committed_copy(self):
        self.minion('spells',health=2,keyword_auras=(KeywordAuraSpec(Keyword.ECHO,'friendly_hand_spells'),))
        g=self.game(('nothing',),board=('spells',),enemy_hand=('EX1_287',));g.apply(EndTurn(1))
        self.play(g,'EX1_287',player=2);g.apply(EndTurn(2));self.play(g,'nothing')
        copies=[e for e in self.cards(g) if e.card_id=='nothing']
        self.assertEqual(len(copies),1);self.assertIsNotNone(copies[0].hand_lifetime)
        self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_effect_repetition_does_not_duplicate_dynamic_echo(self):
        self.minion('spells',health=2,keyword_auras=(KeywordAuraSpec(Keyword.ECHO,'friendly_hand_spells'),),
            spell_repeats=(SpellRepeatSpec(class_mode='any'),))
        self.spell('armor',lambda c:[GainArmor(1,1)])
        g=self.game(('armor',),board=('spells',));self.play(g,'armor')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(self.cards(g)),1);self.check(g)

    def test_deferred_source_removal_retains_aura_until_death_checkpoint(self):
        self.minion('repeat',health=2,spell_repeats=(SpellRepeatSpec(class_mode='any'),))
        self.spell('defer',lambda c:[Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='aura')),
            AddToHand(1,'plain'),RequestChoice(1,(ChoiceOption('yes','Yes',()),),c.source_id)])
        g=self.game(('defer',),board=('aura','repeat'));self.play(g,'defer')
        self.assertTrue(g.state.entities[self.find(g,'aura',zone='board')].doomed)
        self.has_echo(g);self.check(g)
        while g.state.pending_choice:
            choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r)
            g.apply(SelectChoice(1,choice.id,('yes',)))
        self.assertEqual(len(self.cards(g)),2)
        self.assertTrue(all(Keyword.ECHO not in e.keywords for e in self.cards(g)));self.check(g)

    def test_temporary_and_intrinsic_repeat_with_aura_make_one_echo_copy(self):
        self.minion('repeat',health=2,hand_repeat=HandRepeatSpec(echo=False))
        g=self.game(('repeat',));self.play(g,'repeat')
        self.assertEqual(len(self.cards(g)),1);self.assertEqual(self.cards(g)[0].hand_lifetime.minimum_cost,1);self.check(g)


class HandKeywordDefinitionTests(unittest.TestCase):
    def test_echo_is_only_an_aura_in_hand_scopes(self):
        for target in ('friendly_hero','friendly_minions'):
            with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.ECHO,target)
    def test_hand_aura_rejects_board_positions(self):
        for changes in ({'include_self':True},{'adjacent_only':True}):
            with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.ECHO,'friendly_hand_minions',**changes)
    def test_spell_scope_rejects_minion_combat_keywords(self):
        for target in ('friendly_hand','friendly_hand_spells'):
            with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.TAUNT,target)
    def test_consumable_continuous_hand_aura_not_silently_supported(self):
        for k in (Keyword.DIVINE_SHIELD,Keyword.REBORN,Keyword.STEALTH,Keyword.MINIATURIZE):
            with self.assertRaises(ValueError):KeywordAuraSpec(k,'friendly_hand_minions')
    def test_stored_grant_requires_captured_reference_and_supported_keyword(self):
        ref=CardReference(1,1,Zone.HAND,'plain',0)
        for value in (Keyword.TWINSPELL,Keyword.MINIATURIZE,Keyword.TITAN,'echo'):
            with self.assertRaises(ValueError):GrantStoredKeyword(ref,value)
        with self.assertRaises(ValueError):GrantStoredKeyword(1,Keyword.ECHO)
        with self.assertRaises(ValueError):GrantStoredKeyword(ref,Keyword.ECHO,expires_turn=True)
