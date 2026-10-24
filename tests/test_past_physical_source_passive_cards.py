"""Real passive entry points over physical deck and native hand lifetimes."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_physical_source_passive_cards import (
    PATCHES, CHAMELEOS, ZERUS, DEPENDENCIES, POOL_ID, PREFIX, load_batch,
    register_past_physical_source_passive_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayerSetup, Rarity, Registry, Scenario, TriggerSpec, Zone)
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.defining_hand_copies import TransformDefiningHandCardFromHand
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior, RequestChoice,
    Summon, Destroy)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, Keyword
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, ModifyStoredCost, MoveCard

P = 'k487.'
HERO, A, B, PIRATE, ALL, SPELL, WEAPON, LOCATION, HERO_CARD, POWER, WATCH = (
    P+x for x in ('hero', 'a', 'b', 'pirate', 'all', 'spell', 'weapon', 'location', 'hero_card', 'power', 'watch'))
META = CardMetadata(collectible=True, classes=(CardClass.MAGE,), rarity=Rarity.COMMON, tribes=())
CTX = GenerationContext('k487-explicit-complete-fixture', 'experimental')


def native(entity):
    return next((a for a in entity.abilities if a.kind == 'defining_hand_source'), None)


@lru_cache(None)
def registry(mode='normal', role='writer'):
    r = Registry(P+mode)
    register_past_physical_source_passive_cards(r)
    r.register_behavior(P+'marker', lambda c: (GainArmor(c.player_id, 4),))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100,
        metadata=META, initial_hero_power=POWER))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, on_use=P+'marker'))
    for card in (
        CardDefinition(A, A, CardType.MINION, cost=2, attack=2, health=3, metadata=META),
        CardDefinition(B, B, CardType.MINION, cost=5, attack=4, health=5, metadata=META),
        CardDefinition(PIRATE, PIRATE, CardType.MINION, cost=1, attack=1, health=2,
            metadata=replace(META, tribes=('pirate',)), battlecry=P+'morph' if mode=='played_morph' else None),
        CardDefinition(ALL, ALL, CardType.MINION, cost=1, attack=1, health=2,
            metadata=replace(META, tribes=('all',))),
        CardDefinition(SPELL, SPELL, CardType.SPELL, cost=2, on_play=P+'marker', metadata=META),
        CardDefinition(WEAPON, WEAPON, CardType.WEAPON, cost=2, attack=2, durability=3, metadata=META),
        CardDefinition(LOCATION, LOCATION, CardType.LOCATION, cost=2, durability=2,
            on_use=P+'marker', metadata=META),
        CardDefinition(HERO_CARD, HERO_CARD, CardType.HERO, cost=2, health=30,
            hero_card=True, initial_hero_power=POWER, hero_armor=5, metadata=META),
    ):
        r.register_card(card)
    from hs_sim.engine.sacrifice import MinionReference
    from hs_sim.engine.cross_zone import TransformCapturedMinion
    r.register_behavior(P+'morph', lambda c: (TransformCapturedMinion(
        MinionReference.capture(c.source), A, c.source_id),))

    def enemy(c):
        return c.state.entities[c.state.players[3-c.player_id].hand[0]]

    def enhance(c):
        ref = CardReference.capture(enemy(c))
        return (BuffStoredCard(ref, 3, 4, c.source_id),
            ModifyStoredCost(ref, CostSpec(set_to=0), c.source_id))

    scripts = {
        'enhance': enhance,
        'swap': lambda c: (TransformStoredCard(CardReference.capture(enemy(c)), WEAPON, c.source_id),),
        'steal': lambda c: (MoveCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[3-c.player_id].hand if native(c.state.entities[i]))),
            c.player_id, Zone.HAND, source_id=c.source_id),),
        'external': lambda c: (TransformStoredCard(CardReference.capture(c.state.entities[
            next(i for i in c.state.players[c.player_id].hand if native(c.state.entities[i]))]), A, c.source_id),),
        'summon': lambda c: (Summon(c.player_id, PIRATE, c.source_id),),
        'kill': lambda c: (Destroy(c.state.players[c.player_id].board[0], c.source_id),),
        'discount_deck': lambda c: (BuffStoredCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==PATCHES)), 2, 3, c.source_id),),
    }
    for key, body in scripts.items():
        r.register_behavior(P+key, body)
        r.register_card(CardDefinition(P+key, key, CardType.SPELL, on_play=P+key))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K487 deliberate failure')))
    original = r.behavior(PREFIX+'shift')
    def shift(c):
        work = original(c)
        if mode=='before_wait':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue', work),), c.source_id),)
        if mode=='after_wait':
            return (*work, RequestChoice(c.player_id, (
                ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id))
        if mode=='fail':
            return (*work, InvokeBehavior(P+'fail', c.source_id, c.player_id))
        return work
    r._behaviors[PREFIX+'shift'] = shift
    def watch(c):
        if c.event.target_id==c.source_id:
            return ()
        e = c.state.entities[c.event.target_id]
        if e.card_id==PATCHES:
            return (RequestChoice(c.player_id, (ChoiceOption('continue','Continue'),), c.source_id),)
        return ()
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=10,
        triggers=(TriggerSpec('minion_summoned', P+'watch'),)))
    for cid in (A, B):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    members = [PoolMember(A), PoolMember(B)]
    if mode=='unknown':
        r.register_pool_card(PoolCard(P+'unknown', CardType.MINION, 2, META))
        members.append(PoolMember(P+'unknown'))
    if mode=='self':
        members = [PoolMember(ZERUS)]
    if mode=='empty':
        members = []
    r.register_pool(PoolDefinition(POOL_ID, P+'full-fixture', CTX.target_id, CTX.mode,
        tuple(members), complete=True))
    r.validate()
    return r


def rehash(snapshot):
    snapshot['events_hash'] = canonical_hash(snapshot['events'])
    snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return snapshot


class PastPhysicalSourcePassiveTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)

    def game(self, hand=(), *, deck=(), board=(), enemy_hand=(), enemy_deck=(), enemy_board=(),
            mode='normal', active=1, seed=487):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=tuple(hand), deck=tuple(deck), board=tuple(board), mana=10, max_mana=10),
            PlayerSetup(HERO, hand=tuple(enemy_hand), deck=tuple(enemy_deck), board=tuple(enemy_board), mana=10,max_mana=10)),
            seed=seed, active_player=active, generation_context=CTX), registry(mode))

    def cycle(self,g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def test_complete_three_raw_rows_and_six_full_primary_faces(self):
        d=load_batch()
        self.assertEqual(tuple(x['record']['id'] for x in d['dependencies']), DEPENDENCIES)
        self.assertEqual(len(d['official_observations']),6)
        for item in d['dependencies']:
            raw=item['record'];faces=[x['face']for x in d['official_observations']if x['card_id']==raw['id']]
            self.assertEqual(len(faces),2)
            self.assertTrue(all((x['manaCost'],x['attack'],x['health'])==(1,1,1)for x in faces))
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        self.assertEqual(registry().card(PATCHES).keywords,())

    def test_patches_moves_original_deck_entity_after_completed_pirate_play(self):
        g=self.game((PIRATE,),deck=(PATCHES,));original=self.entity(g,PATCHES,zone='deck')
        self.play(g,PIRATE)
        moved=self.entity(g,PATCHES,zone='board')
        self.assertEqual((moved.id,moved.owner,moved.controller),(original.id,1,1))
        self.assertEqual(g.state.players[1].deck,[])
        self.assertEqual(len(g.state.play_history),1)
        self.assertNotIn(Keyword.CHARGE,moved.keywords)
        self.assertLess(next(e.sequence for e in g.events if e.kind=='card_played'),
            next(e.sequence for e in g.events if e.kind=='minion_summoned'and e.target_id==moved.id))
        self.portable(g)

    def test_patches_retains_original_forward_movement_material(self):
        g=self.game((P+'discount_deck',PIRATE),deck=(PATCHES,));self.play(g,P+'discount_deck')
        self.play(g,PIRATE);e=self.entity(g,PATCHES,zone='board');self.assertEqual((e.attack,e.max_health),(3,4))

    def test_patches_in_hand_never_borrows_its_deck_listener(self):
        g=self.game((PATCHES,PIRATE));self.play(g,PIRATE)
        self.assertEqual(self.entity(g,PATCHES).zone,Zone.HAND)

    def test_opponent_play_and_non_pirate_play_are_excluded(self):
        g=self.game((A,),deck=(PATCHES,),enemy_hand=(PIRATE,));self.play(g,A)
        self.assertEqual(self.entity(g,PATCHES,zone='deck').zone,Zone.DECK)
        g.apply(EndTurn(1));self.play(g,PIRATE,player=2)
        self.assertEqual(self.entity(g,PATCHES,zone='deck').zone,Zone.DECK)

    def test_pirate_summon_does_not_count_as_play(self):
        g=self.game((P+'summon',),deck=(PATCHES,));self.play(g,P+'summon')
        self.assertEqual(self.entity(g,PATCHES,zone='deck').zone,Zone.DECK)

    def test_two_physical_deck_sources_each_move_once_without_chain_play(self):
        g=self.game((PIRATE,),deck=(PATCHES,PATCHES));ids=tuple(g.state.players[1].deck);self.play(g,PIRATE)
        self.assertTrue(set(ids)<=set(g.state.players[1].board));self.assertEqual(len(g.state.play_history),1)

    def test_full_board_keeps_deck_source_for_a_later_real_pirate(self):
        g=self.game((PIRATE,PIRATE,P+'kill',P+'kill'),deck=(PATCHES,),board=(A,)*6)
        self.play(g,PIRATE);self.assertEqual(self.entity(g,PATCHES,zone='deck').zone,Zone.DECK)
        self.play(g,P+'kill');self.play(g,P+'kill');self.play(g,PIRATE)
        self.assertEqual(self.entity(g,PATCHES,zone='board').zone,Zone.BOARD)

    def test_patches_uses_frozen_played_tribe_after_battlecry_changed_face(self):
        g=self.game((PIRATE,),deck=(PATCHES,),mode='played_morph');self.play(g,PIRATE)
        self.assertEqual(self.entity(g,PATCHES,zone='board').zone,Zone.BOARD)
        self.assertEqual(g.state.play_history[0].card_id,PIRATE)
        self.assertEqual(g.state.entities[g.state.play_history[0].source_id].card_id,A)

    def test_all_tribes_native_play_qualifies_as_pirate(self):
        g=self.game((ALL,),deck=(PATCHES,));self.play(g,ALL)
        self.assertEqual(self.entity(g,PATCHES,zone='board').zone,Zone.BOARD)

    def test_patches_summon_wait_restores_original_delivery_once(self):
        g=self.game((PIRATE,),deck=(PATCHES,),board=(WATCH,));original=self.entity(g,PATCHES,zone='deck').id
        self.play(g,PIRATE);self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.players[1].board.count(original),1)

    def test_zerus_changes_each_owner_start_without_new_hand_entry(self):
        g=self.game((ZERUS,));original=self.entity(g,ZERUS);old=native(original)
        for turn in range(1,4):
            self.cycle(g);e=g.state.entities[original.id]
            self.assertIn(e.card_id,(A,B));self.assertEqual(e.hand_entry_id,original.hand_entry_id)
            self.assertEqual((native(e).id,native(e).defining_card_id,native(e).progress_completions),(old.id,ZERUS,turn))
        self.assertFalse(g.state.play_history);self.portable(g)

    def test_zerus_retains_the_same_source_when_randomly_returning_to_zerus(self):
        g=self.game((ZERUS,),mode='self');eid=self.entity(g,ZERUS).id;self.cycle(g);self.cycle(g)
        e=g.state.entities[eid];self.assertEqual(e.card_id,ZERUS)
        self.assertEqual(len([a for a in e.abilities if a.kind=='defining_hand_source']),1)
        self.assertEqual(native(e).progress_completions,2)

    def test_zerus_unknown_eligible_candidate_fails_before_rng_and_rolls_back(self):
        g=self.game((ZERUS,),mode='unknown');g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),before)

    def test_zerus_empty_pool_does_not_draw_rng(self):
        g=self.game((ZERUS,),mode='empty');before=g.snapshot()['rng_state'];self.cycle(g)
        self.assertEqual(self.entity(g,ZERUS).card_id,ZERUS);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_real_launch_format_keeps_all_unimplemented_minion_candidates_explicit(self):
        from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
        fmt=build_cn37_launch_candidate_format()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(ZERUS,)),
            PlayerSetup('HERO_08')),generation_context=fmt.context),fmt.registry)
        g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:g.apply(EndTurn(2))
        self.assertTrue(any(cid in str(caught.exception)for cid in ('BE_009','BE_327','BE_588')))
        self.assertEqual(g.snapshot(),before)

    def test_chameleos_copies_all_five_actual_hand_types_and_keeps_native_source(self):
        for cid in (A,SPELL,WEAPON,LOCATION,HERO_CARD):
            with self.subTest(face=cid):
                g=self.game((CHAMELEOS,),enemy_hand=(cid,));e=self.entity(g,CHAMELEOS);binding=native(e)
                self.cycle(g);new=g.state.entities[e.id]
                self.assertEqual((new.card_id,new.kind),(cid,g.registry.card(cid).kind))
                self.assertEqual((new.id,new.hand_entry_id,new.owner,new.controller),(e.id,e.hand_entry_id,1,1))
                self.assertEqual((native(new).id,native(new).defining_card_id),(binding.id,CHAMELEOS))
                self.assertEqual(len(g.state.players[2].hand),1)

    def test_chameleos_keeps_shifting_after_a_spell_then_a_weapon_face(self):
        g=self.game((CHAMELEOS,P+'swap'),enemy_hand=(SPELL,));eid=self.entity(g,CHAMELEOS).id
        self.cycle(g);self.assertEqual(g.state.entities[eid].card_id,SPELL)
        self.play(g,P+'swap');self.cycle(g)
        self.assertEqual(g.state.entities[eid].card_id,WEAPON);self.assertEqual(native(g.state.entities[eid]).progress_completions,2)
        self.portable(g)

    def test_chameleos_uses_current_opponent_local_stats_and_cost(self):
        g=self.game((CHAMELEOS,P+'enhance'),enemy_hand=(A,));self.play(g,P+'enhance');self.cycle(g)
        from hs_sim.engine.costs import local_cost
        e=self.entity(g,A);self.assertEqual((e.attack,e.max_health,local_cost(e)[0]),(5,7,0))
        self.assertFalse(any(x.kind=='card_created'and x.target_id==e.id for x in g.events))
        self.play(g,A);self.assertEqual(self.entity(g,A,zone='board').attack,5)

    def test_chameleos_spell_hero_and_location_faces_are_really_playable(self):
        for cid in (SPELL,HERO_CARD,LOCATION):
            with self.subTest(face=cid):
                g=self.game((CHAMELEOS,),enemy_hand=(cid,));self.cycle(g);eid=self.entity(g,cid).id
                self.play(g,cid);self.assertIsNone(native(g.state.entities[eid]))
                if cid==SPELL:self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4)
                elif cid==HERO_CARD:self.assertEqual(g.state.players[1].hero_id,eid)
                else:self.assertIn(eid,g.state.players[1].board)

    def test_empty_opponent_hand_keeps_current_face_without_rng(self):
        g=self.game((CHAMELEOS,));before=g.snapshot()['rng_state'];self.cycle(g)
        self.assertEqual(self.entity(g,CHAMELEOS).card_id,CHAMELEOS)
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_chameleos_sampled_shifter_keeps_only_its_own_native_source(self):
        g=self.game((CHAMELEOS,),enemy_hand=(ZERUS,),active=2);eid=self.entity(g,CHAMELEOS).id
        g.apply(EndTurn(2));e=g.state.entities[eid]
        self.assertEqual(e.card_id,ZERUS);self.assertEqual(native(e).defining_card_id,CHAMELEOS)
        self.assertEqual(len([a for a in e.abilities if a.kind=='defining_hand_source']),1)

    def test_transferred_spell_face_rearms_original_source_for_its_new_holder(self):
        g=self.game((CHAMELEOS,A),enemy_hand=(SPELL,P+'steal'));eid=self.entity(g,CHAMELEOS).id
        self.cycle(g);old=native(g.state.entities[eid]);self.assertEqual(g.state.entities[eid].kind,CardType.SPELL)
        g.apply(EndTurn(1));self.play(g,P+'steal',player=2);e=g.state.entities[eid]
        self.assertEqual((e.owner,e.controller),(1,2));self.assertNotEqual(native(e).id,old.id)
        self.assertEqual(native(e).progress_keys,())
        g.apply(EndTurn(2));g.apply(EndTurn(1));e=g.state.entities[eid]
        self.assertEqual((e.card_id,native(e).defining_card_id,native(e).progress_completions),(A,CHAMELEOS,1))
        self.portable(g)

    def test_external_transform_retires_original_source(self):
        g=self.game((CHAMELEOS,P+'external'),enemy_hand=(SPELL,));eid=self.entity(g,CHAMELEOS).id
        self.play(g,P+'external');self.assertIsNone(native(g.state.entities[eid]));self.cycle(g)
        self.assertEqual(g.state.entities[eid].card_id,A)

    def test_native_request_wait_restores_before_rng_then_executes_once(self):
        g=self.game((CHAMELEOS,),enemy_hand=(A,B),mode='before_wait');self.cycle(g)
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()['rng_state'];restored=self.portable(g)
        self.assertEqual(self.entity(g,CHAMELEOS).card_id,CHAMELEOS)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertNotEqual(g.snapshot()['rng_state'],before)

    def test_after_transform_wait_restores_and_later_failure_rolls_back_choice(self):
        g=self.game((CHAMELEOS,),enemy_hand=(SPELL,),mode='after_wait');self.cycle(g)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_late_failure_rolls_back_whole_turn_face_source_and_rng(self):
        for cid in (ZERUS,CHAMELEOS):
            with self.subTest(card=cid):
                g=self.game((cid,),enemy_hand=(A,B),mode='fail');g.apply(EndTurn(1));before=g.snapshot()
                with self.assertRaises(ResolutionError):g.apply(EndTurn(2))
                self.assertEqual(g.snapshot(),before)

    def test_rehashed_borrowed_pending_native_source_is_rejected(self):
        g=self.game((CHAMELEOS,),enemy_hand=(A,),mode='before_wait');self.cycle(g);saved=g.snapshot()
        def corrupt(value):
            if isinstance(value,dict):
                if 'source_ability_id'in value and 'defining_card_id'in value:
                    value['source_ability_id']+=1;return True
                return any(corrupt(x)for x in value.values())
            return isinstance(value,list)and any(corrupt(x)for x in value)
        tampered=deepcopy(saved);self.assertTrue(corrupt(tampered['resolution_frame']))
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(tampered),registry('before_wait','tampered'))

    def test_native_source_and_opponent_physical_selection_are_private(self):
        g=self.game((CHAMELEOS,),enemy_hand=(A,B));self.cycle(g)
        for player in (1,2):
            text=json.dumps(g.for_player(player).observe())
            for field in ('defining_card_id','source_ability_id','progress_keys','rng_state'):
                self.assertNotIn('"'+field+'"',text)
