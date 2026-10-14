"""Shatter's hand lifecycle tested without growing the real-card package."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, ShatterSpec, SnapshotError, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor, GrantKeyword,
    InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard, MoveCard, ReorderZone


def family(registry, prefix='split', **fields):
    for name, amount in ((prefix, 3), (prefix+'L', 1), (prefix+'R', 2)):
        registry.register_behavior(name, lambda c, n=amount: [GainArmor(c.player_id, n)])
        root = name == prefix
        registry.register_card(CardDefinition(name, name, CardType.SPELL, cost=4, on_play=name,
            keywords=(Keyword.SHATTER if root else Keyword.SHATTERED,),
            shatter=ShatterSpec(prefix+'L', prefix+'R') if root else None, **fields))


class ShatterTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        family(self.r)
        self.spell('plain', lambda c: [])

    def spell(self, name, fn):
        self.r.register_behavior(name, fn)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def game(self, hand=(), deck=('plain',)*12, enemy_hand=(), rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', hand=hand, deck=deck, max_mana=10, mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=('plain',)*12, max_mana=10, mana=10)), seed=178), self.r, rules)

    def cards(self, g, player=1):
        s=g.state
        return [s.entities[i] for i in s.players[player].hand]

    def names(self, g, player=1): return [e.card_id for e in self.cards(g, player)]
    def find(self, g, name): return next(e.id for e in self.cards(g) if e.card_id==name)
    def play(self, g, name): g.apply(PlayCard(1, self.find(g, name)))
    def ref(self, c, name):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id==name))
    def check(self, g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)

    def test_initial_hand_splits_at_opposite_ends(self):
        g=self.game(('plain','split','plain'))
        self.assertEqual(self.names(g),['splitL','plain','plain','splitR'])
        self.assertTrue(all(x.turn==0 for x in g.state.hand_entries)); self.check(g)

    def test_empty_hand_recombines_immediately_and_consumes_keyword(self):
        g=self.game(('split',))
        self.assertEqual(self.names(g),['split'])
        self.assertNotIn(Keyword.SHATTER,self.cards(g)[0].keywords)
        self.assertEqual(len([e for e in g.events if e.kind=='cards_recombined']),1); self.check(g)

    def test_playing_middle_recombines_before_next_effect(self):
        self.spell('middle',lambda c:[InvokeBehavior('observe',c.source_id,c.player_id)])
        self.r.register_behavior('observe',lambda c:[GainArmor(1,len(c.state.players[1].hand))])
        g=self.game(('split','middle')); self.play(g,'middle')
        self.assertEqual(self.names(g),['split'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.play(g,'split'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4); self.check(g)

    def test_independent_fragments_pay_and_apply_own_behaviors(self):
        g=self.game(('split','plain')); self.play(g,'splitL'); self.play(g,'splitR')
        self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)
        self.assertFalse(any(e.kind=='cards_recombined' for e in g.events)); self.check(g)

    def test_acquisition_does_not_count_as_play_death_or_discard(self):
        self.spell('get',lambda c:[AddToHand(1,'split')])
        g=self.game(('get','plain')); self.play(g,'get')
        self.assertEqual(self.names(g),['splitL','plain','splitR'])
        self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind=='card_discarded' for e in g.events))
        self.assertEqual([e.reason for e in g.state.hand_entries][-3:],['created','shatter','shatter']); self.check(g)

    def test_draw_splits_only_after_successful_entry(self):
        self.spell('draw',lambda c:[Draw(1)])
        g=self.game(('draw','plain'),deck=('split','plain')); self.play(g,'draw')
        self.assertEqual(self.names(g),['splitL','plain','splitR'])
        self.assertEqual(len([e for e in g.events if e.kind=='card_drawn']),1); self.check(g)

    def test_last_hand_slot_keeps_left_and_burns_right(self):
        self.spell('get',lambda c:[AddToHand(1,'plain'),AddToHand(1,'split')])
        g=self.game(('get',)+('plain',)*8); self.play(g,'get')
        self.assertEqual(self.names(g),['splitL']+['plain']*9)
        burned=[g.state.entities[e.target_id].card_id for e in g.events if e.kind=='card_burned']
        self.assertEqual(burned,['splitR']); self.check(g)

    def test_full_hand_burns_root_without_splitting(self):
        self.spell('get',lambda c:[AddToHand(1,'plain'),AddToHand(1,'split')])
        g=self.game(('get',)+('plain',)*9); self.play(g,'get')
        self.assertEqual(self.names(g),['plain']*10)
        self.assertFalse(any(e.kind=='card_shattered' for e in g.events)); self.check(g)

    def test_same_side_does_not_combine(self):
        g=self.game(('splitL','splitL')); self.assertEqual(self.names(g),['splitL','splitL']); self.check(g)

    def test_different_family_does_not_combine(self):
        family(self.r,'other')
        g=self.game(('splitL','otherR')); self.assertEqual(self.names(g),['splitL','otherR'])

    def test_fragments_from_independent_origins_can_combine_in_reverse_order(self):
        g=self.game(('splitR','splitL')); self.assertEqual(self.names(g),['split']); self.check(g)

    def test_reorder_checks_new_neighbors(self):
        self.spell('sort',lambda c:[ReorderZone(1,Zone.HAND,tuple(reversed(c.state.players[1].hand[:2]))+tuple(c.state.players[1].hand[2:]))])
        g=self.game(('sort','splitL','plain','splitR')); self.play(g,'sort')
        self.assertEqual(self.names(g),['plain','split']); self.check(g)

    def test_discarding_separator_merges_without_discarding_fragments(self):
        self.spell('discard',lambda c:[DiscardCard(self.ref(c,'plain'))])
        g=self.game(('discard','split','plain')); self.play(g,'discard')
        self.assertEqual(self.names(g),['split'])
        self.assertEqual(len([e for e in g.events if e.kind=='card_discarded']),1); self.check(g)

    def test_creation_discount_copies_to_both_and_merge_does_not_double_it(self):
        self.spell('get',lambda c:[AddToHand(1,'split',cost=CostSpec(delta=-1))])
        g=self.game(('get','plain')); self.play(g,'get')
        self.assertEqual([g.quote_cost(e.id).amount for e in self.cards(g) if e.card_id!='plain'],[3,3])
        parts=[e for e in self.cards(g) if e.card_id!='plain']
        self.assertNotEqual(parts[0].enchantments[0].id,parts[1].enchantments[0].id)
        self.play(g,'plain'); self.assertEqual(g.quote_cost(self.find(g,'split')).amount,3); self.check(g)

    def test_merge_inherits_declared_left_fragment_after_reordering(self):
        self.spell('discount',lambda c:[ModifyCost(self.ref(c,'splitR').entity_id,CostSpec(delta=-3)),
                                       ModifyCost(self.ref(c,'splitL').entity_id,CostSpec(delta=-1))])
        g=self.game(('splitR','plain','splitL','discount')); self.play(g,'discount'); self.play(g,'plain')
        self.assertEqual(g.quote_cost(self.find(g,'split')).amount,3); self.check(g)

    def test_current_copy_of_combined_card_does_not_split_again(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'split'),1)])
        g=self.game(('splitL','splitR','copy')); self.play(g,'copy')
        self.assertEqual(self.names(g),['split','split'])
        self.assertTrue(all(Keyword.SHATTER not in e.keywords for e in self.cards(g))); self.check(g)

    def test_base_copy_restores_shatter(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'split'),1,mode='base')])
        g=self.game(('splitL','splitR','copy')); self.play(g,'copy')
        self.assertEqual(self.names(g),['splitL','split','splitR']); self.check(g)

    def test_move_combined_to_deck_and_draw_preserves_consumed_state(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c,'split'),1,Zone.DECK,position='top'),Draw(1)])
        g=self.game(('splitL','splitR','move')); self.play(g,'move')
        self.assertEqual(self.names(g),['split']); self.check(g)

    def test_reset_before_redraw_restores_shatter(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c,'split'),1,Zone.DECK,position='top',reset=True),Draw(1)])
        g=self.game(('splitL','splitR','move','plain')); self.play(g,'move')
        self.assertEqual(self.names(g),['splitL','plain','splitR']); self.check(g)

    def test_choice_can_resume_after_split(self):
        self.spell('choose',lambda c:[AddToHand(1,'split'),RequestChoice(1,
            (ChoiceOption('keep','Keep',()),),c.source_id)])
        g=self.game(('choose','plain')); self.play(g,'choose')
        self.assertEqual(self.names(g),['splitL','plain','splitR']); self.check(g)
        choice=g.state.pending_choice
        g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,choice.id,('keep',))); self.check(g)

    def test_failure_rolls_back_split_events_entities_and_hand_history(self):
        self.r.register_behavior('bad',lambda c:[GainArmor(1,-1)])
        self.spell('fail',lambda c:[AddToHand(1,'split'),InvokeBehavior('bad',c.source_id,1)])
        g=self.game(('fail','plain')); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_private_events_and_observation_do_not_leak_fragments(self):
        self.spell('get',lambda c:[AddToHand(1,'split')])
        g=self.game(('get','plain')); self.play(g,'get')
        self.assertIn('card_shattered',[e['kind'] for e in g.player_events(1)])
        self.assertNotIn('card_shattered',[e['kind'] for e in g.player_events(2)])
        self.assertNotIn('split',json.dumps(g.observe(2)))
        self.assertNotIn('split',json.dumps(g.player_events(2))); self.check(g)

    def test_cross_player_fragments_never_merge(self):
        g=self.game(('splitL',),enemy_hand=('splitR',))
        self.assertEqual(self.names(g),['splitL']); self.assertEqual(self.names(g,2),['splitR'])

    def test_snapshot_rejects_unconsumed_combined_card(self):
        g=self.game(('split',)); snap=g.snapshot()
        entity=snap['state']['entities'][str(self.find(g,'split'))]
        for a in entity['abilities']:
            if a['keyword']=='shatter': a['consumed']=False
        entity['keywords']=['shatter']
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_multiple_acquisitions_settle_and_replay_deterministically(self):
        self.spell('get',lambda c:[AddToHand(1,'split'),AddToHand(1,'split')])
        g=self.game(('get','plain')); self.play(g,'get')
        self.assertEqual(self.names(g),['splitL','splitL','plain','splitR','splitR'])
        self.play(g,'plain'); self.assertEqual(self.names(g),['splitL','split','splitR']); self.check(g)

    def test_captured_fragment_is_not_moved_after_recombination(self):
        self.spell('stale',lambda c:[DiscardCard(self.ref(c,'plain')),
                                    MoveCard(self.ref(c,'splitL'),1,Zone.DECK)])
        g=self.game(('stale','split','plain')); self.play(g,'stale')
        self.assertEqual(self.names(g),['split'])
        self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events)); self.check(g)

    def test_temporary_creation_discount_expires_on_both_pieces(self):
        self.spell('get',lambda c:[AddToHand(1,'split',cost=CostSpec(delta=-3),expires_turn=c.state.turn)])
        g=self.game(('get','plain')); self.play(g,'get')
        self.assertEqual(g.quote_cost(self.find(g,'splitL')).amount,1)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual([g.quote_cost(self.find(g,n)).amount for n in ('splitL','splitR')],[4,4]); self.check(g)

    def test_resolution_budget_limits_automatic_hand_work(self):
        from hs_sim.engine import Ruleset, ResolutionLimitExceeded
        with self.assertRaises(ResolutionLimitExceeded):
            self.game(('split',),rules=Ruleset(max_resolution_steps=1))

    def test_fragment_burn_is_public_but_surviving_fragment_stays_hidden(self):
        self.spell('get',lambda c:[AddToHand(1,'plain'),AddToHand(1,'split')])
        g=self.game(('get',)+('plain',)*8); self.play(g,'get')
        public=json.dumps(g.player_events(2))
        self.assertIn('splitR',public); self.assertNotIn('splitL',public); self.check(g)

    def test_merged_card_is_playable_through_player_port(self):
        g=self.game(('split',))
        port=g.for_player(1)
        listing=port.legal_actions()
        command=next(x for x in listing['actions'] if x['type']=='play_card')
        result=port.submit({'revision':listing['revision'],'action':command})
        self.assertTrue(result['accepted'],result['error'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3); self.check(g)


class ShatterOpeningTests(unittest.TestCase):
    def test_mulligan_keeps_root_identity_until_replacements_finish(self):
        from opening_fixtures import registry, metadata, deck, setup
        r=registry();family(r,metadata=metadata())
        g=Game.from_decks(setup(r,decks=(deck(cards=('split',)*30),deck()),max_copies=30),r)
        self.assertTrue(all(g.state.entities[i].card_id=='split' for i in g.state.players[1].hand))
        first=g.state.pending_choice
        g.apply(SelectChoice(1,first.id,(first.options[0].id,)))
        g=Game.from_snapshot(g.snapshot(),r)
        second=g.state.pending_choice
        g.apply(SelectChoice(2,second.id,()))
        self.assertEqual(g.state.opening.stage,'complete')
        self.assertFalse(any(Keyword.SHATTER in g.state.entities[i].keywords for i in g.state.players[1].hand))
        split_entries=[x for x in g.state.hand_entries if x.reason=='shatter']
        self.assertEqual([x.turn for x in split_entries],[0]*6+[1]*2)
        self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())


class ShatterDefinitionTests(unittest.TestCase):
    def test_invalid_pairs_rejected(self):
        for left,right in (('','right'),('left',''),('same','same')):
            with self.subTest(left=left,right=right),self.assertRaises(ValueError):ShatterSpec(left,right)

    def test_missing_declaration_rejected(self):
        r=build_registry();r.register_card(CardDefinition('bad','bad',CardType.SPELL,keywords=(Keyword.SHATTER,)))
        with self.assertRaises(ValueError):r.freeze()

    def test_orphan_fragment_rejected(self):
        r=build_registry();r.register_card(CardDefinition('bad','bad',CardType.SPELL,keywords=(Keyword.SHATTERED,)))
        with self.assertRaises(ValueError):r.freeze()

    def test_shared_fragments_rejected(self):
        r=build_registry();family(r)
        r.register_card(CardDefinition('bad','bad',CardType.SPELL,keywords=(Keyword.SHATTER,),shatter=ShatterSpec('splitL','splitR')))
        with self.assertRaises(ValueError):r.freeze()

    def test_non_spell_root_rejected(self):
        r=build_registry();r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,
            keywords=(Keyword.SHATTER,),shatter=ShatterSpec('a','b')))
        with self.assertRaises(ValueError):r.freeze()
