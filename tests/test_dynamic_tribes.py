"""Public tribe identity, captured references and shared attachment lifecycle."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, ChangeMinionTribes,
    Enchantment, Game, Keyword, MinionScope, PlayCard, PlayerSetup, PoolQuery, Rarity, Registry,
    Scenario, SelectChoice, TargetPredicateSpec, TribeChangeSpec, TribeState, Zone, EndTurn,
    has_any_tribe, minion_references, tribe_state)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, RevealHandCard,
    GainArmor, GrantKeyword, RandomDamage, RemoveEnchantment, RequestChoice,
    ReturnToHand, ShuffleIntoDeck, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import apply_change, tribe_changes


def meta(tribes):
    return CardMetadata(collectible=False, classes=(CardClass.NEUTRAL,), rarity=Rarity.COMMON, tribes=tribes)


def registry(work):
    r = Registry('dynamic-tribes-tests')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    for name, tribes in (('beast', ('beast',)), ('dragon', ('dragon',)), ('all', ('all',)), ('empty', ())):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=2, health=6, metadata=meta(tribes)))
    r.register_card(CardDefinition('unknown', 'Unknown', CardType.MINION, attack=2, health=6))
    r.register_card(CardDefinition('magnet', 'Magnet', CardType.MINION, cost=2, attack=1, health=1,
        keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',), metadata=meta(('mech',))))
    r.register_behavior('work', work)
    r.register_card(CardDefinition('work', 'Work', CardType.SPELL, cost=1, on_play='work'))
    return r


def game(work, *, board=('beast',), hand=('work',), deck=('beast',), enemy_hand=()):
    return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
        deck=deck, mana=10, max_mana=10), PlayerSetup('hero', hand=enemy_hand))), registry(work))


def change(entity, operation, tribes, source_id=None, **kwargs):
    reference = MinionReference.capture(entity) if entity.zone == Zone.BOARD else CardReference.capture(entity)
    return ChangeMinionTribes(reference, TribeChangeSpec(operation, tribes), source_id, **kwargs)


def play_work(g):
    source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'work')
    g.apply(PlayCard(1, source))


def rehash(snapshot):
    excluded = {'schema_version', 'events', 'events_hash', 'state_hash'}
    snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items() if k not in excluded})
    return snapshot


class DynamicTribeTests(unittest.TestCase):
    def assert_state(self, g, target, members, excluded=()):
        self.assertEqual(tribe_state(g.registry, g.state.entities[target]), TribeState(members, excluded))

    def roundtrip(self, g, work):
        snapshot = g.snapshot()
        for other in (Game.from_snapshot(snapshot, registry(work)), g.clone(), replay(build_replay(g), registry(work))):
            self.assertEqual(other.snapshot(), snapshot)
            for viewer in (1,2): self.assertEqual(other.for_player(viewer).observe(), g.for_player(viewer).observe())

    def test_specs_and_effects_reject_mutability_bad_types_and_mixed_attachments(self):
        for operation, values in (('unknown', ('beast',)), ('add', ()), ('remove', ()),
                                  ('add', ['beast']), ('add', ('beast','beast')), ('set', (True,))):
            with self.subTest(operation=operation, values=values), self.assertRaises((ValueError, TypeError)):
                TribeChangeSpec(operation, values)
        spec = TribeChangeSpec('add', ('beast',))
        for kwargs in (dict(attack=1), dict(health=1), dict(cost=1), dict(set_health=1),
                       dict(set_cost=0), dict(cost_minimum=1), dict(magnetic_id=1)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): Enchantment(1, tribe_change=spec, **kwargs)
        with self.assertRaises(ValueError): TribeState(('all','beast'))
        with self.assertRaises(ValueError): TribeState(('beast',), ('dragon',))
        with self.assertRaises(ValueError): MinionScope(tribe_basis='dynamic')

    def test_ordered_add_set_and_remove_keep_printed_metadata_independent(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'add',('dragon',),c.source_id), change(e,'set',('mech','undead'),c.source_id),
                    change(e,'add',('dragon',),c.source_id), change(e,'remove',('mech',),c.source_id)]
        g=game(work); target=g.state.players[1].board[0]; play_work(g)
        self.assert_state(g,target,('dragon','undead'))
        self.assertEqual(tribe_state(g.registry,g.state.entities[target],basis='printed'),TribeState(('beast',)))
        self.assertEqual(g.state.entities[target].attack,2); self.assertEqual(g.state.entities[target].max_health,6)
        self.roundtrip(g,work)

    def test_all_tribes_with_exclusions_does_not_expand_a_partial_card_pool(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'remove',('beast','naga'),c.source_id)]
        g=game(work,board=('all',)); target=g.state.players[1].board[0]; play_work(g)
        self.assert_state(g,target,('all',),('beast','naga'))
        entity=g.state.entities[target]
        self.assertFalse(has_any_tribe(g.registry,entity,('beast','naga')))
        self.assertFalse(has_any_tribe(g.registry,entity,('all',)))
        self.assertTrue(has_any_tribe(g.registry,entity,('future.type',)))
        self.assertTrue(has_any_tribe(g.registry,entity,('beast',),basis='printed'))
        self.roundtrip(g,work)

    def test_add_restores_an_excluded_type_and_remove_all_clears_the_complete_set(self):
        current=apply_change(TribeState(('all',)),TribeChangeSpec('remove',('beast',)))
        current=apply_change(current,TribeChangeSpec('add',('beast',)))
        self.assertEqual(current,TribeState(('all',)))
        self.assertEqual(apply_change(current,TribeChangeSpec('remove',('all',))),TribeState(()))
        self.assertEqual(apply_change(TribeState(('beast',)),TribeChangeSpec('add',('all',))),TribeState(('all',)))

    def test_unknown_is_not_empty_and_partial_addition_stays_unknown(self):
        def work(c): return [change(c.state.entities[c.state.players[1].board[0]],'add',('dragon',),c.source_id)]
        g=game(work,board=('unknown',)); target=g.state.players[1].board[0]
        self.assertIsNone(tribe_state(g.registry,g.state.entities[target])); play_work(g)
        self.assertIsNone(tribe_state(g.registry,g.state.entities[target]))
        with self.assertRaises(UnsupportedDefinitionError): has_any_tribe(g.registry,g.state.entities[target],('dragon',))
        self.assertFalse(has_any_tribe(g.registry,g.state.entities[g.state.players[1].deck[0]],('dragon',)))
        self.roundtrip(g,work)

    def test_explicit_set_provides_a_known_complete_set_without_guessing_printed_tribes(self):
        for values in ((),('dragon',),('all',)):
            def work(c): return [change(c.state.entities[c.state.players[1].board[0]],'set',values,c.source_id)]
            g=game(work,board=('unknown',)); target=g.state.players[1].board[0]; play_work(g)
            self.assert_state(g,target,values)
            self.assertIsNone(tribe_state(g.registry,g.state.entities[target],basis='printed'))
            self.roundtrip(g,work)

    def test_silence_removes_dynamic_changes_and_allows_subsequent_new_grants(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'set',('dragon',),c.source_id),Silence(e.id),change(e,'add',('mech',),c.source_id)]
        g=game(work); target=g.state.players[1].board[0]; play_work(g)
        self.assert_state(g,target,('beast','mech')); self.assertTrue(g.state.entities[target].silenced)
        self.assertEqual(len(tribe_changes(g.state.entities[target])),1); self.roundtrip(g,work)

    def test_explicit_silence_retention_is_part_of_the_attachment_policy(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'set',('dragon',),c.source_id,remove_on_silence=False),Silence(e.id)]
        g=game(work); target=g.state.players[1].board[0]; play_work(g)
        self.assert_state(g,target,('dragon',)); self.roundtrip(g,work)

    def test_removing_one_enchantment_reveals_earlier_ordered_changes(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            if not tribe_changes(e): return [change(e,'add',('dragon',),c.source_id),change(e,'set',('mech',),c.source_id)]
            return [RemoveEnchantment(e.id,tribe_changes(e)[-1].id)]
        g=game(work,hand=('work','work')); target=g.state.players[1].board[0]
        play_work(g); self.assert_state(g,target,('mech',)); play_work(g)
        self.assert_state(g,target,('beast','dragon')); self.roundtrip(g,work)

    def test_end_turn_expiry_removes_only_the_expiring_source(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'add',('dragon',),c.source_id),change(e,'set',('mech',),c.source_id,expires_turn=c.state.turn)]
        g=game(work); target=g.state.players[1].board[0]; play_work(g)
        self.assert_state(g,target,('mech',)); g.apply(EndTurn(1)); self.assert_state(g,target,('beast','dragon'))
        self.roundtrip(g,work)

    def test_current_copy_allocates_independent_changes_and_base_copy_uses_printed_tribes(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'set',('dragon',),c.source_id),CopyMinion(e.id,1,mode='current'),CopyMinion(e.id,1,mode='base')]
        g=game(work); play_work(g); original,current,base=g.state.players[1].board
        self.assert_state(g,original,('dragon',)); self.assert_state(g,current,('dragon',)); self.assert_state(g,base,('beast',))
        self.assertNotEqual(tribe_changes(g.state.entities[original])[0].id,tribe_changes(g.state.entities[current])[0].id)
        self.roundtrip(g,work)

    def test_control_transfer_retains_change_but_invalidates_old_board_reference(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]; later=change(e,'add',('mech',),c.source_id)
            return [change(e,'set',('dragon',),c.source_id),ChangeControl(e.id,2),later]
        g=game(work); target=g.state.players[1].board[0]; play_work(g)
        self.assert_state(g,target,('dragon',)); self.assertEqual(g.state.entities[target].controller,2)
        self.roundtrip(g,work)

    def test_transform_clears_old_modifiers_and_old_same_id_work_cannot_rebind(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]; later=change(e,'add',('mech',),c.source_id)
            return [change(e,'set',('naga',),c.source_id),Transform(e.id,'dragon'),later]
        g=game(work); target=g.state.players[1].board[0]; play_work(g)
        self.assert_state(g,target,('dragon',)); self.assertFalse(tribe_changes(g.state.entities[target])); self.roundtrip(g,work)

    def test_bounce_and_shuffle_reset_current_type_to_printed_face(self):
        for operation in ('bounce','shuffle'):
            def work(c):
                e=c.state.entities[c.state.players[1].board[0]]
                return [change(e,'set',('dragon',),c.source_id),ReturnToHand(e.id) if operation=='bounce' else ShuffleIntoDeck(e.id,1)]
            g=game(work); target=g.state.players[1].board[0]; play_work(g)
            self.assert_state(g,target,('beast',)); self.assertFalse(tribe_changes(g.state.entities[target])); self.roundtrip(g,work)

    def test_stored_changes_move_with_preserved_state_and_current_copy_has_new_ids(self):
        def work(c):
            e=c.state.entities[c.state.players[1].deck[0]]
            return [change(e,'add',('dragon',),c.source_id),CopyCard(CardReference.capture(e),1,Zone.HAND,mode='current'),
                    CopyCard(CardReference.capture(e),1,Zone.HAND,mode='base'),MoveCard(CardReference.capture(e),1,Zone.HAND)]
        g=game(work); original=g.state.players[1].deck[0]; play_work(g); current,base,moved=g.state.players[1].hand
        self.assertEqual(moved,original)
        self.assert_state(g,moved,('beast','dragon')); self.assert_state(g,current,('beast','dragon')); self.assert_state(g,base,('beast',))
        self.assertNotEqual(tribe_changes(g.state.entities[moved])[0].id,tribe_changes(g.state.entities[current])[0].id)
        self.roundtrip(g,work)

    def test_stored_reset_and_stale_reference_do_not_apply_a_future_change(self):
        def work(c):
            e=c.state.entities[c.state.players[1].deck[0]]; reference=CardReference.capture(e)
            return [change(e,'set',('dragon',),c.source_id),MoveCard(reference,1,Zone.HAND,reset=True),
                    ChangeMinionTribes(reference,TribeChangeSpec('add',('mech',)),c.source_id)]
        g=game(work); target=g.state.players[1].deck[0]; play_work(g); self.assert_state(g,target,('beast',)); self.roundtrip(g,work)

    def test_death_freezes_tribes_and_reborn_uses_printed_identity(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'set',('dragon',),c.source_id),GrantKeyword(e.id,Keyword.REBORN,c.source_id),Destroy(e.id)]
        g=game(work); original=g.state.players[1].board[0]; play_work(g)
        self.assertEqual(tribe_state(g.registry,g.state.death_history[0]),TribeState(('dragon',)))
        new=g.state.players[1].board[0]; self.assertNotEqual(original,new); self.assert_state(g,new,('beast',)); self.roundtrip(g,work)

    def test_current_cross_zone_queries_are_pure_and_default_basis_remains_printed(self):
        def work(c):
            return [change(c.state.entities[i],'set',('dragon',),c.source_id)
                    for i in (*c.state.players[1].hand,*c.state.players[1].deck,*c.state.players[1].board)
                    if c.state.entities[i].kind==CardType.MINION]
        g=game(work,hand=('work','beast')); play_work(g); before=g.snapshot(); ids=(*g.state.players[1].hand,*g.state.players[1].deck,*g.state.players[1].board)
        default=minion_references(g.state,g.registry,1,MinionScope(query=PoolQuery(tribes_any=('dragon',))))
        current=minion_references(g.state,g.registry,1,MinionScope(query=PoolQuery(tribes_any=('dragon',)),tribe_basis='current'))
        self.assertEqual(default,()); self.assertEqual(tuple(r.entity_id for r in current),ids); self.assertEqual(g.snapshot(),before)
        self.roundtrip(g,work)

    def test_nonminion_characters_have_no_current_minion_tribes_even_with_unknown_metadata(self):
        def work(c): return []
        g=game(work)
        for target in (g.state.players[1].hero_id,g.state.players[1].hand[0]):
            self.assertEqual(tribe_state(g.registry,g.state.entities[target]),TribeState(()))
            self.assertFalse(has_any_tribe(g.registry,g.state.entities[target],('beast',)))

    def test_remembered_enemy_hand_identity_does_not_reveal_later_type_modifications(self):
        def work(c):
            e=c.state.entities[c.state.players[2].hand[0]]
            return [RevealHandCard(e.id),change(e,'set',('dragon',),c.source_id)]
        g=game(work,enemy_hand=('beast',)); play_work(g)
        opposing=next(p for p in g.for_player(1).observe()['observation']['players'] if p['id']==2)
        self.assertEqual(opposing['hand'][0]['card_id'],'beast')
        self.assertNotIn('tribes',opposing['hand'][0]);self.assertNotIn('tribes_excluded',opposing['hand'][0])
        owner=next(p for p in g.for_player(2).observe()['observation']['players'] if p['id']==2)
        self.assertEqual(owner['hand'][0]['tribes'],['dragon']);self.roundtrip(g,work)

    def test_unknown_query_is_complete_and_is_not_hidden_by_an_earlier_match(self):
        def work(c): return []
        g=game(work,board=('dragon','unknown'))
        with self.assertRaises(UnsupportedDefinitionError):
            minion_references(g.state,g.registry,1,MinionScope(query=PoolQuery(tribes_any=('dragon',)),tribe_basis='current'))

    def test_waiting_serializes_real_typed_work_and_resumes_all_restored_branches(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [RequestChoice(1,(ChoiceOption('go','Go',(change(e,'set',('dragon',),c.source_id),)),),c.source_id)]
        g=game(work); target=g.state.players[1].board[0]; play_work(g); snapshot=g.snapshot()
        branches=[g,Game.from_snapshot(snapshot,registry(work)),g.clone(),replay(build_replay(g),registry(work))]
        for branch in branches:
            pending=branch.state.pending_choice; branch.apply(SelectChoice(1,pending.id,('go',)))
            self.assert_state(branch,target,('dragon',))
        for branch in branches: self.assertEqual(branch.snapshot(),g.snapshot())

    def test_later_failure_rolls_back_identity_payment_allocator_rng_and_history(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [change(e,'set',('dragon',),c.source_id),RandomDamage((e.id,),1,c.source_id),Summon(1,'unknown.card')]
        g=game(work); before=g.snapshot(); history=g.history
        with self.assertRaises(ResolutionError): play_work(g)
        self.assertEqual(g.snapshot(),before); self.assertEqual(g.history,history)

    def test_known_stale_work_in_a_real_wait_restores_and_skips_after_face_change(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            pending=change(e,'set',('mech',),c.source_id)
            return [Transform(e.id,'dragon'),RequestChoice(1,(ChoiceOption('go','Go',(pending,)),),c.source_id)]
        g=game(work); target=g.state.players[1].board[0]; play_work(g); snapshot=g.snapshot()
        branches=(g,Game.from_snapshot(snapshot,registry(work)),g.clone(),replay(build_replay(g),registry(work)))
        for branch in branches:
            choice=branch.state.pending_choice; branch.apply(SelectChoice(1,choice.id,('go',)))
            self.assert_state(branch,target,('dragon',)); self.assertFalse(tribe_changes(branch.state.entities[target]))
        for branch in branches:self.assertEqual(branch.snapshot(),g.snapshot())

    def test_rehashed_waiting_effect_cannot_reference_unknown_future_minion(self):
        def work(c):
            e=c.state.entities[c.state.players[1].board[0]]
            return [RequestChoice(1,(ChoiceOption('go','Go',(change(e,'set',('mech',),c.source_id),)),),c.source_id)]
        g=game(work); play_work(g); snapshot=g.snapshot(); changed=[]
        def corrupt(node):
            if isinstance(node,dict):
                if node.get('type')=='hs_sim.engine.tribes.ChangeMinionTribes':
                    node['fields']['target']['fields']['entity_id']=999; changed.append(node)
                for value in node.values():corrupt(value)
            elif isinstance(node,list):
                for value in node:corrupt(value)
        corrupt(snapshot['resolution_frame']);self.assertTrue(changed)
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(rehash(snapshot),registry(work))
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_unknown_target_and_nonminion_references_fail_before_silent_stale_skip(self):
        for invalid in ('unknown_id','nonminion'):
            def work(c):
                ref=MinionReference(999,1,'beast',0,1) if invalid=='unknown_id' else CardReference(c.source_id,1,Zone.HAND,'work',0)
                return [ChangeMinionTribes(ref,TribeChangeSpec('set',('dragon',)),c.source_id)]
            g=game(work); before=g.snapshot()
            with self.assertRaises(ResolutionError): play_work(g)
            self.assertEqual(g.snapshot(),before)

    def test_corrupt_missing_mixed_and_nonminion_saved_changes_are_rejected_after_rehash(self):
        def work(c): return [change(c.state.entities[c.state.players[1].board[0]],'set',('dragon',),c.source_id)]
        g=game(work); target=g.state.players[1].board[0]; play_work(g)
        for mutation in ('missing','extra','bad_operation','mixed','foreign_carrier'):
            snapshot=g.snapshot(); enchantment=snapshot['state']['entities'][str(target)]['enchantments'][0]
            if mutation=='missing': enchantment['tribe_change'].pop('operation')
            elif mutation=='extra': enchantment['tribe_change']['callback']='foreign'
            elif mutation=='bad_operation': enchantment['tribe_change']['operation']='unknown'
            elif mutation=='mixed': enchantment['attack']=1
            else:
                snapshot['state']['entities'][str(target)]['enchantments']=[]
                snapshot['state']['entities'][str(g.state.players[1].hero_id)]['enchantments']=[enchantment]
            with self.subTest(mutation=mutation), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(snapshot),registry(work))

    def test_current_types_are_visible_only_with_public_or_owner_stat_permission(self):
        def work(c):
            e=c.state.entities[c.state.players[2].hand[0]]
            return [change(e,'set',('dragon',),c.source_id)]
        g=game(work,enemy_hand=('beast',)); before=g.for_player(1).observe(); play_work(g)
        own=g.for_player(2).observe()['observation']; enemy=next(p for p in own['players'] if p['id']==2)
        self.assertEqual(enemy['hand'][0]['tribes'],['dragon'])
        opposing=next(p for p in g.for_player(1).observe()['observation']['players'] if p['id']==2)
        self.assertNotIn('tribes',opposing['hand'][0]); self.assertNotIn('tribe_change',json.dumps(g.for_player(1).observe()))
        self.roundtrip(g,work)


if __name__=='__main__': unittest.main()
