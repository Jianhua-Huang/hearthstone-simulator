"""Hand operations across legality, payment, lifecycle, information and replay."""
from dataclasses import dataclass, replace
import json
import random
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, Game, HandActionSpec, IllegalAction,
    AbilityInstance, Enchantment, Keyword, PaymentType, PlayCard, PlayerSetup, Registry, ResolutionError, Ruleset, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, UseHandAction, Zone)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (AddCostModifier, Buff, ChoiceOption, Damage, Draw, GainArmor,
    Effect, GainTemporaryMana, GrantDeathrattle, GrantKeyword, GrantTrigger, ModifyCost, RequestChoice,
    RevealHandCard, ShuffleIntoDeck)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.lifecycle import attachment_id, refresh_entity


@dataclass(frozen=True)
class StoredAttachmentFixture(Effect):
    target_id: int


def stored_attachment_fixture(r, effect):
    # Construct a pre-existing enchanted hand card through a trusted test effect.
    # Public Buff/Grant effects currently target the board; do not change their
    # departed-target contract merely to arrange this preservation scenario.
    card = r.state.entities[effect.target_id]
    card.enchantments.append(Enchantment(attachment_id(r.state), attack=2, health=4))
    card.abilities.extend((
        AbilityInstance(attachment_id(r.state), 'keyword', keyword=Keyword.TAUNT),
        AbilityInstance(attachment_id(r.state), 'deathrattle', behavior_id='played')))
    refresh_entity(card)



class HandActionTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('hand-tests-v1')
        self.mechanics = default_mechanics('hand-tests-effects-v15')
        self.mechanics.register(StoredAttachmentFixture, stored_attachment_fixture)
        self.registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.registry.register_behavior('played', lambda c: [GainArmor(c.player_id, 99)])
        self.registry.register_card(CardDefinition('plain', 'plain', CardType.MINION, cost=1, attack=1, health=2))
        self.registry.register_card(CardDefinition('trade', 'trade', CardType.SPELL, cost=7,
            on_play='played', hand_actions=(HandActionSpec('trade', 'trade', 1),)))
        self.registry.register_card(CardDefinition('forge', 'forge', CardType.MINION, cost=3, attack=3, health=3,
            on_play='played', hand_actions=(HandActionSpec('forge', 'forge', 2, 'forged'),)))
        self.registry.register_card(CardDefinition('forged', 'forged', CardType.MINION, cost=3, attack=6, health=5,
            keywords=(Keyword.RUSH,), on_play='played'))

    def card(self, card_id, **changes):
        # Add a variant rather than mutating the frozen public registry mapping.
        base = self.registry.card(changes.pop('base', card_id))
        self.registry.register_card(replace(base, id=card_id, **changes))

    def script(self, callback):
        self.registry.register_behavior('script', callback)
        self.registry.register_card(CardDefinition('script', 'script', CardType.SPELL, on_play='script'))

    def watcher(self, event, callback):
        name = 'watch_' + event
        self.registry.register_behavior(name, callback)
        self.registry.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=3,
            triggers=(TriggerSpec(event, name),)))
        return name

    def game(self, hand=('trade',), deck=('plain',), enemy_hand=(), board=(), mana=10, seed=17, rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, deck=deck, board=board,
            max_mana=10, mana=mana), PlayerSetup('hero', hand=enemy_hand)), seed=seed), self.registry, rules, self.mechanics)

    def use(self, g, kind, index=0):
        return g.apply(UseHandAction(1, g.state.players[1].hand[index], kind))

    def cast_script(self, g):
        i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'script')
        return g.apply(PlayCard(1, i))

    def replay(self, g):
        self.assertEqual(replay(build_replay(g), self.registry, self.mechanics).snapshot(), g.snapshot())

    def submit(self, g, kind, viewer=1, ref=None):
        port = g.for_player(viewer)
        view = port.observe()
        if ref is None:
            ref = view['observation']['players'][viewer - 1]['hand'][0]['ref']
        return port.submit({'revision': view['revision'], 'action': {
            'type': 'use_hand_action', 'card': ref, 'action_id': kind}})

    def test_strict_action_codec(self):
        action = UseHandAction(1, 3, 'forge')
        self.assertEqual(action_from_dict(json.loads(json.dumps(action_to_dict(action)))), action)
        row = action_to_dict(action)
        for mutation in ({'player_id': True}, {'entity_id': False}, {'action_id': ''},
                         {'action_id': 1}, {'target_id': 3}, {'position': 0}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                action_from_dict({**row, **mutation})

    def test_declaration_validation(self):
        invalid = [lambda: HandActionSpec('', 'trade', 1), lambda: HandActionSpec('x', 'secret', 1),
            lambda: HandActionSpec('x', 'forge', 2), lambda: HandActionSpec('x', 'trade', True),
            lambda: HandActionSpec('x', 'trade', -1), lambda: HandActionSpec('x', 'trade', 1, 'forged'),
            lambda: HandActionSpec('x', 'forge', 2, ''), lambda: HandActionSpec('x', 'trade', 1, use_rule='')]
        for fn in invalid:
            with self.subTest(fn=fn), self.assertRaises(ValueError): fn()
        with self.assertRaises(ValueError):
            self.card('bad', base='hero', hand_actions=(HandActionSpec('t', 'trade', 1),))
        with self.assertRaises(ValueError):
            self.card('bad', base='trade', hand_actions=(HandActionSpec('t', 'trade', 1),)*2)

    def test_registry_rejects_unknown_upgrade_before_any_match(self):
        self.card('bad', base='forge', hand_actions=(HandActionSpec('f', 'forge', 2, 'missing'),))
        with self.assertRaises(ValueError): self.game()

    def test_registry_rejects_cross_type_upgrade(self):
        self.card('bad', base='forge', hand_actions=(HandActionSpec('f', 'forge', 2, 'trade'),))
        with self.assertRaises(ValueError): self.game()

    def test_registry_validates_hand_rule_and_callback_references(self):
        for field in ('use_rule', 'on_use'):
            with self.subTest(field=field):
                self.setUp()
                self.card('bad', base='trade', hand_actions=(HandActionSpec('t', 'trade', 1, **{field: 'missing'}),))
                with self.assertRaises(ValueError): self.game()

    def test_ownership_turn_zone_unknown_action_and_affordability_are_atomic(self):
        g = self.game(mana=0, enemy_hand=('trade',))
        own = g.state.players[1].hand[0]; enemy = g.state.players[2].hand[0]
        actions = [UseHandAction(1, own, 'trade'), UseHandAction(2, enemy, 'trade'),
            UseHandAction(1, enemy, 'trade'), UseHandAction(1, own, 'forge'),
            UseHandAction(1, g.state.players[1].deck[0], 'trade')]
        for action in actions:
            before = g.snapshot()
            with self.subTest(action=action), self.assertRaises(IllegalAction): g.apply(action)
            self.assertEqual(g.snapshot(), before)

    def test_trade_empty_deck_is_unavailable_and_never_causes_fatigue(self):
        g = self.game(deck=()); before = g.snapshot()
        self.assertFalse(any(isinstance(a, UseHandAction) for a in g.legal_actions()))
        with self.assertRaises(IllegalAction): self.use(g, 'trade')
        self.assertEqual(g.snapshot(), before)

    def test_full_hand_trade_frees_its_own_slot(self):
        g = self.game(hand=('trade',)+('plain',)*9)
        card, drawn = g.state.players[1].hand[0], g.state.players[1].deck[0]
        result = self.use(g, 'trade'); p = g.state.players[1]
        self.assertEqual(len(p.hand), 10); self.assertIn(drawn, p.hand); self.assertIn(card, p.deck)
        self.assertEqual(p.mana, 9); self.assertFalse(p.graveyard)
        self.assertFalse(any(e.kind in ('card_burned', 'card_played', 'card_committed') for e in result.events))
        self.assertEqual(g.state.entities[p.hero_id].armor, 0); self.replay(g)

    def test_trade_can_draw_another_physical_copy_of_the_same_definition(self):
        g = self.game(deck=('trade',)); source, other = g.state.players[1].hand[0], g.state.players[1].deck[0]
        self.use(g, 'trade')
        self.assertEqual(g.state.players[1].hand, [other]); self.assertEqual(g.state.players[1].deck, [source])

    def test_insertion_before_different_draw_preserves_other_deck_order(self):
        for seed in range(8):
            with self.subTest(seed=seed):
                g = self.game(deck=('plain',)*4, seed=seed)
                source, old = g.state.players[1].hand[0], g.state.players[1].deck
                expected = old.copy(); expected.insert(random.Random(seed).randrange(5), source)
                expected.remove(old[0])
                self.use(g, 'trade')
                self.assertEqual(g.state.players[1].hand, [old[0]])
                self.assertEqual(g.state.players[1].deck, expected)

    def test_trade_event_context_draw_sees_traded_card_in_deck(self):
        def drawn(c):
            if c.event.player_id == c.player_id:
                assert any(c.state.entities[i].card_id == 'trade' for i in c.state.players[1].deck)
                return [GainArmor(1, 1)]
            return []
        watcher = self.watcher('card_drawn', drawn)
        g = self.game(board=(watcher,)); self.use(g, 'trade')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)

    def test_trade_keeps_enchantment_ids_and_draws_them_back(self):
        self.script(lambda c: [ModifyCost(c.state.players[1].hand[0], CostSpec(delta=-4))])
        self.registry.register_behavior('draw', lambda c: [Draw(1)])
        self.registry.register_card(CardDefinition('draw', 'draw', CardType.SPELL, on_play='draw'))
        g = self.game(hand=('script','trade','draw'))
        self.cast_script(g); source = g.state.players[1].hand[0]; attachments = g.state.entities[source].enchantments
        self.use(g, 'trade'); self.assertEqual(g.state.entities[source].enchantments, attachments)
        draw = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'draw')
        g.apply(PlayCard(1, draw)); self.assertIn(source, g.state.players[1].hand)
        self.assertEqual(g.quote_cost(source).amount, 3); self.replay(g)

    def test_ordinary_shuffle_still_resets_tradeable_enchantments(self):
        self.script(lambda c: [ModifyCost(c.state.players[1].hand[0], CostSpec(delta=-4)),
                              ShuffleIntoDeck(c.state.players[1].hand[0], 1)])
        g = self.game(hand=('script','trade')); source = g.state.players[1].hand[1]
        self.cast_script(g); self.assertEqual(g.state.entities[source].cost, 7)
        self.assertFalse(g.state.entities[source].enchantments)

    def test_trade_and_forge_do_not_spend_normal_cost_modifiers_or_health(self):
        self.script(lambda c: [AddCostModifier(1, CostSpec(delta=-6, payment=PaymentType.HEALTH), uses_remaining=1),
                              ModifyCost(c.state.players[1].hand[0], CostSpec(set_to=0))])
        g = self.game(hand=('script','trade','forge'))
        self.cast_script(g); modifiers = g.state.players[1].cost_modifiers
        source = g.state.players[1].hand[0]
        self.assertEqual(g.quote_cost(source).payment, PaymentType.HEALTH)
        self.assertEqual(g.quote_hand_action(source, 'trade').amount, 1)
        self.use(g, 'trade'); self.use(g, 'forge')
        p = g.state.players[1]
        self.assertEqual(p.cost_modifiers, modifiers); self.assertEqual(p.mana, 7)
        self.assertEqual(g.state.entities[p.hero_id].health, 30)

    def test_extra_action_spends_temporary_mana_first(self):
        self.script(lambda c: [GainTemporaryMana(1, 2)])
        g = self.game(hand=('script','forge'), mana=5); self.cast_script(g); self.use(g, 'forge')
        p = g.state.players[1]; self.assertEqual(p.temporary_mana, 0); self.assertEqual(p.mana, 5)

    def test_forge_keeps_entity_and_hand_position_with_empty_deck_full_board(self):
        g = self.game(hand=('plain','forge','plain'), deck=(), board=('plain',)*7)
        old = g.state.players[1].hand; source = old[1]
        result = self.use(g, 'forge', index=1)
        self.assertEqual(g.state.players[1].hand, old)
        self.assertEqual(g.state.entities[source].card_id, 'forged')
        self.assertEqual(g.state.entities[source].attack, 6); self.assertEqual(g.state.entities[source].health, 5)
        self.assertFalse(any(e.kind in ('card_played', 'card_committed', 'minion_summoned', 'card_drawn') for e in result.events))
        self.assertFalse(any(isinstance(a, UseHandAction) for a in g.legal_actions()))

    def test_forging_upgrades_printed_rules_and_preserves_granted_attachments(self):
        self.script(lambda c: [StoredAttachmentFixture(c.state.players[1].hand[0]),
            ModifyCost(c.state.players[1].hand[0], CostSpec(delta=-1))])
        g = self.game(hand=('script','forge')); self.cast_script(g)
        source = g.state.players[1].hand[0]; old = g.state.entities[source]
        granted = [a for a in old.abilities if a.origin != 'printed']
        self.use(g, 'forge'); new = g.state.entities[source]
        self.assertEqual(new.enchantments, old.enchantments)
        self.assertEqual([a for a in new.abilities if a.origin != 'printed'], granted)
        self.assertEqual((new.attack, new.health, new.cost), (8, 9, 2))
        self.assertEqual(new.keywords, {Keyword.RUSH, Keyword.TAUNT}); self.replay(g)

    def test_playing_forged_form_uses_normal_action_and_runs_its_on_play(self):
        g = self.game(hand=('forge',)); source = g.state.players[1].hand[0]
        self.use(g, 'forge'); g.apply(PlayCard(1, source))
        self.assertIn(source, g.state.players[1].board)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 99)
        self.assertEqual(g.state.players[1].mana, 5); self.replay(g)

    def test_trade_weapon_never_equips_or_changes_current_hero_attack(self):
        self.registry.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, cost=9, attack=9,
            durability=3, hand_actions=(HandActionSpec('trade', 'trade', 1),)))
        g = self.game(hand=('weapon',)); self.use(g, 'trade')
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 0)

    def test_conditional_hand_action_uses_same_player_predicate_for_enumeration_and_submit(self):
        def available(c):
            assert isinstance(c.source, dict) and not hasattr(c, 'state')
            return c.observation['players'][0]['deck_count'] >= 2
        self.registry.register_use_rule('two', available, visibility='player')
        self.card('conditional', base='trade', hand_actions=(HandActionSpec('trade','trade',1,use_rule='two'),))
        for deck, accepted in ((('plain',), False), (('plain','plain'), True)):
            g = self.game(hand=('conditional',), deck=deck)
            enumeration = g.for_player(1).legal_actions()
            self.assertIsNone(enumeration['error'])
            self.assertEqual(any(a['type']=='use_hand_action' for a in enumeration['actions']), accepted)
            self.assertEqual(self.submit(g, 'trade')['accepted'], accepted)

    def test_legacy_omniscient_hand_predicate_is_blocked_at_player_boundary(self):
        self.registry.register_use_rule('hidden', lambda c: c.state.entities[c.state.players[2].hand[0]].card_id == 'trade')
        self.card('conditional', base='trade', hand_actions=(HandActionSpec('trade','trade',1,use_rule='hidden'),))
        g = self.game(hand=('conditional',), enemy_hand=('trade',)); before = g.snapshot()
        self.assertEqual(g.for_player(1).legal_actions()['error'], 'unsupported_rule')
        self.assertEqual(self.submit(g,'trade')['error'], 'unsupported_rule')
        self.assertEqual(g.snapshot(), before)

    def test_hand_action_does_not_require_normal_play_target(self):
        self.card('targeted', base='trade', requires_target=True)
        g = self.game(hand=('targeted',)); self.assertTrue(self.submit(g,'trade')['accepted'])

    def test_player_hand_submission_does_not_run_unrelated_legacy_play_predicate(self):
        self.registry.register_target_rule('legacy', lambda c: (_ for _ in ()).throw(RuntimeError('must not run')))
        self.card('targeted', base='trade', requires_target=True, target_rule='legacy')
        g = self.game(hand=('targeted',)); self.assertTrue(self.submit(g,'trade')['accepted'])

    def test_invalid_condition_return_is_not_truthy_or_committed(self):
        self.registry.register_use_rule('bad', lambda c: 'yes', visibility='player')
        self.card('bad', base='trade', hand_actions=(HandActionSpec('trade','trade',1,use_rule='bad'),))
        g = self.game(hand=('bad',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g,'trade')
        self.assertEqual(g.snapshot(), before)

    def test_owner_observes_prices_but_enemy_hand_has_no_action_descriptors(self):
        g = self.game(hand=('trade','forge'))
        cards = g.observe(1)['players'][0]['hand']
        self.assertEqual([c['hand_actions'][0]['cost']['amount'] for c in cards], [1,2])
        for c in g.observe(2)['players'][0]['hand']:
            self.assertEqual(set(c), {'ref','card_id'}); self.assertIsNone(c['card_id'])

    def test_hidden_forge_announces_only_slot_not_either_face(self):
        g = self.game(hand=('forge',)); old_ref = g.observe(2)['players'][0]['hand'][0]['ref']
        self.assertTrue(self.submit(g, 'forge')['accepted'])
        enemy = g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(enemy, {'ref': old_ref, 'card_id': None})
        event = next(e for e in g.player_events(2) if e['kind'] == 'card_forged')
        self.assertEqual(event['target'], enemy)
        self.assertNotIn('forged', json.dumps(g.observe(2)))

    def test_forge_retires_old_revealed_identity_without_rewriting_old_logs(self):
        self.script(lambda c: [RevealHandCard(c.state.players[1].hand[0])])
        g = self.game(hand=('script','forge')); self.cast_script(g)
        old_events = g.player_events(2)
        self.assertEqual(g.observe(2)['players'][0]['hand'][0]['card_id'], 'forge')
        self.use(g, 'forge')
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        self.assertEqual(g.player_events(2)[:len(old_events)], old_events)

    def test_trade_reveals_source_but_retires_tracking_and_keeps_draw_secret(self):
        g = self.game(); source = g.state.players[1].hand[0]
        old_ref = g.observe(2)['players'][0]['hand'][0]['ref']; self.use(g, 'trade')
        logs = g.player_events(2)
        started = next(e for e in logs if e['kind']=='trade_started')
        self.assertEqual(started['source'], {'ref': old_ref, 'card_id': 'trade'})
        drawn = next(e for e in logs if e['kind']=='card_drawn')
        self.assertIsNone(drawn['target']['card_id']); self.assertNotEqual(drawn['target']['ref'], old_ref)
        for viewer in (1,2):
            self.assertNotIn(str(source), g._information.players[viewer].refs)
        self.replay(g)

    def test_enemy_reference_cannot_probe_which_hand_actions_it_has(self):
        for enemy in ('plain','forge','trade'):
            g = self.game(enemy_hand=(enemy,)); ref = g.observe(1)['players'][1]['hand'][0]['ref']
            before = g.snapshot(); result = self.submit(g,'trade',ref=ref)
            self.assertFalse(result['accepted']); self.assertEqual(result['error'],'invalid_action')
            self.assertEqual(g.snapshot(), before)

    def test_identical_visible_views_have_identical_commands_with_different_hidden_cards(self):
        a = self.game(deck=('plain',), enemy_hand=('trade',)); b = self.game(deck=('forge',), enemy_hand=('forge',))
        self.assertEqual(a.for_player(1).legal_actions(), b.for_player(1).legal_actions())

    def test_player_commands_are_enumerated_and_stale_revision_rejected(self):
        g = self.game(hand=('forge',)); port=g.for_player(1); legal=port.legal_actions()
        command=next(a for a in legal['actions'] if a['type']=='use_hand_action')
        self.assertEqual(command['action_id'],'forge')
        self.assertTrue(port.submit({'revision':legal['revision'],'action':command})['accepted'])
        self.assertEqual(port.submit({'revision':legal['revision'],'action':command})['error'],'stale_observation')

    def test_bad_callback_rolls_back_payment_insertion_rng_events_and_knowledge(self):
        self.registry.register_behavior('fail', lambda c: (_ for _ in ()).throw(ValueError('bad extension')))
        self.card('bad', base='trade', hand_actions=(HandActionSpec('trade','trade',1,on_use='fail'),))
        g=self.game(hand=('bad',), deck=('plain',)*3); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g,'trade')
        self.assertEqual(g.snapshot(),before); self.assertFalse(g.history)

    def test_choice_from_draw_trigger_resumes_without_trading_or_paying_twice(self):
        watcher=self.watcher('card_drawn', lambda c: [RequestChoice(1, (
            ChoiceOption('armor','armor',(GainArmor(1,2),)),), source_id=c.source_id)])
        g=self.game(board=(watcher,)); self.use(g,'trade'); self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot(); restored=Game.from_snapshot(json.loads(json.dumps(before)),self.registry,self.mechanics)
        self.replay(g)
        for game in (g,restored):
            choice=game.state.pending_choice
            game.apply(SelectChoice(1,choice.id,('armor',)))
            self.assertEqual(game.state.players[1].mana,9)
            self.assertEqual(sum(e.kind=='card_traded' for e in game.events),1)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.replay(g)

    def test_on_forge_callback_choice_can_suspend_and_restore(self):
        self.registry.register_behavior('choose', lambda c: [RequestChoice(1, (
            ChoiceOption('a','a',(GainArmor(1,3),)),),source_id=c.source_id)])
        self.card('choiceforge',base='forge',hand_actions=(HandActionSpec('forge','forge',2,'forged',on_use='choose'),))
        g=self.game(hand=('choiceforge',)); self.use(g,'forge')
        restored=Game.from_snapshot(g.snapshot(),self.registry,self.mechanics); self.replay(g)
        for game in (g,restored):
            choice=game.state.pending_choice; game.apply(SelectChoice(1,choice.id,('a',)))
        self.assertEqual(g.snapshot(),restored.snapshot()); self.replay(g)

    def test_pending_choice_blocks_all_hand_actions(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('a','a',()),),source_id=c.source_id)])
        g=self.game(hand=('script','forge')); self.cast_script(g); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g,'forge')
        self.assertEqual(g.snapshot(),before)

    def test_terminal_draw_reaction_keeps_completed_trade_but_stops_own_callback(self):
        watcher=self.watcher('card_drawn',lambda c:[Damage(c.state.players[2].hero_id,40)])
        self.card('post',base='trade',hand_actions=(HandActionSpec('trade','trade',1,on_use='played'),))
        g=self.game(hand=('post',),board=(watcher,)); self.use(g,'trade')
        self.assertEqual(g.state.status,'finished'); self.assertEqual(g.state.winner,1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertEqual(len(g.state.players[1].deck),1); self.replay(g)

    def test_latest_snapshot_rejects_previous_schema(self):
        g=self.game(); row=g.snapshot(); self.assertEqual(row['schema_version'],265)
        row['schema_version']=19
        with self.assertRaises(SnapshotError): Game.from_snapshot(row,self.registry,self.mechanics)

    def test_multiple_named_alternatives_have_separate_fees_and_do_not_require_play_cost(self):
        self.card('both', base='forge', cost=10, hand_actions=(
            HandActionSpec('exchange', 'trade', 0), HandActionSpec('upgrade', 'forge', 1, 'forged')))
        g=self.game(hand=('both',),mana=1)
        ids={a.action_id for a in g.legal_actions() if isinstance(a,UseHandAction)}
        self.assertEqual(ids,{'exchange','upgrade'})
        self.assertEqual(g.quote_hand_action(g.state.players[1].hand[0],'exchange').amount,0)
        self.assertTrue(self.submit(g,'upgrade')['accepted']); self.assertEqual(g.state.players[1].mana,0)

    def test_forge_failure_rolls_back_face_attachment_allocation_and_private_knowledge(self):
        self.registry.register_behavior('fail',lambda c:[Draw(1),Damage(999999,1),object()])
        self.card('bad',base='forge',hand_actions=(HandActionSpec('forge','forge',2,'forged',on_use='fail'),))
        g=self.game(hand=('bad',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g,'forge')
        self.assertEqual(g.snapshot(),before)

    def test_trade_card_specific_callback_receives_a_captured_completed_exchange(self):
        def traded(c):
            self.assertEqual(c.source.zone,Zone.DECK)
            self.assertEqual(c.event.kind,'card_traded')
            self.assertEqual(c.state.entities[c.state.players[1].hand[0]].card_id,'plain')
            return [GainArmor(1,4)]
        self.registry.register_behavior('traded',traded)
        self.card('post',base='trade',hand_actions=(HandActionSpec('trade','trade',1,on_use='traded'),))
        g=self.game(hand=('post',)); self.use(g,'trade')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4); self.replay(g)

    def test_forge_also_supports_same_type_spell_upgrades(self):
        self.card('upgrade',base='trade',cost=2,hand_actions=())
        self.card('spellforge',base='trade',hand_actions=(HandActionSpec('forge','forge',2,'upgrade'),))
        g=self.game(hand=('spellforge',)); source=g.state.players[1].hand[0]; self.use(g,'forge')
        self.assertEqual(g.state.entities[source].card_id,'upgrade')
        self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        g.apply(PlayCard(1,source)); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,99)


