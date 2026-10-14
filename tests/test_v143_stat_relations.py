"""Synthetic public relation combinations; no real Lightspawn or CN adapter."""
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardDefinition, CardType, DamageKind,
    EndTurn, Game, GrantStatRelation, HealthFlow, HealthLayer, HealthOp, HealthRule, Keyword,
    PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, StatReference, StatRelationSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, EquipWeapon, Freeze, GainArmor, GrantKeyword,
    Heal, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, SetStats,
    Silence, Summon, SwapStats, DoubleStats, Transform)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import validate_frame_references, validate_definition


REL = StatRelationSpec()


def registry():
    r = Registry('isolated-v143-self-current-health-final-attack')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=2, health=8))
    r.register_card(CardDefinition('enemy', 'Enemy', CardType.MINION, attack=4, health=12))
    r.register_card(CardDefinition('fusion', 'Fusion', CardType.MINION, attack=2, health=5,
        keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',)))
    r.register_card(CardDefinition('actor', 'Relation', CardType.MINION, attack=0, health=8,
        keywords=(Keyword.CHARGE,), stat_relations=(REL,)))
    r.register_card(CardDefinition('base2', 'Base two', CardType.MINION, attack=2, health=8,
        stat_relations=(REL,)))
    r.register_card(CardDefinition('enemy_rel', 'Enemy relation', CardType.MINION, health=7,
        stat_relations=(REL,)))
    r.register_card(CardDefinition('dormant', 'Dormant relation', CardType.MINION, health=8,
        dormant_turns=2, stat_relations=(REL,)))
    r.register_card(CardDefinition('aura', 'Stat aura', CardType.MINION, attack=1, health=6,
        auras=(AuraSpec(3, health=2),)))
    r.register_card(CardDefinition('lifesteal', 'Relation lifesteal', CardType.MINION, health=8,
        keywords=(Keyword.CHARGE, Keyword.LIFESTEAL), stat_relations=(REL,)))
    r.register_card(CardDefinition('redirect_damage', 'Redirect', CardType.MINION, health=8,
        stat_relations=(REL,), health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT,
            layer=HealthLayer.TARGET, target_relation='friendly', redirect_to='self', target_kinds=(CardType.MINION,)),)))
    r.register_card(CardDefinition('redirect_heal', 'Heal receiver', CardType.MINION, health=8,
        stat_relations=(REL,), health_rules=(HealthRule(HealthFlow.HEALING, HealthOp.REDIRECT,
            layer=HealthLayer.TARGET, target_relation='friendly', redirect_to='self'),)))
    r.register_card(CardDefinition('converter', 'Converter', CardType.MINION, attack=1, health=8,
        health_rules=(HealthRule(HealthFlow.HEALING, HealthOp.CONVERT,
            target_relation='friendly', target_kinds=(CardType.MINION,)),)))

    def death_wait(c):
        return [RequestChoice(c.player_id, (ChoiceOption('record', 'Record',
            (GainArmor(c.player_id, 1),)),), source_id=c.source_id)]
    r.register_behavior('death_wait', death_wait)
    r.register_card(CardDefinition('reborn_rel', 'Reborn relation', CardType.MINION, health=4,
        stat_relations=(REL,), keywords=(Keyword.REBORN,), deathrattle='death_wait'))

    def declared_wait(c):
        attacker = c.event.source_id
        if c.event.player_id != 1:
            return []
        return [RequestChoice(1, (ChoiceOption('injure', 'Injure',
            (Damage(attacker, 3, c.source_id),)),), source_id=c.source_id)]
    r.register_behavior('declared_wait', declared_wait)
    r.register_card(CardDefinition('watcher', 'Declared watcher', CardType.MINION, attack=1, health=6,
        triggers=(TriggerSpec('attack_declared', 'declared_wait'),)))

    r.register_behavior('quote_attack', lambda c: [GainArmor(c.player_id,
        c.state.entities[c.target_id].attack)])

    def inner_wait(c):
        copied = c.state.players[1].board[-1]
        return [RequestChoice(1, (ChoiceOption('inner', 'Inner',
            (GrantStatRelation(copied, REL, c.source_id), Damage(copied, 1, c.source_id))),),
            source_id=c.source_id)]
    r.register_behavior('inner_wait', inner_wait)

    def relation_wait(c):
        good = (GrantStatRelation(c.target_id, REL, c.source_id, c.state.turn+2),
                Buff(c.target_id, health=-1, source_id=c.source_id), CopyMinion(c.target_id, 1),
                InvokeBehavior('inner_wait', player_id=1, source_id=c.source_id))
        bad = (GrantStatRelation(c.target_id, REL, c.source_id),
               Buff(c.target_id, health=-30, source_id=c.source_id),
               RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
               EquipWeapon(1, 'plain'))
        return [RequestChoice(1, (ChoiceOption('good', 'Good', good), ChoiceOption('bad', 'Bad', bad)),
            source_id=c.source_id), GrantStatRelation(c.target_id, REL, c.source_id)]

    def stale_wait(c):
        old=c.target_id
        return [Buff(old,health=-30,source_id=c.source_id), Summon(1,'plain'),
            RequestChoice(1,(ChoiceOption('skip','Skip',
                (GrantStatRelation(old,REL,c.source_id),)),),source_id=c.source_id)]

    behaviors = {
        'hurt': lambda c: [Damage(c.target_id, 2, c.source_id)],
        'hurt3': lambda c: [Damage(c.target_id, 3, c.source_id)],
        'hurt4': lambda c: [Damage(c.target_id, 4, c.source_id)],
        'heal': lambda c: [Heal(c.target_id, 2, c.source_id)],
        'overheal': lambda c: [Heal(c.target_id, 30, c.source_id)],
        'atk': lambda c: [Buff(c.target_id, attack=5, source_id=c.source_id)],
        'negatk': lambda c: [Buff(c.target_id, attack=-9, source_id=c.source_id)],
        'hp': lambda c: [Buff(c.target_id, health=3, source_id=c.source_id)],
        'neghp': lambda c: [Buff(c.target_id, health=-3, source_id=c.source_id)],
        'setatk': lambda c: [SetStats(c.target_id, attack=1, source_id=c.source_id)],
        'swap': lambda c: [SwapStats(c.target_id, c.source_id)],
        'double': lambda c: [DoubleStats(c.target_id, attack=True, health=True, source_id=c.source_id)],
        'kill': lambda c: [Destroy(c.target_id, c.source_id)],
        'silence': lambda c: [Silence(c.target_id)],
        'copy': lambda c: [CopyMinion(c.target_id, 2)],
        'copybase': lambda c: [CopyMinion(c.target_id, 2, mode='base')],
        'freeze': lambda c: [Freeze(c.target_id, c.source_id)],
        'control': lambda c: [ChangeControl(c.target_id, 2)],
        'plainform': lambda c: [Transform(c.target_id, 'plain')],
        'relform': lambda c: [Transform(c.target_id, 'actor')],
        'bounce': lambda c: [ReturnToHand(c.target_id, to_owner=True)],
        'grant': lambda c: [GrantStatRelation(c.target_id, REL, c.source_id)],
        'grant1': lambda c: [GrantStatRelation(c.target_id, REL, c.source_id, c.state.turn)],
        'grant3': lambda c: [GrantStatRelation(c.target_id, REL, c.source_id, c.state.turn+2)],
        'shield': lambda c: [GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id)],
        'batch': lambda c: [DamageBatch((Damage(c.target_id, 1, c.source_id, on_result='quote_attack'),
            Damage(c.target_id, 2, c.source_id, on_result='quote_attack')))],
        'separate': lambda c: [Damage(c.target_id, 1, c.source_id, on_result='quote_attack'),
            Damage(c.target_id, 2, c.source_id, on_result='quote_attack')],
        'wait': relation_wait,
        'stale_wait': stale_wait,
    }
    for name, behavior in behaviors.items():
        r.register_behavior(name, behavior)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=True))
    return r


