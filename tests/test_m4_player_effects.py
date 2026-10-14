"""Source-independent rules, owner clocks, lifecycle and resumable boundaries."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AddPlayerEffect, CardDefinition, CardType, DamageKind, EndTurn,
    Game, IllegalAction, PlayerAuraSpec, PlayerEffectSpec, PlayerSetup, PlayCard,
    RemovePlayerEffect, ResolutionError, Ruleset, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, RequestChoice, ReplaceHero, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.player_effects import TickPlayerEffect


class PlayerEffectTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=1))
        self.r.register_card(CardDefinition('body', 'Body', CardType.MINION, attack=2, health=8))
        self.spell('wave', lambda c: [Summon(c.player_id, 'plain')])
        self.spell('bolt', lambda c: [Damage(c.state.players[2].hero_id, 1, c.source_id, DamageKind.SPELL)])
        self.spell('effect_damage', lambda c: [Damage(c.state.players[2].hero_id, 1, c.source_id)])
        self.spell('remove', lambda c: [RemovePlayerEffect(c.player_id, c.state.players[c.player_id].player_effects[0].id)])
        self.spell('replace_hero', lambda c: [ReplaceHero(c.player_id, 'HERO_08')])
        self.r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)] if c.event.player_id == c.player_id else [])

    def spell(self, name, callback):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def source_action(self, name, make):
        self.spell(name, lambda c: [make(c.state.players[1].board[0])])

    def persistent(self, name='aura', **kwargs):
        self.r.register_player_effect(PlayerEffectSpec(name, 'body', **kwargs))
        self.spell(name, lambda c: [AddPlayerEffect(c.player_id, name, c.source_id)])

    def timed(self, name='clock', duration=1, tick='turn_started', expire='armor', triggers=()):
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, ongoing_effect_id=name))
        self.r.register_player_effect(PlayerEffectSpec(name, name, 'sigil', duration, tick, expire, triggers))

    def game(self, hand=(), board=(), enemy_board=(), enemy_hand=(), rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', hand=hand, board=board, deck=('plain',)*15, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=('plain',)*15, mana=10, max_mana=10)), seed=93),
            self.r, ruleset=rules)

    def play(self, g, name):
        player = g.state.active_player
        entity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(player, entity))

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def effects(self, g, player=1):
        return g.state.players[player].player_effects

    def health(self, g, player=2):
        return g.state.entities[g.state.players[player].hero_id].health

    def check(self, g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_dawngrasp_battlecry_installs_player_spell_damage(self):
        g=self.game(hand=('SW_450t4','bolt'));self.play(g,'SW_450t4');self.play(g,'bolt')
        self.assertEqual(self.health(g),26);self.assertEqual(len(self.effects(g)),1);self.check(g)

    def test_summoning_dawngrasp_does_not_execute_battlecry(self):
        g=self.game(board=('SW_450t4',),hand=('bolt',));self.play(g,'bolt')
        self.assertEqual(self.health(g),29);self.assertFalse(self.effects(g))

    def test_source_death_preserves_effect(self):
        self.source_action('kill',Destroy);g=self.game(hand=('SW_450t4','kill','bolt'))
        for name in ('SW_450t4','kill','bolt'):self.play(g,name)
        self.assertFalse(g.state.players[1].board);self.assertEqual(self.health(g),26);self.check(g)

    def test_source_silence_preserves_effect(self):
        self.source_action('silence',Silence);g=self.game(hand=('SW_450t4','silence','bolt'))
        for name in ('SW_450t4','silence','bolt'):self.play(g,name)
        self.assertEqual(self.health(g),26)

    def test_source_return_replay_adds_a_distinct_instance(self):
        self.source_action('bounce',ReturnToHand);g=self.game(hand=('SW_450t4','bounce','bolt'))
        for name in ('SW_450t4','bounce','SW_450t4','bolt'):self.play(g,name)
        self.assertEqual(self.health(g),23);self.assertEqual(len({e.id for e in self.effects(g)}),2);self.check(g)

    def test_source_transform_preserves_original_card_provenance(self):
        self.source_action('transform',lambda i:Transform(i,'plain'));g=self.game(hand=('SW_450t4','transform','bolt'))
        for name in ('SW_450t4','transform','bolt'):self.play(g,name)
        effect=self.effects(g)[0];self.assertEqual(effect.source_card_id,'SW_450t4')
        self.assertEqual(g.state.entities[effect.source_id].card_id,'plain');self.assertEqual(self.health(g),26);self.check(g)

    def test_source_control_change_does_not_transfer_player_effect(self):
        self.source_action('steal',lambda i:ChangeControl(i,2));g=self.game(hand=('SW_450t4','steal','bolt'))
        for name in ('SW_450t4','steal','bolt'):self.play(g,name)
        self.assertEqual(self.health(g),26);self.assertFalse(self.effects(g,2));self.check(g)

    def test_hero_replacement_preserves_effect(self):
        g=self.game(hand=('SW_450t4','replace_hero','bolt'));old=g.state.players[1].hero_id
        for name in ('SW_450t4','replace_hero','bolt'):self.play(g,name)
        self.assertNotEqual(old,g.state.players[1].hero_id);self.assertEqual(self.health(g),26);self.check(g)

    def test_source_copy_does_not_duplicate_player_effect(self):
        self.source_action('copy',lambda i:CopyMinion(i,1));g=self.game(hand=('SW_450t4','copy','bolt'))
        for name in ('SW_450t4','copy','bolt'):self.play(g,name)
        self.assertEqual(self.health(g),26);self.assertEqual(len(self.effects(g)),1)

    def test_nonspell_damage_does_not_receive_player_spell_bonus(self):
        g=self.game(hand=('SW_450t4','effect_damage'));self.play(g,'SW_450t4');self.play(g,'effect_damage')
        self.assertEqual(self.health(g),29)

    def test_player_and_board_spell_damage_add_together(self):
        g=self.game(hand=('SW_450t4','bolt'),board=('EX1_012',));self.play(g,'SW_450t4');self.play(g,'bolt')
        self.assertEqual(self.health(g),25)

    def test_removing_one_duplicate_preserves_other(self):
        g=self.game(hand=('SW_450t4','SW_450t4','remove','bolt'))
        for name in ('SW_450t4','SW_450t4','remove','bolt'):self.play(g,name)
        self.assertEqual(self.health(g),26);self.assertEqual(len(self.effects(g)),1);self.check(g)

    def test_bridge_duplicates_stack_independently(self):
        g=self.game(hand=('AV_344','AV_344','wave'))
        for name in ('AV_344','AV_344','wave'):self.play(g,name)
        e=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((e.attack,e.health),(5,5));self.assertEqual(len(self.effects(g)),2);self.check(g)

    def test_bridge_does_not_buff_existing_or_enemy_minions(self):
        g=self.game(hand=('AV_344',),board=('plain',),enemy_hand=('wave',));self.play(g,'AV_344')
        g.apply(EndTurn(1));self.play(g,'wave')
        self.assertEqual([g.state.entities[p.board[0]].attack for p in g.state.players.values()],[1,1])

    def test_objective_counts_only_three_owner_turn_ends(self):
        g=self.game(hand=('AV_344',));self.play(g,'AV_344');g.apply(EndTurn(1))
        self.assertEqual(self.effects(g)[0].remaining_turns,2);g.apply(EndTurn(2))
        self.assertEqual(self.effects(g)[0].remaining_turns,2);self.cycle(g)
        self.assertEqual(self.effects(g)[0].remaining_turns,1);g.apply(EndTurn(1))
        self.assertFalse(self.effects(g));self.check(g)

    def test_objective_buff_remains_after_expiry(self):
        g=self.game(hand=('AV_344','wave','wave'));self.play(g,'AV_344');self.play(g,'wave')
        for _ in range(3):self.cycle(g)
        self.play(g,'wave');self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board],[3,1])

    def test_objective_triggered_buff_can_be_silenced(self):
        self.source_action('silence',Silence);g=self.game(hand=('AV_344','wave','silence'))
        for name in ('AV_344','wave','silence'):self.play(g,name)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,1);self.assertTrue(self.effects(g))

    def test_end_turn_reaction_runs_before_final_expiry(self):
        self.r.register_behavior('endwave',lambda c:[Summon(c.player_id,'plain')] if c.event.player_id==c.player_id else [])
        self.r.register_card(CardDefinition('summoner','Summoner',CardType.MINION,health=3,
            triggers=(TriggerSpec('turn_ended','endwave'),)))
        g=self.game(hand=('AV_344',),board=('summoner',));self.play(g,'AV_344')
        for _ in range(3):self.cycle(g)
        self.assertFalse(self.effects(g));self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board[1:]],[3,3,3])

    def test_full_ongoing_area_rejects_before_payment_and_player_listing(self):
        g=self.game(hand=('AV_344','BAR_306'),rules=Ruleset(max_ongoing_effects=1));self.play(g,'AV_344');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'BAR_306')
        self.assertEqual(before,g.snapshot());self.assertFalse(any(a['type']=='play_card' for a in g.for_player(1).legal_actions()['actions']))

    def test_whole_game_effect_does_not_use_ongoing_capacity(self):
        g=self.game(hand=('AV_344','SW_450t4'),rules=Ruleset(max_ongoing_effects=1))
        self.play(g,'AV_344');self.play(g,'SW_450t4');self.assertEqual(len(self.effects(g)),2);self.check(g)

    def test_effect_added_to_full_area_fails_without_deleting_existing(self):
        self.spell('add',lambda c:[AddPlayerEffect(1,'m4.sigil_flame',c.source_id)])
        g=self.game(hand=('AV_344','add'),rules=Ruleset(max_ongoing_effects=1));self.play(g,'AV_344');self.play(g,'add')
        self.assertEqual([e.spec_id for e in self.effects(g)],['m4.bridge'])
        self.assertTrue(any(e.kind=='player_effect_failed' for e in g.events))

    def test_sigil_expires_next_owner_start_before_natural_draw(self):
        g=self.game(hand=('BAR_306',),board=('body',),enemy_board=('body',));self.play(g,'BAR_306');g.apply(EndTurn(1))
        self.assertEqual(self.effects(g)[0].remaining_turns,1);g.apply(EndTurn(2))
        self.assertFalse(self.effects(g));self.assertEqual([g.state.entities[p.board[0]].health for p in g.state.players.values()],[5,5])
        events=list(g.events);damage=max(i for i,e in enumerate(events) if e.kind=='damage_dealt')
        draw=max(i for i,e in enumerate(events) if e.kind=='card_drawn');self.assertLess(damage,draw)
        self.assertEqual((self.health(g,1),self.health(g,2)),(30,30));self.check(g)

    def test_sigil_uses_spell_damage_at_resolution(self):
        g=self.game(hand=('BAR_306','SW_450t4'),enemy_board=('body',));self.play(g,'BAR_306');self.play(g,'SW_450t4')
        self.cycle(g);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,2);self.check(g)

    def test_duplicate_sigils_resolve_as_separate_batches(self):
        self.r.register_behavior('deathwave',lambda c:[Summon(c.player_id,'plain')])
        self.r.register_card(CardDefinition('egg','Egg',CardType.MINION,health=1,deathrattle='deathwave'))
        g=self.game(hand=('BAR_306','BAR_306'),enemy_board=('egg',))
        self.play(g,'BAR_306');self.play(g,'BAR_306');self.cycle(g)
        self.assertFalse(g.state.players[2].board);self.assertEqual([d.card_id for d in g.state.death_history],['egg','plain']);self.check(g)

    def test_explicit_removal_does_not_execute_expiry_payload(self):
        g=self.game(hand=('BAR_306','remove'),enemy_board=('body',))
        self.play(g,'BAR_306');self.play(g,'remove');self.cycle(g)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,8)

    def test_expiry_choice_releases_slot_and_restores_pending_turn(self):
        self.r.register_behavior('choice',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('armor','Armor',(GainArmor(c.player_id,2),)),),c.source_id)])
        self.timed(expire='choice');g=self.game(hand=('clock',));self.play(g,'clock');self.cycle(g)
        self.assertFalse(self.effects(g));self.assertIsNotNone(g.state.pending_choice)
        saved=g.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(saved)),self.r)
        for match in (g,restored):
            choice=match.state.pending_choice;match.apply(SelectChoice(1,choice.id,('armor',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_choice_in_first_timer_preserves_second_timer_continuation(self):
        self.r.register_behavior('choice',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('armor','Armor',(GainArmor(c.player_id,2),)),),c.source_id)])
        self.timed(expire='choice');g=self.game(hand=('clock','BAR_306'),enemy_board=('body',))
        self.play(g,'clock');self.play(g,'BAR_306');self.cycle(g)
        self.assertEqual(len(self.effects(g)),1);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,8)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        for match in (g,restored):
            choice=match.state.pending_choice;match.apply(SelectChoice(1,choice.id,('armor',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,5);self.check(g)

    def test_effect_added_during_boundary_does_not_tick_immediately(self):
        self.timed();self.r.register_behavior('install',lambda c:[AddPlayerEffect(c.player_id,'clock',c.source_id)]
            if c.event.player_id==c.player_id else [])
        self.r.register_card(CardDefinition('installer','Installer',CardType.MINION,health=3,
            triggers=(TriggerSpec('turn_started','install'),)))
        g=self.game(board=('installer',));self.cycle(g)
        self.assertEqual(len(self.effects(g)),1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.cycle(g);self.assertEqual(len(self.effects(g)),1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.check(g)

    def test_stale_tick_does_not_touch_new_instance(self):
        self.timed(duration=2);self.spell('renew',lambda c:[RemovePlayerEffect(1,c.state.players[1].player_effects[0].id),
            AddPlayerEffect(1,'clock',c.source_id),TickPlayerEffect(1,c.state.players[1].player_effects[0].id,2)])
        g=self.game(hand=('clock','renew'));self.play(g,'clock');old=self.effects(g)[0].id;self.play(g,'renew')
        self.assertNotEqual(old,self.effects(g)[0].id);self.assertEqual(self.effects(g)[0].remaining_turns,2);self.check(g)

    def test_stale_duplicate_tick_does_not_decrement_twice(self):
        self.timed(duration=3);self.spell('tick',lambda c:[TickPlayerEffect(1,c.state.players[1].player_effects[0].id,3)]*2)
        g=self.game(hand=('clock','tick'));self.play(g,'clock');self.play(g,'tick')
        self.assertEqual(self.effects(g)[0].remaining_turns,2)

    def test_persistent_trigger_uses_recipient_after_source_leaves(self):
        self.r.register_player_effect(PlayerEffectSpec('permanent','SW_450t4',triggers=(TriggerSpec('turn_ended','armor'),)))
        self.spell('install',lambda c:[AddPlayerEffect(2,'permanent',c.state.players[1].board[0])])
        self.source_action('kill',Destroy);g=self.game(hand=('install','kill'),board=('SW_450t4',))
        self.play(g,'install');self.play(g,'kill');self.cycle(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,1);self.check(g)

    def test_board_and_player_trigger_order_uses_acquisition_order(self):
        self.r.register_behavior('two_armor',lambda c:[GainArmor(c.player_id,2)] if c.event.player_id==c.player_id else [])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,
            triggers=(TriggerSpec('turn_ended','two_armor'),)))
        self.persistent(triggers=(TriggerSpec('turn_ended','armor'),))
        for board,hand,expected in ((('watcher',),('aura',),[2,1]),((),('aura','watcher'),[1,2])):
            with self.subTest(expected=expected):
                g=self.game(board=board,hand=hand)
                for name in hand:self.play(g,name)
                g.apply(EndTurn(1))
                self.assertEqual([e.amount for e in g.events if e.kind=='armor_gained'],expected)

    def test_persistent_aura_filters_existing_and_new_minions(self):
        self.persistent(auras=(PlayerAuraSpec(2,2,('plain',)),));g=self.game(hand=('aura','wave'),board=('plain','body'))
        self.play(g,'aura');self.play(g,'wave')
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board],[3,2,3]);self.check(g)

    def test_persistent_aura_survives_target_silence(self):
        self.persistent(auras=(PlayerAuraSpec(2,2),));self.source_action('silence',Silence)
        g=self.game(hand=('aura','silence'),board=('plain',));self.play(g,'aura');self.play(g,'silence')
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,3);self.check(g)

    def test_persistent_aura_recomputes_on_transform_and_control_change(self):
        self.persistent(auras=(PlayerAuraSpec(2,2,('plain',)),))
        self.source_action('transform',lambda i:Transform(i,'plain'));self.source_action('steal',lambda i:ChangeControl(i,2))
        g=self.game(hand=('aura','transform','steal'),board=('body',));self.play(g,'aura');self.play(g,'transform')
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,3);self.play(g,'steal')
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].attack,1);self.check(g)

    def test_persistent_aura_is_not_baked_into_copy(self):
        self.persistent(auras=(PlayerAuraSpec(2,2),));self.source_action('copy',lambda i:CopyMinion(i,1))
        g=self.game(hand=('aura','copy','remove'),board=('plain',))
        self.play(g,'aura');self.play(g,'copy');self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board],[3,3])
        self.play(g,'remove');self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board],[1,1]);self.check(g)

    def test_aura_removal_uses_existing_health_clamp_policy(self):
        self.persistent(auras=(PlayerAuraSpec(0,3),));self.source_action('hurt',lambda i:Damage(i,2))
        g=self.game(hand=('aura','hurt','remove'),board=('plain',))
        for name in ('aura','hurt','remove'):self.play(g,name)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,1);self.check(g)

    def test_public_view_and_event_have_no_global_instance_ids(self):
        g=self.game(hand=('AV_344','AV_344'));self.play(g,'AV_344');self.play(g,'AV_344')
        for viewer in (1,2):
            rows=g.observe(viewer)['players'][0]['player_effects'];self.assertEqual(len(rows),2)
            self.assertEqual(set(rows[0]),{'effect_key','card_id','effect_kind','remaining_turns'})
        self.check(g)

    def test_late_failure_rolls_back_effect_ids_state_and_information(self):
        self.spell('bad',lambda c:[AddPlayerEffect(1,'m4.dawngrasp',c.source_id),AddPlayerEffect(1,'missing',c.source_id)])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,'bad')
        self.assertEqual(before,g.snapshot())

    def test_malformed_player_effect_snapshot_is_rejected(self):
        g=self.game(hand=('AV_344',));self.play(g,'AV_344')
        for field,value in (('id',True),('spec_id','missing'),('remaining_turns',0),('remaining_turns',4),
                            ('remaining_turns',None),('created_turn',100),('entered_order',99999),
                            ('source_id',99999),('source_card_id','missing')):
            with self.subTest(field=field,value=value):
                data=g.snapshot();data['state']['players']['1']['player_effects'][0][field]=value
                with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_attachment_id_collision_is_rejected(self):
        g=self.game(hand=('AV_344','SW_450t4'));self.play(g,'AV_344');self.play(g,'SW_450t4')
        data=g.snapshot();rows=data['state']['players']['1']['player_effects'];rows[1]['id']=rows[0]['id']
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_unknown_spec_and_bad_source_fail_transactionally(self):
        self.spell('missing_source',lambda c:[AddPlayerEffect(1,'m4.dawngrasp',99999)])
        g=self.game(hand=('missing_source',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'missing_source')
        self.assertEqual(before,g.snapshot())

    def test_registry_fingerprint_includes_player_effect_specs(self):
        first=self.r.fingerprint();self.persistent(spell_damage=2);self.assertNotEqual(first,self.r.fingerprint())
        self.r.freeze()
        with self.assertRaises(ValueError):self.r.register_player_effect(PlayerEffectSpec('new','body'))

    def test_invalid_specs_fail_explicitly(self):
        for kwargs in ({'kind':'unknown'},{'duration':1},{'kind':'sigil'},{'kind':'objective','duration':0,'tick_event':'turn_ended'},
                       {'kind':'sigil','duration':1,'tick_event':'attack_declared'},{'spell_damage':True},{'triggers':[]}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):PlayerEffectSpec('a','body',**kwargs)

    def test_registry_rejects_missing_expiry_behavior(self):
        self.timed(expire='missing')
        with self.assertRaises(ValueError):self.r.freeze()

    def test_registry_rejects_ongoing_spell_with_ordinary_on_play(self):
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.SPELL,on_play='armor',ongoing_effect_id='clock'))

    def test_previous_snapshot_schema_is_explicitly_rejected(self):
        g=self.game();data=g.snapshot();self.assertEqual(data['schema_version'],265);data['schema_version']=24
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_expiry_callback_sees_removed_aura(self):
        self.r.register_behavior('health_armor',lambda c:[GainArmor(c.player_id,
            c.state.entities[c.state.players[c.player_id].board[0]].max_health)])
        self.r.register_card(CardDefinition('clock','Clock',CardType.SPELL,ongoing_effect_id='clock'))
        self.r.register_player_effect(PlayerEffectSpec('clock','clock','objective',1,'turn_ended',
            'health_armor',auras=(PlayerAuraSpec(0,3),)))
        g=self.game(hand=('clock',),board=('plain',));self.play(g,'clock');g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.check(g)

    def test_added_effect_event_sees_new_aura(self):
        self.r.register_behavior('health_armor',lambda c:[GainArmor(c.player_id,
            c.state.entities[c.state.players[c.player_id].board[0]].max_health)])
        self.persistent(auras=(PlayerAuraSpec(0,3),),triggers=(TriggerSpec('player_effect_added','health_armor'),))
        g=self.game(hand=('aura',),board=('plain',));self.play(g,'aura')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.check(g)

    def test_end_turn_expiry_choice_resumes_next_turn_once(self):
        self.r.register_behavior('choice',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('armor','Armor',(GainArmor(c.player_id,2),)),),c.source_id)])
        self.timed(tick='turn_ended',expire='choice');g=self.game(hand=('clock',));self.play(g,'clock');g.apply(EndTurn(1))
        self.assertEqual(g.state.turn,1);self.check(g)
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,('armor',)))
        self.assertEqual(g.state.turn,2);self.assertEqual(sum(e.kind=='turn_started' and e.player_id==2 for e in g.events),1);self.check(g)

    def test_lethal_expiry_stops_later_timer_and_draw(self):
        self.r.register_behavior('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)])
        self.timed(expire='lethal');g=self.game(hand=('clock','BAR_306'),enemy_board=('body',))
        self.play(g,'clock');self.play(g,'BAR_306');g.apply(EndTurn(1));draws=sum(e.kind=='card_drawn' for e in g.events)
        g.apply(EndTurn(2));self.assertEqual(g.state.winner,1);self.assertEqual(len(self.effects(g)),1)
        self.assertEqual(sum(e.kind=='card_drawn' for e in g.events),draws);self.check(g)

    def test_failed_expiry_rolls_back_entire_turn_action(self):
        self.r.register_behavior('bad_expiry',lambda c:[AddPlayerEffect(1,'missing',c.source_id)])
        self.timed(expire='bad_expiry');g=self.game(hand=('clock',));self.play(g,'clock');g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ValueError):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),before)

    def test_effect_order_collision_with_board_entity_is_rejected(self):
        g=self.game(hand=('AV_344',),board=('plain',));self.play(g,'AV_344');data=g.snapshot()
        data['state']['players']['1']['player_effects'][0]['entered_order']=g.state.entities[g.state.players[1].board[0]].entered_order
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_public_effect_event_counter_corruption_is_rejected(self):
        g=self.game(hand=('AV_344',));self.play(g,'AV_344');data=g.snapshot()
        event=next(e for e in data['information']['players']['1']['events'] if e['kind']=='player_effect_added')
        event['player_effect']['remaining_turns']=0
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_real_player_command_example_restores_and_replays(self):
        from examples.persistent_effects import run
        g,snapshot=run();self.assertEqual(snapshot['schema_version'],265);self.assertEqual(len(g.history),12)


if __name__ == '__main__':
    unittest.main()
