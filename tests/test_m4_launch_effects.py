"""Launch fees and real launch effects, including suspended death boundaries."""
from dataclasses import replace
from copy import deepcopy
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostScope, CostSpec, EndTurn, Game,
    IllegalAction, Keyword, LaunchStarship, LaunchStarshipEffect, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone, Ruleset)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, DamageBatch,
    Destroy, GainArmor, RandomDamage, RandomDestroy, RequestChoice, Summon, ModifyWeapon)
from hs_sim.engine.model import PaymentType
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction, launch_quote


class LaunchEffectsTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.spell('scrap', lambda c: [DamageBatch(tuple(Damage(i, 100)
            for i in c.state.players[c.player_id].board))])
        self.spell('free', lambda c: [LaunchStarshipEffect(c.player_id, construction(c.state, c.player_id).id)])
        self.r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=1, health=1))
        self.r.register_card(CardDefinition('tough', 'tough', CardType.MINION, attack=1, health=20))

    def spell(self, name, callback, **kwargs):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kwargs))

    def game(self, board=('SC_403a',), hand=('scrap',), enemy=(), mana=10, seed=19,
             enemy_hand=(), enemy_deck=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', board=board, hand=hand,
            max_mana=10, mana=mana), PlayerSetup('HERO_01', board=enemy,
            hand=enemy_hand, deck=enemy_deck, max_mana=10, mana=10)), seed=seed), self.r)

    def cast(self, g, card, target=None, player=1):
        i = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card)
        return g.apply(PlayCard(player, i, target))

    def ship(self, g, player=1):
        return construction(g.state, player)

    def launch(self, g):
        i = self.ship(g).id
        return g.apply(LaunchStarship(1, i))

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def quote(self, g, player=1):
        return launch_quote(g.state, self.ship(g, player)).amount

    def check_replay(self, g):
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def add_discount(self, uses=1, **kwargs):
        self.spell('discount', lambda c: [AddCostModifier(1, CostSpec(delta=-2),
            uses_remaining=uses, scope=CostScope.STARSHIP_LAUNCH, **kwargs)])

    def test_scv_discount_persists_after_source_death_and_before_construction(self):
        g = self.game(hand=('SC_401', 'scrap'))
        self.cast(g, 'SC_401'); self.assertIsNone(self.ship(g))
        self.cast(g, 'scrap'); self.assertEqual(self.quote(g), 3)
        result = self.launch(g)
        self.assertEqual(g.state.players[1].mana, 6)
        self.assertEqual([e.amount for e in result.events if e.kind == 'mana_spent'], [3])
        self.assertFalse(g.state.players[1].cost_modifiers); self.check_replay(g)

    def test_discounts_stack_to_zero_and_all_are_consumed(self):
        g = self.game(hand=('SC_401',)*3 + ('scrap',))
        for _ in range(3): self.cast(g, 'SC_401')
        self.cast(g, 'scrap'); self.assertEqual(self.quote(g), 0)
        self.launch(g); self.assertEqual(g.state.players[1].mana, 7)
        self.assertFalse(g.state.players[1].cost_modifiers)

    def test_next_ship_resets_to_base_fee(self):
        self.spell('new', lambda c: [Summon(1, 'SC_403a')])
        g = self.game(hand=('SC_401', 'scrap', 'new', 'scrap'))
        self.cast(g, 'SC_401'); self.cast(g, 'scrap'); self.launch(g)
        self.cast(g, 'new'); self.cast(g, 'scrap'); self.assertEqual(self.quote(g), 5)

    def test_launch_discount_does_not_change_or_get_consumed_by_card_play(self):
        g = self.game(hand=('SC_401', 'SC_403a', 'scrap'))
        self.cast(g, 'SC_401'); self.cast(g, 'SC_403a')
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1)
        self.cast(g, 'scrap'); self.assertEqual(self.quote(g), 3)

    def test_discount_survives_turns_and_restore(self):
        g = self.game(hand=('SC_401', 'scrap'))
        self.cast(g, 'SC_401'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.cast(g, 'scrap'); self.assertEqual(self.quote(g), 3); self.check_replay(g)

    def test_opponent_discount_is_isolated(self):
        g = self.game(hand=('SC_401', 'scrap'), enemy=('SC_403a',), enemy_hand=('scrap',))
        self.cast(g, 'SC_401'); self.cast(g, 'scrap')
        g.apply(EndTurn(1)); self.cast(g, 'scrap', player=2)
        self.assertEqual((self.quote(g, 1), self.quote(g, 2)), (3, 5))

    def test_finite_uses_are_consumed_once_by_paid_launch(self):
        self.add_discount(2); g = self.game(hand=('discount', 'scrap'))
        self.cast(g, 'discount'); self.cast(g, 'scrap'); self.launch(g)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)

    def test_free_launch_consumes_next_launch_modifier_without_paying(self):
        self.add_discount(2); g = self.game(hand=('discount', 'scrap', 'free'), mana=0)
        self.cast(g, 'discount'); self.cast(g, 'scrap'); self.cast(g, 'free')
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.check_replay(g)

    def test_stale_free_launch_does_not_consume_modifier(self):
        self.add_discount(); self.spell('stale', lambda c: [LaunchStarshipEffect(1, c.source_id)])
        g = self.game(hand=('discount', 'scrap', 'stale'))
        self.cast(g, 'discount'); self.cast(g, 'scrap'); self.cast(g, 'stale')
        self.assertEqual(self.quote(g), 3)
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1)

    def test_rejected_paid_launch_does_not_consume_or_change_rng(self):
        self.add_discount(); g = self.game(hand=('discount', 'scrap'), mana=2)
        self.cast(g, 'discount'); self.cast(g, 'scrap'); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.launch(g)
        self.assertEqual(before, g.snapshot())

    def test_expiring_and_permanent_scopes_share_attachment_expiry(self):
        self.add_discount(expires_turn=1); g = self.game(hand=('discount', 'SC_401', 'scrap'))
        self.cast(g, 'discount'); self.cast(g, 'SC_401'); self.cast(g, 'scrap')
        self.assertEqual(self.quote(g), 1)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.quote(g), 3)

    def test_unlimited_launch_modifier_is_retained(self):
        self.add_discount(None); g = self.game(hand=('discount', 'scrap'))
        self.cast(g, 'discount'); self.cast(g, 'scrap'); self.launch(g)
        self.assertIsNone(g.state.players[1].cost_modifiers[0].uses_remaining)

    def test_launch_scope_rejects_card_filters_and_alternate_payment(self):
        for spec in (CostSpec(card_types=(CardType.MINION,)), CostSpec(payment=PaymentType.HEALTH)):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                AddCostModifier(1, spec, scope=CostScope.STARSHIP_LAUNCH)
        with self.assertRaises(ValueError): AddCostModifier(1, CostSpec(), scope='starship_launch')

    def test_discount_view_and_fixed_seat_legal_launch_use_same_quote(self):
        self.add_discount(); g = self.game(hand=('discount', 'scrap'), mana=3)
        self.cast(g, 'scrap')
        self.assertFalse(any(isinstance(a, LaunchStarship) for a in g.legal_actions()))
        self.cast(g, 'discount')
        for seat in (1, 2):
            self.assertEqual(g.observe(seat)['players'][0]['board'][0]['starship']['launch_cost'], 3)
        port = g.for_player(1); actions = port.legal_actions()
        cmd = next(a for a in actions['actions'] if a['type'] == 'launch_starship')
        self.assertTrue(port.submit({'revision': actions['revision'], 'action': cmd})['accepted'])
        self.assertEqual(g.state.players[1].mana, 0); self.check_replay(g)

    def test_salvage_bunker_summons_taunts_and_reduces_launch(self):
        g = self.game(hand=('scrap', 'SC_404'))
        self.cast(g, 'scrap'); self.cast(g, 'SC_404')
        marines = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].active]
        self.assertEqual([(m.card_id,m.attack,m.health,m.keywords) for m in marines],
                         [('SC_403t',2,2,{Keyword.TAUNT})]*2)
        self.assertEqual(self.quote(g), 3); self.check_replay(g)

    def test_lock_on_targets_minions_only_and_sets_health(self):
        g = self.game(hand=('scrap', 'SC_407'), enemy=('tough',))
        self.cast(g, 'scrap'); target = g.state.players[2].board[0]
        card = g.state.players[1].hand[0]
        with self.assertRaises(IllegalAction): g.apply(PlayCard(1,card,g.state.players[2].hero_id))
        self.cast(g, 'SC_407', target); self.assertEqual(g.state.entities[target].health, 1)
        self.assertEqual(self.quote(g), 3)

    def test_concussive_shells_damage_armor_discount(self):
        g = self.game(hand=('scrap', 'SC_411'))
        self.cast(g, 'scrap'); target = g.state.players[2].hero_id
        self.cast(g, 'SC_411', target)
        self.assertEqual((g.state.entities[target].health, self.armor(g), self.quote(g)), (28,2,3))
        self.check_replay(g)

    def test_viking_play_has_no_armor_but_duplicate_launch_does(self):
        g = self.game(hand=('SC_403a', 'scrap'))
        self.cast(g, 'SC_403a'); self.assertEqual(self.armor(g), 0)
        self.cast(g, 'scrap'); self.launch(g); self.assertEqual(self.armor(g), 10)

    def test_liberator_hits_minions_but_not_hero(self):
        g = self.game(board=('SC_403b',), enemy=('tough',))
        self.cast(g, 'scrap'); self.launch(g)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 18)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def damage_watcher(self):
        self.r.register_behavior('watch', lambda c: [GainArmor(c.player_id, 1)]
            if c.event.target_id == c.source_id else [])
        self.r.register_card(CardDefinition('watcher', 'watcher', CardType.MINION, attack=1, health=1,
            triggers=(TriggerSpec('damage_dealt', 'watch'),)))

    def test_three_liberators_hit_functionally_dead_minion_three_times(self):
        self.damage_watcher()
        g = self.game(board=('SC_403b',)*3, enemy=('watcher',))
        self.cast(g, 'scrap'); target = g.state.players[2].board[0]; result = self.launch(g)
        self.assertEqual(self.armor(g, 2), 3)
        hits = [e for e in result.events if e.kind=='damage_dealt' and e.target_id==target]
        deaths = [e for e in result.events if e.kind=='minion_died' and e.target_id==target]
        self.assertEqual(len(hits), 3); self.assertEqual(len(deaths), 1)
        self.assertGreater(deaths[0].sequence, hits[-1].sequence); self.check_replay(g)

    def test_banshee_excludes_dying_minions_and_hits_hero(self):
        self.r.register_behavior('shot', lambda c: [Damage(c.state.players[2].board[0], 1),
            RandomDamage((c.state.players[2].board[0], c.state.players[2].hero_id), 3, c.source_id)])
        self.r.register_card(replace(self.r.card('SC_403d'), id='shot_piece', on_launch='shot'))
        g = self.game(board=('shot_piece',), enemy=('plain',))
        self.cast(g, 'scrap'); self.launch(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_real_banshee_uses_current_three_damage(self):
        g = self.game(board=('SC_403d',)); self.cast(g, 'scrap'); self.launch(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_yamato_battlecry_and_launch_destroy_separate_minions(self):
        g = self.game(board=(), hand=('SC_406', 'scrap'), enemy=('tough','tough'))
        self.cast(g, 'SC_406'); self.assertEqual(len(g.state.players[2].board),1)
        self.cast(g, 'scrap'); self.launch(g); self.assertFalse(g.state.players[2].board)
        self.check_replay(g)

    def test_duplicate_yamatos_skip_already_doomed_target(self):
        g = self.game(board=('SC_406',)*2, enemy=('tough','tough'))
        self.cast(g, 'scrap'); result = self.launch(g)
        choices = [e.target_id for e in result.events if e.kind=='random_choice']
        self.assertEqual(len(set(choices)),2); self.assertFalse(g.state.players[2].board)

    def test_yamato_empty_board_does_not_destroy_hero(self):
        g = self.game(board=('SC_406',)); self.cast(g, 'scrap'); result=self.launch(g)
        self.assertTrue(any(e.kind=='random_choice_skipped' for e in result.events))
        self.assertEqual(g.state.status,'playing')

    def test_missile_pod_battlecry_and_launch_each_hit_all_enemies(self):
        g = self.game(board=(), hand=('SC_409','scrap'), enemy=('tough',))
        self.cast(g, 'SC_409'); self.cast(g, 'scrap'); self.launch(g)
        p=g.state.players[2]
        self.assertEqual((g.state.entities[p.hero_id].health,g.state.entities[p.board[0]].health),(28,18))

    def test_medivac_respects_remaining_board_capacity(self):
        self.spell('fill', lambda c: [Summon(1,'plain') for _ in range(5)])
        g=self.game(board=('SC_403f',),hand=('scrap','fill'))
        self.cast(g,'scrap'); self.cast(g,'fill'); result=self.launch(g)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(sum(g.state.entities[i].card_id=='SC_403t' for i in g.state.players[1].board),1)
        self.assertTrue(any(e.kind=='summon_failed' for e in result.events))

    def test_supercapacitor_battlecry_ignores_construction_and_buff_does_not_contribute(self):
        g=self.game(hand=('scrap','SC_404','SC_405','scrap'))
        self.cast(g,'scrap'); self.cast(g,'SC_404'); self.cast(g,'SC_405')
        source=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((source.attack,source.health),(3,3))
        self.cast(g,'scrap'); self.assertEqual((self.ship(g).attack,self.ship(g).health),(3,2))

    def test_later_launch_callbacks_see_earlier_summons(self):
        attacks=set()
        for seed in range(6):
            g=self.game(board=('SC_403f','SC_405'),seed=seed)
            self.cast(g,'scrap'); i=self.ship(g).id; self.launch(g)
            attacks.add(g.state.entities[i].attack); self.check_replay(g)
        self.assertEqual(attacks,{3,5})

    def test_displacer_copies_current_buffed_ship_without_relaunching(self):
        seen=set()
        self.spell('friend',lambda c:[Summon(1,'plain')])
        for seed in range(6):
            g=self.game(board=('GDB_466','SC_405'),hand=('scrap','friend'),seed=seed)
            self.cast(g,'scrap'); self.cast(g,'friend'); original=self.ship(g).id; result=self.launch(g)
            ships=[g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].components]
            self.assertEqual(len(ships),2)
            self.assertEqual(sum(e.kind=='starship_launched' for e in result.events),1)
            seen.add(tuple(sorted(e.attack for e in ships)))
            copied=next(e for e in ships if e.id!=original)
            self.assertEqual(copied.components,('GDB_466','SC_405')); self.check_replay(g)
        self.assertEqual(seen,{(7,7),(6,8)})

    def choice_piece(self):
        def behavior(c):
            work=[Damage(c.state.players[2].board[0],1)]
            return [*work,RequestChoice(1,(ChoiceOption('ok','ok',(GainArmor(1,2),)),),
                source_id=c.source_id),Damage(c.state.players[2].board[0],1)]
        self.r.register_behavior('pause_launch',behavior)
        self.r.register_card(replace(self.r.card('SC_403a'),id='pauser',on_launch='pause_launch'))

    def waiting_game(self):
        self.damage_watcher(); self.choice_piece()
        g=self.game(board=('pauser',),enemy=('watcher',))
        self.cast(g,'scrap'); self.launch(g); return g

    def test_dead_minion_and_launch_boundary_survive_choice_snapshot(self):
        g=self.waiting_game(); target=g.state.players[2].board[0]
        self.assertEqual(g.state.entities[target].health,0)
        self.assertEqual(g.snapshot()['resolution_frame']['fields']['death_deferrals'],1)
        clone=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        choice=g.state.pending_choice; action=SelectChoice(1,choice.id,('ok',))
        g.apply(action); clone.apply(action)
        self.assertEqual(g.snapshot(),clone.snapshot()); self.assertFalse(g.state.players[2].board)
        self.assertEqual(self.armor(g,2),2); self.check_replay(g)

    def test_choice_validation_failure_preserves_deferred_frame(self):
        g=self.waiting_game(); before=g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(SelectChoice(1,g.state.pending_choice.id,('missing',)))
        self.assertEqual(before,g.snapshot())

    def test_corrupt_launch_depth_or_closer_is_rejected(self):
        g=self.waiting_game()
        for mode in ('depth','closer'):
            row=deepcopy(g.snapshot()); frame=row['resolution_frame']['fields']
            if mode=='depth': frame['death_deferrals']=0
            else: frame['continuation']['tuple']=[w for w in frame['continuation']['tuple']
                if not w.get('type','').endswith('FinishStarshipLaunch')]
            row['state_hash']=canonical_hash({k:v for k,v in row.items()
                if k not in ('schema_version','events','events_hash','state_hash')})
            with self.subTest(mode=mode),self.assertRaisesRegex(SnapshotError,'Invalid suspended death deferral boundaries'):
                Game.from_snapshot(row,self.r)

    def test_nested_launch_choice_preserves_both_death_boundaries(self):
        self.damage_watcher()
        self.r.register_behavior('outer',lambda c:[LaunchStarshipEffect(2,construction(c.state,2).id),GainArmor(1,5)])
        self.r.register_behavior('inner',lambda c:[Damage(c.state.players[1].board[-1],1),
            RequestChoice(2,(ChoiceOption('ok','ok',(GainArmor(2,4),)),),source_id=c.source_id),
            Damage(c.state.players[1].board[-1],1)])
        for name in ('outer','inner'):
            self.r.register_card(replace(self.r.card('SC_403a'),id=name,on_launch=name))
        self.spell('prepare',lambda c:[DamageBatch(tuple(Damage(i,100)
            for p in c.state.players.values() for i in p.board)),Summon(1,'watcher')])
        g=self.game(board=('outer',),enemy=('inner',),hand=('prepare',))
        self.cast(g,'prepare'); self.launch(g)
        self.assertEqual(g.snapshot()['resolution_frame']['fields']['death_deferrals'],2)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        a=SelectChoice(2,g.state.pending_choice.id,('ok',)); g.apply(a); restored.apply(a)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual((self.armor(g),self.armor(g,2)),(7,4))
        self.assertEqual(len(g.state.players[1].board),1); self.check_replay(g)

    def test_broken_weapon_can_wait_with_launch_and_settles_on_resume(self):
        self.r.register_behavior('break_pause',lambda c:[ModifyWeapon(c.state.players[1].weapon_id,durability=-1),
            RequestChoice(1,(ChoiceOption('ok','ok',()),),source_id=c.source_id)])
        self.r.register_card(replace(self.r.card('SC_403a'),id='breaker',on_launch='break_pause'))
        self.r.register_card(CardDefinition('weapon','weapon',CardType.WEAPON,attack=1,durability=1))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('breaker',),hand=('scrap',),
            weapon_card_id='weapon',mana=10,max_mana=10),PlayerSetup('HERO_01'))),self.r)
        self.cast(g,'scrap'); self.launch(g); i=g.state.players[1].weapon_id
        self.assertEqual(g.state.entities[i].durability,0)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        a=SelectChoice(1,g.state.pending_choice.id,('ok',)); g.apply(a); restored.apply(a)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.check_replay(g)

    def test_resolution_budget_rolls_back_launch_boundary_and_rng(self):
        self.r.register_behavior('many',lambda c:[GainArmor(1,1) for _ in range(40)])
        self.r.register_card(replace(self.r.card('SC_403a'),id='many',on_launch='many'))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('many',),hand=('scrap',),
            mana=10,max_mana=10),PlayerSetup('HERO_01'))),self.r,ruleset=Ruleset(max_resolution_steps=30))
        self.cast(g,'scrap'); before=g.snapshot()
        from hs_sim.engine.errors import ResolutionLimitExceeded
        with self.assertRaises(ResolutionLimitExceeded): self.launch(g)
        self.assertEqual(before,g.snapshot())

    def test_fee_modifiers_follow_acquisition_order_and_floors(self):
        self.spell('ordered',lambda c:[
            AddCostModifier(1,CostSpec(delta=-9,minimum=1),scope=CostScope.STARSHIP_LAUNCH),
            AddCostModifier(1,CostSpec(set_to=4),scope=CostScope.STARSHIP_LAUNCH),
            AddCostModifier(1,CostSpec(delta=-2),scope=CostScope.STARSHIP_LAUNCH)])
        g=self.game(hand=('ordered','scrap')); self.cast(g,'ordered'); self.cast(g,'scrap')
        self.assertEqual(self.quote(g),2); self.launch(g)
        self.assertEqual(g.state.players[1].mana,8)

    def test_snapshot_rejects_invalid_cost_scope_with_recomputed_hash(self):
        self.add_discount(); g=self.game(hand=('discount',)); self.cast(g,'discount'); row=g.snapshot()
        row['state']['players']['1']['cost_modifiers'][0]['scope']='unknown'
        row['state_hash']=canonical_hash({k:v for k,v in row.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(row,self.r)

    def test_raynor_is_explicitly_a_playable_hero(self):
        card = self.r.card('SC_400')
        self.assertEqual(card.kind, CardType.HERO)
        self.assertTrue(card.hero_card)

    def test_real_terran_example_runs_restores_and_replays(self):
        from examples.launch_starship import run
        game, snapshot = run()
        # One hand minion now has a counter-check and accepted-entry event.
        self.assertEqual((len(game.history),len(game.events)),(6,67))
        self.assertEqual(sum(e.kind == 'health_resolved' for e in game.events), 5)
        self.assertEqual(snapshot['schema_version'],265)

    def test_launch_failure_rolls_back_fee_rng_and_all_state(self):
        self.r.register_behavior('bad',lambda c:[RandomDestroy(tuple(c.state.players[2].board),999999)])
        self.r.register_card(replace(self.r.card('SC_406'),id='bad_piece',on_launch='bad'))
        g=self.game(board=('bad_piece',),hand=('SC_401','scrap'),enemy=('plain',))
        self.cast(g,'SC_401'); self.cast(g,'scrap'); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.launch(g)
        self.assertEqual(before,g.snapshot())

    def test_hero_death_flushes_held_deaths_under_prototype_terminal_policy(self):
        self.r.register_behavior('lethal',lambda c:[Damage(c.state.players[2].board[0],1),
            Damage(c.state.players[2].hero_id,30),GainArmor(1,99)])
        self.r.register_card(replace(self.r.card('SC_403a'),id='lethal',on_launch='lethal'))
        g=self.game(board=('lethal',),enemy=('plain',))
        self.cast(g,'scrap'); self.launch(g)
        self.assertEqual(g.state.winner,1); self.assertFalse(g.state.players[2].board)
        self.assertEqual(self.armor(g),0); self.check_replay(g)


if __name__ == '__main__': unittest.main()
