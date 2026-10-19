"""Ascendance uses the real paid spell, ordinary transformations and captured Deathrattles."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.ascendance_card import CARD, RETURN, load_batch
from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.cross_zone import MinionScope, TransformMinionsInZones, TransformCapturedMinion
from hs_sim.engine.effects import Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, GainArmor, GrantDeathrattle, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_rules import spell_damage_sources
from hs_sim.engine.model import CardClass, CardMetadata, DeathrattleMemory, NativeDeathrattleSpec, SummonQuantitySpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest

P = 'ascendance.test.'
A, B, SLEEP, WATCH, FAIL, POP, DOUBLE = (P + x for x in ('a', 'b', 'sleep', 'watch', 'fail', 'pop', 'double'))
FILL, KILL, BUFF, TEMP, CURRENT, BASE, QUIET, CHANGE, BOUNCE, GIVE, TRIGGER = (P + x for x in (
    'fill', 'kill', 'buff', 'temp', 'current', 'base', 'quiet', 'change', 'bounce', 'give', 'trigger'))
EVOLVED = {n: P + 'evolved' + str(n) for n in (2, 3, 4)}
CONTEXT = GenerationContext('ascendance-local-fixture-v1', 'experimental')


@lru_cache(maxsize=None)
def registry(role='writer', mode='normal'):
    assert role in ('writer', 'reader')
    r = build_registry(); meta = CardMetadata(True, (CardClass.NEUTRAL,), None, tribes=())
    r.register_behavior(P + 'bc', lambda c: (GainArmor(c.player_id, 99),))
    for cid, cost, attack, health, dormant in ((A, 2, 3, 6, 0), (B, 3, 4, 5, 0), (SLEEP, 2, 2, 5, 2)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=attack, health=health,
            dormant_turns=dormant, metadata=meta, battlecry=P + 'bc'))
    r.register_behavior(P + 'natural', lambda c: (GainArmor(c.player_id, 1),))
    for cost, cid in EVOLVED.items():
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=cost+2, health=7,
            metadata=meta, deathrattle=P + 'natural', dormant_turns=1 if mode == 'dormant' and cost == 3 else 0))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    members = [] if mode == 'empty' else [PoolMember(cid) for cid in EVOLVED.values()]
    if mode == 'unknown':
        c = replace(r.card(EVOLVED[4]), id=P + 'unknown'); r.register_pool_card(PoolCard.from_definition(c)); members.append(PoolMember(c.id))
    r.register_pool(PoolDefinition('constructed.cards', 'ascendance-fixture-v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(sorted(members, key=lambda x: x.card_id))))

    def evolved(c):
        return next(c.state.entities[i] for pid in (1, 2) for i in c.state.players[pid].board if c.state.entities[i].card_id in EVOLVED.values())
    scripts = {
        FILL: lambda c: (), KILL: lambda c: (Destroy(evolved(c).id, c.source_id),),
        BUFF: lambda c: (Buff(c.state.players[c.player_id].board[0], 2, 3, c.source_id), Damage(c.state.players[c.player_id].board[0], 2, c.source_id)),
        TEMP: lambda c: (Buff(c.state.players[c.player_id].board[0], 5, 0, c.source_id, expires_turn=c.state.turn),),
        CURRENT: lambda c: (CopyMinion(evolved(c).id, c.player_id),), BASE: lambda c: (CopyMinion(evolved(c).id, c.player_id, mode='base'),),
        QUIET: lambda c: (Silence(evolved(c).id),), CHANGE: lambda c: (Transform(evolved(c).id, B),),
        BOUNCE: lambda c: (ReturnToHand(evolved(c).id),), GIVE: lambda c: (ChangeControl(evolved(c).id, 2),),
        TRIGGER: lambda c: (TriggerDeathrattles(evolved(c).id, c.source_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body); r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    def fail(c): raise ResolutionError('Deliberate Ascendance reaction failure')
    r.register_behavior(P + 'fail_body', fail)
    def react(c, mode):
        if dict(c.event.data).get('card_id') not in EVOLVED.values(): return ()
        e = c.state.entities[c.event.target_id]
        if not any(a.deathrattle_memory is not None for a in e.abilities):
            raise ResolutionError('Transformation published before remembered grant installation')
        if mode == 'pop': return (Destroy(e.id, c.source_id),)
        if mode == 'fail': return (InvokeBehavior(P + 'fail_body', c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('kill', 'Destroy transformed original', (Destroy(e.id, c.source_id),)),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P + 'fail_body', c.source_id, c.player_id),))), c.source_id),)
    for cid, mode in ((WATCH, 'watch'), (FAIL, 'fail'), (POP, 'pop')):
        r.register_behavior(cid, lambda c, mode=mode: react(c, mode))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=30, health=5, metadata=meta,
            triggers=(TriggerSpec('transformed', cid),)))
    r.register_card(CardDefinition(DOUBLE, DOUBLE, CardType.MINION, cost=30, health=5, metadata=meta,
        summon_quantities=(SummonQuantitySpec(),)))
    r.validate(); r.freeze(); return r


class AscendanceTests(unittest.TestCase):
    def game(self, hand=(CARD, KILL), board=(A,), *, enemy=(B,), mode='normal'):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_02', hand=hand, board=board, deck=(FILL,)*20, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=(FILL,)*20, mana=10, max_mana=10)),
            generation_context=CONTEXT, seed=263), registry('writer', mode))
    def play(self, g, cid=CARD):
        pid=g.state.active_player; i=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid, i)); return i
    def choose(self, g, key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def copies(self, g, pid=1):
        return [d.entity.entity_id for root in g.state.card_summon_history
            if isinstance(root.request.materials[0], CopyEntryMaterial) and root.request.materials[0].profile=='remembered_copy'
            for d in root.deliveries if d.entity is not None and d.entity.controller==pid]
    def portable(self, g):
        s=json.loads(json.dumps(g.snapshot())); other=Game.from_snapshot(s, registry('reader',self.mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry('reader',self.mode)).snapshot(),s);return other

    def test_a00_complete_real_spell_primary_faces_and_nonexecutable_enchantment(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),2)
        self.assertEqual(d['cards'][0]['record']['cost'],4);self.assertEqual(d['evidence_only'][0]['record']['id'],'CATA_567e')
        self.assertNotIn('CATA_567e',registry().cards)

    def test_a01_paid_batch_transforms_original_positions_and_death_returns_frozen_original(self):
        g=self.game(board=(A,B));old=tuple(g.state.players[1].board);enemy=tuple(g.state.players[2].board);self.play(g)
        self.assertEqual(g.state.players[1].board,list(old));self.assertEqual(tuple(g.state.players[2].board),enemy)
        self.assertEqual([g.state.entities[i].card_id for i in old],[EVOLVED[3],EVOLVED[4]])
        self.assertEqual(g.state.players[1].mana,6);self.assertFalse(g.state.death_history);self.assertFalse(g.state.card_summon_history)
        self.play(g,KILL);copy=self.copies(g)[0];self.assertEqual(g.state.entities[copy].card_id,A)
        self.assertEqual(g.state.players[1].board[0],copy)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)

    def test_a02_current_buffs_and_damage_use_frozen_original_without_leaving_old_layers_on_transform(self):
        g=self.game((BUFF,CARD,KILL));self.play(g,BUFF);self.play(g)
        transformed=g.state.entities[g.state.players[1].board[0]];self.assertEqual((transformed.attack,transformed.max_health,transformed.damage),(5,7,0))
        self.play(g,KILL);e=g.state.entities[self.copies(g)[0]];self.assertEqual((e.attack,e.max_health,e.damage),(5,9,2))

    def test_a03_empty_friendly_board_and_empty_tier_have_no_random_or_grant(self):
        for board,mode in (((),'normal'),((A,),'empty')):
            with self.subTest(board=board,mode=mode):
                g=self.game(board=board,mode=mode);rng=g._rng.getstate();self.play(g)
                self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.copies(g))
                self.assertFalse(any(a.deathrattle_memory is not None for i in g.state.players[1].board for a in g.state.entities[i].abilities))

    def test_a04_unknown_eligible_definition_rejects_whole_batch_before_random_payment_or_transform(self):
        g=self.game(board=(A,B),mode='unknown');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_a05_dormant_original_is_untouched_and_dormant_destination_keeps_complete_grant(self):
        g=self.game(board=(A,SLEEP),mode='dormant');sleep=g.state.players[1].board[1];self.play(g)
        first=g.state.entities[g.state.players[1].board[0]]
        self.assertIsNotNone(first.dormancy);self.assertTrue(any(a.deathrattle_memory is not None for a in first.abilities))
        self.assertEqual(g.state.entities[sleep].card_id,SLEEP);self.portable(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,KILL);self.assertEqual(g.state.entities[self.copies(g)[0]].card_id,A)

    def test_b00_immediate_transform_reaction_death_already_has_original_payload(self):
        g=self.game(board=(A,POP));self.play(g);self.assertEqual(len(self.copies(g)),1)
        self.assertEqual(g.state.entities[self.copies(g)[0]].card_id,A)

    def test_b01_silence_and_later_transform_remove_return_grant(self):
        for operation in (QUIET,CHANGE):
            with self.subTest(operation=operation):
                g=self.game((CARD,operation,KILL));self.play(g);self.play(g,operation)
                if operation==QUIET:self.play(g,KILL)
                self.assertFalse(self.copies(g))

    def test_b02_current_copy_keeps_independent_return_grant_while_base_copy_does_not(self):
        for operation,count in ((CURRENT,2),(BASE,1)):
            with self.subTest(operation=operation):
                g=self.game((CARD,operation,KILL,KILL));self.play(g);self.play(g,operation);self.play(g,KILL);self.play(g,KILL)
                self.assertEqual(len(self.copies(g)),count)

    def test_b03_return_reset_replay_keeps_printed_deathrattle_without_old_original_return(self):
        g=self.game((CARD,BOUNCE,KILL));self.play(g);self.play(g,BOUNCE);self.play(g,EVOLVED[3]);self.play(g,KILL)
        self.assertFalse(self.copies(g));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)

    def test_b04_control_transfer_uses_actual_deathrattle_executor_and_original_material(self):
        g=self.game((CARD,GIVE,KILL));self.play(g);self.play(g,GIVE);self.play(g,KILL)
        e=g.state.entities[self.copies(g,2)[0]];self.assertEqual((e.card_id,e.owner,e.controller),(A,2,2))

    def test_b05_non_death_trigger_and_later_death_each_use_original_material(self):
        g=self.game((CARD,TRIGGER,KILL));self.play(g);self.play(g,TRIGGER);self.assertEqual(len(self.copies(g)),1)
        self.play(g,KILL);self.assertEqual(len(self.copies(g)),2)

    def test_b06_repeated_ascendance_keeps_nested_original_grants_with_finite_material(self):
        g=self.game((CARD,CARD,KILL,KILL));self.play(g);self.play(g);self.play(g,KILL)
        first=g.state.entities[self.copies(g)[0]];self.assertEqual(first.card_id,EVOLVED[3])
        self.play(g,KILL);self.assertEqual(g.state.entities[self.copies(g)[-1]].card_id,A)

    def test_c00_quantity_duplicates_returned_original_and_full_board_uses_shared_capacity(self):
        g=self.game(board=(A,DOUBLE));self.play(g);self.play(g,KILL);self.assertEqual(len(self.copies(g)),2)
        g=self.game((CARD,TRIGGER),board=(A,)+(DOUBLE,)*6);self.play(g);self.play(g,TRIGGER);self.assertFalse(self.copies(g))

    def test_c01_lapsed_temporary_layer_is_not_restarted_by_later_return(self):
        g=self.game((TEMP,CARD,KILL));self.play(g,TEMP);self.play(g);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,KILL)
        self.assertEqual(g.state.entities[self.copies(g)[0]].attack,3)

    def test_c02_real_damaged_seer_does_not_leave_permanent_spell_damage_after_transformation(self):
        g=self.game((BUFF,CARD,KILL),board=('END_022',));self.play(g,BUFF)
        def amount():return sum(row[3] for row in spell_damage_sources(g.state,1,g.registry))
        self.assertEqual(amount(),2);self.play(g);self.assertEqual(amount(),0)
        self.play(g,KILL);self.assertEqual(amount(),2)
        returned=self.copies(g)[0];self.assertEqual(g.state.entities[returned].card_id,'END_022')

    def test_d00_wait_after_first_transform_restores_original_second_step_and_failed_resume(self):
        g=self.game(board=(A,B,WATCH));self.play(g);other=self.portable(g);s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate Ascendance reaction failure'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),s)
        for game in (g,other):
            while game.state.pending_choice is not None:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].board),3)

    def test_d01_waiting_accepted_deathrattle_has_original_material_after_transform_source_is_gone(self):
        g=self.game(board=(A,WATCH));self.play(g);other=self.portable(g)
        self.choose(g,'kill');self.choose(other,'kill');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.copies(g)),1)
        self.portable(g)

    def test_d02_late_transform_reaction_failure_rolls_back_payment_all_bodies_grants_and_rng(self):
        g=self.game(board=(A,FAIL));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate Ascendance reaction failure'):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_d03_strict_memory_payload_shapes_future_capture_and_player_information(self):
        g=self.game();self.play(g)
        for pid in (1,2):
            view=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"summon_copy"','"deathrattle_memory"','"captured_action"'):self.assertNotIn(key,view)
        s=g.snapshot();eid=g.state.players[1].board[0];a=next(a for a in s['state']['entities'][str(eid)]['abilities'] if a['deathrattle_memory'] is not None)
        a['deathrattle_memory']['summon_copy']['captured_turn']+=5
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame','rewind_session','match_setup','generation_context','information')
        s['state_hash']=canonical_digest({k:s[k] for k in keys})
        with self.assertRaises(ValueError):Game.from_snapshot(s,registry('reader'))
        with self.assertRaises(ValueError):GrantDeathrattle(eid,RETURN,eid,deathrattle_memory=DeathrattleMemory(NativeDeathrattleSpec('draw_link')))
        with self.assertRaises(ValueError):TransformMinionsInZones(1,'constructed.cards',deathrattle_behavior_id=RETURN,source_id=eid)


if __name__=='__main__':unittest.main()