class StatRelationTests(unittest.TestCase):
    def save_blob(self, value, label):
        directory = os.environ.get('V143_INPUT_DIR')
        if not directory:
            return
        self.input_number = getattr(self, 'input_number', 0)+1
        p = Path(directory)/self._testMethodName
        p.mkdir(parents=True, exist_ok=True)
        (p/(f'{self.input_number:03d}-'+label+'.json')).write_text(
            json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def game(self, hand=(), board=('actor',), enemy=('enemy',), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy, mana=10, max_mana=10),
        ), seed=143), registry())

    def cast(self, g, name, target):
        self.save_blob(g.snapshot(), 'before-cast-'+name)
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid, target))

    def choose(self, g, name):
        self.save_blob(g.snapshot(), 'before-choice-'+name)
        p = g.state.pending_choice
        return g.apply(SelectChoice(p.player_id, p.id, (name,)))

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        self.save_blob(snap, 'restore-clone-fresh-registry-replay')
        restored = Game.from_snapshot(snap, registry())
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return restored

    def rows(self, g, eid):
        return tuple(a for a in g.state.entities[eid].abilities if a.kind == 'stat_relation')

    def private(self, g):
        public = json.dumps(g.observe(1))+json.dumps(g.observe(2))
        public += json.dumps(g.for_player(1).legal_actions())
        for name in ('stat_relation', 'stat_relations', 'resolution_frame', 'SELF_CURRENT_HEALTH',
                     'source_id', 'next_attachment_id', 'paid_hand_choice_boundary'):
            self.assertNotIn('"'+name+'"', public)

    def rehash(self, snap):
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return snap

    def reject(self, snap, label, message=None):
        self.rehash(snap); self.save_blob(snap, 'rehash-negative-'+label)
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(snap, registry())
        if message:
            self.assertIn(message, str(caught.exception))

    def test_current_health_healing_prevention_and_nonactive_pure_display(self):
        g = self.game(('hurt','heal','overheal','shield','hurt'), board=('actor','dormant'))
        actor, dormant = g.state.players[1].board
        self.assertEqual((g.state.entities[dormant].active, g.state.entities[dormant].attack), (False,8))
        self.cast(g, 'hurt', actor)
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].health,g.state.entities[actor].max_health),(6,6,8))
        self.cast(g, 'heal', actor); self.assertEqual(g.state.entities[actor].attack,8)
        self.cast(g, 'overheal', actor); self.assertEqual(g.state.entities[actor].attack,8)
        self.cast(g, 'shield', actor); self.cast(g, 'hurt', actor)
        self.assertEqual(g.state.entities[actor].damage,0)
        before = g.snapshot()
        for _ in range(3):
            self.assertEqual(g.state.entities[actor].attack,8); g.observe(1); g.observe(2); g.legal_actions()
        self.assertEqual(g.snapshot(),before); self.private(g); self.portable(g)

    def test_ordered_attack_and_health_layers_are_preserved_under_final_relation(self):
        g = self.game(('hurt','atk','setatk','negatk','hp','neghp','swap','double'))
        actor = g.state.players[1].board[0]
        for name in ('hurt','atk','setatk','negatk'):
            self.cast(g,name,actor)
        e = g.state.entities[actor]
        self.assertEqual((e.attack,e.attack_bonus,e.damage),(6,-8,2))
        self.assertEqual([(x.attack,x.set_attack) for x in e.enchantments],[(5,None),(0,1),(-9,None)])
        self.cast(g,'hp',actor); self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].damage),(9,2))
        self.cast(g,'neghp',actor); self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].damage),(6,2))
        self.cast(g,'swap',actor)
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].max_health,g.state.entities[actor].damage),(6,6,0))
        self.cast(g,'double',actor); self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].health),(12,12))
        self.portable(g)

    def test_life_aura_removal_clamps_old_remaining_health_and_preserves_last_batch(self):
        g = self.game(('hurt4','kill'),board=('aura','actor','plain'))
        aura,actor,plain = g.state.players[1].board
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[plain].attack),(10,5))
        self.cast(g,'hurt4',actor); self.assertEqual((g.state.entities[actor].health,g.state.entities[actor].damage),(6,4))
        self.cast(g,'kill',aura)
        e = g.state.entities[actor]
        self.assertEqual((e.attack,e.health,e.max_health,e.damage,e.aura_attack),(6,6,8,2,0))
        self.assertEqual(g.state.entities[plain].attack,2)
        self.assertEqual(g.state.death_history[-1].entity_id,aura)
        snap=g.snapshot();self.portable(g);self.assertEqual(g.snapshot(),snap)

    def test_primary_packets_freeze_and_callbacks_observe_full_batch_not_interposed_sets(self):
        batch = self.game(('batch',)); separate=self.game(('separate',))
        for g,name,armor in ((batch,'batch',10),(separate,'separate',12)):
            actor=g.state.players[1].board[0]
            result=self.cast(g,name,actor)
            facts=[dict(dict(e.data)['result']) for e in result.events if e.kind=='health_resolved']
            self.assertEqual([(f['health_before'],f['health_after']) for f in facts],[(8,7),(7,5)])
            self.assertEqual(g.state.entities[actor].attack,5)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,armor)
            self.assertFalse(g.state.entities[actor].enchantments)
            self.portable(g)

    def test_real_declared_wait_changes_delivery_attack_but_not_frozen_retaliation(self):
        g=self.game(board=('actor','watcher'),enemy=('enemy_rel',))
        actor=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
        self.save_blob(g.snapshot(),'before-real-attack')
        g.apply(Attack(1,actor,enemy)); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[actor].attack,8)
        restored=self.portable(g); clone=g.clone()
        for branch in (g,restored,clone):
            result=self.choose(branch,'injure')
            combat=[e for e in result.events if e.kind=='damage_dealt' and dict(e.data).get('damage_kind')=='combat']
            self.assertEqual([e.amount for e in combat],[5,7])
            self.assertEqual(branch.state.entities[enemy].attack,2)
            self.assertEqual(branch.state.entities[actor].zone,Zone.GRAVEYARD)
            death=next(d for d in branch.state.death_history if d.entity_id==actor)
            self.assertEqual((death.attack,death.max_health,death.damage),(0,8,10))
            self.private(branch);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())

    def test_conversion_routing_and_redirected_intrinsic_lifesteal_use_actual_health(self):
        g=self.game(('hurt','heal'),board=('actor','converter'))
        actor=g.state.players[1].board[0]
        self.cast(g,'hurt',actor);self.cast(g,'heal',actor)
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].damage),(4,4));self.portable(g)
        redirected=self.game(('hurt3',),board=('actor','redirect_damage'))
        actor,receiver=redirected.state.players[1].board
        result=self.cast(redirected,'hurt3',actor)
        self.assertEqual((redirected.state.entities[actor].attack,redirected.state.entities[receiver].attack),(8,5))
        self.assertTrue(any(e.kind=='health_effect_redirected' and e.target_id==receiver for e in result.events))
        self.portable(redirected)
        steal=self.game(('hurt3',),board=('lifesteal','redirect_heal'),enemy=('enemy',))
        actor,receiver=steal.state.players[1].board;enemy=steal.state.players[2].board[0]
        self.cast(steal,'hurt3',receiver)
        self.save_blob(steal.snapshot(),'before-lifesteal-combat');steal.apply(Attack(1,actor,enemy))
        self.assertEqual((steal.state.entities[actor].attack,steal.state.entities[receiver].attack),(4,8))
        self.assertEqual(steal.state.entities[steal.state.players[1].hero_id].health,80);self.portable(steal)

    def test_duplicate_grant_ids_expire_independently_and_silence_allows_new_grant(self):
        g=self.game(('grant1','grant3'),board=('plain',))
        actor=g.state.players[1].board[0]
        self.cast(g,'grant1',actor);self.cast(g,'grant3',actor)
        rows=self.rows(g,actor);self.assertEqual(len(rows),2);self.assertNotEqual(rows[0].id,rows[1].id)
        self.assertEqual(g.state.entities[actor].attack,8)
        g.apply(EndTurn(1));self.assertEqual(self.rows(g,actor),(rows[1],));self.assertEqual(g.state.entities[actor].attack,8)
        g.apply(EndTurn(2));g.apply(EndTurn(1));self.assertEqual(self.rows(g,actor),());self.assertEqual(g.state.entities[actor].attack,2)
        self.portable(g)
        silenced=self.game(('atk','hurt','silence','grant'),board=('aura','base2'))
        actor=silenced.state.players[1].board[1]
        self.cast(silenced,'atk',actor);self.cast(silenced,'hurt',actor);self.cast(silenced,'silence',actor)
        self.assertEqual((silenced.state.entities[actor].attack,silenced.state.entities[actor].health),(5,8))
        self.assertEqual(self.rows(silenced,actor),())
        self.cast(silenced,'grant',actor);self.assertTrue(silenced.state.entities[actor].silenced)
        self.assertEqual(silenced.state.entities[actor].attack,8);self.portable(silenced)

    def test_current_copy_self_is_independent_and_base_copy_does_not_freeze_old_relation(self):
        g=self.game(('hurt','grant','freeze','copy','copybase','heal','hurt'),board=('aura','actor'))
        actor=g.state.players[1].board[1]
        for name in ('hurt','grant','freeze','copy','copybase'):self.cast(g,name,actor)
        current,base=g.state.players[2].board[-2:]
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[current].attack,g.state.entities[base].attack),(8,6,8))
        self.assertEqual((g.state.entities[current].damage,g.state.entities[base].damage),(2,0))
        self.assertEqual((g.state.entities[actor].frozen_until_owner_turn,g.state.entities[current].frozen_until_owner_turn),(1,1))
        self.assertFalse(g.state.entities[base].frozen)
        rowids=[a.id for eid in (actor,current,base) for a in self.rows(g,eid)]
        self.assertEqual(len(set(rowids)),5)
        self.assertEqual([a.source_id for a in self.rows(g,current)],[a.source_id for a in self.rows(g,actor)])
        self.cast(g,'heal',actor);self.cast(g,'hurt',current)
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[current].attack,g.state.entities[base].attack),(10,4,8))
        self.portable(g)

    def test_control_transform_and_bounce_keep_original_identity_and_reset_relation_face(self):
        g=self.game(('control','plainform','relform','bounce'),board=('aura','actor'))
        actor=g.state.players[1].board[1];enemy=g.state.players[2].board[0]
        g.apply(Attack(1,actor,enemy)); rows=self.rows(g,actor);epoch=g.state.entities[actor].zone_epoch
        self.cast(g,'control',actor)
        self.assertEqual((g.state.entities[actor].owner,g.state.entities[actor].controller,g.state.entities[actor].attack),(1,2,6))
        self.assertEqual(self.rows(g,actor),rows)
        self.cast(g,'plainform',actor)
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].attacks_this_turn),(2,1));self.assertEqual(self.rows(g,actor),())
        self.assertGreater(g.state.entities[actor].zone_epoch,epoch)
        self.cast(g,'relform',actor);self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].damage),(8,0))
        self.cast(g,'bounce',actor);self.assertEqual(g.state.entities[actor].zone,Zone.HAND)
        self.assertEqual(g.observe(1)['players'][0]['hand'][-1]['attack'],8)
        g.apply(PlayCard(1,actor));self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].damage),(10,0))
        self.portable(g)

    def test_death_record_uses_own_final_health_and_reborn_reinstalls_new_self(self):
        g=self.game(('hurt','grant','neghp'),board=('reborn_rel',))
        actor=g.state.players[1].board[0]
        self.cast(g,'hurt',actor);self.cast(g,'grant',actor);self.cast(g,'neghp',actor)
        self.assertIsNotNone(g.state.pending_choice);record=g.state.death_history[-1]
        self.assertEqual((record.attack,record.max_health,record.damage),(0,1,2));self.assertEqual(len([a for a in record.abilities if a.kind=='stat_relation']),2)
        restored=self.portable(g)
        for branch in (g,restored):
            self.choose(branch,'record');new=branch.state.players[1].board[-1]
            self.assertNotEqual(actor,new);self.assertEqual((branch.state.entities[new].attack,branch.state.entities[new].health),(1,1))
            self.assertEqual(len(self.rows(branch,new)),1);self.assertEqual(branch.state.death_history[-1],record);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())
        doomed=self.game(('hurt','kill'));actor=doomed.state.players[1].board[0]
        self.cast(doomed,'hurt',actor);self.cast(doomed,'kill',actor)
        record=doomed.state.death_history[-1];self.assertEqual((record.attack,record.max_health-record.damage),(6,6))
        bad=doomed.snapshot();bad['state']['death_history'][-1]['attack']=0
        self.reject(bad,'frozen-positive-doomed-attack','Frozen stat relation attack')

    def test_nested_waiting_restore_clone_replay_and_original_proof_scope(self):
        g=self.game(('wait',),board=('plain',),enemy_hand=('actor',))
        actor=g.state.players[1].board[0]
        self.cast(g,'wait',actor);self.assertIsNotNone(g.state.pending_choice)
        original_proof=g._frame.paid_hand_choice_boundary
        restored=self.portable(g);clone=g.clone()
        for branch in (g,restored,clone):
            self.choose(branch,'good');self.assertIsNotNone(branch.state.pending_choice)
            copy=branch.state.players[1].board[-1]
            self.assertEqual((branch.state.entities[actor].attack,branch.state.entities[copy].attack),(7,7))
            self.private(branch);self.portable(branch)
            if branch is g:
                effect=GrantStatRelation(copy,REL,source_id=original_proof.event.source_id)
                validate_frame_references(branch.state,branch.registry,effect)
                invalid=replace(original_proof,work=(effect,))
                with self.assertRaisesRegex(ValueError,'Unknown continuous stat relation target'):
                    FrameCodec(branch.mechanics,branch.registry).encode(invalid)
            self.choose(branch,'inner')
            self.assertEqual((branch.state.entities[actor].attack,branch.state.entities[copy].attack),(7,6))
            self.assertEqual((len(self.rows(branch,actor)),len(self.rows(branch,copy))),(2,2))
            self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())
        enemy_identity=g.observe(1)['players'][1]['hand']
        self.assertEqual(len(enemy_identity),1)
        self.assertEqual(set(enemy_identity[0]),{'ref','card_id'})
        self.assertIsNone(enemy_identity[0]['card_id'])

    def test_rehashed_closed_payload_carrier_future_work_and_real_choice_failure_roll_back(self):
        g=self.game(('wait',),board=('plain',));actor=g.state.players[1].board[0]
        self.cast(g,'wait',actor);before=g.snapshot();restored=self.portable(g)
        def typed(value, name):
            if isinstance(value,dict):
                if value.get('type')==name:return value
                for child in value.values():
                    result=typed(child,name)
                    if result is not None:return result
            if isinstance(value,list):
                for child in value:
                    result=typed(child,name)
                    if result is not None:return result
            return None
        for field in ('target_id','source_id'):
            bad=json.loads(json.dumps(before));grant=typed(bad['resolution_frame']['fields']['options'],'hs_sim.engine.stat_relations.GrantStatRelation')
            grant['fields'][field]=bad['state']['next_entity_id']+100
            self.reject(bad,'future-'+field,'Unknown continuous stat relation '+('target' if field=='target_id' else 'source'))
        bad=json.loads(json.dumps(before));spec=typed(bad['resolution_frame'],'hs_sim.engine.model.StatRelationSpec')
        spec['fields']['target']['value']='max_health';self.reject(bad,'max-health-operand','Unsupported continuous stat relation')
        bad=json.loads(json.dumps(before));spec=typed(bad['resolution_frame'],'hs_sim.engine.model.StatRelationSpec')
        spec['fields']['extra']=1;self.reject(bad,'extra-spec-field')
        actor_game=self.game();eid=actor_game.state.players[1].board[0];snap=actor_game.snapshot()
        bad=json.loads(json.dumps(snap));row=next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='stat_relation')
        row['stat_relation']['operand']='source_health';self.reject(bad,'foreign-operand')
        bad=json.loads(json.dumps(snap));row=next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='stat_relation')
        row['stat_relation']['layer']='before_aura';self.reject(bad,'unknown-layer')
        bad=json.loads(json.dumps(snap));row=next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='stat_relation')
        row['kind']='keyword';self.reject(bad,'wrong-ability-kind','Only stat relation abilities')
        bad=json.loads(json.dumps(snap));entity=bad['state']['entities'][str(eid)];row=next(a for a in entity['abilities'] if a['kind']=='stat_relation');entity['abilities'].remove(row)
        row['origin']='granted';hero=bad['state']['players']['1']['hero_id'];bad['state']['entities'][str(hero)]['abilities'].append(row)
        self.reject(bad,'hero-carrier','non-composite minion or native weapon carrier')
        with self.assertRaises(ValueError):StatRelationSpec(target=StatReference.MAX_HEALTH)
        with self.assertRaises(ValueError):StatRelationSpec(target=True)
        with self.assertRaises(ValueError):validate_definition(CardDefinition('fusion','Fusion',CardType.MINION,
            health=5,keywords=(Keyword.MAGNETIC,),stat_relations=(REL,)))
        for branch in (g,restored):
            history=branch.history;clock=branch.state.owner_turn_history
            with self.assertRaises(ResolutionError):self.choose(branch,'bad')
            self.assertEqual(branch.snapshot(),before);self.assertEqual(branch.history,history)
            self.assertEqual(branch.state.owner_turn_history,clock);self.assertEqual(branch.state.death_history,[])
            self.assertEqual(self.rows(branch,actor),());self.choose(branch,'good');self.choose(branch,'inner')
        self.assertEqual(g.snapshot(),restored.snapshot());self.private(g);self.portable(g)


    def test_known_stale_waiting_grant_does_not_bind_new_same_face(self):
        g=self.game(('stale_wait',),board=('plain',))
        old=g.state.players[1].board[0]
        self.cast(g,'stale_wait',old);self.assertIsNotNone(g.state.pending_choice)
        new=g.state.players[1].board[-1]
        self.assertNotEqual(new,old)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[new].card_id,g.state.entities[old].card_id)
        record=g.state.death_history[-1]
        restored=self.portable(g);clone=g.clone()
        for branch in (g,restored,clone):
            result=self.choose(branch,'skip')
            skipped=[dict(e.data) for e in result.events if e.kind=='effect_skipped']
            self.assertTrue(any(d.get('effect')=='GrantStatRelation' for d in skipped))
            self.assertEqual(self.rows(branch,new),())
            self.assertEqual(branch.state.entities[new].attack,2)
            self.assertEqual(branch.state.death_history[-1],record)
            self.private(branch);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())

    def test_dynamic_fusion_carrier_rejects_at_delivery_and_rehashed_restore(self):
        g=self.game(('grant',),board=('fusion',));target=g.state.players[1].board[0]
        before=g.snapshot();self.save_blob(before,'before-unsupported-fusion-grant')
        with self.assertRaisesRegex(ResolutionError,'ordinary non-fusion'):
            self.cast(g,'grant',target)
        self.assertEqual(g.snapshot(),before)
        self.assertEqual(self.rows(g,target),())
        donor=self.game();eid=donor.state.players[1].board[0]
        row=next(a for a in donor.snapshot()['state']['entities'][str(eid)]['abilities'] if a['kind']=='stat_relation')
        bad=json.loads(json.dumps(before));row['origin']='granted';row['source_id']=target
        bad['state']['entities'][str(target)]['abilities'].append(row)
        bad['state']['next_attachment_id']=max(bad['state']['next_attachment_id'],row['id']+1)
        self.reject(bad,'dynamic-fusion-carrier','ordinary non-fusion')
        self.portable(g)


if __name__=='__main__':
    unittest.main()
