from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_reactive_cards import (
    ANOMALY, BUCCANEER, COGMASTER, HOOK, LEAVES, MATE, OFFERING, ORACLE,
    RELATIONS, ROVER, SELFLESS, TIDECALLER, TILLER, load_batch,
)
from hs_sim.engine import (
    Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, StatReference, StatRelationLayer,
    StatRelationOperand, StatRelationSpec, TargetSpec, TriggerSpec, UseHeroPower, Zone,
)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, DamageBatch, Destroy,
    EquipWeapon, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, SetStats, Silence,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, TargetMode, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation, conditional_attack
from hs_sim.engine.tribes import ChangeMinionTribes
from tools.card_batch import check_face


P = 'k456.'
ZERO, KILL, HURT, LETHAL, TWICE, SILENCE, TAKE, GROW, SET, BOUNCE, COPY, BASECOPY, SLEEP, WAKE, FAIL, WATCH, UNKNOWN = (
    P+key for key in ('zero', 'kill', 'hurt', 'lethal', 'twice', 'silence', 'take', 'grow', 'set', 'bounce',
        'copy', 'basecopy', 'sleep', 'wake', 'fail', 'watch', 'unknown'))
YETI, RAVEN, MURLOC, SHIELDED, COUNTER, FLASHBACK = (
    'CORE_CS2_182', 'KAR_300', 'ICC_220', 'ICC_038', 'CORE_EX1_287', 'TIME_711')
