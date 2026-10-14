"""Physical bottom selection, continuations, hidden information and composition."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardPreview, CardType, CastSpell, CopyStoredMinion,
    Dredge, Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError,
    ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice, SnapshotError, SummonStoredCard,
    TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw, GainArmor, ModifyCost,
    RequestChoice, Summon)
from hs_sim.engine.model import CardMetadata, CardClass, CostSpec, Rarity, SummonStats, SpellRepeatSpec
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.dredge import SelectDredgedCard
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard, ShuffleDeck
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class DredgeTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('dredge-tests-v1')
        self.r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        for cid, cost in (('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)):
            self.r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=cost, health=cost+1,
                metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('murloc',))))
        self.r.register_card(CardDefinition('plain', 'plain', CardType.SPELL, cost=4))

    def script(self, fn=None, name='script', **kw):
        self.r.register_behavior(name, fn or (lambda c: [Dredge(c.player_id, source_id=c.source_id)]))
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))

    def game(self, deck=('a','b','c','d','e'), hand=('script',), enemy_deck=(), board=(), enemy_board=(), rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, deck=deck, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', deck=enemy_deck, board=enemy_board)), seed=41), self.r, rules)

    def play(self, g, name='script'):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(1, source)); return source

    def choose(self, g, cid=None, index=0):
        ch = g.state.pending_choice
        option = next(o for o in ch.options if o.card_id == cid) if cid else ch.options[index]
        g.apply(SelectChoice(ch.player_id, ch.id, (option.id,)))

    def check(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap, self.r).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), snap)

    def callback(self, fn):
        self.r.register_behavior('selected', fn)
        self.script(lambda c: [Dredge(c.player_id, source_id=c.source_id, on_select='selected')])

    def ref(self, c): return CardReference.capture(c.state.entities[c.target_id])

    def armor(self, g): return g.state.entities[g.state.players[1].hero_id].armor

    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as e: Game.from_snapshot(snap, self.r)
        self.assertNotIn('digest mismatch', str(e.exception))

    def test_only_bottom_three_without_mutating_order_until_selection(self):
        self.script(); g=self.game(); old=list(g.state.players[1].deck); self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {'c','d','e'})
        self.assertEqual(g.state.pending_choice.purpose.value, 'dredge')
        self.assertEqual(g.state.players[1].deck, old); self.check(g)

    def test_select_moves_same_physical_entity_and_preserves_all_other_order(self):
        self.script(); g=self.game(); old=list(g.state.players[1].deck); self.play(g); self.choose(g,'d')
        self.assertEqual(g.state.players[1].deck, [old[3], *old[:3], old[4]])
        self.assertEqual(g.state.entities[old[3]].zone_epoch, 1)
        self.assertFalse(g.state.draw_history); self.assertFalse(g.state.death_history); self.check(g)

    def test_empty_deck_does_not_choose_fatigue_run_callback_or_consume_random(self):
        self.callback(lambda c:[GainArmor(1,10)]); g=self.game(deck=()); rng=g.snapshot()['rng_state']; self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.armor(g),0)
        self.assertEqual(g.state.players[1].fatigue,0); self.assertEqual(g.snapshot()['rng_state'],rng); self.check(g)

    def test_short_decks_offer_existing_physical_cards_including_singleton(self):
        self.script()
        for deck in (('a',), ('a','b'), ('a','b','c')):
            with self.subTest(deck=deck):
                g=self.game(deck=deck); self.play(g)
                self.assertEqual(len(g.state.pending_choice.options),len(deck)); self.choose(g,deck[-1]); self.check(g)

    def test_duplicate_definitions_remain_distinct_and_display_local_modifiers(self):
        self.script(lambda c:[ModifyCost(c.state.players[1].deck[-1],CostSpec(delta=-1)),
            BuffStoredCard(CardReference.capture(c.state.entities[c.state.players[1].deck[-1]]),2,3),
            Dredge(1,source_id=c.source_id)])
        g=self.game(deck=('b','b','b')); old=list(g.state.players[1].deck); self.play(g)
        options=g.state.pending_choice.options; self.assertEqual(len(options),3)
        n=next(i for i,o in enumerate(options) if o.preview.cost==1)
        self.assertEqual((options[n].preview.attack, options[n].preview.health),(4,6))
        self.choose(g,index=n); self.assertEqual(g.state.players[1].deck[0],old[-1]); self.check(g)

    def test_private_candidates_and_selection_never_allocate_deck_handles(self):
        self.script();g=self.game();self.play(g)
        self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1})
        for o in g.observe(1)['pending_choice']['options']:
            self.assertIsNone(o['entity']);self.assertIn('preview',o)
        self.choose(g,'c')
        for viewer in (1,2):
            event=next(e for e in g.player_events(viewer) if e['kind']=='card_dredged')
            self.assertIsNone(event['target'])
            self.assertEqual(event['dredge']['selected'] is None,viewer==2)
            ledger=g.snapshot()['information']['players'][str(viewer)]
            self.assertFalse(set(map(str,g.state.players[1].deck)) & set(ledger['refs']))
        self.check(g)

    def test_opponent_deck_changes_owner_deck_but_only_selector_sees_offers(self):
        self.script(lambda c:[Dredge(1,owner_id=2,source_id=c.source_id)])
        g=self.game(enemy_deck=('e','d','c','b','a')); own=list(g.state.players[1].deck)
        target=g.state.players[2].deck[-1];self.play(g);self.choose(g,'a')
        self.assertEqual(g.state.players[1].deck,own);self.assertEqual(g.state.players[2].deck[0],target)
        self.assertEqual(g.state.entities[target].owner,2);self.check(g)

    def test_selector_can_be_non_active_player(self):
        self.script(lambda c:[Dredge(2,owner_id=1,source_id=c.source_id)])
        g=self.game();self.play(g);self.assertEqual(g.observe(1)['pending_choice'],{'player_id':2})
        self.choose(g,'e');self.check(g)

    def test_reveal_exposes_selected_snapshot_but_not_other_candidates_or_tracking(self):
        self.script(lambda c:[Dredge(1,source_id=c.source_id,reveal=True)])
        g=self.game();self.play(g);self.choose(g,'e')
        event=next(e for e in g.player_events(2) if e['kind']=='card_dredged')
        self.assertEqual(event['dredge']['selected']['card_id'],'e')
        self.assertEqual(event['dredge']['selected']['preview']['cost'],5);self.assertIsNone(event['target'])
        self.check(g)

    def test_continuation_sees_selected_entity_after_placement(self):
        def selected(c):
            self.assertEqual(c.state.players[1].deck[0],c.target_id)
            return [ModifyCost(c.target_id,CostSpec(set_to=6))]
        self.callback(selected);g=self.game();self.play(g);self.choose(g,'d')
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].cost,6);self.check(g)

    def test_selected_card_draw_uses_same_entity_and_draw_history(self):
        self.callback(lambda c:[MoveCard(self.ref(c),1,Zone.HAND,draw=True)])
        g=self.game();target=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        self.assertEqual(g.state.players[1].hand,[target]);self.assertEqual(len(g.state.draw_history),1);self.check(g)

    def test_full_hand_burns_drawn_selected_entity(self):
        self.callback(lambda c:[AddToHand(1,'a'),MoveCard(self.ref(c),1,Zone.HAND,draw=True)])
        g=self.game(hand=('script',)+('b',)*9);target=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.check(g)

    def test_selected_card_summon_keeps_entity_without_play_or_battlecry(self):
        self.callback(lambda c:[SummonStoredCard(self.ref(c),1)])
        g=self.game();target=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        self.assertEqual(g.state.players[1].board,[target]);self.assertEqual(len(g.state.play_history),1);self.check(g)

    def test_full_board_leaves_selected_original_at_deck_top(self):
        self.callback(lambda c:[SummonStoredCard(self.ref(c),1)])
        g=self.game(board=('a',)*7);target=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        self.assertEqual(g.state.players[1].deck[0],target);self.assertEqual(len(g.state.players[1].board),7);self.check(g)

    def test_selected_card_copy_summon_preserves_original_and_applies_entry_stats(self):
        self.callback(lambda c:[CopyStoredMinion(self.ref(c),1,stats=SummonStats(attack=2,health=2))])
        g=self.game();target=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        copy=g.state.entities[g.state.players[1].board[0]]
        self.assertNotEqual(copy.id,target);self.assertEqual(copy.origin_entity_id,target)
        self.assertEqual((copy.attack,copy.health),(2,2));self.assertEqual(g.state.players[1].deck[0],target);self.check(g)

    def test_copy_summon_current_and_base_modes_and_fresh_attachment_ids(self):
        def selected(c):return [CopyStoredMinion(self.ref(c),1),CopyStoredMinion(self.ref(c),1,mode='base')]
        self.r.register_behavior('selected',selected)
        self.script(lambda c:[BuffStoredCard(CardReference.capture(c.state.entities[c.state.players[1].deck[-1]]),2,3),
            Dredge(1,source_id=c.source_id,on_select='selected')])
        g=self.game();original=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        copies=[g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(x.attack,x.health) for x in copies],[(7,9),(5,6)])
        self.assertNotEqual(copies[0].enchantments[0].id,g.state.entities[original].enchantments[0].id);self.check(g)

    def test_copy_summon_full_board_does_not_consume_original_or_allocate_entity(self):
        self.callback(lambda c:[CopyStoredMinion(self.ref(c),1)]);g=self.game(board=('a',)*7)
        before=g.state.next_entity_id;self.play(g);self.choose(g,'e')
        self.assertEqual(g.state.next_entity_id,before);self.assertEqual(len(g.state.players[1].deck),5)

    def test_copy_summon_rejects_spell_instead_of_silent_whiteboard(self):
        self.callback(lambda c:[CopyStoredMinion(self.ref(c),1)]);g=self.game(deck=('plain',));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before)

    def test_nested_choice_resumes_and_preserves_selected_continuation(self):
        self.callback(lambda c:[RequestChoice(1,(ChoiceOption('x','x',(GainArmor(1,3),)),),source_id=c.source_id)])
        g=self.game();self.play(g);self.choose(g,'c');self.check(g)
        self.assertEqual(self.armor(g),0);self.choose(g);self.assertEqual(self.armor(g),3);self.check(g)

    def test_second_dredge_uses_new_bottom_after_first(self):
        self.script(lambda c:[Dredge(1,source_id=c.source_id),Dredge(1,source_id=c.source_id)])
        g=self.game();self.play(g);self.choose(g,'e')
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'b','c','d'})
        self.check(g);self.choose(g,'b');self.check(g)

    def test_source_destroyed_by_choice_reaction_does_not_cancel_captured_dredge(self):
        self.r.register_behavior('kill',lambda c:[Destroy(c.event.source_id)])
        self.r.register_card(CardDefinition('observer','observer',CardType.MINION,health=2,
            triggers=(TriggerSpec('choice_selected','kill'),)))
        self.r.register_behavior('body',lambda c:[Dredge(1,source_id=c.source_id)])
        self.r.register_card(CardDefinition('body','body',CardType.MINION,health=2,on_play='body'))
        g=self.game(hand=('body',),board=('observer',));source=self.play(g,'body');self.choose(g,'e')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id,'e');self.check(g)

    def test_departed_selected_candidate_is_not_replaced_with_another_card(self):
        self.r.register_behavior('steal',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[1].deck[-1]]),2,Zone.HAND)])
        self.r.register_card(CardDefinition('observer','observer',CardType.MINION,health=2,triggers=(TriggerSpec('choice_selected','steal'),)))
        self.callback(lambda c:[GainArmor(1,10)]);g=self.game(board=('observer',));self.play(g);self.choose(g,'e')
        self.assertEqual(self.armor(g),0);self.assertFalse(any(e.kind=='card_dredged' for e in g.events));self.check(g)

    def test_selected_card_returned_before_resolution_is_stale_even_same_entity(self):
        def roundtrip(c):
            e=c.state.entities[c.state.players[1].deck[-1]];ref=CardReference.capture(e)
            return [MoveCard(ref,1,Zone.HAND),MoveCard(replace(ref,zone=Zone.HAND,zone_epoch=ref.zone_epoch+1),1,Zone.DECK)]
        self.r.register_behavior('bounce',roundtrip)
        self.r.register_card(CardDefinition('observer','observer',CardType.MINION,health=2,triggers=(TriggerSpec('choice_selected','bounce'),)))
        self.script();g=self.game(board=('observer',));self.play(g);self.choose(g,'e')
        self.assertFalse(any(e.kind=='card_dredged' for e in g.events));self.check(g)

    def test_shuffle_reaction_does_not_invalidate_physical_candidate(self):
        self.r.register_behavior('shuffle',lambda c:[ShuffleDeck(1)])
        self.r.register_card(CardDefinition('observer','observer',CardType.MINION,health=2,triggers=(TriggerSpec('choice_selected','shuffle'),)))
        self.script();g=self.game(board=('observer',));target=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        self.assertEqual(g.state.players[1].deck[0],target);self.check(g)

    def test_unknown_callback_is_rejected_even_with_empty_deck(self):
        self.script(lambda c:[Dredge(1,on_select='unknown')]);g=self.game(deck=());before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_invalid_specifications_reject_bool_ids_and_bad_callbacks(self):
        ref=CardReference(1,1,Zone.DECK,'a',0)
        for fn in (lambda:Dredge(True),lambda:Dredge(1,owner_id=0),lambda:Dredge(1,on_select=''),
            lambda:Dredge(1,reveal=1),lambda:SelectDredgedCard(Dredge(2),ref),
            lambda:CopyStoredMinion(ref,1,mode='guess'),lambda:CardPreview(-1,0,0,0,0)):
            with self.subTest(fn=fn),self.assertRaises(ValueError):fn()

    def test_callback_exception_restores_choice_order_rng_and_payment(self):
        def fail(c):raise ValueError('selected failure')
        self.callback(fail);g=self.game();self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'d')
        self.assertEqual(g.snapshot(),before)

    def test_option_limit_rolls_back_request_and_offer_randomization(self):
        self.script();g=self.game(rules=Ruleset(max_choice_options=2));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_callback_resolution_budget_exhaustion_restores_selection(self):
        self.callback(lambda c:[GainArmor(1,1)]*100);g=self.game(rules=Ruleset(max_resolution_steps=55))
        self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.choose(g,'e')
        self.assertEqual(g.snapshot(),before)

    def test_automatic_spell_dredge_resolves_without_player_prompt(self):
        self.script();self.script(lambda c:[CastSpell(1,'script',c.source_id)],'auto')
        g=self.game(hand=('auto',));self.play(g,'auto');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(sum(e.kind=='card_dredged' for e in g.events),1);self.check(g)

    def test_automatic_spell_can_request_dredge_from_player(self):
        self.script();self.script(lambda c:[CastSpell(1,'script',c.source_id,choices='player')],'auto')
        g=self.game(hand=('auto',));self.play(g,'auto');self.check(g);self.choose(g,'c');self.check(g)

    def test_repeated_spell_asks_again_using_changed_deck(self):
        self.script();self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=2,spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
        g=self.game(board=('aura',));self.play(g);self.choose(g,'e')
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'b','c','d'})
        self.choose(g,'d');self.assertEqual(sum(e.kind=='card_dredged' for e in g.events),2);self.check(g)

    def test_snapshot_rejects_unknown_callback_and_wrong_owner_reference(self):
        self.callback(lambda c:[]);g=self.game();self.play(g)
        for mutate in ('callback','owner'):
            snap=g.snapshot();effect=snap['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple'][0]['fields']
            if mutate=='callback':effect['spec']['fields']['on_select']='unknown'
            else:effect['card']['fields']['player_id']=2
            self.reject(snap)

    def test_snapshot_rejects_malformed_preview_and_missing_preview_field(self):
        self.script();g=self.game();self.play(g)
        for mutate in ('negative','missing'):
            snap=g.snapshot();item=snap['state']['pending_choice']['options'][0]
            if mutate=='negative':item['preview']['cost']=-1
            else:del item['preview']
            self.reject(snap)

    def test_player_port_stale_first_choice_cannot_submit_second(self):
        self.script(lambda c:[Dredge(1,source_id=c.source_id),Dredge(1,source_id=c.source_id)])
        g=self.game();self.play(g);port=g.for_player(1);first=port.legal_actions()
        cmd={'revision':first['revision'],'action':first['actions'][0]}
        self.assertTrue(port.submit(cmd)['accepted']);before=g.snapshot()
        self.assertFalse(port.submit(cmd)['accepted'])
        self.assertEqual(g.snapshot(),before);self.choose(g);self.check(g)

    def test_clones_resume_distinct_branches_without_sharing_deck_order(self):
        self.script();g=self.game();self.play(g);fork=g.clone();self.choose(g,'c');self.choose(fork,'e')
        self.assertNotEqual(g.state.players[1].deck,fork.state.players[1].deck);self.check(g);self.check(fork)

    def test_draw_reaction_cannot_make_callback_copy_a_different_top_card(self):
        self.r.register_behavior('draw',lambda c:[Draw(1)])
        self.r.register_card(CardDefinition('observer','observer',CardType.MINION,health=2,
            triggers=(TriggerSpec('card_dredged','draw'),)))
        self.callback(lambda c:[CopyCard(self.ref(c),1)])
        g=self.game(board=('observer',));original=g.state.players[1].deck[-1];self.play(g);self.choose(g,'e')
        self.assertEqual(g.state.players[1].hand,[original]);self.check(g)

    def test_selected_cost_result_remains_captured_after_reaction_draw(self):
        self.r.register_behavior('draw',lambda c:[Draw(1)])
        self.r.register_card(CardDefinition('observer','observer',CardType.MINION,health=2,
            triggers=(TriggerSpec('card_dredged','draw'),)))
        self.callback(lambda c:[GainArmor(1,c.state.entities[c.target_id].cost)])
        g=self.game(board=('observer',));self.play(g);self.choose(g,'e');self.assertEqual(self.armor(g),5);self.check(g)

    def test_bottom_insert_is_offered_on_the_next_dredge(self):
        self.script(lambda c:[AddToDeck(1,'a','bottom'),Dredge(1,source_id=c.source_id)])
        g=self.game();self.play(g);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'a','d','e'})
        self.choose(g,'a');self.check(g)

    def test_copy_stored_colossal_enters_with_appendages_and_one_original(self):
        from hs_sim.engine import AppendageSpec
        self.r.register_card(CardDefinition('big','big',CardType.MINION,attack=3,health=6,keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('a'),)))
        self.callback(lambda c:[CopyStoredMinion(self.ref(c),1,stats=SummonStats(attack=2,health=2))])
        g=self.game(deck=('big',));original=g.state.players[1].deck[0];self.play(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(g.state.players[1].deck,[original]);self.check(g)

    def test_copied_hand_minion_can_summon_to_other_player_with_new_owner(self):
        self.script(lambda c:[CopyStoredMinion(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),2)])
        g=self.game(hand=('script','a'));original=g.state.players[1].hand[-1];self.play(g)
        entity=g.state.entities[g.state.players[2].board[0]]
        self.assertEqual((entity.owner,entity.controller,entity.origin_entity_id),(2,2,original));self.check(g)

    def test_dredge_preserves_physical_attributes_and_attachments(self):
        self.callback(lambda c:[])
        g=self.game();self.play(g);before=[g.state.entities[i] for i in g.state.players[1].deck];self.choose(g,'d')
        for e in before:
            current=g.state.entities[e.id]
            self.assertEqual((current.base_cost,current.enchantments,current.abilities),(e.base_cost,e.enchantments,e.abilities))

    def test_public_selection_snapshot_does_not_change_after_later_cost_reduction(self):
        self.r.register_behavior('selected',lambda c:[ModifyCost(c.target_id,CostSpec(delta=-3))])
        self.script(lambda c:[Dredge(1,source_id=c.source_id,on_select='selected',reveal=True)])
        g=self.game();self.play(g);self.choose(g,'e')
        event=next(e for e in g.player_events(2) if e['kind']=='card_dredged')
        self.assertEqual(event['dredge']['selected']['preview']['cost'],5)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].cost,2);self.check(g)

    def test_snapshot_rejects_candidate_branch_metadata_mismatch(self):
        self.script();g=self.game();self.play(g);snap=g.snapshot()
        branch=snap['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple'][0]['fields']
        branch['card']['fields']['card_id']='a';self.reject(snap)

    def test_snapshot_rejects_private_result_added_to_opponent_log(self):
        self.script();g=self.game();self.play(g);self.choose(g,'c');snap=g.snapshot()
        event=next(e for e in snap['information']['players']['2']['events'] if e['kind']=='card_dredged')
        own=next(e for e in snap['information']['players']['1']['events'] if e['kind']=='card_dredged')
        event['dredge']['selected']=own['dredge']['selected'];self.reject(snap)


class DredgeRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()

    def game(self, hand, deck, enemy=(), board=(), enemy_board=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=10,max_mana=10),
            PlayerSetup('HERO_01',deck=enemy,board=enemy_board)),seed=54),self.r)

    def use(self,g,cid):
        g.apply(PlayCard(1,g.state.players[1].hand[0]));ch=g.state.pending_choice
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        g.apply(SelectChoice(1,ch.id,(next(o.id for o in ch.options if o.card_id==cid),)))
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_disarming_elemental_modifies_opponent_selected_card_only(self):
        g=self.game(('TID_700',),('CS2_182',),('CS2_029','CS2_024','EX1_019'))
        target=g.state.players[2].deck[-1];self.use(g,'EX1_019')
        self.assertEqual(g.state.players[2].deck[0],target);self.assertEqual(g.state.entities[target].cost,6)
        self.assertIsNone(next(e for e in g.player_events(2) if e['kind']=='card_dredged')['dredge']['selected'])

    def test_k9_summons_original_one_cost_minion_without_battlecry(self):
        g=self.game(('TID_099',),('CS2_188',));original=g.state.players[1].deck[0];self.use(g,'CS2_188')
        self.assertIn(original,g.state.players[1].board);self.assertFalse(g.state.players[1].deck)
        self.assertEqual(len(g.state.play_history),1)

    def test_burrower_summons_two_two_copy_and_keeps_original(self):
        g=self.game(('TID_003',),('TID_003',));original=g.state.players[1].deck[0];self.use(g,'TID_003')
        copy=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((copy.attack,copy.health,copy.origin_entity_id),(2,2,original))
        self.assertEqual(g.state.players[1].deck,[original])

    def test_idol_reveals_selected_cost_and_hits_both_boards_with_spell_power(self):
        g=self.game(('TID_703',),('CS2_182',),board=('EX1_012',),enemy_board=('CS2_182',))
        self.use(g,'CS2_182');damage=[e.amount for e in g.events if e.kind=='damage_dealt']
        self.assertEqual(damage,[5,5]);self.assertEqual(len(g.state.death_history),2)
        self.assertEqual(next(e for e in g.player_events(2) if e['kind']=='card_dredged')['dredge']['selected']['card_id'],'CS2_182')

    def test_k9_non_minion_or_non_one_cost_remains_in_deck(self):
        for cid in ('CS2_182','GAME_005'):
            with self.subTest(cid=cid):
                g=self.game(('TID_099',),(cid,));self.use(g,cid)
                self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(len(g.state.players[1].deck),1)

    def test_burrower_non_murloc_is_not_summoned(self):
        g=self.game(('TID_003',),('CS2_182',));self.use(g,'CS2_182')
        self.assertEqual(len(g.state.players[1].board),1)


if __name__=='__main__':unittest.main()
