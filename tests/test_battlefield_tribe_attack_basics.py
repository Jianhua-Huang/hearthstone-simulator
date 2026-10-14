"""One Old Murk-Eye, current other-board tribes and the existing kernel paths."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, Registry, ResolutionError, RewindSpec, Scenario, SelectChoice,
    SnapshotError, StatRelationLayer, StatRelationOperand, StatRelationSpec, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.model import AbilityInstance, TribeChangeSpec
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation, conditional_attack
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD = 'EX1_062'
PIN = '42b18d8ddae4659c63e5436ef15f1ecb01e9cde6bbd8e791ad53db5c104f3e2e'
REL = StatRelationSpec(operand=StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT,
    layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=1, count_tribe='murloc')


def evidence():
    data = json.loads((Path(__file__).resolve().parents[1] /
        'data/support/battlefield-tribe-attack-basics.json').read_bytes())
    if canonical_digest(data) != PIN: raise ValueError('Complete battlefield tribe evidence changed')
    for row in data['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Raw card changed')
    return data


def registry():
    r = Registry('isolated-other-battlefield-tribe-attack-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80, metadata=metadata()))
    for cid, tribes in (('murloc', ('murloc',)), ('plain', ()), ('all', ('all',)), ('dragon', ('dragon',))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=20, metadata=metadata(tribes=tribes)))
    r.register_card(CardDefinition('unknown-tribes', 'Unknown tribes', CardType.MINION, health=5))
    r.register_behavior('noop', lambda c: ())
    r.register_card(CardDefinition('location', 'Location', CardType.LOCATION, durability=2, on_use='noop', metadata=metadata()))
    raw = evidence()['records'][0]['data']
    r.register_card(CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.CHARGE,),
        stat_relations=(REL,), metadata=metadata_from_record(raw)))

    def change(c, operation, tribes):
        return (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec(operation, tribes), c.source_id),)
    def waiting(c):
        other = next(i for i in c.state.players[2].board if c.state.entities[i].card_id == 'murloc')
        return (RequestChoice(c.player_id, (
            ChoiceOption('kill', 'Remove another murloc', (Destroy(other, c.source_id),)),
            ChoiceOption('summon', 'Summon another murloc', (Summon(2, 'murloc'),)),
            ChoiceOption('fault', 'Remove then fail', (Destroy(other, c.source_id),
                InvokeBehavior('fault-body', c.source_id, c.player_id))),
        ), c.source_id),)
    scripts = {
        'summon': lambda c: (Summon(c.player_id, 'murloc'),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'lethal': lambda c: (Damage(c.target_id, 20, c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, 'plain'),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'copy': lambda c: (CopyMinion(c.target_id, 2),),
        'copy-base': lambda c: (CopyMinion(c.target_id, 2, mode='base'),),
        'buff': lambda c: (Buff(c.target_id, 3, source_id=c.source_id),),
        'sleep': lambda c: (MakeDormant(c.target_id, None, c.source_id),),
        'awake': lambda c: (AwakenMinion(c.state.players[c.player_id].board[0], c.source_id),),
        'add-murloc': lambda c: change(c, 'add', ('murloc',)),
        'remove-murloc': lambda c: change(c, 'remove', ('murloc',)),
        'wait': waiting,
        'fault': lambda c: (Summon(c.player_id, 'murloc'), InvokeBehavior('fault-body', c.source_id, c.player_id)),
    }
    targeted = set(scripts) - {'summon', 'wait', 'fault', 'awake'}
    for name, body in scripts.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            requires_target=name in targeted, metadata=metadata()))
    r.register_behavior('fault-body', lambda c: (AddToHand(c.player_id, 'unknown.battlefield-tribe'),))
    r.register_behavior('rewind-body', scripts['summon'])
    r.register_card(CardDefinition('rewind', 'Normalization retry', CardType.SPELL, cost=1,
        on_play='rewind-body', keywords=(Keyword.REWIND,), rewind=RewindSpec(), metadata=metadata()))
    r.register_behavior('declared-choice', lambda c: waiting(c) if c.event.source_id == c.state.players[c.player_id].board[0] else ())
    r.register_card(CardDefinition('watcher', 'Attack listener', CardType.MINION, health=5,
        triggers=(TriggerSpec('attack_declared', 'declared-choice'),), metadata=metadata(tribes=())))
    r.register_behavior('observe', lambda c: (Buff(c.source_id,
        c.state.entities[c.state.players[c.player_id].board[0]].attack, source_id=c.source_id),))
    r.register_card(CardDefinition('observer', 'Summon listener', CardType.MINION, health=5,
        triggers=tuple(TriggerSpec(event, 'observe') for event in ('minion_summoned','damage_dealt')),
        metadata=metadata(tribes=())))
    return r


class BattlefieldTribeAttackBasicsTests(unittest.TestCase):
    def game(self, hand=(), *, board=(CARD, 'murloc'), enemy=('murloc',), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', deck=('plain',)*3, hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', deck=('plain',)*3, hand=enemy_hand, board=enemy, mana=10, max_mana=10),
        ), seed=29), registry())
    def actor(self, g): return g.state.players[1].board[0]
    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]
    def cast(self, g, name, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid, target))
    def choose(self, g, name):
        p = g.state.pending_choice; return g.apply(SelectChoice(p.player_id, p.id, (name,)))
    def value(self, g, attack, contribution, eid=None):
        entity = g.state.entities[self.actor(g) if eid is None else eid]
        self.assertEqual((entity.attack, entity.conditional_attack), (attack, contribution))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot())); restored = Game.from_snapshot(snap, registry())
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return restored
    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snap, registry())

    def test_complete_raw_and_only_old_murk_eye_adapter(self):
        data = evidence(); card = registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'], [CARD])
        self.assertEqual((card.cost, card.attack, card.health, card.stat_relations), (4, 2, 4, (REL,)))
        self.assertEqual(card.metadata.tribes, ('murloc',)); self.assertEqual(card.keywords, (Keyword.CHARGE,))

    def test_closed_spec_old_defaults_and_no_new_grant(self):
        self.assertIsNone(StatRelationSpec().count_tribe)
        for changes in ({'count_tribe':None}, {'count_tribe':''}, {'count_tribe':True}, {'count_tribe':('murloc',)},
                {'amount':0}, {'amount':True}, {'layer':StatRelationLayer.FINAL_ATTACK}, {'card_count':1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(REL, **changes)
        with self.assertRaises(ValueError): replace(StatRelationSpec(), count_tribe='murloc')
        with self.assertRaises(ValueError): GrantStatRelation(1, REL, 1)
        with self.assertRaises(ValueError): Registry('bad').register_card(CardDefinition('bad','Bad',CardType.WEAPON,
            durability=2, stat_relations=(REL,), metadata=metadata()))

    def test_both_boards_other_physical_minions_and_no_duplicate_identity_weight(self):
        g = self.game(board=(CARD,'murloc','murloc','plain','location'), enemy=('murloc','all','dragon'))
        self.value(g, 6, 4); self.portable(g)
        alone = self.game(board=(CARD,), enemy=()); self.value(alone, 2, 0)

    def test_summon_removal_and_hand_zone_are_current_without_accumulation(self):
        g = self.game(('summon','kill','bounce'))
        self.cast(g,'summon'); self.value(g, 5, 3)
        self.cast(g,'kill',g.state.players[1].board[-1]); self.value(g, 4, 2)
        self.cast(g,'bounce',g.state.players[2].board[0]); self.value(g, 3, 1)
        self.assertEqual(g.state.entities[self.actor(g)].base_attack, 2); self.portable(g)

    def test_current_tribes_and_all_tribe_exclusions_are_used(self):
        g = self.game(('add-murloc','remove-murloc','silence'), board=(CARD,'dragon'), enemy=('all',))
        other = g.state.players[1].board[1]; universal = g.state.players[2].board[0]
        self.value(g,3,1); self.cast(g,'add-murloc',other); self.value(g,4,2)
        self.cast(g,'remove-murloc',universal); self.value(g,3,1)
        self.cast(g,'silence',other); self.value(g,2,0); self.portable(g)

    def test_unknown_other_tribe_metadata_is_not_silently_omitted(self):
        with self.assertRaises(UnsupportedDefinitionError): self.game(enemy=('unknown-tribes',))
        g = self.game()
        with self.assertRaisesRegex(ValueError,'fixed registry'): conditional_attack(g.state,g.state.entities[self.actor(g)])

    def test_native_silence_removes_contribution_and_current_copy_stays_silenced(self):
        g = self.game(('silence','copy')); source = self.actor(g)
        self.cast(g,'silence',source); self.value(g,2,0)
        self.cast(g,'copy',source); copied = g.state.players[2].board[-1]
        self.value(g,2,0,copied); self.assertFalse(any(a.kind=='stat_relation' for a in g.state.entities[copied].abilities))
        self.portable(g)

    def test_current_copy_and_base_copy_recompute_local_other_count(self):
        for name in ('copy','copy-base'):
            with self.subTest(name=name):
                g = self.game((name,)); source = self.actor(g); self.cast(g,name,source)
                copied = g.state.players[2].board[-1]
                self.value(g,5,3,source); self.value(g,5,3,copied)
                a = next(a for a in g.state.entities[source].abilities if a.kind=='stat_relation')
                b = next(a for a in g.state.entities[copied].abilities if a.kind=='stat_relation')
                self.assertNotEqual(a.id,b.id); self.portable(g)

    def test_bounce_and_replay_install_native_relation_again(self):
        g = self.game(('bounce',)); source = self.actor(g); self.cast(g,'bounce',source)
        self.cast(g,CARD); self.value(g,4,2,source)
        self.assertEqual(g.state.players[1].mana,6); self.portable(g)

    def test_transform_changes_count_and_resets_carrier_relation(self):
        g = self.game(('transform','transform')); source = self.actor(g)
        self.cast(g,'transform',g.state.players[2].board[0]); self.value(g,3,1)
        self.cast(g,'transform',source); self.value(g,1,0,source); self.portable(g)

    def test_control_move_keeps_both_side_scope_without_restoring_attack_uses(self):
        g = self.game(('control',)); source = self.actor(g)
        g.apply(Attack(1,source,self.hero(g,2).id)); self.cast(g,'control',source)
        self.value(g,4,2,source); self.assertEqual(g.state.entities[source].controller,2)
        self.assertEqual(g.state.entities[source].attacks_this_turn,1); self.portable(g)

    def test_dormant_other_presence_and_dormant_carrier_activity_are_separate(self):
        g = self.game(('sleep','sleep','awake')); source = self.actor(g); other = g.state.players[1].board[1]
        self.cast(g,'sleep',other); self.value(g,4,2)
        self.cast(g,'sleep',source); self.value(g,2,0,source)
        self.cast(g,'awake'); self.value(g,4,2,source); self.portable(g)

    def test_ordinary_buff_and_turn_transition_do_not_make_count_permanent(self):
        g = self.game(('buff','kill')); source = self.actor(g)
        self.cast(g,'buff',source); self.value(g,7,2)
        self.cast(g,'kill',g.state.players[2].board[0]); self.value(g,6,1)
        g.apply(EndTurn(1)); self.value(g,6,1); self.portable(g)

    def test_source_death_freezes_original_attack_and_later_count_does_not_reprice(self):
        g = self.game(('kill','summon')); source = self.actor(g); self.cast(g,'kill',source)
        row = next(r for r in g.state.death_history if r.entity_id==source)
        self.assertEqual(row.attack,4); self.cast(g,'summon'); self.assertEqual(row.attack,4); self.portable(g)

    def test_summon_event_context_sees_new_board_before_observing(self):
        g = self.game(('summon',),board=(CARD,'murloc','observer'))
        observer = g.state.players[1].board[-1]; before = g.state.entities[observer].attack
        self.cast(g,'summon'); self.value(g,5,3)
        self.assertEqual(g.state.entities[observer].attack,before+5); self.portable(g)

    def test_lethal_damage_context_counts_physical_other_before_death_removal(self):
        g = self.game(('lethal',),board=(CARD,'murloc','observer'))
        observer = g.state.players[1].board[-1]; before = g.state.entities[observer].attack
        self.cast(g,'lethal',g.state.players[2].board[0]); self.value(g,3,1)
        self.assertEqual(g.state.entities[observer].attack,before+4); self.portable(g)

    def test_attack_declared_choice_restores_and_reads_changed_current_count(self):
        g = self.game(board=(CARD,'murloc','watcher')); source = self.actor(g)
        g.apply(Attack(1,source,self.hero(g,2).id)); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g)
        for branch in (g,restored):
            self.choose(branch,'kill'); self.value(branch,3,1)
            self.assertEqual(self.hero(branch,2).damage,3); self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_waiting_payment_and_failed_effect_roll_back_full_board_and_count(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g,'fault')
        self.assertEqual(g.snapshot(),before)
        g = self.game(('wait',)); self.cast(g,'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before); self.portable(g)

    def test_retry_normalization_uses_registry_and_does_not_accumulate_old_outcome(self):
        g = self.game(('rewind',)); self.cast(g,'rewind'); self.value(g,5,3); self.portable(g)
        self.choose(g,'retry'); self.value(g,5,3)
        self.assertEqual(g.state.players[1].mana,9); self.portable(g)

    def test_original_context_retains_its_own_board_and_current_tribes(self):
        g = self.game(('kill',)); source = self.actor(g); context = RuleContext(g.state,source,1)
        self.cast(g,'kill',g.state.players[2].board[0]); self.value(g,3,1)
        codec = FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        restored = codec.decode(codec.encode(context)); self.assertEqual(restored.state.entities[source].attack,4)
        bad = deepcopy(context.state); bad.entities[source].conditional_attack=1
        with self.assertRaises(ValueError): codec.encode(RuleContext(bad,source,1))

    def test_rehashed_snapshot_rejects_missing_stale_scope_and_duplicate_native_relation(self):
        g = self.game(); snap = g.snapshot(); source = str(self.actor(g))
        for mode in ('missing','stale','tribe','duplicate','granted'):
            with self.subTest(mode=mode):
                bad = deepcopy(snap); entity = bad['state']['entities'][source]
                ability = next(a for a in entity['abilities'] if a['kind']=='stat_relation')
                if mode=='missing': del ability['stat_relation']['count_tribe']
                elif mode=='stale': entity['conditional_attack']=3
                elif mode=='tribe': ability['stat_relation']['count_tribe']='dragon'
                elif mode=='granted': ability['origin']='granted'
                else:
                    copy=deepcopy(ability);copy['id']=bad['state']['next_attachment_id'];bad['state']['next_attachment_id']+=1
                    entity['abilities'].append(copy)
                self.reject(bad)

    def test_query_and_player_interface_are_pure_and_hide_formula(self):
        g = self.game(); before = g.snapshot()
        self.assertEqual(conditional_attack(g.state,g.state.entities[self.actor(g)],g.registry),2)
        public = json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.for_player(1).legal_actions())
        for key in ('count_tribe','stat_relation','conditional_attack','resolution_frame'):
            self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