CONTEXT = GenerationContext('k456-explicit-ten-reactive-leaves', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'explicit-ten-reactive-leaves-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))
    r.register_card(CardDefinition(UNKNOWN, UNKNOWN, CardType.MINION, cost=1, attack=1, health=1,
        metadata=replace(r.card(YETI).metadata, collectible=False, tribes=None, deck_identity=UNKNOWN)))

    def fail(c):
        raise ResolutionError('K456 deliberate reaction failure')

    def change(c, tribes):
        return (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', tribes), c.source_id),)

    bodies = {
        ZERO: lambda c: (),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HURT: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.EFFECT),),
        LETHAL: lambda c: (Damage(c.target_id, 6, c.source_id, DamageKind.EFFECT),),
        TWICE: lambda c: (DamageBatch((Damage(c.target_id, 1, c.source_id, DamageKind.EFFECT),
            Damage(c.target_id, 1, c.source_id, DamageKind.EFFECT))),),
        SILENCE: lambda c: (Silence(c.target_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        GROW: lambda c: (Buff(c.target_id, attack=2, health=1, source_id=c.source_id),),
        SET: lambda c: (SetStats(c.target_id, attack=1, source_id=c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, 3-c.player_id),),
        BASECOPY: lambda c: (CopyMinion(c.target_id, 3-c.player_id, mode='base'),),
        SLEEP: lambda c: (MakeDormant(c.target_id, None, c.source_id),),
        WAKE: lambda c: (AwakenMinion(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == ROVER), c.source_id),),
        P+'mech': lambda c: change(c, ('mech',)),
        P+'murloc': lambda c: change(c, ('murloc',)),
        P+'plain': lambda c: change(c, ()),
        P+'shield': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        P+'equip': lambda c: (EquipWeapon(c.player_id, HOOK),),
        P+'lose_weapon': lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),),
        FAIL: fail,
    }
    no_target = {ZERO, WAKE, P+'equip', P+'lose_weapon', FAIL}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=None if cid in no_target else
                TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))))

    def watch(c):
        event = c.event
        event_player = event.player_id
        if event_player is None and event.target_id is not None:
            event_player = c.state.entities[event.target_id].controller
        if event_player != c.player_id:
            return ()
        if event.kind == 'attack_declared' and c.state.entities[event.source_id].card_id not in (COGMASTER, TILLER):
            return ()
        if mode == 'fail':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        options = [ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))]
        if event.kind == 'attack_declared':
            mechs = [i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == ROVER]
            if mechs:
                options.append(ChoiceOption('lose_mech', 'Destroy the original Mech',
                    (Destroy(mechs[0], c.source_id),)))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)

    behavior = WATCH+'.'+mode
    r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        metadata=replace(r.card(YETI).metadata, collectible=False, deck_identity=WATCH),
        triggers=tuple(TriggerSpec(event, behavior) for event in
            ('ability_granted', 'weapon_equipped', 'armor_gained', 'attack_declared'))
            if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostReactiveTests(unittest.TestCase):
    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), deck=(), enemy_deck=(),
             active=1, mode='normal'):
        self.mode = mode
        marker = () if mode == 'normal' else (WATCH,)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=marker+board, deck=deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=456, generation_context=CONTEXT), fixture(mode))

    def entity(self, g, cid, player=1, zone='board'):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
            if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        eid = self.entity(g, cid, player, 'hand').id
        g.apply(PlayCard(player, eid, target))
        return eid

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def choose(self, g, key='continue'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = fixture(self.mode, 'independent-reader')
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())
            for key in ('conditional_attack', 'controller_has_mech', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"'+key+'"', public)

    def reject(self, snap):
        snap['state_hash'] = canonical_hash(snap['state'])
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snap, fixture())

    def test_eleven_full_rows_twenty_two_faces_zero_attack_and_named_hook(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (11, 22))
        for x in data['official_observations']:
            check_face(rows[x['card_id']], x['face'], x['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(x['card_id']))
        faces = {(x['card_id'], x['locale']): x['face'] for x in data['official_observations']}
        self.assertEqual(rows[MATE]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'], rows[HOOK]['dbf_id'])
        for locale in ('zh_CN', 'en_US'):
            self.assertEqual(faces[HOOK, locale]['id'], rows[HOOK]['dbf_id'])
            self.assertIsNone(faces[MATE, locale].get('childIds'))
            self.assertIsNone(faces[HOOK, locale].get('parentId'))
        self.assertEqual((fixture().card(HOOK).attack, fixture().card(HOOK).durability), (1, 3))
        self.assertEqual(asdict(RELATIONS[COGMASTER])['operand'], StatRelationOperand.CONTROLLER_HAS_MECH)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_ten_original_bodies_pay_one_mana_without_own_entry_buffs(self):
        rows = {x['record']['id']: x['record'] for x in load_batch()['dependencies']}
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); eid = self.play(g, cid); e = g.state.entities[eid]
                self.assertEqual((e.attack, e.health, g.state.players[1].mana),
                    (rows[cid]['attack'] or 0, rows[cid]['health'], 9))

    def test_cogmaster_condition_is_friendly_presence_not_mech_count(self):
        g = self.game((ROVER, ROVER, KILL, KILL), board=(COGMASTER,), enemy_board=(ROVER,))
        source = self.entity(g, COGMASTER).id
        self.assertEqual(g.state.entities[source].attack, 1)
        first = self.play(g, ROVER); second = self.play(g, ROVER)
        self.assertEqual(g.state.entities[source].attack, 3)
        self.play(g, KILL, first); self.assertEqual(g.state.entities[source].attack, 3)
        self.play(g, KILL, second); self.assertEqual(g.state.entities[source].attack, 1)
        self.assertFalse(g.state.entities[source].enchantments)
        self.portable(g)

    def test_cogmaster_rechecks_current_tribe_including_its_own_changed_tribe(self):
        g = self.game((P+'mech', P+'plain'), board=(COGMASTER, YETI))
        target = self.entity(g, YETI).id
        self.play(g, P+'mech', target); self.assertEqual(self.entity(g, COGMASTER).attack, 3)
        self.play(g, P+'plain', target); self.assertEqual(self.entity(g, COGMASTER).attack, 1)
        h = self.game((P+'mech', P+'plain'), board=(COGMASTER,))
        source = self.entity(h, COGMASTER).id
        self.play(h, P+'mech', source); self.assertEqual(h.state.entities[source].attack, 3)
        self.play(h, P+'plain', source); self.assertEqual(h.state.entities[source].attack, 1)

    def test_cogmaster_excludes_dormant_mech_and_reactivates_after_awaken(self):
        g = self.game((SLEEP, WAKE), board=(COGMASTER, ROVER))
        target = self.entity(g, ROVER).id
        self.play(g, SLEEP, target); self.assertEqual(self.entity(g, COGMASTER).attack, 1)
        self.play(g, WAKE); self.assertEqual(self.entity(g, COGMASTER).attack, 3)

    def test_cogmaster_uses_existing_numeric_layer_and_silence(self):
        g = self.game((GROW, SET, KILL, SILENCE), board=(COGMASTER, ROVER))
        source = self.entity(g, COGMASTER).id
        self.play(g, GROW, source); self.assertEqual(g.state.entities[source].attack, 5)
        self.play(g, SET, source); self.assertEqual(g.state.entities[source].attack, 3)
        self.play(g, SILENCE, source); self.assertEqual(g.state.entities[source].attack, 1)
        self.play(g, KILL, self.entity(g, ROVER).id); self.assertEqual(g.state.entities[source].attack, 1)

    def test_cogmaster_current_and_base_copies_recompute_for_destination_controller(self):
        g = self.game((GROW, COPY, BASECOPY, TAKE), board=(COGMASTER, ROVER))
        source = self.entity(g, COGMASTER).id
        self.play(g, GROW, source); self.play(g, COPY, source); self.play(g, BASECOPY, source)
        copied = [g.state.entities[i] for i in g.state.players[2].board]
        self.assertEqual([e.attack for e in copied], [3, 1])
        self.play(g, TAKE, source)
        self.assertEqual(g.state.entities[source].attack, 3)
        self.assertEqual(g.state.entities[source].controller, 2)
        self.portable(g)

    def test_unknown_current_mech_membership_rejects_and_rolls_back_play(self):
        g = self.game((UNKNOWN,), board=(COGMASTER, ROVER)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown current tribe'):
            self.play(g, UNKNOWN)
        self.assertEqual(g.snapshot(), before)

    def test_cogmaster_query_is_pure_and_requires_registry(self):
        g = self.game(board=(COGMASTER, ROVER)); e = self.entity(g, COGMASTER); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(conditional_attack(g.state, e, g.registry), 2)
        self.assertEqual(g.snapshot(), before)
        with self.assertRaises(ValueError): conditional_attack(g.state, e)

    def test_mech_relation_closed_validation_and_no_special_grant(self):
        for changes in ({'amount': 0}, {'amount': True}, {'layer': StatRelationLayer.FINAL_ATTACK},
                        {'target': StatReference.HEALTH}, {'count_tribe': 'mech'}, {'card_count': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(RELATIONS[COGMASTER], **changes)
        with self.assertRaises(ValueError): GrantStatRelation(1, RELATIONS[COGMASTER])

    def test_rehashed_snapshot_rejects_stale_mech_cache_changed_declaration_and_duplicate(self):
        g = self.game(board=(COGMASTER, ROVER)); source = self.entity(g, COGMASTER).id; saved = g.snapshot()
        for value in (0, 1, 3, True, 2.0, -1, None):
            bad = deepcopy(saved); bad['state']['entities'][str(source)]['conditional_attack'] = value
            with self.subTest(value=value): self.reject(bad)
        for field, value in (('operand', 'controller_has_weapon'), ('amount', 3)):
            bad = deepcopy(saved)
            row = next(a for a in bad['state']['entities'][str(source)]['abilities'] if a['kind'] == 'stat_relation')
            row['stat_relation'][field] = value; self.reject(bad)
        bad = deepcopy(saved)
        row = deepcopy(next(a for a in bad['state']['entities'][str(source)]['abilities'] if a['kind'] == 'stat_relation'))
        row['id'] = bad['state']['next_attachment_id']; bad['state']['next_attachment_id'] += 1
        bad['state']['entities'][str(source)]['abilities'].append(row); self.reject(bad)

    def test_mech_loss_during_attack_wait_uses_updated_prepared_damage(self):
        g = self.game(board=(COGMASTER, ROVER), enemy_board=(YETI,), mode='wait')
        source, target = self.entity(g, COGMASTER).id, self.entity(g, YETI, 2).id
        g.apply(Attack(1, source, target)); self.assertIsNotNone(g.state.pending_choice)
        self.portable(g); self.choose(g, 'lose_mech')
        self.assertEqual(g.state.entities[target].damage, 1)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_buccaneer_native_relation_tracks_new_named_weapon_and_loss(self):
        g = self.game((MATE, KILL, P+'lose_weapon'), board=(BUCCANEER,))
        self.assertEqual(self.entity(g, BUCCANEER).attack, 1)
        self.play(g, MATE)
        weapon = g.state.players[1].weapon_id
        self.assertEqual((g.state.entities[weapon].card_id, self.entity(g, BUCCANEER).attack), (HOOK, 3))
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[weapon].durability, 2)
        self.play(g, KILL, self.entity(g, MATE).id)
        self.assertEqual(self.entity(g, BUCCANEER).attack, 3)
        self.play(g, P+'lose_weapon'); self.assertEqual(self.entity(g, BUCCANEER).attack, 1)

    def test_oracle_is_other_friendly_current_murlocs_and_not_permanent_buff(self):
        g = self.game((P+'murloc', P+'plain', SILENCE), board=(ORACLE, MURLOC, YETI), enemy_board=(MURLOC,))
        self.assertEqual((self.entity(g, ORACLE).attack, self.entity(g, MURLOC).attack,
            self.entity(g, MURLOC, 2).attack), (1, 2, 1))
        plain = self.entity(g, YETI).id
        self.play(g, P+'murloc', plain); self.assertEqual(g.state.entities[plain].attack, 5)
        self.play(g, P+'plain', plain); self.assertEqual(g.state.entities[plain].attack, 4)
        self.play(g, SILENCE, self.entity(g, ORACLE).id)
        self.assertEqual(self.entity(g, MURLOC).attack, 1)
        self.assertFalse(self.entity(g, MURLOC).enchantments)

    def test_oracle_transfer_uses_new_friendly_domain(self):
        g = self.game((TAKE,), board=(ORACLE, MURLOC), enemy_board=(MURLOC,))
        self.play(g, TAKE, self.entity(g, ORACLE).id)
        self.assertEqual((self.entity(g, MURLOC).attack, self.entity(g, MURLOC, 2).attack), (1, 2))

    def test_tidecaller_excludes_itself_and_enemy_entries(self):
        g = self.game((TIDECALLER, MURLOC), enemy_hand=(MURLOC,))
        source = self.play(g, TIDECALLER); self.assertEqual(g.state.entities[source].attack, 1)
        self.play(g, MURLOC); self.assertEqual(g.state.entities[source].attack, 2)
        g.apply(EndTurn(1)); self.play(g, MURLOC, player=2)
        self.assertEqual(g.state.entities[source].attack, 2)

    def test_anomaly_only_own_successful_spells_and_not_hero_power(self):
        g = self.game((ZERO,), board=(ANOMALY,), enemy_hand=(ZERO,))
        source = self.entity(g, ANOMALY).id
        self.play(g, ZERO); self.assertEqual(g.state.entities[source].max_health, 2)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[source].max_health, 2)
        g.apply(EndTurn(1)); self.play(g, ZERO, player=2)
        self.assertEqual(g.state.entities[source].max_health, 2)

    def test_countered_spell_does_not_grow_anomaly(self):
        g = self.game((ZERO,), board=(ANOMALY,), enemy_hand=(COUNTER,), active=2)
        self.play(g, COUNTER, player=2); g.apply(EndTurn(2)); self.play(g, ZERO)
        self.assertEqual(self.entity(g, ANOMALY).max_health, 1)

    def test_tiller_attack_trigger_precedes_ordinary_combat_and_ignores_others(self):
        g = self.game(board=(TILLER, YETI), enemy_board=(YETI,))
        source, target = self.entity(g, TILLER).id, self.entity(g, YETI, 2).id
        g.apply(Attack(1, source, target))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 2)
        self.assertEqual(g.state.entities[target].damage, 1)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        g.apply(Attack(1, self.entity(g, YETI).id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 6)

    def test_tiller_bonus_is_not_spell_damage_and_invalid_attack_rolls_back(self):
        g = self.game(board=(TILLER, 'CORE_EX1_012'), enemy_board=(YETI,))
        source = self.entity(g, TILLER).id
        before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, source, 999999))
        self.assertEqual(g.snapshot(), before)
        g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 3)

    def test_rover_gains_two_per_actual_damage_event_including_lethal(self):
        g = self.game((HURT, LETHAL), board=(ROVER,))
        source = self.entity(g, ROVER).id
        self.play(g, HURT, source); self.assertEqual(self.armor(g), 2)
        self.play(g, LETHAL, source); self.assertEqual(self.armor(g), 4)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        h = self.game((TWICE,), board=(ROVER,))
        self.play(h, TWICE, self.entity(h, ROVER).id); self.assertEqual(self.armor(h), 4)

    def test_rover_shield_absorbs_damage_without_armor_and_silence_stops_future_armor(self):
        g = self.game((P+'shield', HURT, HURT, SILENCE, HURT), board=(ROVER,))
        source = self.entity(g, ROVER).id
        self.play(g, P+'shield', source); self.play(g, HURT, source)
        self.assertEqual(self.armor(g), 0)
        self.play(g, HURT, source); self.play(g, SILENCE, source); self.play(g, HURT, source)
        self.assertEqual(self.armor(g), 2)

    def test_offering_owner_start_destroys_original_and_grants_armor_once(self):
        g = self.game(board=(OFFERING,), deck=(RAVEN,)*3, enemy_deck=(RAVEN,)*3)
        source = self.entity(g, OFFERING).id
        g.apply(EndTurn(1)); self.assertEqual(self.armor(g), 0)
        g.apply(EndTurn(2)); self.assertEqual(self.armor(g), 8)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.armor(g), 8)

    def test_offering_control_and_silence_use_current_native_source(self):
        g = self.game((TAKE,), board=(OFFERING,), enemy_deck=(RAVEN,))
        self.play(g, TAKE, self.entity(g, OFFERING).id); g.apply(EndTurn(1))
        self.assertEqual((self.armor(g), self.armor(g, 2)), (0, 8))
        h = self.game((SILENCE,), board=(OFFERING,), deck=(RAVEN,), enemy_deck=(RAVEN,))
        self.play(h, SILENCE, self.entity(h, OFFERING).id)
        h.apply(EndTurn(1)); h.apply(EndTurn(2)); self.assertEqual(self.armor(h), 0)

    def test_selfless_selects_one_original_friendly_reference_with_one_rng_draw(self):
        g = self.game((KILL,), board=(SELFLESS, YETI, RAVEN), enemy_board=(YETI,))
        source = self.entity(g, SELFLESS).id
        candidates = sorted(i for i in g.state.players[1].board if i != source)
        rng = Random(); rng.setstate(g._rng.getstate()); chosen = rng.choice(candidates)
        self.play(g, KILL, source)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        for i in candidates:
            self.assertEqual(Keyword.DIVINE_SHIELD in g.state.entities[i].keywords, i == chosen)
        self.assertNotIn(Keyword.DIVINE_SHIELD, self.entity(g, YETI, 2).keywords)

    def test_selfless_empty_domain_does_not_consume_rng(self):
        g = self.game((KILL,), board=(SELFLESS,)); before = g._rng.getstate()
        self.play(g, KILL, self.entity(g, SELFLESS).id)
        self.assertEqual(g._rng.getstate(), before)

    def test_selfless_internal_constructed_policy_keeps_an_existing_shield_recipient(self):
        g = self.game((KILL,), board=(SELFLESS, SHIELDED))
        source = self.entity(g, SELFLESS).id; target = self.entity(g, SHIELDED).id
        self.play(g, KILL, source)
        choices = [e for e in g.events if e.kind == 'random_choice']
        self.assertEqual([e.target_id for e in choices], [target])
        self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)
        self.assertIn('not a CN-certified selector', load_batch()['selfless_constructed_policy'])

    def test_keyword_weapon_and_armor_waits_restore_without_duplicate_effects(self):
        for source in (SELFLESS, MATE, OFFERING, ROVER):
            with self.subTest(card=source):
                if source == SELFLESS:
                    g = self.game((KILL,), board=(SELFLESS, YETI), mode='wait')
                    self.play(g, KILL, self.entity(g, SELFLESS).id)
                elif source == MATE:
                    g = self.game((MATE,), mode='wait'); self.play(g, MATE)
                elif source == OFFERING:
                    g = self.game(board=(OFFERING,), active=2, deck=(RAVEN,), mode='wait'); g.apply(EndTurn(2))
                else:
                    g = self.game((HURT,), board=(ROVER,), mode='wait'); self.play(g, HURT, self.entity(g, ROVER).id)
                self.assertIsNotNone(g.state.pending_choice); self.portable(g)
                rng = g._rng.getstate(); armor = self.armor(g)
                self.choose(g); self.assertEqual((g._rng.getstate(), self.armor(g)), (rng, armor))
                self.portable(g)

    def test_late_native_effect_failures_roll_back_whole_play_or_turn(self):
        for source in (SELFLESS, MATE, OFFERING, ROVER):
            with self.subTest(card=source):
                if source == SELFLESS:
                    g = self.game((KILL,), board=(SELFLESS, YETI), mode='fail')
                    action = PlayCard(1, self.entity(g, KILL, zone='hand').id, self.entity(g, SELFLESS).id)
                elif source == MATE:
                    g = self.game((MATE,), mode='fail'); action = PlayCard(1, self.entity(g, MATE, zone='hand').id)
                elif source == OFFERING:
                    g = self.game(board=(OFFERING,), active=2, deck=(RAVEN,), mode='fail'); action = EndTurn(2)
                else:
                    g = self.game((HURT,), board=(ROVER,), mode='fail')
                    action = PlayCard(1, self.entity(g, HURT, zone='hand').id, self.entity(g, ROVER).id)
                before = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'K456 deliberate'): g.apply(action)
                self.assertEqual(g.snapshot(), before)

    def test_real_flashback_uses_reactive_bodies_without_their_battlecries(self):
        g = self.game((FLASHBACK, RAVEN)); self.play(g, RAVEN); self.play(g, FLASHBACK)
        made = g.state.players[1].board[1:]; self.assertEqual(len(made), 2)
        for i in made: self.assertIn(g.state.entities[i].card_id, LEAVES)
        self.assertFalse(g.state.battlecry_history)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.portable(g)

    def test_production_past_domain_is_not_fabricated(self):
        self.assertNotIn('constructed.past.cards', build_registry().pools)


if __name__ == '__main__':
    unittest.main()
