"""One real discovery offer, actual Corpse branch and ordinary kept-card delivery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest
from unittest.mock import patch

from hs_sim.cards.native_corpse_keep_discovery_cards import (
    PALEOMANCY, POOL_ID, QUERY, load_batch, register_native_corpse_keep_discovery_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard,
    PlayerSetup, Rarity, Registry, Scenario, SelectChoice, SpellSchool, Keyword, RewindSpec)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, GainArmor, GainResource,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.discovery_keep import KeepPoolDiscovery
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.model import LimitedTriggerSpec, Resource
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.spell_casts import CastSpell

P = 'k185.'
HERO, FILLER, A, B, C, D, UNKNOWN = (P+s for s in ('hero','filler','a','b','c','d','unknown'))
CTX = GenerationContext('k185-explicit-bounded-undead', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON,
    tribes=('undead',), factions=(), subtypes=())


@lru_cache(None)
def registry(members=(A,B,C,D), mode=None, pool=True, role='writer'):
    r = Registry('k185-original-offer-v1')
    register_native_corpse_keep_discovery_cards(r)
    r.register_behavior(P+'battlecry', lambda c: (GainArmor(c.player_id, 999),))
    for cid in (A,B,C,D):
        card = CardDefinition(cid, cid, CardType.MINION, cost=2, attack=1, health=3,
            metadata=replace(META, classes=(CardClass.MAGE,)) if cid == B else META,
            battlecry=P+'battlecry' if cid == C else None)
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    r.register_card(CardDefinition(FILLER, FILLER, CardType.MINION, cost=1, attack=1, health=2))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 2, META,
            battlecry=False, deathrattle=False, choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k185-bounded-complete-v1', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    def fail(c): raise ResolutionError('K185 deliberate acquisition failure')
    r.register_behavior(P+'fail', fail)
    r.register_behavior(P+'auto', lambda c: (CastSpell(c.player_id, PALEOMANCY, c.source_id, choices='player'),))
    r.register_card(CardDefinition(P+'auto', 'Automatic Paleomancy', CardType.SPELL, on_play=P+'auto'))
    r.register_card(replace(r.card(PALEOMANCY),id=P+'rewind',name='Existing Retry pipeline fixture',
        keywords=(Keyword.REWIND,),rewind=RewindSpec()))
    kwargs = {}
    if mode:
        def eligible(c):
            if c.event.player_id != c.player_id: return False
            return mode == 'corpse-wait' or (c.event.target_id is not None and
                c.state.entities[c.event.target_id].card_id in (A,B,C,D))
        def observer(c):
            if mode == 'gain': return (GainResource(c.player_id, Resource.CORPSES, 10),)
            if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            if mode == 'nested': return (CastSpell(c.player_id,PALEOMANCY,c.source_id,choices='player'),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_behavior(P+'observe', observer)
        kwargs['limited_triggers'] = (LimitedTriggerSpec('resource_spent' if mode == 'corpse-wait' else
            'card_created', P+'observe', condition_id=P+'eligible'),)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100,
        metadata=CardMetadata(False, (CardClass.DEATH_KNIGHT,), None), **kwargs))
    r.validate()
    return r


class NativeCorpseKeepDiscoveryTests(unittest.TestCase):
    def game(self, bank=5, members=(A,B,C,D), mode=None, pool=True, hand=(PALEOMANCY,)):
        self.config = (members, mode, pool)
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, deck=(FILLER,)*8, corpses=bank, mana=20, max_mana=20, mana_cap=20),
            PlayerSetup(HERO, deck=(FILLER,)*8, corpses=9)), seed=185, generation_context=CTX), registry(*self.config))

    def play(self, g, cid=PALEOMANCY):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, source)); return source

    def pick(self, g, index=1):
        q = g.state.pending_choice
        offered = tuple(o.card_id for o in q.options)
        chosen = q.options[index % len(q.options)]
        g.apply(SelectChoice(q.player_id, q.id, (chosen.id,)))
        return offered, chosen.card_id

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def kept(self, g):
        return [g.state.entities[i].card_id for i in g.state.players[1].hand
            if g.state.entities[i].card_id in (A,B,C,D)]

    def bank(self, g): return g.state.players[1].resources[Resource.CORPSES]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = registry(*self.config, role='reader')
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1,2):
            text = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('keep_all_corpse_cost','resolution_frame','rng_state','original_offer','behavior_id'):
                self.assertNotIn('"'+key+'"', text)
        return other

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(*self.config, role='reader'))

    def test_complete_native_face_shadow_school_unholy_rune_and_central_assembly(self):
        d = load_batch(); c = registry().card(PALEOMANCY)
        self.assertEqual((c.cost,c.spell_school,c.metadata.runes.unholy), (3,SpellSchool.SHADOW,1))
        self.assertEqual({o['locale'] for o in d['official_observations']}, {'en_US','zh_CN'})
        self.assertFalse(d['formal_pool_complete']); self.assertFalse(d['cn_calibrated'])
        from hs_sim.cards import build_registry
        central = build_registry(); self.assertEqual(central.card(PALEOMANCY), c)
        self.assertFalse(any(key[0] == POOL_ID for key in central.pools))

    def test_insufficient_corpses_keeps_only_actual_selected_undead_without_fake_spend(self):
        for bank in (0,4):
            g = self.game(bank=bank); self.play(g); self.assertEqual(self.bank(g), bank)
            _, chosen = self.pick(g)
            self.assertEqual(self.kept(g), [chosen]); self.assertEqual(self.bank(g), bank)
            self.assertFalse(g.state.corpse_spend_history); self.assertEqual(g.state.players[1].mana,17)

    def test_five_corpses_keeps_same_three_chosen_first_then_original_offer_order(self):
        g = self.game(); source = self.play(g); offered, chosen = self.pick(g)
        self.assertEqual(self.kept(g), [chosen, *(cid for cid in offered if cid != chosen)])
        self.assertEqual(self.bank(g), 0); self.assertEqual(len(g.state.corpse_spend_history),1)
        self.assertEqual(g.state.corpse_spend_history[0].amount,5)
        self.assertEqual(g.state.players[2].resources[Resource.CORPSES],9)
        created = [e for e in g.events if e.kind == 'card_created']
        self.assertEqual(len(created),3); self.assertTrue(all(e.source_id == source for e in created))

    def test_spends_exactly_five_once_not_entire_bank_and_one_original_payment(self):
        g = self.game(bank=12); self.play(g); self.pick(g)
        self.assertEqual((self.bank(g),g.state.players[1].mana), (7,17))
        self.assertEqual(len(g.state.play_history),1); self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(len(g.state.corpse_spend_history),1)

    def test_keep_uses_no_rng_beyond_one_actual_three_option_offer(self):
        g = self.game(); self.play(g); state = g._rng.getstate(); offered, _ = self.pick(g)
        self.assertEqual(len(set(offered)),3); self.assertEqual(g._rng.getstate(),state)
        self.assertEqual(set(self.kept(g)),set(offered)); self.assertEqual(len(self.kept(g)),3)

    def test_keep_does_not_fabricate_extra_discovery_choices_or_run_minion_battlecries(self):
        g = self.game(members=(A,B,C)); self.play(g); self.pick(g)
        self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(sum(e.kind=='card_discovered' for e in g.events),1)
        self.assertEqual(sum(e.kind=='card_created' for e in g.events),3)
        self.assertFalse(g.state.battlecry_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_one_and_two_actual_options_keep_only_available_original_cards(self):
        for members in ((A,), (A,B)):
            g = self.game(members=members); self.play(g); offered,_ = self.pick(g)
            self.assertEqual(len(offered),len(members)); self.assertEqual(set(self.kept(g)),set(members))
            self.assertEqual(self.bank(g),0)

    def test_empty_complete_pool_has_no_choice_no_spend_or_extra_rng(self):
        g = self.game(members=()); rng = g._rng.getstate(); self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.card_discovery_history)
        self.assertEqual(self.bank(g),5); self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.players[1].mana,17)

    def test_full_hand_keeps_selected_slot_and_burns_both_remainders_with_original_source(self):
        g = self.game(hand=(PALEOMANCY,)+(FILLER,)*9); source = self.play(g); _,chosen = self.pick(g)
        self.assertEqual(len(g.state.players[1].hand),10); self.assertEqual(self.kept(g),[chosen])
        burns = [e for e in g.events if e.kind=='card_burned']
        self.assertEqual(len(burns),2); self.assertTrue(all(e.source_id==source for e in burns))
        self.assertEqual(self.bank(g),0)

    def test_unknown_eligible_content_fails_before_rng_even_at_full_hand(self):
        for hand in ((PALEOMANCY,), (PALEOMANCY,)+(FILLER,)*9):
            g = self.game(members=(A,UNKNOWN),hand=hand); saved = g.snapshot()
            with patch.object(Random,'randrange',side_effect=AssertionError('Unknown candidate cropped')):
                with self.assertRaises(ResolutionError): self.play(g)
            self.assertEqual(g.snapshot(),saved)

    def test_missing_host_pool_rolls_back_mana_bank_and_entire_play(self):
        g = self.game(pool=False); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_original_offer_wait_roundtrip_preserves_menu_bank_and_random_state(self):
        g = self.game(); self.play(g); offered = tuple(o.card_id for o in g.state.pending_choice.options)
        other = self.portable(g); self.assertEqual(self.bank(g),5)
        for h in (g,other): self.pick(h,2)
        self.assertEqual(g.snapshot(),other.snapshot()); self.assertEqual(set(self.kept(g)),set(offered))

    def test_first_creation_wait_keeps_two_owed_original_cards_without_repaying(self):
        g = self.game(mode='wait'); self.play(g); offered,chosen = self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.kept(g),[chosen])
        self.assertEqual(self.bank(g),0); other = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in (g,other): self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot()); self.assertEqual(set(self.kept(g)),set(offered))
        self.assertEqual(len(g.state.corpse_spend_history),1); self.portable(g)

    def test_resource_spend_wait_occurs_before_first_creation_and_resumes_original_branch(self):
        g = self.game(mode='corpse-wait'); self.play(g); offered,_ = self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.bank(g),0)
        self.assertFalse(self.kept(g)); other = self.portable(g)
        for h in (g,other): self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot()); self.assertEqual(set(self.kept(g)),set(offered))
        self.assertEqual(len(g.state.corpse_spend_history),1)

    def test_failed_first_creation_reaction_restores_original_unpaid_choice(self):
        g = self.game(mode='fail'); self.play(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(),saved); self.assertEqual(self.bank(g),5)
        self.assertFalse(g.state.corpse_spend_history)

    def test_creation_gain_does_not_recompute_the_already_selected_resource_branch(self):
        for bank, expected, count in ((0,10,1),(5,10,3)):
            g = self.game(bank=bank,mode='gain'); self.play(g); self.pick(g)
            self.assertEqual((self.bank(g),len(self.kept(g))), (expected,count))

    def test_nested_actual_discovery_groups_keep_separate_debits_and_complete_deliveries(self):
        g = self.game(bank=10,mode='nested'); self.play(g); self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual((self.bank(g),len(self.kept(g))),(5,1))
        other = self.portable(g)
        for h in (g,other): self.pick(h)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((self.bank(g),len(self.kept(g)),len(g.state.card_discovery_history)),(0,6,2))
        self.assertEqual([r.amount for r in g.state.corpse_spend_history],[5,5]); self.portable(g)

    def test_existing_retry_pipeline_retires_old_keep_and_corpse_diagnostic_events(self):
        g = self.game(hand=(P+'rewind',)); self.play(g,P+'rewind'); self.pick(g); self.portable(g)
        self.choose(g,'retry')
        self.assertEqual((self.bank(g),len(self.kept(g)),len(g.state.corpse_spend_history)),(5,0,0))
        self.portable(g); self.pick(g)
        self.assertEqual((self.bank(g),len(self.kept(g)),len(g.state.corpse_spend_history)),(0,3,1)); self.portable(g)

    def test_payment_reaction_wait_cannot_drop_the_owed_first_creation(self):
        g = self.game(mode='corpse-wait'); self.play(g); self.pick(g); self.assertFalse(self.kept(g))
        bad = g.clone(); frame = bad._frame
        self.assertTrue(any(type(w)is KeepPoolDiscovery for w in (*frame.prefix,*frame.continuation)))
        bad._frame = replace(frame,prefix=tuple(w for w in frame.prefix if type(w)is not KeepPoolDiscovery),
            continuation=tuple(w for w in frame.continuation if type(w)is not KeepPoolDiscovery))
        self.reject(bad.snapshot())

    def test_automatic_cast_uses_same_offer_and_corpse_branch_without_extra_hand_payment(self):
        g = self.game(hand=(P+'auto',)); self.play(g,P+'auto'); self.pick(g)
        self.assertEqual((self.bank(g),len(self.kept(g)),g.state.players[1].mana),(0,3,20))
        self.assertEqual([p.card_id for p in g.state.play_history],[P+'auto']); self.portable(g)

    def test_opponent_cannot_read_selected_or_kept_card_faces_or_original_menu(self):
        g = self.game(); self.play(g); self.pick(g)
        text = json.dumps(g.for_player(2).observe()) + json.dumps(g.player_events(2))
        for cid in (A,B,C,D): self.assertNotIn(cid,text)

    def test_restore_rejects_dropped_owed_kept_card_and_changed_cost(self):
        g = self.game(mode='wait'); self.play(g); self.pick(g)
        bad = g.clone(); frame = bad._frame; removed = False
        def clip(queue):
            nonlocal removed
            out = []
            for work in queue:
                if not removed and type(work)is KeepPoolDiscovery: removed = True
                else: out.append(work)
            return tuple(out)
        prefix,continuation = clip(frame.prefix),clip(frame.continuation)
        self.assertTrue(removed)
        bad._frame = replace(frame,prefix=prefix,continuation=continuation)
        self.reject(bad.snapshot())
        saved = deepcopy(g.snapshot()); changed = False
        def change(value):
            nonlocal changed
            if isinstance(value,dict):
                if not changed and 'keep_all_corpse_cost'in value:
                    value['keep_all_corpse_cost']=0; changed=True; return
                for v in value.values(): change(v)
            elif isinstance(value,list):
                for v in value: change(v)
        change(saved); self.assertTrue(changed); self.reject(saved)

    def test_old_schema_and_lossy_hand_followup_wrapper_reject_new_declaration(self):
        g = self.game(); self.play(g); saved = g.snapshot(); saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved,registry(*self.config))
        spec = DiscoverFromPool(1,POOL_ID,QUERY,source_id=g.state.cast_history[-1].source_id,keep_all_corpse_cost=5)
        with self.assertRaises(ValueError): DiscoverForPlayFollowup(spec)
        with self.assertRaises(ValueError): replace(spec,keep_all_corpse_cost=True)
        with self.assertRaises(ValueError): replace(spec,destination='board')


if __name__ == '__main__': unittest.main()
