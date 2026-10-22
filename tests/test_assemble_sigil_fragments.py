"""Real Sigil text borrowing, original spell preservation and native lifecycle."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_sigil_fragments import SOURCES, TOKENS, load_batch
from hs_sim.cards.native_assemble_entry_cards import FETCHER, NURTURER, POOL_ID, SHAPER, FLESH
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import (AssemblePrefix, AssembleProjection, AssembleRecipe,
    AssembleSuffix, OWNER_START_PREFIX, recipe_from_id)
from hs_sim.engine.assemble_offers import ResolveAssemble, validate_offer
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, SummonQuantitySpec, TargetSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

FLY, LOOT, DRAIN, CAIRNE = 'CORE_UNG_809', 'CORE_EX1_096', 'CORE_GIL_622', 'CORE_EX1_110'
LOW, HIGH = (FLY, LOOT, SOURCES[1]), (DRAIN, CAIRNE, SOURCES[0])
FLAME = 'UNG_809t1'
P = 'fixture.assemble_sigil.'
KILL, MUTE, BOUNCE, COPY, STEAL, SHIFT, WATCH, FAULT, MULT, UNKNOWN = (
    P+x for x in ('kill','mute','bounce','copy','steal','shift','watch','fault','mult','unknown'))
CTX = GenerationContext('k392-reviewed-sigil-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(high=False, mode='normal'):
    r = build_registry(); r._version += '.k392.'+str(high)+'.'+mode
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        MUTE: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current'),),
        STEAL: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        SHIFT: lambda c: (Transform(c.target_id, 'CORE_CS2_182'),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def wait(c):
        if c.event.player_id != c.player_id: return ()
        assembled = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id.startswith('assemble:'))
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('shift', 'Transform accepted carrier', (Transform(assembled, 'CORE_CS2_182'),))), c.source_id),)
    r.register_behavior(WATCH, wait)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=10, metadata=META,
        triggers=(TriggerSpec('turn_started', WATCH),)))
    def fault(c):
        if c.event.target_id in c.state.entities and c.state.entities[c.event.target_id].card_id in TOKENS:
            raise ResolutionError('deliberate Sigil downstream fault')
        return ()
    r.register_behavior(FAULT, fault)
    r.register_card(CardDefinition(FAULT, FAULT, CardType.MINION, health=10, metadata=META,
        triggers=(TriggerSpec('minion_summoned', FAULT),)))
    r.register_card(CardDefinition(MULT, MULT, CardType.MINION, health=10, metadata=META,
        summon_quantities=(SummonQuantitySpec(factor=2, source_kinds=(CardType.SPELL,)),)))
    members = ((LOOT,DRAIN,SOURCES[0]) if mode == 'deathrattle' else
        ('TIME_428',DRAIN,SOURCES[0]) if mode == 'end_turn' else HIGH if high else LOW)
    if mode == 'unknown':
        r.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, 1, META)); members += (UNKNOWN,)
    if mode == 'unreviewed':
        r.register_card(CardDefinition(UNKNOWN, UNKNOWN, CardType.SPELL, cost=1, metadata=META))
        r.register_pool_card(PoolCard.from_definition(r.card(UNKNOWN))); members += (UNKNOWN,)
    if mode == 'missing_projection': r._assemble_projections.pop(SOURCES[1])
    if mode != 'missing_pool':
        r.register_pool(PoolDefinition(POOL_ID, 'reviewed-fixture-v1', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    return r


class AssembleSigilFragmentTests(unittest.TestCase):
    def game(self, high=False, mode='normal', hand=(), board=(), enemy=()):
        root = FLESH if mode == 'deathrattle' else SHAPER if mode == 'end_turn' else FETCHER if high else NURTURER
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_10', hand=(root,)+hand, board=board, deck=('GAME_005',)*16,
                mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', board=enemy, deck=('GAME_005',)*16,
                mana=30, max_mana=30, mana_cap=30)), seed=392, generation_context=CTX), fixture(high, mode))

    def play(self, g, cid, target=None):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid, target_id=target)); return eid

    def end(self, g, count=1):
        for _ in range(count): g.apply(EndTurn(g.state.active_player))

    def offer(self, g):
        return next(e.offer for o in g._frame.options for e in o.effects if isinstance(e, ResolveAssemble))

    def create(self, g, half='top', high=False):
        self.play(g, FETCHER if high else NURTURER)
        primary, donor = (DRAIN, SOURCES[0]) if high else (FLY, SOURCES[1])
        cid = AssembleRecipe(primary, donor, half).card_id
        q = g.state.pending_choice; item = next(o for o in q.options if o.card_id == cid)
        g.apply(SelectChoice(1, q.id, (item.id,)))
        return cid

    def count(self, g, cid, pid=1, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[pid], zone))

    def portable(self, g, high=False):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = fixture.__wrapped__(high)
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        return saved

    def test_complete_originals_full_primary_faces_and_no_formal_domain(self):
        data = load_batch(); r = build_registry()
        rows = {x['record']['id']: x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows), SOURCES+TOKENS)
        for cid, row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        for observation in data['official_observations']:
            check_face(rows[observation['card_id']]['record'], observation['face'], observation['locale'],
                display_normalizations={'~GAMEPLAY_ASPROXY_'+observation['card_id']:''})
        for cid in SOURCES:
            self.assertIsNone(rows[cid]['record']['attack']); self.assertIsNone(rows[cid]['record']['health'])
            self.assertEqual(r.card(cid).kind, CardType.SPELL)
            self.assertIsNotNone(r.card(cid).ongoing_effect_id)
        self.assertNotIn(POOL_ID, r.pools); self.assertFalse(data['formal_pool_complete'])

    def test_secondary_spell_preserves_physical_primary_header_and_registry_inventory(self):
        r = fixture(); fp = r.fingerprint(); inventory = tuple(r.cards)
        for half in ('top','bottom'):
            c = r.card(AssembleRecipe(FLY, SOURCES[1], half).card_id); base = r.card(FLY)
            self.assertEqual((c.kind,c.name,c.cost,c.attack,c.health,c.metadata),
                (base.kind,base.name,base.cost,base.attack,base.health,base.metadata))
            self.assertIsNone(c.ongoing_effect_id)
        self.assertEqual(r.fingerprint(), fp); self.assertEqual(tuple(r.cards), inventory)
        with self.assertRaises(UnsupportedDefinitionError): r.card(AssembleRecipe(SOURCES[1], FLY, 'top').card_id)

    def test_projection_rejects_wrong_complete_pin_source_kind_and_duplicate(self):
        r = build_registry(); p = r.assemble_projections[SOURCES[1]]
        for kw in ({'definition_sha256':'0'*64},{'source_kind':CardType.WEAPON},{'card_id':FLY}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): r.register_assemble_projection(replace(p, **kw))
        with self.assertRaises(ValueError): r.register_assemble_projection(p)
        with self.assertRaises(TypeError): r.assemble_projections['bad'] = p
        r.freeze()
        with self.assertRaises(ValueError): r.register_assemble_projection(p)

    def test_owner_start_wrapper_is_reviewed_bound_and_cannot_be_registered_or_nested(self):
        r = fixture(); p = r.assemble_templates[FLY]
        self.assertTrue(callable(r.behavior(OWNER_START_PREFIX+p.suffix.behavior_id)))
        for body in ('missing', OWNER_START_PREFIX+p.suffix.behavior_id, r.assemble_templates[LOOT].suffix.behavior_id):
            with self.assertRaises(UnsupportedDefinitionError): r.behavior(OWNER_START_PREFIX+body)
        with self.assertRaises(ValueError): r.register_behavior(OWNER_START_PREFIX+'fake', lambda c: ())
        with self.assertRaises(ValueError): AssembleSuffix(OWNER_START_PREFIX+'fake', ('start_turn',))

    def test_real_nurturer_selects_minion_primary_and_preserves_whole_spell_secondary(self):
        g = self.game(); self.play(g, NURTURER); offer = self.offer(g)
        self.assertEqual(offer.primary_candidates, (FLY,))
        self.assertEqual(set(offer.secondary_candidates), {LOOT,SOURCES[1]})
        self.assertEqual(set(offer.secondary_card_ids), {LOOT,SOURCES[1]})
        validate_offer(g.registry, CTX, offer)
        self.portable(g)
        for pid in (1,2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for hidden in ('"primary_candidates"','"secondary_candidates"','"rng_before"','"rng_after"'):
                self.assertNotIn(hidden, public)

    def test_borrowed_prefix_repeats_each_owner_start_without_spell_or_sigil(self):
        g = self.game(); cid = self.create(g); self.play(g, cid)
        self.assertEqual(self.count(g, FLAME), 0)
        self.end(g); self.assertEqual(self.count(g, FLAME), 0)
        self.end(g); self.assertEqual(self.count(g, FLAME), 1)
        self.end(g, 2); self.assertEqual(self.count(g, FLAME), 2)
        self.assertFalse(g.state.cast_history); self.assertFalse(g.state.players[1].player_effects)
        self.portable(g)

    def test_actual_fetcher_prefix_uses_minion_damage_and_healing_each_owner_start(self):
        g = self.game(high=True); cid = self.create(g, high=True); eid = self.play(g, cid)
        before = g.state.entities[g.state.players[2].hero_id].health
        self.end(g, 2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, before-3)
        self.end(g, 2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, before-6)
        self.assertEqual(g.state.entities[eid].card_id, cid)
        self.assertFalse(g.state.players[1].player_effects); self.assertFalse(g.state.cast_history)

    def test_borrowed_seas_suffix_is_native_battlecry_and_not_a_delayed_spell(self):
        g = self.game(); cid = self.create(g, half='bottom'); eid = self.play(g, cid)
        self.assertEqual(self.count(g, TOKENS[1], zone='board'), 1)
        record = g.state.card_summon_history[-1]
        self.assertEqual(record.request.cause.source.entity_id, eid)
        self.assertEqual(record.request.cause.source.kind, CardType.MINION)
        self.assertFalse(g.state.players[1].player_effects); self.assertFalse(g.state.cast_history)
        self.end(g,2); self.assertEqual(self.count(g, TOKENS[1], zone='board'), 1)

    def test_hatching_suffix_uses_three_native_summons_and_not_spell_quantity_bonus(self):
        g = self.game(high=True, board=(MULT,)); cid = self.create(g, half='bottom', high=True)
        eid = self.play(g, cid)
        self.assertEqual(self.count(g, TOKENS[0], zone='board'), 3)
        records = [x for x in g.state.card_summon_history if x.request.cause.source.entity_id == eid]
        self.assertEqual(len(records), 3)
        self.assertTrue(all(x.request.cause.source.kind == CardType.MINION for x in records))
        self.assertFalse(g.state.players[1].player_effects)

    def test_hatching_suffix_full_board_keeps_normal_capacity_without_delayed_fallback(self):
        g = self.game(high=True, board=(FLY,FLY,FLY)); cid = self.create(g, half='bottom', high=True)
        self.play(g, cid)
        self.assertEqual(self.count(g, TOKENS[0], zone='board'), 2)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertFalse(g.state.players[1].player_effects)

    def test_real_fleshshape_borrows_hatching_payload_into_a_native_deathrattle(self):
        g = self.game(mode='deathrattle', hand=(KILL,))
        self.play(g, FLESH)
        cid = AssembleRecipe(LOOT, SOURCES[0], 'bottom').card_id
        q = g.state.pending_choice; item = next(o for o in q.options if o.card_id == cid)
        g.apply(SelectChoice(1,q.id,(item.id,)))
        eid = self.play(g,cid); self.assertEqual(self.count(g,TOKENS[0],zone='board'),0)
        self.play(g,KILL,eid)
        self.assertEqual(self.count(g,TOKENS[0],zone='board'),3)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.players[1].player_effects)

    def test_real_shaper_borrows_hatching_payload_into_owner_end_without_delayed_sigil(self):
        g = self.game(mode='end_turn'); self.play(g,SHAPER)
        cid = AssembleRecipe('TIME_428', SOURCES[0], 'bottom').card_id
        q = g.state.pending_choice; item = next(o for o in q.options if o.card_id == cid)
        g.apply(SelectChoice(1,q.id,(item.id,)))
        self.play(g,cid); self.assertEqual(self.count(g,TOKENS[0],zone='board'),0)
        self.end(g); self.assertEqual(self.count(g,TOKENS[0],zone='board'),3)
        self.end(g); self.assertEqual(self.count(g,TOKENS[0],zone='board'),3)
        self.assertFalse(g.state.players[1].player_effects)

    def test_silence_and_death_remove_future_repeated_start_listener(self):
        for operation in (MUTE,KILL):
            with self.subTest(operation=operation):
                g = self.game(hand=(operation,)); cid = self.create(g); eid = self.play(g, cid)
                self.play(g, operation, eid); self.end(g,2)
                self.assertEqual(self.count(g, FLAME), 0)

    def test_control_change_uses_new_controller_start_and_copy_keeps_its_own_listener(self):
        g = self.game(hand=(COPY,STEAL)); cid = self.create(g); eid = self.play(g, cid)
        self.play(g, COPY, eid); self.play(g, STEAL, eid)
        self.end(g)
        self.assertEqual(self.count(g, FLAME, pid=2), 1); self.assertEqual(self.count(g, FLAME), 0)
        self.end(g)
        self.assertEqual(self.count(g, FLAME), 1); self.assertEqual(self.count(g, cid, zone='board'), 1)

    def test_bounce_and_replay_keep_new_printed_face_and_transform_retires_it(self):
        g = self.game(hand=(BOUNCE,SHIFT)); cid = self.create(g); eid = self.play(g, cid)
        self.play(g, BOUNCE, eid); self.assertEqual(g.state.entities[eid].card_id, cid)
        self.play(g, cid); self.play(g, SHIFT, eid); self.end(g,2)
        self.assertEqual(self.count(g, FLAME), 0)
        self.assertEqual(g.state.entities[eid].card_id, 'CORE_CS2_182')

    def test_accepted_start_body_survives_later_carrier_transform_and_restores_wait(self):
        g = self.game(board=(WATCH,), hand=(SHIFT,)); cid = self.create(g); eid = self.play(g, cid)
        self.end(g,2)
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id,q.id,('shift',)))
        self.assertEqual(self.count(g, FLAME), 1)
        self.assertEqual(g.state.entities[eid].card_id, 'CORE_CS2_182')
        self.portable(g)

    def test_unknown_or_unreviewed_secondary_is_not_silently_removed_before_sampling(self):
        for mode in ('unknown','unreviewed','missing_projection','missing_pool'):
            with self.subTest(mode=mode):
                g = self.game(mode=mode); before = g.snapshot()
                with self.assertRaises(ValueError): self.play(g, NURTURER)
                self.assertEqual(g.snapshot(), before)

    def test_actual_downstream_summon_failure_rolls_back_original_paid_battlecry(self):
        g = self.game(high=True, hand=(FAULT,)); cid = self.create(g, half='bottom', high=True)
        self.play(g, FAULT); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate Sigil downstream fault'): self.play(g, cid)
        self.assertEqual(g.snapshot(), before)

    def test_rehashed_pending_source_or_removed_spell_option_is_rejected(self):
        from hs_sim.engine.serialization import canonical_hash
        g = self.game(); self.play(g, NURTURER); saved = g.snapshot()
        for field in ('source_projection','options'):
            if field == 'source_projection':
                reader = fixture.__wrapped__(); reader._assemble_projections.pop(SOURCES[1])
                with self.assertRaises(SnapshotError): Game.from_snapshot(saved, reader)
            else:
                changed = deepcopy(saved)
                changed['state']['pending_choice']['options'].pop()
                changed['state_hash'] = canonical_hash(changed['state'])
                with self.assertRaises(SnapshotError): Game.from_snapshot(changed, fixture())

    def test_unreviewed_passive_projection_remains_explicitly_unsupported(self):
        from hs_sim.engine.assembled_powers import AssembledPowerRecipe
        r = fixture(); minion = AssembleRecipe(FLY, SOURCES[1], 'top').card_id
        with self.assertRaises(UnsupportedDefinitionError):
            r.card(AssembledPowerRecipe('BE_004p', minion).card_id)


if __name__ == '__main__': unittest.main()
