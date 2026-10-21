"""Hero cards and immutable Starship launch history across all public boundaries."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CostScope,
    CostSpec, EndTurn, Game, IllegalAction, Keyword, LaunchStarship, PlayCard, PlayerSetup,
    RelaunchStarships, ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec,
    UseHeroPower, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, Buff, ChoiceOption, Damage,
    Destroy, Freeze, GainArmor, ModifyCost, RequestChoice, ShuffleIntoDeck, Summon)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction


class HeroHistoryTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=4))
        self.spell('kill', lambda c: [Destroy(c.target_id)], requires_target=True)
        self.spell('hurt', lambda c: [Damage(c.state.players[1].hero_id, 6)])
        self.spell('relaunch', lambda c: [RelaunchStarships(c.player_id)])

    def spell(self, name, callback, **fields):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **fields))

    def hero(self, name='custom', callback=None, **fields):
        self.r.register_behavior(name, callback or (lambda c: []))
        defaults = dict(health=30, hero_card=True, hero_armor=5,
            initial_hero_power='HERO_08bp', on_play=name,
            metadata=CardMetadata(False, (CardClass.MAGE,), None))
        defaults.update(fields)
        self.r.register_card(CardDefinition(name, name, CardType.HERO, **defaults))

    def game(self, hand=(), board=(), enemy=(), deck=('plain',)*6, enemy_hand=(), armor=0, weapon=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=hand, board=board,
            deck=deck, armor=armor, weapon_card_id=weapon, hero_power_card_id='HERO_01bp', mana=10,max_mana=10),
            PlayerSetup('HERO_08', board=enemy, hand=enemy_hand, deck=('plain',)*6, mana=10,max_mana=10)),seed=57),self.r)

    def play(self,g,card,target=None,player=1):
        i=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==card)
        return g.apply(PlayCard(player,i,target))

    def use(self,g):
        return g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))

    def current(self,g):
        return g.state.entities[g.state.players[1].hero_id]

    def cycle(self,g):
        g.apply(EndTurn(1));g.apply(EndTurn(2))

    def launch(self,g):
        ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));return ship.id

    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def built(self,extra=(),piece='SC_403a'):
        g=self.game(hand=('kill',*extra),board=(piece,))
        self.play(g,'kill',g.state.players[1].board[0]);return g

    def test_real_hero_uses_hand_identity_preserves_health_and_adds_armor(self):
        g=self.game(hand=('hurt','SC_400'),armor=3)
        self.play(g,'hurt');old=self.current(g).id;card=g.state.players[1].hand[0]
        self.play(g,'SC_400')
        self.assertEqual((self.current(g).id,self.current(g).health,self.current(g).armor),(card,27,5))
        self.assertIn(old,g.state.players[1].graveyard)
        self.assertEqual(g.state.players[1].mana,3)
        self.assertFalse(any(e.kind=='minion_died' for e in g.events));self.check(g)

    def test_hero_play_on_full_board_uses_no_slot(self):
        g=self.game(hand=('SC_400',),board=('plain',)*7)
        before=list(g.state.players[1].board);self.play(g,'SC_400')
        self.assertEqual(g.state.players[1].board,before);self.check(g)

    def test_raynor_preserves_class_for_new_ship_and_generation(self):
        g=self.game(hand=('SC_400','kill'),board=('SC_403a',))
        self.play(g,'SC_400');self.play(g,'kill',g.state.players[1].board[0])
        self.assertEqual(g.state.players[1].hero_class,CardClass.WARRIOR)
        self.assertEqual(construction(g.state,1).card_id,'SC_999t')
        self.assertEqual(g.observe(2)['players'][0]['hero_class'],'warrior');self.check(g)

    def test_single_class_hero_changes_current_class(self):
        self.hero();g=self.game(hand=('custom','kill'),board=('SC_403a',))
        self.play(g,'custom');self.play(g,'kill',g.state.players[1].board[0])
        self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)
        self.assertNotEqual(construction(g.state,1).card_id,'SC_999t');self.check(g)

    def test_power_is_replaced_and_can_be_used_after_old_power(self):
        g=self.game(hand=('SC_400',));old=g.state.players[1].hero_power_id
        self.use(g);self.play(g,'SC_400');self.cycle(g);self.use(g)
        self.assertIn(old,g.state.players[1].graveyard)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'SC_400p')
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,1);self.check(g)

    def test_replacement_refreshes_power_in_same_turn(self):
        self.hero();g=self.game(hand=('custom',));self.use(g);self.play(g,'custom')
        power=g.state.players[1].hero_power_id
        g.apply(UseHeroPower(1,power,g.state.players[2].hero_id))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,2);self.check(g)

    def test_attack_spent_weapon_freeze_and_max_health_survive(self):
        self.spell('enhance',lambda c:[Buff(c.state.players[1].hero_id,health=10),Freeze(c.state.players[1].hero_id)])
        g=self.game(hand=('enhance','SC_400'),weapon='CS2_106')
        g.apply(Attack(1,self.current(g).id,g.state.players[2].hero_id));self.play(g,'enhance')
        weapon=g.state.players[1].weapon_id;self.play(g,'SC_400')
        self.assertEqual((self.current(g).max_health,self.current(g).attacks_this_turn),(40,1))
        self.assertTrue(self.current(g).frozen);self.assertEqual(g.state.players[1].weapon_id,weapon);self.check(g)

    def test_hero_battlecry_sees_new_hero_and_new_power(self):
        self.hero(callback=lambda c:[GainArmor(1,11 if c.source_id==c.state.players[1].hero_id and
            c.state.entities[c.state.players[1].hero_power_id].card_id=='HERO_08bp' else 100)])
        g=self.game(hand=('custom',));self.play(g,'custom');self.assertEqual(self.current(g).armor,16)

    def test_targeted_hero_requires_target_and_no_board_position(self):
        self.hero(callback=lambda c:[Damage(c.target_id,2,c.source_id)],requires_target=True)
        g=self.game(hand=('custom',));i=g.state.players[1].hand[0]
        for action in (PlayCard(1,i),PlayCard(1,i,g.state.players[2].hero_id,0)):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(before,g.snapshot())
        self.play(g,'custom',g.state.players[2].hero_id);self.check(g)

    def test_hero_card_can_be_drawn_generated_copied_and_shuffled(self):
        self.spell('generate',lambda c:[AddToHand(1,'SC_400')])
        self.spell('shuffle',lambda c:[ShuffleIntoDeck(c.state.players[1].hand[-1],1)])
        g=self.game(hand=('generate','shuffle'),deck=('SC_400',))
        self.play(g,'generate');self.play(g,'shuffle');self.assertEqual(len(g.state.players[1].deck),2);self.check(g)

    def test_starting_hero_is_not_a_hand_card(self):
        self.spell('bad',lambda c:[AddToHand(1,'HERO_01')])
        with self.assertRaises(ValueError):self.game(hand=('HERO_01',))
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(before,g.snapshot())

    def test_global_discount_applies_to_hero_and_consumes_once(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-4),uses_remaining=1)])
        g=self.game(hand=('discount','SC_400'));self.play(g,'discount');self.play(g,'SC_400')
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(g.state.players[1].cost_modifiers,[]);self.check(g)

    def test_spell_discount_does_not_apply_to_hero(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-4,card_types=(CardType.SPELL,)),uses_remaining=1)])
        g=self.game(hand=('discount','SC_400'));self.play(g,'discount');self.play(g,'SC_400')
        self.assertEqual(g.state.players[1].mana,3);self.assertEqual(len(g.state.players[1].cost_modifiers),1)

    def test_failed_hero_battlecry_restores_hero_power_class_hand_and_rng(self):
        self.hero(callback=lambda c:[Summon(1,'missing')]);g=self.game(hand=('custom',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'custom')
        self.assertEqual(before,g.snapshot())

    def test_stimpack_buffs_new_marine_existing_terran_only(self):
        g=self.game(hand=('SC_400',),board=('SC_403a','plain','SC_403'),enemy=('SC_403a',))
        self.play(g,'SC_400');self.use(g)
        board=[g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(e.card_id,e.attack) for e in board],[('SC_403a',4),('plain',1),('SC_403',0),('SC_403t',4)])
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].attack,2);self.check(g)

    def test_stimpack_can_buff_existing_minions_when_board_full(self):
        g=self.game(hand=('SC_400',),board=('SC_403a',)*7);self.play(g,'SC_400');self.use(g)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertTrue(all(g.state.entities[i].attack==4 for i in g.state.players[1].board));self.check(g)

    def test_stimpack_does_not_buff_construction(self):
        g=self.built(extra=('SC_400',));self.play(g,'SC_400');self.use(g)
        self.assertEqual(construction(g.state,1).attack,2);self.check(g)

    def test_launch_records_owner_components_and_immutable_snapshot(self):
        g=self.built(extra=('kill',));ship=self.launch(g);record=g.state.starship_history[0]
        self.play(g,'kill',ship)
        self.assertEqual(g.state.starship_history,[record]);self.assertEqual(record.components,('SC_403a',))
        self.assertEqual(record.player_id,1);self.check(g)

    def test_failed_and_absent_launches_do_not_add_history(self):
        g=self.game();before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(LaunchStarship(1,self.current(g).id))
        self.assertEqual(before,g.snapshot());self.play_no_history(g)

    def play_no_history(self,g):
        self.assertEqual(g.state.starship_history,[])

    def test_raynor_relaunch_creates_fresh_ship_and_reexecutes_effect(self):
        g=self.built(extra=('SC_400',));ship=self.launch(g);self.cycle(g);self.play(g,'SC_400')
        ships=[g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual(len(ships),2);self.assertNotEqual(ships[1].id,ship)
        self.assertEqual(ships[1].components,('SC_403a',))
        self.assertEqual(self.current(g).armor,15);self.assertEqual(len(g.state.starship_history),1)
        self.assertEqual(sum(e.kind=='starship_launched' for e in g.events),1)
        self.assertEqual(sum(e.kind=='starship_relaunched' for e in g.events),1);self.check(g)

    def test_relaunch_does_not_copy_post_launch_buffs_or_damage(self):
        self.spell('buff',lambda c:[Buff(c.target_id,attack=7,health=5),Damage(c.target_id,1)],requires_target=True)
        g=self.built(extra=('buff','relaunch'));ship=self.launch(g);self.play(g,'buff',ship);self.play(g,'relaunch')
        fresh=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((fresh.attack,fresh.health,fresh.damage),(2,1,0));self.check(g)

    def test_relaunch_does_not_consume_future_launch_discount(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-2),uses_remaining=1,scope=CostScope.STARSHIP_LAUNCH)])
        g=self.built(extra=('discount','relaunch'));self.launch(g);self.play(g,'discount');self.play(g,'relaunch')
        self.assertEqual(len(g.state.players[1].cost_modifiers),1);self.check(g)

    def test_relaunch_does_not_touch_current_construction(self):
        g=self.built(extra=('SC_403a','kill','relaunch'));self.launch(g);self.play(g,'SC_403a')
        piece=g.state.players[1].board[-1];self.play(g,'kill',piece);building=construction(g.state,1).id
        self.play(g,'relaunch');self.assertEqual(construction(g.state,1).id,building);self.check(g)

    def test_repeated_relaunch_does_not_multiply_history(self):
        g=self.built(extra=('relaunch','relaunch'));self.launch(g);self.play(g,'relaunch');self.play(g,'relaunch')
        self.assertEqual(len(g.state.starship_history),1);self.assertEqual(len(g.state.players[1].board),3);self.check(g)

    def test_opponent_does_not_receive_players_history(self):
        self.spell('other_relaunch',lambda c:[RelaunchStarships(2)])
        g=self.built(extra=('other_relaunch',));self.launch(g);self.play(g,'other_relaunch')
        self.assertEqual(g.state.players[2].board,[]);self.check(g)

    def test_full_board_relaunch_skips_without_history_or_fee(self):
        self.spell('fill',lambda c:[Summon(1,'plain') for _ in range(7)])
        g=self.built(extra=('fill','relaunch'));self.launch(g);self.play(g,'fill');mana=g.state.players[1].mana
        self.play(g,'relaunch');self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(len(g.state.starship_history),1);self.assertEqual(g.state.players[1].mana,mana);self.check(g)

    def test_pending_hero_battlecry_saves_replacement_and_resumes_once(self):
        self.hero(callback=lambda c:[RequestChoice(1,(ChoiceOption('a','Armor',effects=(GainArmor(1,2),)),),source_id=c.source_id)])
        g=self.game(hand=('custom',));self.play(g,'custom');self.assertIsNotNone(g.state.pending_choice)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for game in (g,restored):game.apply(SelectChoice(1,game.state.pending_choice.id,('a',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.current(g).armor,7);self.check(g)

    def test_player_port_plays_hero_and_uses_stimpack(self):
        g=self.game(hand=('SC_400',));port=g.for_player(1)
        for kind in ('play_card','use_hero_power'):
            listing=port.legal_actions();a=next(a for a in listing['actions'] if a['type']==kind)
            self.assertTrue(port.submit({'revision':listing['revision'],'action':a})['accepted'])
        self.assertEqual(self.current(g).card_id,'SC_400');self.check(g)

    def test_hidden_hero_card_does_not_leak_via_blind_target_legality(self):
        kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO)
        self.spell('blind',lambda c:[],targeting=TargetSpec(zones=(Zone.HAND,),kinds=kinds,relation='enemy'))
        a=self.game(hand=('blind',),enemy_hand=('SC_400',));b=self.game(hand=('blind',),enemy_hand=('CS2_029',))
        self.assertEqual(a.for_player(1).legal_actions(),b.for_player(1).legal_actions())

    def test_corrupt_history_is_rejected_after_hash_recomputed(self):
        g=self.built();self.launch(g)
        for key,value in [('id',2),('player_id',3),('entity_id',999),('card_id','plain'),('components',[]),('turn',99),('action',999)]:
            row=deepcopy(g.snapshot());row['state']['starship_history'][0][key]=value
            row['state_hash']=canonical_hash({k:v for k,v in row.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.subTest(key=key),self.assertRaises(SnapshotError):Game.from_snapshot(row,self.r)

    def test_hero_definition_constraints_are_explicit(self):
        for fields in ({'hero_card':1},{'hero_armor':-1},{'keep_hero_class':1},{'initial_hero_power':None}):
            defaults=dict(health=30,hero_card=True,initial_hero_power='HERO_01bp');defaults.update(fields)
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('bad','Bad',CardType.HERO,**defaults))

    def test_hero_card_is_valid_in_constructed_deck_and_opening(self):
        from hs_sim.engine import DeckPolicy,DeckSpec,MatchSetup,validate_deck
        policy=DeckPolicy('heroes','t','experimental',('SC_400','SC_401','SC_411','SC_403','CORE_REV_990'),deck_size=8)
        cards=('SC_400','SC_401','SC_401','SC_411','SC_411','SC_403','SC_403','CORE_REV_990')
        deck=DeckSpec('HERO_01','HERO_01bp',CardClass.WARRIOR,cards)
        self.assertTrue(validate_deck(deck,self.r,policy).valid)
        duplicate=replace(deck,cards=('SC_400','SC_400',*cards[2:]))
        self.assertFalse(validate_deck(duplicate,self.r,policy).valid)
        game=Game.from_decks(MatchSetup((deck,deck),policy,'GAME_005',seed=2),self.r);self.check(game)

    def test_current_class_drives_zone_query_after_raynor(self):
        from hs_sim.engine import DrawMatching, PoolQuery
        self.spell('classdraw',lambda c:[DrawMatching(1,PoolQuery(class_mode='current',include_neutral=False),empty_deck='skip')])
        g=self.game(hand=('SC_400','classdraw'),deck=('CS2_029','SC_411'))
        self.play(g,'SC_400');self.play(g,'classdraw')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['SC_411']);self.check(g)

    def test_current_class_drives_static_generation_after_raynor(self):
        from hs_sim.engine import GenerateFromPool, PoolCard, PoolDefinition, PoolMember, PoolQuery, GenerationContext
        for cid in ('CS2_029','SC_411','SC_400'):
            if cid not in self.r.pool_cards:self.r.register_pool_card(PoolCard.from_definition(self.r.card(cid)))
        self.r.register_pool(PoolDefinition('heroes','v1','t','experimental',tuple(PoolMember(i) for i in ('CS2_029','SC_411','SC_400'))))
        self.spell('generatehero',lambda c:[GenerateFromPool(1,'heroes',PoolQuery(kinds=(CardType.HERO,),class_mode='current',include_neutral=False))])
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('SC_400','generatehero'),mana=10,max_mana=10),
            PlayerSetup('HERO_08')),generation_context=GenerationContext('t','experimental')),self.r)
        self.play(g,'SC_400');self.play(g,'generatehero')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['SC_400']);self.check(g)

    def test_multiple_launches_preserve_duplicate_compositions(self):
        g=self.built(extra=('SC_403a','kill','relaunch'));self.launch(g)
        self.play(g,'SC_403a');self.play(g,'kill',g.state.players[1].board[-1]);self.cycle(g);self.launch(g)
        self.play(g,'relaunch');self.assertEqual(len(g.state.starship_history),2)
        self.assertEqual(len(g.state.players[1].board),4);self.check(g)

    def test_exodar_free_launch_is_recorded_for_raynor(self):
        g=self.built(extra=('GDB_120','SC_400'));self.play(g,'GDB_120')
        self.assertEqual(len(g.state.starship_history),1)
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,('GDB_100a',)))
        self.cycle(g);self.play(g,'SC_400')
        self.assertEqual(sum(e.kind=='starship_relaunched' for e in g.events),1);self.check(g)

    def test_pending_relaunch_keeps_original_history_and_remaining_queue(self):
        self.r.register_behavior('ask',lambda c:[RequestChoice(1,(ChoiceOption('a','A',effects=(GainArmor(1,1),)),),source_id=c.source_id)])
        self.r.register_card(CardDefinition('piece','Piece',CardType.MINION,attack=1,health=1,
            keywords=(Keyword.STARSHIP_PIECE,),on_launch='ask'))
        g=self.built(extra=('relaunch',),piece='piece');self.launch(g)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('a',)));self.play(g,'relaunch')
        self.assertIsNotNone(g.state.pending_choice);restored=Game.from_snapshot(g.snapshot(),self.r)
        for game in (g,restored):game.apply(SelectChoice(1,game.state.pending_choice.id,('a',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(g.state.starship_history),1);self.check(g)

    def test_failed_relaunch_rolls_back_new_ship_history_and_rng(self):
        self.r.register_behavior('once',lambda c:[GainArmor(1,1)] if c.event.kind=='starship_launched' else [Summon(1,'missing')])
        self.r.register_card(CardDefinition('piece','Piece',CardType.MINION,attack=1,health=1,
            keywords=(Keyword.STARSHIP_PIECE,),on_launch='once'))
        g=self.built(extra=('relaunch',),piece='piece');self.launch(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'relaunch')
        self.assertEqual(before,g.snapshot())

    def test_failed_launch_does_not_leave_history(self):
        self.r.register_behavior('badlaunch',lambda c:[Summon(1,'missing')])
        self.r.register_card(CardDefinition('piece','Piece',CardType.MINION,attack=1,health=1,
            keywords=(Keyword.STARSHIP_PIECE,),on_launch='badlaunch'))
        g=self.built(piece='piece');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.launch(g)
        self.assertEqual(before,g.snapshot());self.assertEqual(g.state.starship_history,[])

    def test_local_hero_cost_attachment_is_allowed_while_in_hand(self):
        self.spell('cheap',lambda c:[ModifyCost(c.state.players[1].hand[-1],CostSpec(delta=-5))])
        g=self.game(hand=('cheap','SC_400'));self.play(g,'cheap');self.play(g,'SC_400')
        self.assertEqual(g.state.players[1].mana,8);self.check(g)

    def test_non_playable_hero_cannot_enter_generation_pool_as_hand_card(self):
        from hs_sim.engine import GenerateFromPool,PoolCard,PoolDefinition,PoolMember,PoolQuery,GenerationContext
        self.r.register_pool_card(PoolCard.from_definition(self.r.card('HERO_01')))
        self.r.register_pool(PoolDefinition('bad','v1','t','experimental',(PoolMember('HERO_01'),)))
        self.spell('badpool',lambda c:[GenerateFromPool(1,'bad',PoolQuery())])
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('badpool',)),PlayerSetup('HERO_08')),
            generation_context=GenerationContext('t','experimental')),self.r);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'badpool')
        self.assertEqual(before,g.snapshot())

    def test_hero_card_preserves_nonstandard_starting_max_health(self):
        self.r.register_card(replace(self.r.card('HERO_01'),id='forty',health=40))
        g=Game.from_scenario(Scenario((PlayerSetup('forty',hand=('hurt','SC_400'),mana=10,max_mana=10),
            PlayerSetup('HERO_08'))),self.r)
        self.play(g,'hurt');self.play(g,'SC_400')
        self.assertEqual((self.current(g).health,self.current(g).max_health),(34,40));self.check(g)

    def test_corrupt_current_class_is_rejected(self):
        g=self.game();row=g.snapshot();row['state']['players']['1']['hero_class']='mage'
        row['state_hash']=canonical_hash({k:v for k,v in row.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(row,self.r)

    def test_real_raynor_example_uses_players_restores_and_replays(self):
        from examples.relaunch_with_raynor import run
        g,snapshot=run();self.assertEqual((len(g.history),len(g.events)),(7,65))
        self.assertEqual(sum(e.kind != 'armor_gain_recorded' for e in g.events),60)
        self.assertEqual(sum(e.kind == 'armor_gain_recorded' for e in g.events),5)
        self.assertEqual(sum(e.kind == 'health_resolved' for e in g.events), 2)
        self.assertEqual(snapshot['schema_version'],SNAPSHOT_SCHEMA_VERSION)

    def test_raynor_armor_witness_control_preserves_actual_gameplay(self):
        from unittest.mock import patch
        from examples.relaunch_with_raynor import run
        # Controlled bookkeeping comparison, not a claim to execute an old
        # commit. The original mutators still own every balance and checkpoint.
        with patch('hs_sim.engine.armor_gains.commit', return_value=None), patch(
                'hs_sim.engine.armor_gains.validate_boundary', return_value=None):
            control,control_snapshot=run()
        actual,actual_snapshot=run()
        self.assertEqual((len(control.events),len(actual.events)),(60,65))
        self.assertEqual(len(actual.state.armor_gain_history),5)
        def headers(g):
            return [(e.action,e.kind,e.source_id,e.target_id,e.player_id,e.amount)
                for e in g.events if e.kind!='armor_gain_recorded']
        self.assertEqual(headers(actual),headers(control))
        self.assertEqual(actual.state.entities,control.state.entities)
        self.assertEqual(actual.state.players,control.state.players)
        self.assertEqual(actual_snapshot['rng_state'],control_snapshot['rng_state'])
        for player in (1,2):
            self.assertEqual(actual.for_player(player).observe(),control.for_player(player).observe())
            def projected(g):
                return [{k:v for k,v in e.items() if k!='sequence'} for e in g.player_events(player)]
            self.assertEqual(projected(actual),projected(control))


if __name__=='__main__':
    unittest.main()
