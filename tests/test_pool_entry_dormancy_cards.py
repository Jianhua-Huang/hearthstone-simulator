"""Real forced dormant entry, original pool material and ordinary owner clock."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.pool_entry_dormancy_cards import FLUTTERWING, QUERY, POOL_ID, ENTRY_POLICY, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.effects import (GainArmor, ChoiceOption, Destroy, InvokeBehavior, RequestChoice,
    Summon, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import LimitedTriggerSpec, Rarity, SummonQuantitySpec, SummonStats
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
    SummonFromPool, resolve_candidates, sample_candidates)
from hs_sim.engine.pool_summons import PoolSummonBatchSpec, validate_weighted_request
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import canonical_digest

P = 'k126.test.'
CROC, YETI = 'CORE_CS2_120', 'CORE_CS2_182'
NATIVE, PERMANENT, UNKNOWN = P+'native', P+'permanent', P+'unknown'
MEMBERS = (CROC, NATIVE, YETI, FLUTTERWING)
CTX = GenerationContext('k126-complete-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())
ELIGIBLE = replace(META, collectible=True, classes=(CardClass.MAGE,), rarity=Rarity.COMMON)


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = build_registry()
    r.register_behavior(P+'awake', lambda c: (GainArmor(c.player_id, 7),))
    r.register_behavior(P+'battlecry', lambda c: (GainArmor(c.player_id, 90),))
    for cid, turns, permanent in ((NATIVE, 1, False), (PERMANENT, None, True)):
        card = CardDefinition(cid, cid, CardType.MINION, cost=2, attack=2, health=3, metadata=ELIGIBLE,
            dormant_turns=turns, permanent_dormancy=permanent, on_awaken=None if permanent else P+'awake', battlecry=P+'battlecry')
        r.register_card(card)
        r.register_pool_card(PoolCard.from_definition(card))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 2, ELIGIBLE,
            battlecry=False, deathrattle=False, choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k126-explicit-complete-v1', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid, 3 if cid == CROC else 1) for cid in members), complete=True))
    def fail(c):
        raise ResolutionError('K126 deliberate entry failure')
    scripts = {
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'live': lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        'twice_live': lambda c: (TriggerDeathrattles(c.target_id, c.source_id, times=2),),
        'fail': fail,
        'ordinary': lambda c: (Summon(c.player_id, NATIVE),),
        'before': lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('get', 'Original forced dormant entry', (SummonFromPool(c.player_id, POOL_ID, QUERY,
                source_id=c.source_id, cause=SummonCause.capture(c), entry_dormant_turns=2),)),
            ChoiceOption('skip', 'Skip')), c.source_id),),
    }
    for name, fn in scripts.items():
        r.register_behavior(P+name, fn)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, metadata=META, on_play=P+name,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if name in ('kill','live','twice_live') else None))
    r.register_card(CardDefinition(P+'twice', 'Existing summon quantity', CardType.MINION, health=8,
        metadata=META, summon_quantities=(SummonQuantitySpec(),)))
    if mode:
        def observer(c):
            entity = c.state.entities[c.event.target_id]
            if entity.active or entity.dormancy is None or entity.dormancy.remaining_turns != 2:
                raise ResolutionError('First acquisition exposed an active or wrong dormant body')
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(P+'observe', observer)
        r.register_trigger_condition(P+'eligible', lambda c: c.state.entities[c.event.target_id].card_id in (CROC,NATIVE,PERMANENT))
        r.register_card(CardDefinition(P+'watch', 'First actual summon observer', CardType.MINION, health=8, metadata=META,
            limited_triggers=(LimitedTriggerSpec('minion_summoned', P+'observe', condition_id=P+'eligible'),)))
    r.validate()
    return r


class PoolEntryDormancyTests(unittest.TestCase):
    def game(self, members=MEMBERS, mode=None, pool=True, context=CTX, board=(FLUTTERWING,), hand=(P+'kill',), seed=126):
        self.config = (members, mode, pool)
        if mode:
            board = (P+'watch', *board)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', hand=hand, board=board, deck=(YETI,)*8, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', deck=(YETI,)*8)), seed=seed, generation_context=context), registry(*self.config))

    def first(self, g, cid, zone='board'):
        return next(g.state.entities[i] for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        eid = self.first(g, cid, 'hand').id
        g.apply(PlayCard(1, eid, target, position=len(g.state.players[1].board) if g.registry.card(cid).kind == CardType.MINION else None))
        return eid

    def activate(self, g, live=False):
        return self.play(g, P+'live' if live else P+'kill', self.first(g, FLUTTERWING).id)

    def root(self, g):
        return g.state.card_summon_history[-1]

    def body(self, g):
        return g.state.entities[self.root(g).deliveries[0].entity.entity_id]

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def owner_start(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry.__wrapped__(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(*self.config)).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','pool_basis','entry_dormant_turns','behavior_id'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def reject(self, g, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry(*self.config))

    def test_full_original_beast_source_two_faces_and_no_dormancy_on_source(self):
        data=load_batch();raw=data['cards'][0]['record'];c=registry().card(FLUTTERWING)
        self.assertEqual(canonical_digest(raw),data['cards'][0]['record_sha256'])
        self.assertEqual((c.cost,c.attack,c.health,c.metadata),(1,1,1,metadata_from_record(raw)))
        self.assertEqual(c.metadata.tribes,('beast',));self.assertEqual(c.dormant_turns,0);self.assertFalse(c.keywords)
        self.assertIsNone(c.battlecry);self.assertIsNotNone(c.deathrattle)
        self.assertEqual(data['entry_policy'],ENTRY_POLICY);self.assertFalse(data['cn_calibrated']);self.assertFalse(data['formal_pool_complete'])
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        self.assertEqual(len(data['official_observations']['observations']),2)
        for ob in data['official_observations']['observations']:
            en=ob['locale']=='en_US';self.assertEqual(ob['face']['name'],raw['name_en'if en else'name']);self.assertEqual(norm(ob['face']['text']),norm(raw['text_en'if en else'text']))

    def test_only_one_definition_preserves_complete_old_facts_and_default_identity(self):
        with patch('hs_sim.cards.pool_entry_dormancy_cards.register_pool_entry_dormancy_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{FLUTTERWING})
        self.assertTrue(all(asdict(c)==asdict(after.card(cid)) for cid,c in before.cards.items()))
        self.assertEqual(dict(after.pool_cards),dict(before.pool_cards));self.assertEqual(dict(after.pools),dict(before.pools))
        self.assertEqual(dict(after.generation_families),dict(before.generation_families))
        from hs_sim.engine.representative import build_registry as defaults
        self.assertEqual(defaults().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_natural_death_keeps_original_slot_and_installs_complete_two_turn_body(self):
        g=self.game(members=(CROC,),board=(YETI,FLUTTERWING,YETI));old=self.first(g,FLUTTERWING).id;self.activate(g)
        e=self.body(g);root=self.root(g);self.assertEqual(g.state.players[1].board[1],e.id)
        self.assertEqual((e.card_id,e.attack,e.health,e.dormancy.remaining_turns),(CROC,2,3,2));self.assertFalse(e.active)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(root.request.cause.source.entity_id,old)
        self.assertEqual(root.request.materials,(SummonEntryMaterial(CROC,dormant_turns=2),))
        self.assertEqual(root.request.pool_basis.entry_dormant_turns,2);self.assertEqual(len(g.state.deathrattle_history),1)
        self.portable(g)

    def test_live_deathrattle_uses_carrier_right_side_without_killing_it(self):
        g=self.game(members=(CROC,),hand=(P+'live',),board=(YETI,FLUTTERWING,YETI));old=self.first(g,FLUTTERWING).id;self.activate(g,live=True)
        self.assertEqual(g.state.players[1].board[1:3],[old,self.body(g).id]);self.assertEqual(g.state.entities[old].zone,Zone.BOARD)
        self.assertFalse(g.state.death_history);self.assertEqual(self.body(g).dormancy.remaining_turns,2)

    def test_exact_printed_two_anyclass_weighted_pool_is_not_a_dormant_filter(self):
        g=self.game();rows=resolve_candidates(g.registry,CTX,POOL_ID,QUERY,source_card_id=FLUTTERWING,exclude_source_by_rule=True,player_id=1)
        self.assertEqual([(x.card_id,x.weight)for x in rows],[(CROC,3),(NATIVE,1)])
        rng=random.Random();rng.setstate(g._rng.getstate());expected=sample_candidates(rng,rows,1,replacement=True)[0]
        self.activate(g);self.assertEqual(self.body(g).card_id,expected);self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(QUERY.class_mode,'any');self.assertFalse(QUERY.keywords_all)

    def test_first_summon_observer_sees_dormancy_and_pending_finish_restores_exactly(self):
        g=self.game(members=(CROC,),mode='wait');self.activate(g);e=self.body(g)
        self.assertFalse(e.active);self.assertEqual(e.dormancy.remaining_turns,2);self.assertEqual(self.root(g).status,'active')
        other=self.portable(g);saved=g.snapshot();rng=g._rng.getstate()
        with self.assertRaisesRegex(ResolutionError,'K126 deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.root(g).status,'completed')

    def test_original_native_one_turn_uses_selected_two_turn_policy_and_original_awake_callback(self):
        g=self.game(members=(NATIVE,));self.activate(g);e=self.body(g)
        self.assertEqual(e.dormancy.remaining_turns,2);self.assertFalse(e.dormancy.permanent)
        self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.owner_start(g);self.assertEqual(g.state.entities[e.id].dormancy.remaining_turns,1)
        self.owner_start(g);self.assertIsNone(g.state.entities[e.id].dormancy)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7)
        self.assertEqual(len([x for x in g.events if x.kind=='minion_summoned']),1)

    def test_real_two_cost_imprisoned_vilefiend_retains_original_rush_after_forced_clock(self):
        g=self.game(members=('CORE_BT_156',));self.activate(g);e=self.body(g)
        self.assertEqual((e.card_id,e.dormancy.remaining_turns),('CORE_BT_156',2));self.assertFalse(e.keywords)
        self.owner_start(g);self.owner_start(g)
        self.assertIsNone(g.state.entities[e.id].dormancy);self.assertIn(Keyword.RUSH,g.state.entities[e.id].keywords)
        self.assertEqual(len([x for x in g.events if x.kind=='minion_summoned']),1)

    def test_permanent_dormancy_remains_explicitly_unsupported_before_rng_not_cropped(self):
        g=self.game(members=(CROC,PERMANENT));saved=g.snapshot()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Permanent candidate was cropped')):
            with self.assertRaisesRegex(ResolutionError,'permanent dormant carrier'):self.activate(g)
        self.assertEqual(g.snapshot(),saved)

    def test_ordinary_summon_retains_printed_dormancy_and_does_not_run_battlecry(self):
        g=self.game(board=(),hand=(P+'ordinary',));self.play(g,P+'ordinary');e=self.first(g,NATIVE)
        self.assertEqual(e.dormancy.remaining_turns,1);self.assertFalse(g.state.battlecry_history)
        self.owner_start(g);self.assertIsNone(g.state.entities[e.id].dormancy)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7)

    def test_owner_clock_ignores_opponent_start_and_awakens_same_entity_without_new_summon(self):
        g=self.game(members=(CROC,));self.activate(g);e=self.body(g);did=e.dormancy.id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[e.id].dormancy.remaining_turns,2)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[e.id].dormancy.remaining_turns,1)
        self.assertEqual(g.state.entities[e.id].dormancy.id,did);other=self.portable(g)
        for game in (g,other):self.owner_start(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIsNone(g.state.entities[e.id].dormancy)
        self.assertEqual(len([x for x in g.events if x.kind=='minion_summoned']),1)

    def test_quantity_extras_reuse_selected_material_but_have_independent_dormancy_ids(self):
        g=self.game(members=(CROC,),board=(P+'twice',FLUTTERWING));self.activate(g);root=self.root(g)
        self.assertEqual(root.plan.total,2);bodies=[g.state.entities[x.entity.entity_id]for x in root.deliveries]
        self.assertEqual(len({e.id for e in bodies}),2);self.assertEqual(len({e.dormancy.id for e in bodies}),2)
        self.assertTrue(all(not e.active and e.dormancy.remaining_turns==2 for e in bodies));self.assertEqual(len(g.state.deathrattle_history),1)
        self.portable(g)

    def test_two_actual_live_deathrattles_accept_independent_pool_roots(self):
        g=self.game(hand=(P+'twice_live',));old=self.first(g,FLUTTERWING).id;self.play(g,P+'twice_live',old)
        roots=g.state.card_summon_history;self.assertEqual(len(roots),2);self.assertEqual(len(g.state.deathrattle_history),2)
        self.assertTrue(all(root.request.cause.source.entity_id==old and root.request.pool_basis.entry_dormant_turns==2 for root in roots))
        self.assertNotEqual(roots[0].deliveries[0].entity.entity_id,roots[1].deliveries[0].entity.entity_id)

    def test_full_board_live_trigger_still_validates_pool_but_does_not_roll_or_create(self):
        g=self.game(members=(CROC,),board=(FLUTTERWING,)+(YETI,)*6,hand=(P+'live',));rng=g._rng.getstate();self.activate(g,live=True)
        self.assertEqual(self.root(g).status,'skipped');self.assertFalse(self.root(g).deliveries);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(g.state.players[1].board),7)

    def test_empty_pool_keeps_real_death_and_has_no_rng_or_dormant_body(self):
        g=self.game(members=(YETI,));rng=g._rng.getstate();old=self.first(g,FLUTTERWING).id;self.activate(g)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(self.root(g).status,'skipped');self.assertFalse(self.root(g).deliveries)

    def test_unknown_complete_candidate_fails_before_rng_even_for_full_board(self):
        for full in (False,True):
            with self.subTest(full=full):
                g=self.game(members=(CROC,UNKNOWN),board=(FLUTTERWING,)+(YETI,)*6 if full else (FLUTTERWING,),hand=(P+'live',))
                saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before full eligibility')):
                    with self.assertRaises(ResolutionError):self.activate(g,live=True)
                self.assertEqual(g.snapshot(),saved)

    def test_missing_context_pool_and_late_entry_failure_roll_back_original_death(self):
        for config in ({'context':None},{'pool':False},{'mode':'fail'}):
            with self.subTest(config=config):
                g=self.game(members=(CROC,),**config);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.activate(g)
                self.assertEqual(g.snapshot(),saved)

    def test_natural_hand_play_is_active_pays_one_and_needs_no_generated_pool(self):
        g=self.game(board=(),hand=(FLUTTERWING,),pool=False,context=None);source=self.play(g,FLUTTERWING)
        self.assertTrue(g.state.entities[source].active);self.assertIsNone(g.state.entities[source].dormancy)
        self.assertEqual(g.state.players[1].mana,29);self.assertFalse(g.state.card_summon_history)

    def test_finite_fields_reject_bool_zero_unattributed_or_unrequested_material_shapes(self):
        for value in (True,False,0,-1,2.0,'2'):
            with self.subTest(value=value),self.assertRaises(ValueError):SummonEntryMaterial(CROC,dormant_turns=value)
            with self.subTest(value=value),self.assertRaises(ValueError):SummonFromPool(1,POOL_ID,QUERY,source_id=1,entry_dormant_turns=value)
        with self.assertRaises(ValueError):SummonFromPool(1,POOL_ID,QUERY,source_id=1,entry_dormant_turns=2)
        for extra in ({'stats':SummonStats(attack=2,health=3)},{'keywords':(Keyword.TAUNT,)},{'deathrattles':('always',)}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):SummonEntryMaterial(CROC,dormant_turns=2,**extra)

    def test_selected_basis_and_material_are_bound_in_history_and_manual_decoder(self):
        g=self.game(members=(CROC,),mode='wait');self.activate(g);root=self.root(g)
        validate_weighted_request(g.state,g.registry,root.request)
        for req in (replace(root.request,materials=(SummonEntryMaterial(CROC),)),
                    replace(root.request,pool_basis=replace(root.request.pool_basis,entry_dormant_turns=1))):
            with self.assertRaises(ValueError):validate_weighted_request(g.state,g.registry,req)
        with self.assertRaises(ValueError):PoolSummonBatchSpec(root.request.cause,root.request.pool_basis,1,True)
        for part in ('materials','pool_basis'):
            saved=deepcopy(g.snapshot());row=saved['state']['card_summon_history'][-1]['request']
            if part=='materials':row['materials'][0]['dormant_turns']=1
            else:row['pool_basis']['entry_dormant_turns']=1
            self.reject(g,saved)

    def test_nested_unexecuted_request_restores_then_enforces_explicit_positive_integer(self):
        g=self.game(members=(CROC,),board=(),hand=(P+'before',));self.play(g,P+'before');self.portable(g)
        def nodes(node):
            if isinstance(node,dict):
                if node.get('type','').endswith('.SummonFromPool'):yield node['fields']
                for v in node.values():yield from nodes(v)
            elif isinstance(node,list):
                for v in node:yield from nodes(v)
        for value in (True,0,2.0):
            saved=deepcopy(g.snapshot());next(nodes(saved))['entry_dormant_turns']=value;self.reject(g,saved)
        self.choose(g,'get');self.assertEqual(self.body(g).dormancy.remaining_turns,2)
        saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))


if __name__ == '__main__':
    unittest.main()
