"""Independent Prepare behavior and its required persistence/lifecycle paths."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game,
    HandActionSpec, IllegalAction, PlayCard, PlayerSetup, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHandAction, Zone)
from hs_sim.engine.effects import (ChoiceOption, Draw, GainArmor, GainTemporaryMana,
    ModifyCost, RequestChoice, ReturnToHand, ShuffleIntoDeck)
from hs_sim.engine.model import HandPreparation
from hs_sim.engine.prepare import validate_boundary
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import entity_from_dict, entity_to_dict
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest


FIXTURE = Path(__file__).resolve().parents[1]/'data/support/prepare-basics.json'
FIXTURE_PIN = '7629d36d8aaa77132051ee7f878e6b454da2245fdfefc4aebeac9a3c48d6fb77'
REAL_ID = 'CATA_EVENT_401'
PREPARE = HandActionSpec('prepare', 'prepare', 1)


def real_card():
    evidence = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(evidence) != FIXTURE_PIN:
        raise ValueError('Prepare representative evidence changed')
    row = next(r for r in evidence['records'] if r['id'] == REAL_ID)
    raw = row['data']
    if canonical_digest(raw) != row['data_sha256']:
        raise ValueError('Prepare raw card pin differs')
    tags = raw['tags']
    if tags['PREPARE'] != 1 or raw['type'] != 'MINION':
        raise ValueError('Prepare representative no longer matches its adapter')
    return CardDefinition(REAL_ID, raw['name'], CardType.MINION,
        cost=tags['COST'], attack=tags['ATK'], health=tags['HEALTH'],
        spell_damage=tags['SPELLPOWER'], hand_actions=(PREPARE,))


class PrepareBasicsTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('prepare-basics-v1')
        self.r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.r.register_card(CardDefinition('plain', 'plain', CardType.MINION, cost=1, attack=1, health=3))
        self.r.register_card(real_card())
        for name, cost in (('big', 8), ('cheap', 1), ('zero', 0)):
            self.r.register_card(CardDefinition(name, name, CardType.MINION,
                cost=cost, attack=2, health=3, hand_actions=(PREPARE,)))
        self.r.register_behavior('played', lambda c: [GainArmor(c.player_id, 5)])
        self.r.register_card(CardDefinition('spell', 'spell', CardType.SPELL,
            cost=4, on_play='played', hand_actions=(PREPARE,)))

    def script(self, callback, *, owner='script'):
        self.r.register_behavior(owner, callback)
        self.r.register_card(CardDefinition(owner, owner, CardType.SPELL, on_play=owner))

    def game(self, hand=(REAL_ID,), mana=10, board=(), enemy_hand=(), deck=('plain',)*4):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand,
            board=board, deck=deck, mana=mana, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, deck=('plain',)*4,
                        mana=10, max_mana=10)), seed=7), self.r)

    def source(self, g, name=REAL_ID, player=1):
        return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)

    def use(self, g, source=None):
        source = source if source is not None else self.source(g)
        return g.apply(UseHandAction(g.state.active_player, source, 'prepare'))

    def next_own_turn(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def cast(self, g, name='script'):
        return g.apply(PlayCard(g.state.active_player,
            self.source(g, name, g.state.active_player)))

    def assert_restoration(self, g):
        saved = g.snapshot()
        self.assertEqual(Game.from_snapshot(saved, self.r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), saved)

    def test_real_representative_matches_full_pinned_face(self):
        card = real_card()
        self.assertEqual((card.name, card.cost, card.attack, card.health, card.spell_damage),
                         ('坑道地卜师', 3, 2, 3, 1))
        self.assertEqual(card.hand_actions, (PREPARE,))

    def test_prepare_spec_rejects_extra_fee_body_rule_and_upgrade(self):
        for values in ({'cost':0}, {'cost':2}, {'on_use':'played'},
                       {'use_rule':'other'}, {'upgrade_card_id':'plain'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(PREPARE, **values)
        for kind in (CardType.WEAPON, CardType.LOCATION):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('bad', 'bad', kind,
                    durability=3, hand_actions=(PREPARE,)))

    def test_remaining_mana_investment_has_immediate_bonus_discount(self):
        g = self.game(hand=('big',), mana=3); source = self.source(g, 'big')
        before = g.snapshot()
        self.assertEqual(g.quote_hand_action(source, 'prepare').amount, 3)
        self.assertEqual(g.snapshot(), before)
        self.use(g, source)
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(g.quote_cost(source).amount, 4)
        self.assertEqual(g.state.entities[source].preparation.mana_spent, 3)

    def test_investment_caps_at_current_cost_minus_one(self):
        g = self.game(); source = self.source(g)
        self.assertEqual(g.quote_hand_action(source, 'prepare').amount, 2)
        self.use(g)
        self.assertEqual((g.state.players[1].mana, g.quote_cost(source).amount), (8,0))

    def test_one_cost_card_spends_one_mana_with_zero_floor(self):
        g = self.game(hand=('cheap',)); source = self.source(g, 'cheap')
        self.assertEqual(g.quote_hand_action(source, 'prepare').amount, 1)
        self.use(g, source)
        self.assertEqual((g.state.players[1].mana, g.quote_cost(source).amount), (9,0))

    def test_zero_mana_or_zero_cost_is_illegal_without_changes(self):
        for hand, mana in (((REAL_ID,),0), (('zero',),10)):
            with self.subTest(hand=hand,mana=mana):
                g=self.game(hand=hand,mana=mana); source=g.state.players[1].hand[0]
                before=g.snapshot()
                self.assertNotIn(UseHandAction(1,source,'prepare'),g.legal_actions())
                with self.assertRaises(IllegalAction):self.use(g,source)
                self.assertEqual(g.snapshot(),before)

    def test_once_per_physical_card_persists_into_later_turns(self):
        g=self.game(hand=('big',),mana=1); source=self.source(g,'big');self.use(g,source)
        self.next_own_turn(g)
        self.assertEqual(g.quote_cost(source).amount,6)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g,source)
        self.assertEqual(g.snapshot(),before)
        self.assertNotIn(UseHandAction(1,source,'prepare'),g.legal_actions())

    def test_same_turn_play_lock_then_normal_play_on_later_turn(self):
        g=self.game();source=self.source(g);self.use(g)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source))
        self.assertEqual(g.snapshot(),before)
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==source for a in g.legal_actions()))
        self.next_own_turn(g);g.apply(PlayCard(1,source))
        self.assertIn(source,g.state.players[1].board)
        self.assertEqual(g.state.play_history[-1].cost,0)
        self.assert_restoration(g)

    def test_unprepared_card_can_be_played_normally(self):
        g=self.game();source=self.source(g);g.apply(PlayCard(1,source))
        self.assertEqual(g.state.players[1].mana,7)
        self.assertIsNone(g.state.entities[source].preparation)

    def test_prepare_does_not_play_draw_shuffle_or_use_rng(self):
        g=self.game(deck=());before=g.snapshot();source=self.source(g);self.use(g)
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])
        self.assertEqual(g.state.players[1].hand,[source])
        self.assertEqual(g.state.players[1].deck,[])
        self.assertEqual(g.state.players[1].fatigue,0)
        self.assertEqual(g.state.hand_entries, Game.from_snapshot(before,self.r).state.hand_entries)
        self.assertEqual(g.state.play_history,[])
        self.assertEqual(g.state.entities[source].zone_epoch,
                         before['state']['entities'][str(source)]['zone_epoch'])

    def test_temporary_mana_is_paid_before_regular_mana(self):
        self.script(lambda c:[GainTemporaryMana(c.player_id,3)])
        g=self.game(hand=('big','script'),mana=2);self.cast(g);source=self.source(g,'big')
        self.assertEqual(g.quote_hand_action(source,'prepare').amount,5)
        self.use(g,source);p=g.state.players[1]
        self.assertEqual((p.mana,p.temporary_mana,p.mana_spent),(0,0,10))
        self.assertEqual(g.quote_cost(source).amount,2)

    def test_current_card_cost_bounds_investment(self):
        self.script(lambda c:[ModifyCost(next(i for i in c.state.players[1].hand
            if c.state.entities[i].card_id=='big'),CostSpec(delta=-3))])
        g=self.game(hand=('big','script'));self.cast(g);source=self.source(g,'big')
        self.assertEqual(g.quote_hand_action(source,'prepare').amount,4)
        self.use(g,source)
        self.assertEqual((g.state.players[1].mana,g.quote_cost(source).amount),(6,0))

    def test_prepare_spell_does_not_execute_its_play_body(self):
        g=self.game(hand=('spell',));source=self.source(g,'spell');self.use(g,source)
        hero=g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].armor,0)
        self.next_own_turn(g);g.apply(PlayCard(1,source))
        self.assertEqual(g.state.entities[hero].armor,5)

    def test_prepare_ignores_play_target_and_board_capacity(self):
        self.r.register_card(CardDefinition('targeted','targeted',CardType.SPELL,
            cost=4,requires_target=True,hand_actions=(PREPARE,)))
        g=self.game(hand=('targeted',REAL_ID),board=('plain',)*7)
        self.use(g,self.source(g,'targeted'));self.use(g)
        self.assertEqual(len(g.state.players[1].board),7)

    def test_prepared_snapshot_clone_and_replay_preserve_lock(self):
        g=self.game();self.use(g);self.assert_restoration(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        with self.assertRaises(IllegalAction):restored.apply(PlayCard(1,self.source(restored)))
        self.next_own_turn(restored)
        restored.apply(PlayCard(1,self.source(restored)))

    def test_copy_preserves_discount_once_state_and_global_turn_lock(self):
        self.script(lambda c:[CopyCard(CardReference.capture(next(e for e in c.state.entities.values()
            if e.card_id==REAL_ID and e.zone==Zone.HAND)),c.player_id,Zone.HAND)])
        g=self.game(hand=(REAL_ID,'script'));self.use(g);self.cast(g)
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==REAL_ID]
        self.assertEqual(len(ids),2)
        self.assertNotEqual(g.state.entities[ids[0]].preparation.cost_id,
                            g.state.entities[ids[1]].preparation.cost_id)
        for source in ids:
            self.assertEqual(g.quote_cost(source).amount,0)
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source))
        self.assert_restoration(g)

    def test_hidden_hand_transfer_is_playable_on_another_global_turn(self):
        self.script(lambda c:[MoveCard(CardReference.capture(next(e for e in c.state.entities.values()
            if e.card_id==REAL_ID and e.zone==Zone.HAND)),c.player_id,Zone.HAND)],owner='steal')
        g=self.game(enemy_hand=('steal',));self.use(g);source=self.source(g);g.apply(EndTurn(1))
        self.cast(g,'steal');g.apply(PlayCard(2,source))
        self.assertIn(source,g.state.players[2].board)
        self.assert_restoration(g)

    def test_shuffle_resets_prepare_and_discount(self):
        self.script(lambda c:[ShuffleIntoDeck(next(i for i in c.state.players[1].hand
            if c.state.entities[i].card_id==REAL_ID)),Draw(c.player_id)])
        g=self.game(hand=(REAL_ID,'script'),deck=());self.use(g);source=self.source(g);self.cast(g)
        self.assertEqual(self.source(g),source)
        self.assertIsNone(g.state.entities[source].preparation)
        self.assertEqual(g.quote_cost(source).amount,3)
        self.use(g);self.assertEqual(g.quote_cost(source).amount,0)

    def test_bounce_resets_prepare_to_unprepared_printed_face(self):
        self.script(lambda c:[ReturnToHand(next(i for i in c.state.players[1].board
            if c.state.entities[i].card_id==REAL_ID))])
        g=self.game(hand=(REAL_ID,'script'));source=self.source(g);self.use(g)
        self.next_own_turn(g);g.apply(PlayCard(1,source));self.cast(g)
        self.assertIsNone(g.state.entities[source].preparation)
        self.assertEqual(g.quote_cost(source).amount,3)
        self.assertIn(UseHandAction(1,source,'prepare'),g.legal_actions())

    def test_owner_prices_and_state_are_private_but_spent_mana_is_public(self):
        g=self.game();source=self.source(g)
        own=g.observe(1)['players'][0]['hand'][0]
        self.assertEqual(own['hand_actions'][0]['cost']['amount'],2)
        self.use(g)
        own=g.observe(1)['players'][0]['hand'][0]
        self.assertEqual(own['preparation'],{'turn':1,'mana_spent':2,'playable':False})
        enemy=g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(set(enemy),{'ref','card_id'});self.assertIsNone(enemy['card_id'])
        event=next(e for e in g.player_events(2) if e['kind']=='card_prepared')
        self.assertEqual(event['amount'],2)
        self.assertIsNone(event['source']);self.assertIsNone(event['target'])
        self.assert_restoration(g)

    def test_player_commands_share_prepare_and_play_lock_legality(self):
        g=self.game();port=g.for_player(1);view=port.observe()
        command=next(a for a in port.legal_actions()['actions'] if a['type']=='use_hand_action')
        result=port.submit({'revision':view['revision'],'action':command})
        self.assertTrue(result['accepted'])
        self.assertFalse(any(a['type']=='play_card' for a in port.legal_actions()['actions']))

    def test_strict_preparation_codec_and_boundary_link(self):
        g=self.game();self.use(g);source=self.source(g);entity=g.state.entities[source]
        row=entity_to_dict(entity)
        self.assertEqual(entity_from_dict(row).preparation,entity.preparation)
        for change in ({'turn':True},{'mana_spent':0},{'cost_id':False},{'extra':1}):
            bad=json.loads(json.dumps(row));bad['preparation'].update(change)
            with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):
                entity_from_dict(bad)
        original=g._state.entities[source].preparation
        for value in (replace(original,turn=2),replace(original,mana_spent=3),
                      replace(original,cost_id=99999)):
            g._state.entities[source].preparation=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate_boundary(g)
            with self.subTest(restored=value),self.assertRaises(SnapshotError):
                Game.from_snapshot(g.snapshot(),self.r)
        g._state.entities[source].preparation=original
        self.assert_restoration(g)

    def test_previous_schema_is_rejected(self):
        g=self.game();self.use(g);snapshot=g.snapshot();self.assertEqual(snapshot['schema_version'],265)
        snapshot['schema_version']=149
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,self.r)

    def test_failing_post_prepare_reaction_rolls_back_everything(self):
        def fail(c):raise ValueError('prepare fixture failure')
        self.r.register_behavior('fail',fail)
        self.r.register_card(CardDefinition('watcher','watcher',CardType.MINION,
            attack=1,health=3,triggers=(TriggerSpec('card_prepared','fail'),)))
        g=self.game(board=('watcher',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_waiting_reaction_restores_prepare_without_paying_twice(self):
        self.r.register_behavior('wait',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('armor','armor',(GainArmor(c.player_id,2),)),))])
        self.r.register_card(CardDefinition('watcher','watcher',CardType.MINION,
            attack=1,health=3,triggers=(TriggerSpec('card_prepared','wait'),)))
        g=self.game(board=('watcher',));self.use(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,8)
        self.assert_restoration(g)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),before)
        restored=Game.from_snapshot(before,self.r);choice=restored.state.pending_choice
        restored.apply(SelectChoice(1,choice.id,('armor',)))
        self.assertEqual(restored.state.players[1].mana,8)
        self.assertEqual(restored.state.entities[self.source(restored)].preparation.mana_spent,2)
        self.assertEqual(restored.state.entities[restored.state.players[1].hero_id].armor,2)
        self.assert_restoration(restored)


if __name__ == '__main__':
    unittest.main()