class RepresentativeHandTests(unittest.TestCase):
    def test_constructed_match_uses_player_commands_choices_zones_and_terminal_replay(self):
        from examples.play_hand_actions import play_match
        g=play_match()
        self.assertEqual(g.state.status,'finished')
        self.assertEqual(g.state.opening.stage,'complete')
        kinds=[e.kind for e in g.events]
        self.assertGreaterEqual(kinds.count('card_traded'),1)
        self.assertGreaterEqual(kinds.count('card_forged'),1)
        self.assertGreater(kinds.count('choice_requested'),2)
        self.assertIn('card_added_to_deck',kinds)
        self.assertIn('weapon_equipped',kinds)
        self.assertIn('attack_finished',kinds)

    def game(self, hand, deck=('CS2_182',)):
        from hs_sim.engine.representative import build_registry
        self.registry=build_registry()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,deck=deck,max_mana=10,mana=10),
            PlayerSetup('HERO_08'))),self.registry)

    def use(self,g,action):
        g.apply(UseHandAction(1,g.state.players[1].hand[0],action))

    def test_heavy_plate_can_trade_without_armor_or_play_for_eight(self):
        g=self.game(('SW_094',)); self.use(g,'trade')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        h=self.game(('SW_094',)); h.apply(PlayCard(1,h.state.players[1].hand[0]))
        self.assertEqual(h.state.entities[h.state.players[1].hero_id].armor,8)
        self.assertEqual(h.state.players[1].mana,7)

    def test_crusher_upgrades_once_then_plays_as_six_five_rush(self):
        g=self.game(('TTN_042',)); source=g.state.players[1].hand[0]; self.use(g,'forge')
        self.assertFalse(any(isinstance(a,UseHandAction) for a in g.legal_actions()))
        g.apply(PlayCard(1,source)); card=g.state.entities[source]
        self.assertEqual((card.card_id,card.attack,card.health),('TTN_042t',6,5))
        self.assertIn(Keyword.RUSH,card.keywords)
        self.assertEqual(replay(build_replay(g),self.registry).snapshot(),g.snapshot())

    def test_giant_repeated_forge_including_zero_cost_keeps_two_mana_fee(self):
        g=self.game(('TTN_724',)); source=g.state.players[1].hand[0]
        for expected in (6,4,2,0,0):
            self.use(g,'forge'); self.assertEqual(g.quote_cost(source).amount,expected)
        self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual(g.quote_hand_action(source,'forge').amount,2)
        self.assertFalse(any(isinstance(a,UseHandAction) for a in g.legal_actions()))
        restored=Game.from_snapshot(g.snapshot(),self.registry)
        self.assertEqual(restored.snapshot(),g.snapshot())
        g.apply(PlayCard(1,source)); self.assertEqual(g.state.entities[source].attack,8)
        self.assertEqual(replay(build_replay(g),self.registry).snapshot(),g.snapshot())


if __name__ == '__main__':
    unittest.main()
