"""Actual sleeping seeds and a corpse-paid, capacity-checked Deathrattle summon."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_native_summon_costs as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_assemble_entry_cards import FLESH, SHAPER, POOL_ID
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, Silence, SpendResource, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Keyword, Resource, SummonQuantitySpec, SummonStats
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha

CORRUPTER, NECRO = cards.SOURCES
SEEDS, FOOTMAN = cards.SEEDS, cards.FOOTMAN
DRAIN, PHOENIX, RUST = 'CORE_GIL_622', 'CORE_UNG_084', 'CORE_SW_072'
COIN = 'GAME_005'
P = 'k441.'
N, KILL, MUTE, COPY, BASE_COPY, STEAL, TRIGGER, PAY_WAIT, SEED_WAIT, FILL, FAIL, QUANTITY, BAD = (
    P+k for k in ('n', 'kill', 'mute', 'copy', 'base_copy', 'steal', 'trigger', 'pay_wait',
        'seed_wait', 'fill', 'fail', 'quantity', 'bad_target'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
CTX = GenerationContext('k441-three-reviewed-source-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version += '.k441.'+mode
    r.register_card(CardDefinition(N, N, CardType.MINION, health=20, metadata=META))
    r.register_card(CardDefinition(QUANTITY, QUANTITY, CardType.MINION, health=20,
        summon_quantities=(SummonQuantitySpec(),), metadata=META))
    def fail(c): raise ResolutionError('K441 deliberate paid summon continuation failure')
    r.register_behavior(FAIL, fail)
    def fill(c):
        if (c.event.player_id != c.player_id or
                c.state.entities[c.event.source_id].card_id != recipe(CORRUPTER, NECRO)): return ()
        return (SummonByCard(c.player_id, (SummonEntryMaterial(N),), SummonCause.capture(c)),)
    def wait(c, seed=False):
        if c.event.player_id != c.player_id: return ()
        if seed and c.state.entities[c.event.target_id].card_id not in SEEDS: return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('go', 'Continue'),
            ChoiceOption('fill', 'Fill last slot', (SummonByCard(c.player_id,
                (SummonEntryMaterial(N),), SummonCause.capture(c)),)),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id)))),
            c.source_id),)
    for cid,event,body in ((FILL, 'minion_died', fill),
            (PAY_WAIT, 'resource_spent', lambda c: wait(c)),
            (SEED_WAIT, 'minion_summoned', lambda c: wait(c, True))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20,
            triggers=(TriggerSpec(event, cid),), metadata=META))
    bodies = {KILL:lambda c:(Destroy(c.target_id, c.source_id),),
        MUTE:lambda c:(Silence(c.target_id),),
        COPY:lambda c:(CopyMinion(c.target_id, c.player_id, mode='current'),),
        BASE_COPY:lambda c:(CopyMinion(c.target_id, c.player_id, mode='base'),),
        STEAL:lambda c:(ChangeControl(c.target_id, 3-c.player_id),),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id, c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    r.register_behavior(BAD, lambda c: (SpendResource(c.player_id, Resource.CORPSES, 1,
        on_success=(SummonByCard(c.player_id, (SummonEntryMaterial(COIN),), SummonCause.capture(c)),),
        requires_board_space=True),))
    r.register_card(CardDefinition(BAD, BAD, CardType.MINION, cost=1, health=2, battlecry=BAD, metadata=META))
    domains = {'seed_offer': (CORRUPTER, DRAIN, PHOENIX), 'necro_offer': (NECRO, DRAIN, RUST)}
    if mode in domains:
        r.register_pool(PoolDefinition(POOL_ID, 'k441-complete-explicit-three-reviewed-members',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in domains[mode]), complete=True))
    if mode == 'missing_seed': del r._cards[SEEDS[1]]
    if mode == 'missing_footman': del r._cards[FOOTMAN]
    r.validate(); return r


class AssembleNativeSummonTests(unittest.TestCase):
    def game(self, hand=(), board=(), corpses=0, mode='normal'):
        hero = 'HERO_10' if mode == 'seed_offer' else 'HERO_11'
        return Game.from_scenario(Scenario((PlayerSetup(hero, hand=hand, board=board,
            deck=(COIN,)*24, mana=50, max_mana=50, mana_cap=50, corpses=corpses),
            PlayerSetup('HERO_08', deck=(COIN,)*24, mana=50, max_mana=50, mana_cap=50)),
            seed=1, generation_context=CTX), fixture(mode))

    def ids(self, g, cid, zone='board', p=1):
        return [i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid]

    def play(self, g, cid, target=None):
        source = self.ids(g, cid, 'hand')[0]; g.apply(PlayCard(1, source, target)); return source

    def bank(self, g, p=1): return g.state.players[p].resources[Resource.CORPSES]

    def seeds(self, g):
        return [i for i in g.state.players[1].board if g.state.entities[i].card_id in SEEDS]

    def end(self, g): g.apply(EndTurn(g.state.active_player))

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved); self.assertEqual(g.snapshot(), saved)
        for player in (1,2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('next_entity_id', 'resolution_frame', 'rng_state', 'primary_candidates'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def test_a_complete_six_originals_four_faces_seed_evidence_and_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 6); self.assertEqual(len(d['evidence_only']), 4)
        self.assertEqual(len(d['official_observations']), 4)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        for cid in cards.SOURCES:
            original = asdict(r.card(cid)); new = asdict(r.card(recipe(cid))); new['id'] = cid
            self.assertEqual(new, original); self.assertEqual(recipe_options(r, cid, cid), ())
        self.assertEqual({cid:r.card(cid).dormant_turns for cid in SEEDS}, cards.TURNS)

    def test_b_raw_and_self_corruptor_pay_once_and_preserve_both_original_causes_and_death_slot(self):
        for cid in (CORRUPTER, recipe(CORRUPTER)):
            g = self.game((cid, KILL), (N, N)); source = self.ids(g, cid, 'hand')[0]
            g.apply(PlayCard(1, source, position=1)); before = set(self.seeds(g))
            self.assertEqual(len(before), 1); self.assertEqual(g.state.players[1].mana, 46)
            self.play(g, KILL, source); born, = set(self.seeds(g))-before
            self.assertEqual(g.state.players[1].board[1], born)
            roots = g.state.card_summon_history; self.assertEqual(len(roots), 2)
            for root in roots:
                self.assertEqual(tuple(x.card_id for x in root.request.materials), SEEDS)
                self.assertEqual((root.request.cause.source.entity_id, root.request.cause.player_id), (source, 1))
            self.assertIsNone(roots[0].request.position); self.assertEqual(roots[1].request.position, 1)
            self.assertEqual(len(g.state.battlecry_history), 1); self.assertEqual(len(g.state.deathrattle_history), 1)

    def test_c_raw_and_self_necromancer_keep_original_end_guard_and_exact_footman(self):
        for cid in (NECRO, recipe(NECRO)):
            g = self.game((cid,), corpses=1); self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, 48); self.end(g)
            body = g.state.entities[self.ids(g, FOOTMAN)[0]]
            self.assertEqual((body.attack, body.health), (1, 3)); self.assertIn(Keyword.TAUNT, body.keywords)
            self.assertEqual(self.bank(g), 0); self.assertEqual(len(g.state.corpse_spend_history), 1)

    def test_d_dual_prefix_keeps_two_independent_payments_and_uses_deaths_new_corpse(self):
        cid = recipe(CORRUPTER, NECRO)
        for bank,expected in ((0,1), (2,2)):
            g = self.game((cid, KILL), corpses=bank); source = self.play(g, cid)
            self.play(g, KILL, source)
            self.assertEqual(len(self.ids(g, FOOTMAN)), expected)
            self.assertEqual(len(g.state.corpse_spend_history), expected); self.assertEqual(self.seeds(g), [])
            self.assertEqual(self.bank(g), bank+1-expected)
            self.assertEqual(g.state.card_summon_history[-1].request.cause.source.zone, Zone.GRAVEYARD)

    def test_e_necromancer_end_prefix_borrows_seed_body_without_corpse_payment(self):
        cid = recipe(NECRO, CORRUPTER); g = self.game((cid,), corpses=2); self.play(g, cid); self.end(g)
        self.assertEqual(len(self.seeds(g)), 1); self.assertEqual(self.ids(g, FOOTMAN), [])
        self.assertEqual(self.bank(g), 2); self.assertEqual(g.state.corpse_spend_history, [])
        self.assertIsNotNone(g.state.entities[self.seeds(g)[0]].dormancy)

    def test_f_borrowed_battlecry_preserves_native_insufficient_corpse_guard_and_no_old_damage(self):
        cid = recipe(DRAIN, NECRO)
        for bank in (0,1):
            g = self.game((cid,), corpses=bank); self.play(g, cid)
            self.assertEqual(len(self.ids(g, FOOTMAN)), bank); self.assertEqual(self.bank(g), 0)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_g_controlled_death_spends_and_summons_for_actual_dead_controller(self):
        cid = recipe(CORRUPTER, NECRO); g = self.game((STEAL, KILL), (cid,)); source = self.ids(g, cid)[0]
        self.play(g, STEAL, source); self.play(g, KILL, source)
        self.assertEqual(self.ids(g, FOOTMAN), []); self.assertEqual(len(self.ids(g, FOOTMAN, p=2)), 1)
        self.assertEqual((self.bank(g), self.bank(g,2)), (0,0))
        self.assertEqual(g.state.card_summon_history[-1].request.cause.player_id, 2); self.portable(g)

    def test_h_active_deathrattle_uses_real_activation_without_fake_death_and_right_position(self):
        cid = recipe(CORRUPTER, NECRO); g = self.game((TRIGGER,), (N, cid, N), corpses=1)
        source = self.ids(g, cid)[0]; self.play(g, TRIGGER, source)
        self.assertEqual(g.state.death_history, []); self.assertEqual(self.bank(g), 0)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(g.state.players[1].board[2], self.ids(g, FOOTMAN)[0])
        self.assertEqual(len(g.state.deathrattle_history), 1)

    def test_i_filled_before_payment_skips_debit_even_after_natural_corpse_gain(self):
        cid = recipe(CORRUPTER, NECRO); g = self.game((KILL,), (cid, FILL)+(N,)*5, corpses=2)
        before = g.snapshot()['rng_state']; self.play(g, KILL, self.ids(g, cid)[0])
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(self.ids(g, FOOTMAN), [])
        self.assertEqual(self.bank(g), 3); self.assertEqual(g.state.corpse_spend_history, [])
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_j_filled_after_payment_does_not_refund_or_accept_a_second_payment(self):
        cid = recipe(CORRUPTER, NECRO); g = self.game((KILL,), (cid, PAY_WAIT)+(N,)*5, corpses=2)
        self.play(g, KILL, self.ids(g, cid)[0]); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.bank(g), 2); self.pick(g, 'fill')
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(self.ids(g, FOOTMAN), [])
        self.assertEqual(self.bank(g), 2); self.assertEqual(len(g.state.corpse_spend_history), 1)

    def test_k_paid_wait_restores_and_failed_resume_keeps_original_debit_and_choice(self):
        cid = recipe(CORRUPTER, NECRO); g = self.game((KILL,), (cid, PAY_WAIT), corpses=2)
        source = self.ids(g, cid)[0]; self.play(g, KILL, source)
        reader = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.pick(g); self.pick(reader); self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual((self.bank(g), len(g.state.corpse_spend_history), len(self.ids(g, FOOTMAN))), (2,1,1))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.portable(g)

    def test_l_seed_wait_restores_selected_named_material_without_resampling_on_failed_resume(self):
        cid = recipe(DRAIN, CORRUPTER); g = self.game((cid,), (SEED_WAIT,)); self.play(g, cid)
        reader = self.portable(g); saved = g.snapshot(); selected = self.seeds(g)
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.pick(g); self.pick(reader); self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual(self.seeds(g), selected); self.assertEqual(g.snapshot()['rng_state'], saved['rng_state'])

    def test_m_full_end_boards_preserve_bank_or_rng_under_original_capacity_policy(self):
        seed = recipe(NECRO, CORRUPTER)
        for cid in (seed, recipe(NECRO)):
            g = self.game(board=(cid,)+(N,)*6, corpses=2); before = g.snapshot()['rng_state']; self.end(g)
            self.assertEqual(self.bank(g), 2); self.assertEqual(self.seeds(g), [])
            self.assertEqual(self.ids(g, FOOTMAN), []); self.assertEqual(g.snapshot()['rng_state'], before)

    def test_n_silenced_current_copy_has_no_payment_and_base_copy_restores_new_printed_death(self):
        cid = recipe(CORRUPTER, NECRO); g = self.game((MUTE,COPY,BASE_COPY,KILL,KILL,KILL), (cid,))
        original = self.ids(g, cid)[0]; self.play(g, MUTE, original)
        self.play(g, COPY, original); current = next(i for i in self.ids(g,cid) if i!=original)
        self.play(g, BASE_COPY, original); base = next(i for i in self.ids(g,cid) if i not in (original,current))
        self.assertEqual(g.state.corpse_spend_history, [])
        for source in (original,current,base): self.play(g, KILL, source)
        self.assertEqual((self.bank(g),len(self.ids(g,FOOTMAN)),len(g.state.corpse_spend_history)), (2,1,1))

    def test_o_missing_seed_rolls_back_whole_action_and_missing_footman_rejects_setup(self):
        cid = recipe(DRAIN,CORRUPTER); g = self.game((cid,), corpses=1, mode='missing_seed')
        saved = g.snapshot()
        with self.assertRaises(ValueError): self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(ValueError): fixture.__wrapped__('missing_footman')

    def test_p_real_flesh_offer_keeps_buffed_primary_price_and_single_seed_battlecry(self):
        cid=recipe(CORRUPTER,DRAIN,'top');g=self.game((FLESH,),mode='seed_offer');entry=self.play(g,FLESH)
        self.portable(g,'seed_offer');q=g.state.pending_choice
        self.assertIn(cid,[o.card_id for o in q.options]);self.pick(g,next(o.id for o in q.options if o.card_id==cid))
        source=self.play(g,cid)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(6,6))
        self.assertEqual(g.state.players[1].mana,43);self.assertIsNone(g.registry.card(cid).deathrattle)
        self.assertEqual(len(self.seeds(g)),1);self.assertEqual(g.state.entities[entry].zone,Zone.GRAVEYARD)
        self.portable(g,'seed_offer')

    def test_q_real_shaper_offer_spends_one_corpse_from_new_two_cost_battlecry(self):
        cid=recipe(NECRO,DRAIN,'top');g=self.game((SHAPER,),corpses=1,mode='necro_offer');self.play(g,SHAPER)
        self.portable(g,'necro_offer');q=g.state.pending_choice
        self.assertIn(cid,[o.card_id for o in q.options]);self.pick(g,next(o.id for o in q.options if o.card_id==cid))
        self.play(g,cid);self.assertEqual((self.bank(g),len(self.ids(g,FOOTMAN))),(0,1))
        self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.registry.card(cid).triggers,())
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30);self.portable(g,'necro_offer')

    def test_r_fixed_corpse_gate_is_finite_and_rejects_non_minion_target_before_payment(self):
        g=self.game(board=(N,));source=self.ids(g,N)[0];cause=SummonCause.capture(RuleContext(g.state,source,1))
        summon=SummonByCard(1,(SummonEntryMaterial(FOOTMAN),),cause)
        valid=SpendResource(1,Resource.CORPSES,1,on_success=(summon,),requires_board_space=True)
        for change in ({'amount':0},{'required':True},{'on_failure':(GainArmor(1,1),)},
                {'on_success':(replace(summon,player_id=2),)},
                {'on_success':(replace(summon,materials=(SummonEntryMaterial(FOOTMAN,stats=SummonStats(2,2)),)),)},
                {'on_success':(replace(summon,selection='random'),)},
                {'on_success':(replace(summon,materials=(*summon.materials,SummonEntryMaterial(N))),)}):
            with self.assertRaises(ValueError):replace(valid,**change)
        g=self.game((BAD,),corpses=2);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),saved)

    def test_s_complete_dependency_pin_and_original_end_identity_are_strict(self):
        r=fixture.__wrapped__();r._cards[FOOTMAN]=replace(r.card(FOOTMAN),attack=2)
        with self.assertRaises(TargetValidationError):cards.register_assemble_native_summon_costs(r)
        t=fixture().assemble_templates[NECRO]
        self.assertEqual(t.suffix.behavior_id,fixture().card(NECRO).triggers[0].behavior_id)
        self.assertEqual(t.suffix.deathrattle_behavior_id,cards.DEATH_BODY)

    def test_t_quantity_extras_use_one_actual_debit_for_the_original_death_body(self):
        cid=recipe(CORRUPTER,NECRO);g=self.game((KILL,),(cid,QUANTITY),corpses=1)
        self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual((self.bank(g),len(self.ids(g,FOOTMAN)),len(g.state.corpse_spend_history)),(1,2,1))


if __name__=='__main__':unittest.main()
