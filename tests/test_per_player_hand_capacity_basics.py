"""Independent player capacity and the existing physical hand-entry pipeline."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game,
    PlayCard, PlayerSetup, PlayerTargetRuleSpec, Rarity, Registry, ResolutionError,
    Ruleset, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw,
    DrawToHandLimit, GainArmor, InvokeBehavior, ReplaceHero, RequestChoice,
    ReturnToHand, Silence, Transform)
from hs_sim.engine.hand_capacity import SetHandCapacity, hand_capacity
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT = Path(__file__).resolve().parents[1]
PIN = '60db5b686fb8db49987a8c2fe70fb5a2280688895d2f5d3cefad5d7fa27245c1'


def evidence():
    packet = json.loads((ROOT/'data/support/per-player-hand-capacity-basics.json').read_bytes())
    if canonical_digest(packet) != PIN: raise ValueError('Capacity representative requires complete pinned raw')
    return packet['records'][0]


def registry(watcher=False):
    r = Registry('per-player-hand-capacity-basics-v1')
    r.register_card(CardDefinition('hc.hero', 'Finite hero', CardType.HERO, health=30,
        metadata=metadata(CardClass.WARLOCK, collectible=False)))
    r.register_card(CardDefinition('hc.new.hero', 'Replacement hero probe', CardType.HERO,
        health=30, metadata=metadata(CardClass.WARLOCK, collectible=False)))
    for cid in ('hc.filler', 'hc.hidden', 'hc.other'):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=1, metadata=metadata()))
    raw = evidence()
    r.register_behavior('hc.native', lambda c: (SetHandCapacity(c.player_id, 12, 'raise'), Draw(c.player_id, 4)))
    r.register_card(CardDefinition('DRG_208', raw['name'], CardType.MINION, cost=7,
        attack=4, health=4, battlecry='hc.native',
        metadata=metadata(CardClass.WARLOCK, rarity=Rarity.LEGENDARY, tribes=())))
    def first(c, zone):
        return next(c.state.entities[i] for i in getattr(c.state.players[c.player_id], zone)
            if c.state.entities[i].card_id == 'hc.filler')
    def native(c):
        return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == 'DRG_208')
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('fail', 'Fail', (SetHandCapacity(c.player_id, 15),
                InvokeBehavior('hc.error', c.source_id, c.player_id))),
        ), c.source_id),)
    def failure(c): raise ResolutionError('Deliberate capacity continuation failure')
    r.register_behavior('hc.error', failure)
    operations = {
        'raise': lambda c: (SetHandCapacity(c.player_id, 12, 'raise'),),
        'set': lambda c: (SetHandCapacity(c.player_id, 11),),
        'lower': lambda c: (SetHandCapacity(c.player_id, 3),),
        'draw': lambda c: (Draw(c.player_id, 4),),
        'fill': lambda c: (DrawToHandLimit(c.player_id),),
        'add': lambda c: (AddToHand(c.player_id, 'hc.filler', c.source_id),),
        'copy': lambda c: (CopyCard(CardReference.capture(first(c, 'hand')), c.player_id),),
        'move': lambda c: (MoveCard(CardReference.capture(first(c, 'deck')), c.player_id, Zone.HAND),),
        'return': lambda c: (ReturnToHand(first(c, 'board').id),),
        'no.reentry': lambda c: (AddToHand(c.player_id, 'hc.filler', c.source_id),
            MoveCard(CardReference.capture(first(c, 'hand')), c.player_id, Zone.HAND)),
        'replace.hero': lambda c: (ReplaceHero(c.player_id, 'hc.new.hero'),),
        'source.destroy': lambda c: (Destroy(native(c)),),
        'source.silence': lambda c: (Silence(native(c)),),
        'source.transform': lambda c: (Transform(native(c), 'hc.other'),),
        'wait': lambda c: (SetHandCapacity(c.player_id, 12, 'raise'), *wait(c)),
        'early.wait': lambda c: (*wait(c), SetHandCapacity(c.player_id, 12, 'raise'), Draw(c.player_id)),
        'fail': lambda c: (SetHandCapacity(c.player_id, 12), InvokeBehavior('hc.error', c.source_id, c.player_id)),
    }
    for name, body in operations.items():
        cid = 'hc.'+name; r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    r.register_behavior('hc.paid', lambda c: (SetHandCapacity(c.player_id, 12, 'raise'), *wait(c)))
    r.register_card(CardDefinition('hc.paid', 'Finite original payment probe', CardType.MINION,
        cost=2, health=2, battlecry='hc.paid', metadata=metadata()))
    r.register_player_target_rule(PlayerTargetRuleSpec('hc.capacity.target', 'v1'),
        lambda c: c.observation['players'][c.player_id-1]['hand_cap'] == 12)
    r.register_behavior('hc.target', lambda c: (SetHandCapacity(c.player_id, 11), *wait(c)))
    r.register_card(CardDefinition('hc.target', 'Finite visible capacity predicate', CardType.SPELL,
        cost=2, on_play='hc.target', targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'),
        target_rule='hc.capacity.target', metadata=metadata()))
    def pause_draw(c):
        if c.event.player_id != c.player_id or len(c.state.players[c.player_id].hand) != 10: return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('keep', 'Keep capacity', ()),
            ChoiceOption('eleven', 'Set capacity to eleven', (SetHandCapacity(c.player_id, 11),)),
        ), c.source_id),)
    r.register_behavior('hc.draw.watch', pause_draw)
    r.register_card(CardDefinition('hc.draw.watch', 'Single existing draw checkpoint', CardType.MINION,
        health=1, triggers=(TriggerSpec('card_drawn', 'hc.draw.watch'),), metadata=metadata()))
    return r


class PerPlayerHandCapacityTests(unittest.TestCase):
    def match(self, hand=(), cap=None, enemy_hand=(), enemy_cap=None, board=(), rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hc.hero', deck=('hc.filler',)*20, hand=hand, board=board,
                max_mana=10, mana=10, hand_cap=cap),
            PlayerSetup('hc.hero', deck=('hc.hidden',)*20, hand=enemy_hand, board=('hc.other',),
                max_mana=10, mana=10, hand_cap=enemy_cap),
        ), seed=29), registry(), ruleset=rules)

    def play(self, g, cid, player=1, target=None):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target)); return eid

    def cap(self, g, player=1): return hand_capacity(g.state.players[player], g.ruleset)

    def choose(self, g, option='ok'):
        p=g.state.pending_choice;g.apply(SelectChoice(p.player_id,p.id,(option,)))

    def portable(self, g):
        saved=g.snapshot()
        copies=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        for candidate in copies:self.assertEqual(candidate.snapshot(),saved)
        return copies

    def test_effect_and_setup_use_strict_positive_capacity_and_declared_mode(self):
        for value in (True,0,-1,1.5,'12',None):
            with self.subTest(value=value), self.assertRaises(ValueError):SetHandCapacity(1,value)
        for mode in ('add','',None,True):
            with self.subTest(mode=mode),self.assertRaises(ValueError):SetHandCapacity(1,12,mode)
        for value in (True,0,-1,1.5,'12'):
            with self.subTest(setup=value),self.assertRaises(ValueError):PlayerSetup('hc.hero',hand_cap=value)

    def test_query_is_pure_and_uses_only_player_override_or_rules_default(self):
        g=self.match(cap=12,rules=Ruleset(max_hand=15));saved=g.snapshot()
        self.assertEqual((self.cap(g),self.cap(g,2)),(12,15))
        self.assertIsNone(g.state.players[2].hand_cap);self.assertEqual(g.snapshot(),saved)

    def test_raise_and_set_have_distinct_exact_meaning_without_affecting_opponent(self):
        g=self.match(('hc.raise','hc.set'),cap=15)
        self.play(g,'hc.raise');self.assertEqual((self.cap(g),self.cap(g,2)),(15,10))
        self.play(g,'hc.set');self.assertEqual((self.cap(g),self.cap(g,2)),(11,10));self.portable(g)

    def test_setting_capacity_neither_draws_cards_nor_consumes_rng(self):
        g=self.match(('hc.raise',));before=len(g.state.players[1].deck);rng=g._rng.getstate()
        self.play(g,'hc.raise');self.assertEqual(len(g.state.players[1].hand),0)
        self.assertEqual(len(g.state.players[1].deck),before);self.assertEqual(g._rng.getstate(),rng)

    def test_initial_hand_uses_each_player_capacity_and_rejects_oversized_initial_group(self):
        g=self.match(('hc.filler',)*12,cap=12,enemy_hand=('hc.hidden',)*10)
        self.assertEqual((len(g.state.players[1].hand),len(g.state.players[2].hand)),(12,10));self.portable(g)
        with self.assertRaises(ValueError):self.match(('hc.filler',)*11)
        with self.assertRaises(ValueError):self.match(('hc.filler',)*13,cap=12)

    def test_complete_native_raw_and_definition_metadata_are_pinned(self):
        raw=evidence();definition=registry().card('DRG_208')
        self.assertEqual((raw['id'],raw['cost'],raw['attack'],raw['health']),('DRG_208',7,4,4))
        self.assertEqual((definition.cost,definition.attack,definition.health),(7,4,4))
        self.assertEqual(definition.metadata.classes,(CardClass.WARLOCK,))
        self.assertEqual(definition.metadata.rarity,Rarity.LEGENDARY)
        baseline=json.loads((ROOT/'outputs/foundation-gap-audit-20261011/necessary-gap-raw.json').read_bytes())
        self.assertEqual(raw,next(r for r in baseline['hand_capacity_records'] if r['id']=='DRG_208'))

    def test_native_raise_then_four_draws_use_twelve_capacity_at_full_initial_hand(self):
        g=self.match(('DRG_208',)+('hc.filler',)*9,enemy_hand=('hc.hidden',)*10)
        source=self.play(g,'DRG_208')
        self.assertEqual((self.cap(g),len(g.state.players[1].hand)),(12,12))
        self.assertEqual((self.cap(g,2),len(g.state.players[2].hand)),(10,10))
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),1)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_draw_above_global_default_admits_to_player_capacity_then_burns(self):
        g=self.match(('hc.draw',)+('hc.filler',)*10,cap=12)
        self.play(g,'hc.draw');self.assertEqual(len(g.state.players[1].hand),12)
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),2)

    def test_fill_uses_current_player_capacity_instead_of_global_default(self):
        g=self.match(('hc.fill',)+('hc.filler',)*10,cap=12)
        self.play(g,'hc.fill');self.assertEqual(len(g.state.players[1].hand),12)
        self.assertEqual(sum(e.kind=='card_drawn' for e in g.events),2)
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),0)

    def test_generated_cards_use_original_delivery_with_player_capacity(self):
        g=self.match(('hc.add',)+('hc.filler',)*10,cap=12)
        self.play(g,'hc.add');self.assertEqual(len(g.state.players[1].hand),11)
        self.assertFalse(any(e.kind=='card_burned' for e in g.events))

    def test_current_copies_use_player_capacity_and_keep_independent_entities(self):
        g=self.match(('hc.copy',)+('hc.filler',)*10,cap=12)
        old=set(g.state.players[1].hand);self.play(g,'hc.copy')
        self.assertEqual(len(g.state.players[1].hand),11)
        self.assertEqual(len(set(g.state.players[1].hand)-old),1)

    def test_physical_deck_move_preserves_material_at_eleven_cards(self):
        g=self.match(('hc.move',)+('hc.filler',)*10,cap=12)
        physical=g.state.players[1].deck[0];self.play(g,'hc.move')
        self.assertIn(physical,g.state.players[1].hand);self.assertEqual(len(g.state.players[1].hand),11)

    def test_return_from_board_uses_player_capacity_without_death_or_burn(self):
        g=self.match(('hc.return',)+('hc.filler',)*10,cap=12,board=('hc.filler',))
        physical=g.state.players[1].board[0];self.play(g,'hc.return')
        self.assertIn(physical,g.state.players[1].hand);self.assertEqual(len(g.state.players[1].hand),11)
        self.assertFalse(any(e.kind in ('card_burned','minion_died') for e in g.events))

    def test_moving_same_hand_material_does_not_burn_when_capacity_is_full(self):
        g=self.match(('hc.no.reentry',)+('hc.filler',)*11,cap=12)
        physical=g.state.players[1].hand[1];self.play(g,'hc.no.reentry')
        self.assertIn(physical,g.state.players[1].hand);self.assertEqual(len(g.state.players[1].hand),12)

    def test_lower_capacity_retains_held_cards_and_blocks_new_admission_until_space(self):
        g=self.match(('hc.lower','hc.add')+('hc.filler',)*4,cap=12)
        physical=tuple(g.state.players[1].hand[1:]);self.play(g,'hc.lower')
        self.assertEqual(self.cap(g),3);self.assertEqual(tuple(g.state.players[1].hand),physical)
        self.portable(g);self.play(g,'hc.add')
        self.assertEqual(len(g.state.players[1].hand),4)
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),1)

    def test_player_capacity_persists_across_turns_and_hero_replacement(self):
        g=self.match(('hc.raise','hc.replace.hero'));self.play(g,'hc.raise')
        self.play(g,'hc.replace.hero');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((self.cap(g),self.cap(g,2)),(12,10));self.portable(g)

    def test_native_source_silence_destruction_or_transform_does_not_revoke_capacity(self):
        for suffix in ('silence','destroy','transform'):
            with self.subTest(suffix=suffix):
                g=self.match(('DRG_208','hc.source.'+suffix));self.play(g,'DRG_208')
                self.play(g,'hc.source.'+suffix);self.assertEqual(self.cap(g),12)

    def test_second_player_has_own_override_and_consumers(self):
        g=self.match(enemy_hand=('hc.raise','hc.fill')+('hc.hidden',)*8)
        g.apply(EndTurn(1));self.play(g,'hc.raise',2);self.play(g,'hc.fill',2)
        self.assertEqual((self.cap(g),self.cap(g,2),len(g.state.players[2].hand)),(10,12,12));self.portable(g)

    def test_changed_capacity_after_draw_wait_is_used_by_remaining_draws(self):
        g=self.match(('DRG_208',)+('hc.filler',)*9,board=('hc.draw.watch',))
        self.play(g,'DRG_208');self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.cap(g),len(g.state.players[1].hand)),(12,10))
        copies=self.portable(g)
        for candidate in (g,*copies):self.choose(candidate,'eleven')
        for candidate in copies:self.assertEqual(candidate.snapshot(),g.snapshot())
        self.assertEqual((self.cap(g),len(g.state.players[1].hand)),(11,11))
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),2)

    def test_capacity_change_before_wait_roundtrips_and_failed_resume_restores_boundary(self):
        g=self.match(('hc.wait',));self.play(g,'hc.wait');saved=g.snapshot();copies=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        for candidate in (g,*copies):self.choose(candidate)
        for candidate in copies:self.assertEqual(candidate.snapshot(),g.snapshot())

    def test_wait_before_change_resumes_once_without_early_capacity_or_draw(self):
        g=self.match(('hc.early.wait',));self.play(g,'hc.early.wait')
        self.assertEqual((self.cap(g),len(g.state.players[1].hand)),(10,0))
        copies=self.portable(g)
        for candidate in (g,*copies):self.choose(candidate)
        for candidate in copies:self.assertEqual(candidate.snapshot(),g.snapshot())
        self.assertEqual((self.cap(g),len(g.state.players[1].hand)),(12,1))

    def test_paid_hand_wait_keeps_complete_original_payment_and_changed_capacity(self):
        g=self.match(('hc.paid',));self.play(g,'hc.paid');copies=self.portable(g)
        self.assertEqual((self.cap(g),g.state.players[1].mana),(12,8))
        for candidate in (g,*copies):self.choose(candidate)
        for candidate in copies:self.assertEqual(candidate.snapshot(),g.snapshot())

    def test_paid_public_target_dto_captures_original_player_capacity(self):
        g=self.match(('hc.target',),cap=12);target=g.state.players[2].board[0]
        self.play(g,'hc.target',target=target);self.assertEqual(self.cap(g),11);copies=self.portable(g)
        for candidate in (g,*copies):self.choose(candidate)
        for candidate in copies:self.assertEqual(candidate.snapshot(),g.snapshot())

    def test_immediate_failure_rolls_back_capacity_action_and_rng(self):
        g=self.match(('hc.fail',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'hc.fail')
        self.assertEqual(g.snapshot(),saved)

    def test_missing_bad_capacity_and_previous_snapshot_schema_are_rejected(self):
        g=self.match(cap=12)
        for value in (True,0,-1,1.5,'12'):
            saved=g.snapshot();saved['state']['players']['1']['hand_cap']=value
            payload=g._hash_payload();payload['state']=saved['state'];saved['state_hash']=canonical_hash(payload)
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
        saved=g.snapshot();del saved['state']['players']['1']['hand_cap']
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
        saved=g.snapshot();saved['schema_version']=218
        with self.assertRaisesRegex(SnapshotError,'1 through 265'):Game.from_snapshot(saved,registry())

    def test_public_capacities_are_separate_and_hidden_hand_state_stays_private(self):
        g=self.match(('hc.raise',),enemy_hand=('hc.hidden',)*10);self.play(g,'hc.raise');saved=g.snapshot()
        for viewer in (1,2):
            view=g.observe(viewer);self.assertEqual([p['hand_cap'] for p in view['players']],[12,10])
            self.assertEqual(view['limits']['max_hand'],10)
            public=json.dumps(view)+json.dumps(g.for_player(viewer).legal_actions())
            for key in ('rng_state','resolution_frame','original_deck','submission_base','payment_state'):
                self.assertNotIn('"'+key+'"',public)
            if viewer==1:self.assertNotIn('hc.hidden',public)
        self.assertEqual(g.snapshot(),saved)

    def test_wire_and_engine_versions_include_new_capacity_field_and_view(self):
        g=self.match();saved=g.snapshot()
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version'],g.observe(1)['version']),
            ('prototype-v302',CORE_EFFECTS_VERSION,266,'player-view-v85'))
        self.assertIn('hand_cap',saved['state']['players']['1']);self.assertIsNone(saved['state']['players']['1']['hand_cap'])

    def test_unexpanded_default_hand_cannot_be_imported_over_default_limit(self):
        g=self.match(('hc.filler',)*11,cap=12);saved=g.snapshot()
        saved['state']['players']['1']['hand_cap']=None
        payload=g._hash_payload();payload['state']=saved['state'];saved['state_hash']=canonical_hash(payload)
        with self.assertRaisesRegex(SnapshotError,'Unexpanded hand exceeds default capacity'):
            Game.from_snapshot(saved,registry())
        valid=self.match(('hc.filler',)*12,rules=Ruleset(max_hand=12))
        self.assertEqual(self.cap(valid),12);self.assertIsNone(valid.state.players[1].hand_cap)
        self.portable(valid)


if __name__=='__main__':unittest.main()
