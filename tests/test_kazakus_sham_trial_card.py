"""Native Godfather manufacture, spell recipes and real countdown payloads."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
from itertools import combinations
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.kazakus_sham_trial_card import CARD, VOIDLORD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Ruleset, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.sham_trials import (CREATED, END, INSTALLED, OFFER, PREFIX, START, STEP,
    ShamTrialRecipe, checked_recipe, recipe_from_id)
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from test_current_deck_empty_basics import rehash
from tools.card_batch import check_face

P = 'fixture.sham_trial.'
UNIT, ENEMY, SPELL, WATCH, HURT, KILL, TRIGGER = (P+x for x in ('unit', 'enemy', 'spell', 'watch', 'hurt', 'kill', 'trigger'))
FRAIL = P+'frail'
CTX = GenerationContext('sham-trial-explicit-complete-experiment', 'experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r = build_registry()
    r.register_card(CardDefinition(UNIT, 'Explicit three-cost minion', CardType.MINION,
        cost=3, attack=1, health=20, metadata=metadata()))
    r.register_card(CardDefinition(ENEMY, 'Explicit opposing minion', CardType.MINION,
        cost=3, attack=1, health=20, metadata=metadata()))
    r.register_card(CardDefinition(SPELL, 'Explicit ordinary spell', CardType.SPELL, cost=3))
    r.register_card(CardDefinition(FRAIL, 'Explicit fragile combatant', CardType.MINION, attack=1, health=1))
    def fail(c): raise ResolutionError('Explicit sham trial observer failure')
    def watch(c):
        event = c.event
        entity = c.state.entities.get(event.target_id)
        if mode in ('wait_creation', 'fail_creation') and event.kind == 'card_added_to_hand' and entity is not None and entity.card_id.startswith(PREFIX):
            if mode == 'fail_creation': raise ResolutionError('Explicit sham trial creation failure')
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, 1),))), c.source_id),)
        if mode in ('wait_component', 'fail_component') and event.kind == 'card_drawn' and event.source_id is not None and c.state.entities[event.source_id].card_id.startswith(PREFIX):
            if mode == 'fail_component': raise ResolutionError('Explicit sham trial draw failure')
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),)
        if mode == 'kill_root' and event.kind == 'choice_selected' and event.source_id is not None:
            source = c.state.entities[event.source_id]
            if source.card_id == CARD and source.zone == Zone.BOARD: return (Destroy(source.id, c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    from hs_sim.engine.model import TriggerSpec
    r.register_card(CardDefinition(WATCH, 'Explicit observer', CardType.MINION, health=20,
        triggers=tuple(TriggerSpec(event, P+'watch') for event in ('card_added_to_hand', 'card_drawn', 'choice_selected'))))
    r.register_behavior(P+'hurt', lambda c: (Damage(c.state.players[c.player_id].hero_id, 10, c.source_id),))
    r.register_behavior(P+'kill', lambda c: (Destroy(next(eid for eid in c.state.players[c.player_id].board
        if c.state.entities[eid].card_id == VOIDLORD), c.source_id),))
    def trigger(c):
        entity = next(c.state.entities[eid] for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == CARD)
        return (TriggerBattlecry(MinionReference.capture(entity), c.source_id),)
    r.register_behavior(P+'trigger', trigger)
    r.register_card(CardDefinition(HURT, 'Explicit self damage', CardType.SPELL, on_play=P+'hurt'))
    r.register_card(CardDefinition(KILL, 'Explicit Voidlord destruction', CardType.SPELL, on_play=P+'kill'))
    r.register_card(CardDefinition(TRIGGER, 'Explicit Battlecry trigger', CardType.MINION, health=1, battlecry=P+'trigger'))
    r.register_pool_card(PoolCard.from_definition(r.card(UNIT)))
    r.register_pool(PoolDefinition('constructed.minions', 'sham-trial-experiment-v1', CTX.target_id, CTX.mode,
        (PoolMember(UNIT),), complete=True))
    r.validate()
    return r


def recipe(a, b, cost=7):
    profile = fixture()._sham_trial_profiles[CARD]
    parts = sorted(('CAP_405t'+str(a), 'CAP_405t'+str(b)), key=profile.component_ids.index)
    tier = next(t for t in profile.tiers if fixture().card(t.template_card_id).cost == cost)
    return ShamTrialRecipe(tier.template_card_id, *parts).card_id


def craft_seed(first, second):
    ids = fixture()._sham_trial_profiles[CARD].component_ids
    for seed in range(10000):
        rng = Random(seed)
        if first in rng.sample(ids, 3) and second in rng.sample(tuple(c for c in ids if c != first), 3): return seed
    raise AssertionError('No seed for native full-domain craft coverage')


class KazakusShamTrialTests(unittest.TestCase):
    def game(self, hand=(), *, board=(), enemy=(), enemy_hand=(), mode='normal', seed=321, context=CTX):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_07', hand=hand, board=((WATCH,) if mode != 'normal' else ())+board,
                deck=(UNIT,)*12, mana=10, max_mana=10),
            PlayerSetup('HERO_07', hand=enemy_hand, board=enemy, deck=(UNIT,)*12, mana=10, max_mana=10)),
            seed=seed, generation_context=context), fixture(mode))
    def eid(self, g, cid, player=1, zone='hand'):
        return next(eid for eid in getattr(g.state.players[player], zone) if g.state.entities[eid].card_id == cid)
    def play(self, g, cid):
        eid = self.eid(g, cid); g.apply(PlayCard(1, eid)); return eid
    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture.__wrapped__(mode)
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        return saved
    def manufacture(self, cost=7, *, mode='normal'):
        first, second = 'CAP_405t5', 'CAP_405t2'
        g = self.game((CARD,), enemy=(ENEMY,), mode=mode, seed=craft_seed(first, second))
        source = self.play(g, CARD); self.choose(g, first); self.choose(g, second)
        tier = next(t for t in fixture()._sham_trial_profiles[CARD].tiers if fixture().card(t.template_card_id).cost == cost)
        self.choose(g, tier.choice_card_id)
        return g, source, recipe(5, 2, cost)
    def end(self, g): g.apply(EndTurn(g.state.active_player))

    def test_complete_original_records_and_primary_display_exceptions_are_pinned(self):
        data = load_batch(); raw = {v['record']['id']:v['record'] for key in
            ('cards','dependencies','choice_only','existing_dependencies','evidence_only') for v in data[key]}
        self.assertEqual(len(raw), 19); self.assertEqual(len(data['official_observations']), 32)
        self.assertEqual(raw['CAP_405t1']['name'], '')
        self.assertEqual(fixture().card('CAP_405t1').name, raw['CAP_405t1']['name_en'])
        for obs in data['official_observations']:
            check_face(raw[obs['card_id']], obs['face'], obs['locale'], obs['display_normalizations'],
                numeric_normalizations=obs['numeric_normalizations'])
            body = json.loads(obs['full_response'])
            self.assertEqual(next(c for c in body['cards'] if c['id']==raw[obs['card_id']]['dbf_id']), obs['face'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertEqual(canonical_digest(asdict(fixture().card(VOIDLORD))), data['existing_definition_pins'][VOIDLORD])

    def test_108_native_recipes_and_countdowns_are_pure_immutable_definitions(self):
        r = fixture(); profile = r._sham_trial_profiles[CARD]; before=(len(r.cards), len(r.player_effects), r.fingerprint())
        count=0
        for a,b in combinations(profile.component_ids, 2):
            for tier in profile.tiers:
                value=ShamTrialRecipe(tier.template_card_id,a,b); face=r.card(value.card_id); count+=1
                self.assertEqual(recipe_from_id(value.card_id),value)
                self.assertTrue(face.manual_playable); self.assertIsNone(face.targeting)
                self.assertEqual(face.ongoing_effect_id is not None, bool(tier.owner_starts))
                if tier.owner_starts:
                    spec=r.player_effect(value.card_id)
                    self.assertEqual((spec.duration,spec.tick_event,spec.card_id),(tier.owner_starts,'turn_started',value.card_id))
        self.assertEqual(count,108); self.assertEqual((len(r.cards),len(r.player_effects),r.fingerprint()),before)

    def test_original_display_exceptions_reject_changed_rules_and_unpinned_localization(self):
        data=load_batch();raw={r['record']['id']:r['record']for key in ('cards','dependencies','choice_only','existing_dependencies')for r in data[key]}
        for cid in ('CAP_405t1','CAP_405tb1','CAP_405tb2','CAP_405tb3'):
            obs=next(o for o in data['official_observations']if o['card_id']==cid and o['locale']=='zh_CN')
            changed=deepcopy(raw[cid]);changed['text_en']+=' Draw 99 cards.'
            with self.subTest(cid=cid),self.assertRaises(ValueError):
                check_face(changed,obs['face'],obs['locale'],obs['display_normalizations'],numeric_normalizations=obs['numeric_normalizations'])

    def test_unknown_reversed_duplicate_and_noncanonical_recipes_reject(self):
        cid=recipe(3,4); value=recipe_from_id(cid)
        for bad in (cid+'=',ShamTrialRecipe(value.template_card_id,value.second_card_id,value.first_card_id).card_id,
                ShamTrialRecipe(value.template_card_id,value.first_card_id,'missing.actual.trial').card_id):
            with self.subTest(bad=bad),self.assertRaises(ValueError):fixture().card(bad)
        with self.assertRaises(ValueError):ShamTrialRecipe(value.template_card_id,value.first_card_id,value.first_card_id).card_id
        with self.assertRaises(ValueError):fixture().player_effect(cid)

    def test_actual_three_stage_manufacture_keeps_one_original_payment_and_native_order(self):
        for cost in (0,4,7):
            with self.subTest(cost=cost):
                g,source,cid=self.manufacture(cost); self.assertEqual(g.state.players[1].mana,7)
                self.assertEqual(len([e for e in g.events if e.kind==OFFER]),3)
                self.assertEqual(len([e for e in g.events if e.kind==CREATED]),1)
                self.assertEqual(recipe_from_id(cid).parts,('CAP_405t2','CAP_405t5'))
                self.play(g,cid);self.assertEqual(g.state.players[1].mana,7-cost)
                self.assertEqual(len(g.state.cast_history),1)
                if cost==7:
                    self.assertEqual([dict(e.data)['component']for e in g.events if e.kind==STEP],['CAP_405t2','CAP_405t5'])
                    stolen=g.state.entities[self.eid(g,ENEMY,zone='board')]
                    self.assertEqual((stolen.attack,stolen.max_health),(4,23))
                    self.assertFalse(g.state.players[1].player_effects)
                else:self.assertEqual(len(g.state.players[1].player_effects),1)

    def test_waiting_all_three_original_menus_restore_without_rerolling(self):
        g=self.game((CARD,),seed=craft_seed('CAP_405t5','CAP_405t2')); self.play(g,CARD)
        for selection in ('CAP_405t5','CAP_405t2','CAP_405tb1b'):
            self.portable(g); self.choose(g,selection)
        self.assertEqual(len([e for e in g.events if e.kind==CREATED]),1)

    def test_original_manufacture_continues_after_source_dies(self):
        g,source,cid=self.manufacture(mode='kill_root')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertIn(self.eid(g,cid),g.state.players[1].hand);self.portable(g,'kill_root')

    def test_delayed_lengths_count_only_future_owner_starts_and_never_recast(self):
        for cost,turns in ((4,1),(0,4)):
            with self.subTest(cost=cost):
                cid=recipe(2,5,cost);g=self.game((cid,),enemy=(ENEMY,));self.play(g,cid)
                for index in range(turns):
                    self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,turns-index)
                    self.end(g);self.assertFalse(any(e.kind==START for e in g.events))
                    self.end(g)
                    if index+1<turns:self.assertFalse(any(e.kind==START for e in g.events))
                self.assertFalse(g.state.players[1].player_effects)
                self.assertEqual(len([e for e in g.events if e.kind==START]),1)
                self.assertEqual(len(g.state.cast_history),1)
                self.assertEqual(g.state.entities[self.eid(g,ENEMY,zone='board')].attack,4)

    def test_delayed_program_restores_after_tick_and_replays_complete_expiry(self):
        cid=recipe(2,5,0);g=self.game((cid,),enemy=(ENEMY,));self.play(g,cid)
        self.end(g);self.end(g);self.portable(g)
        for _ in range(6):self.end(g)
        self.assertEqual(len([e for e in g.events if e.kind==END]),1);self.portable(g)

    def test_actual_draw_then_hand_battlefield_buff_uses_original_component_order(self):
        cid=recipe(4,5);g=self.game((cid,),board=(UNIT,));self.play(g,cid)
        self.assertEqual(len(g.state.players[1].hand),3)
        for eid in (*g.state.players[1].hand,*g.state.players[1].board):
            self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(4,23))
        self.assertTrue(all(g.state.entities[eid].attack==1 for eid in g.state.players[1].deck))

    def test_original_hand_theft_moves_two_physical_cards_and_full_hand_burns_overflow(self):
        cid=recipe(3,8);g=self.game((cid,)+(UNIT,)*9,enemy_hand=(UNIT,SPELL,ENEMY))
        original=set(g.state.players[2].hand);self.play(g,cid)
        left=set(g.state.players[2].hand);stolen=original-left
        self.assertEqual(len(stolen),2);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(sum(g.state.entities[e].zone==Zone.HAND for e in stolen),1)
        self.assertEqual(sum(g.state.entities[e].zone==Zone.GRAVEYARD for e in stolen),1)
        self.assertTrue(all(g.state.entities[e].owner==2 for e in stolen))
        self.assertFalse(any(e.kind=='card_discarded'for e in g.events));self.portable(g)

    def test_pool_group_summons_three_plain_bodies_and_unknown_context_is_not_filtered(self):
        cid=recipe(6,8);g=self.game((cid,));self.play(g,cid)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],[UNIT]*3)
        self.assertEqual(len(g.state.pool_summon_history),1)
        bad=self.game((cid,),context=None);saved=bad.snapshot()
        with self.assertRaises(ResolutionError):self.play(bad,cid)
        self.assertEqual(bad.snapshot(),saved)

    def test_cost_reduction_applies_only_to_current_hand_minions(self):
        cid=recipe(7,8);g=self.game((cid,UNIT,SPELL));self.play(g,cid)
        self.assertEqual(g.state.entities[self.eid(g,UNIT)].cost,1)
        self.assertEqual(g.state.entities[self.eid(g,SPELL)].cost,3)
        self.assertTrue(all(g.state.entities[e].cost==3 for e in g.state.players[1].deck))

    def test_real_hero_healing_and_voidlord_original_deathrattle(self):
        cid=recipe(8,9);g=self.game((HURT,cid,KILL));self.play(g,HURT);self.play(g,cid)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        lord=g.state.entities[self.eid(g,VOIDLORD,zone='board')]
        self.assertEqual((lord.attack,lord.health),(3,9));self.assertIn(Keyword.TAUNT,lord.keywords)
        self.play(g,KILL)
        self.assertEqual(len(g.state.players[1].board),3)
        self.assertTrue(all((g.state.entities[e].attack,g.state.entities[e].health)==(1,3) and Keyword.TAUNT in g.state.entities[e].keywords for e in g.state.players[1].board))

    def test_forced_attacks_use_each_surviving_original_residence_once_and_no_hero(self):
        cid=recipe(1,8);g=self.game((cid,),board=(UNIT,UNIT),enemy=(ENEMY,ENEMY));original=set(g.state.players[1].board+g.state.players[2].board)
        self.play(g,cid)
        attacks=[e for e in g.events if e.kind=='random_choice'and dict(e.data).get('producer')=='each_minion_forced_attack']
        self.assertEqual(len(attacks),4);self.assertEqual({e.source_id for e in attacks},original)
        self.assertTrue(all(e.target_id in original and e.target_id!=e.source_id for e in attacks))
        self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_no_attacker_pair_has_no_combat_rng_draw(self):
        cid=recipe(1,8);g=self.game((cid,),board=(UNIT,));before=g.snapshot()['rng_state'];self.play(g,cid)
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertFalse(any(e.kind=='random_choice'and dict(e.data).get('producer')=='each_minion_forced_attack'for e in g.events))

    def test_each_forced_combat_finishes_deaths_before_selecting_the_next_original_attacker(self):
        cid=recipe(1,8);g=self.game((cid,),board=(FRAIL,),enemy=(FRAIL,))
        original=set(g.state.players[1].board+g.state.players[2].board);self.play(g,cid)
        self.assertTrue(all(g.state.entities[e].zone==Zone.GRAVEYARD for e in original))
        attacks=[e for e in g.events if e.kind=='random_choice'and dict(e.data).get('producer')=='each_minion_forced_attack']
        self.assertEqual(len(attacks),1);self.assertEqual(len([e for e in g.events if e.kind==END]),1)
        self.portable(g)

    def test_uninitialized_templates_and_nonphysical_choices_do_not_play_as_blank_spells(self):
        g=self.game(('CAP_405tb1',));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'CAP_405tb1')
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaisesRegex(ResolutionError,'Choice-only'):self.game(('CAP_405t1',))

    def test_shared_ongoing_area_capacity_rejects_before_spending_or_creating_a_program(self):
        capacity=min(Ruleset().max_ongoing_effects,Ruleset().max_secret_zone)
        cid=recipe(2,5,0);g=self.game((cid,)*(capacity+1))
        for _ in range(capacity):self.play(g,cid)
        self.assertEqual(len(g.state.players[1].player_effects),capacity);saved=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'area is full'):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)

    def test_repeated_indirect_battlecry_keeps_each_original_automatic_menu(self):
        g=self.game((TRIGGER,TRIGGER),board=(CARD,));self.play(g,TRIGGER);self.play(g,TRIGGER)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len([e for e in g.events if e.kind==CREATED]),2)
        self.assertEqual(len([e for e in g.events if e.kind=='battlecry_choice_randomized']),6)
        self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_delivery_wait_keeps_one_original_reward_and_failed_choice_rolls_back(self):
        g,source,cid=self.manufacture(mode='wait_creation');saved=self.portable(g,'wait_creation')
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok')
        self.assertEqual(len([e for e in g.events if e.kind==CREATED]),1)

    def test_creation_exception_restores_original_length_choice_and_rng(self):
        g=self.game((CARD,),mode='fail_creation',seed=craft_seed('CAP_405t5','CAP_405t2'))
        self.play(g,CARD);self.choose(g,'CAP_405t5');self.choose(g,'CAP_405t2');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'CAP_405tb1b')
        self.assertEqual(g.snapshot(),saved)

    def test_delayed_component_wait_restores_original_recipe_and_next_component(self):
        cid=recipe(4,5,4);g=self.game((cid,),mode='wait_component');self.play(g,cid);self.end(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait_component')
        while g.state.pending_choice is not None:self.choose(g,'ok')
        self.assertEqual(len([e for e in g.events if e.kind==END]),1)
        stats=[(g.state.entities[eid].attack,g.state.entities[eid].max_health)for eid in g.state.players[1].hand]
        self.assertEqual(stats.count((4,23)),3)
        self.assertEqual(stats.count((1,20)),1)  # Natural turn draw follows the expired trial and its buff.

    def test_component_exception_rolls_back_spell_payment_draws_rng_and_history(self):
        cid=recipe(4,5);g=self.game((cid,),mode='fail_component');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)

    def test_private_manufacture_and_hand_recipe_remain_hidden_until_public_activation(self):
        g,_,cid=self.manufacture(4)
        for player in (1,2):
            text=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for hidden in ('rng_before',OFFER,'profile_card_id','selection_sequence'):self.assertNotIn(hidden,text)
        own=next(p for p in g.observe(1)['players']if p['id']==1)['hand'];enemy=next(p for p in g.observe(2)['players']if p['id']==1)['hand']
        self.assertTrue(any(e.get('trial_recipe')for e in own));self.assertFalse(any(e.get('trial_recipe')for e in enemy))
        self.play(g,cid)
        for player in (1,2):self.assertIn('trial_recipe',json.dumps(g.observe(player)))

    def test_rehashed_cropped_domain_changed_prior_and_changed_program_reject(self):
        g=self.game((CARD,),seed=craft_seed('CAP_405t5','CAP_405t2'));self.play(g,CARD);saved=g.snapshot()
        bad=deepcopy(saved);event=next(e for e in bad['events']if e['kind']==OFFER);event['data']['candidates'].pop()
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())
        cid=recipe(2,5,0);g=self.game((cid,));self.play(g,cid);bad=g.snapshot()
        bad['state']['players']['1']['player_effects'][0]['spec_id']=recipe(2,8,0)
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_waiting_component_cursor_cannot_be_removed_duplicated_or_borrowed(self):
        cid=recipe(4,5);g=self.game((cid,),mode='wait_component');self.play(g,cid);saved=g.snapshot()
        def edit(value,mode):
            if isinstance(value,list):
                for index,row in enumerate(value):
                    if isinstance(row,dict)and row.get('type','').endswith('.ContinueShamTrial'):
                        if mode=='remove':value.pop(index)
                        elif mode=='duplicate':value.insert(index,deepcopy(row))
                        else:row['fields']['start_id']+=1
                        return True
                    if edit(row,mode):return True
            elif isinstance(value,dict):
                for row in value.values():
                    if edit(row,mode):return True
            return False
        for mode in ('remove','duplicate','borrow'):
            bad=deepcopy(saved);self.assertTrue(edit(bad,mode))
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('wait_component'))
