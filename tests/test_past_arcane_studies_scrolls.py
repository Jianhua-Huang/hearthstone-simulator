"""Real Studies quotations and original Wonder Scroll draw/cast chains."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_studies_scrolls as native
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass, CardDefinition, CardType, CastSpell, EndTurn, Game,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.card_conditions import matches_ability
from hs_sim.engine.costs import matches_cost_values, quote_cost, quote_generated_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor, GrantSpellDamage,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.model import CardAbilityCondition, CardMetadata, ChoicePurpose, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

DECK, STUDIES, SCROLL = native.DEPENDENCIES
LAB, BLOOD, CONDITIONAL = 'SCH_310','CORE_EX1_012','END_022'
P = 'k599.'
UNIT, PLAIN, DRAW, FILL_DRAW, FOREIGN, AUTO_STUDIES, AUTO_DECK, GRANT_COPY, SILENCE_COPY, MOVE, FAULT, SCHOOL = (
    P+x for x in ('unit','plain','draw','fill_draw','foreign','auto_studies','auto_deck','grant_copy','silence_copy','move','fault','school'))
ACQUIRE_WAIT, DRAW_WAIT, SHUFFLE_WAIT, FILL_WAIT = (P+x for x in ('acquire_wait','draw_wait','shuffle_wait','fill_wait'))
CTX = GenerationContext('k599-complete-explicit-diagnostic-domain','experimental')
META = CardMetadata(True,(CardClass.PALADIN,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r = build_registry()
    def fail(c):raise ResolutionError('K599 deliberate original continuation failure')
    def board_ref(c):return MinionReference.capture(c.state.entities[c.state.players[c.player_id].board[0]])
    def copied(c,silence=False):
        ref = board_ref(c)
        return ((Silence(ref.entity_id)if silence else GrantSpellDamage(ref.entity_id,1,c.source_id)),
            CopyCard(ref,c.player_id,mode='current',source_id=c.source_id))
    def move(c):return (MoveCard(CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]]),
        c.player_id,Zone.HAND,source_id=c.source_id),)
    def watch(c):
        event = c.event;source = c.state.entities.get(event.source_id);target = c.state.entities.get(event.target_id)
        if event.player_id != c.player_id:return ()
        cid = c.source.card_id
        if cid == FILL_WAIT and event.kind == 'choice_requested' and source is not None and source.card_id == STUDIES:
            return (AddToHand(c.player_id,PLAIN,c.source_id),)
        acquired = cid == ACQUIRE_WAIT and event.kind == 'card_added_to_hand' and source is not None and source.card_id == STUDIES
        drawn = cid == DRAW_WAIT and event.kind == 'card_drawn' and target is not None and target.card_id == SCROLL
        shuffled = cid == SHUFFLE_WAIT and event.kind == 'card_added_to_deck' and source is not None and source.card_id == DECK
        if acquired or drawn or shuffled:
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
        return ()
    bodies = {FAULT:fail, PLAIN:lambda c:(), DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        FILL_DRAW:lambda c:(AddToHand(c.player_id,PLAIN,c.source_id),Draw(c.player_id,1,c.source_id)),
        FOREIGN:lambda c:(GainArmor(c.player_id,3),), AUTO_STUDIES:lambda c:(CastSpell(c.player_id,STUDIES,c.source_id),),
        AUTO_DECK:lambda c:(CastSpell(c.player_id,DECK,c.source_id),CastSpell(c.player_id,DECK,c.source_id)),
        GRANT_COPY:lambda c:copied(c), SILENCE_COPY:lambda c:copied(c,True), MOVE:move}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            cost=3 if cid == FOREIGN else 0,metadata=META if cid == FOREIGN else None))
    r.register_pool_card(PoolCard.from_definition(r.card(FOREIGN)))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=2,attack=1,health=6))
    r.register_card(CardDefinition(SCHOOL,SCHOOL,CardType.MINION,cost=3,attack=1,health=4,
        spell_damage=2,spell_damage_schools=(SpellSchool.NATURE,)))
    r.register_behavior(P+'watch',watch)
    for cid in (ACQUIRE_WAIT,DRAW_WAIT,SHUFFLE_WAIT,FILL_WAIT):r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,
        triggers=tuple(TriggerSpec(k,P+'watch')for k in ('card_added_to_hand','card_drawn','card_added_to_deck','choice_requested'))))
    members = (FOREIGN,)if mode == 'empty_discovery'else (LAB,BLOOD,FOREIGN)
    if mode == 'empty_scroll':members = (LAB,BLOOD)
    if mode == 'unknown_minion':
        raw = next(x['record']for x in native.load_batch()['spell_damage_eligibility_records']if x['record']['id'] == 'TTN_071')
        assert raw['id']not in r.cards
        r.register_pool_card(PoolCard(raw['id'],CardType.MINION,raw['cost'],metadata_from_record(raw)));members += (raw['id'],)
    if mode == 'unknown_spell':
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,1,META));members = (P+'unknown',)
    r.register_pool(PoolDefinition(native.POOL,P+'complete-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


class PastArcaneStudiesScrollTests(CardBatchTestMixin,unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(registry)

    def game(self,hand=(),*,deck=(),board=(),player=1,mode='normal'):
        self.mode = mode
        players = tuple(PlayerSetup('HERO_08',hand=hand if p == player else (),deck=deck if p == player else (PLAIN,)*6,
            board=board if p == player else (),mana=20,max_mana=20,mana_cap=20)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=599,generation_context=CTX),registry(mode))

    def pick(self,g,cid=LAB):
        q = g.state.pending_choice;self.assertEqual(q.purpose,ChoicePurpose.POOL_DISCOVERY)
        self.choose(g,next(o.id for o in q.options if o.card_id == cid))

    def cost(self,g,cid):return quote_cost(g.state,g.registry,self.entity(g,cid)).amount

    def test_three_full_sources_six_primary_faces_and_independent66_printed_identities(self):
        data = native.load_batch();rows = {x['record']['id']:x['record']for x in data['dependencies']}
        for observation in data['official_observations']:batch.check_face(rows[observation['card_id']],observation['face'],observation['locale'])
        self.assertEqual((len(data['dependencies']),len(data['official_observations'])),(3,6))
        self.assertEqual((len(data['spell_damage_eligibility_records']),len(data['printed_spell_damage_ids'])),(86,66))
        eligible = set(data['printed_spell_damage_ids'])
        self.assertTrue({'AT_006','WON_029','BAR_048','TSC_635','TOY_807','TTN_071','END_022','TRL_312'}<=eligible)
        self.assertTrue({'BT_724','SCH_400','SCH_530','TOY_801'}.isdisjoint(eligible))
        self.assertFalse(data['eligibility_uses_executable_coverage']);self.assertEqual(native.COLLECTIBLE_ROOTS,())
        self.assertEqual([registry().card(cid).cost for cid in native.DEPENDENCIES],[5,1,5])

    def test_studies_both_actors_pay_one_discover_a_real_minion_and_spend_next_discount(self):
        for player in (1,2):
            g = self.game((STUDIES,),player=player);self.play(g,STUDIES,player=player)
            self.assertEqual(g.state.players[player].mana,19);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{LAB,BLOOD})
            self.pick(g);copy = self.entity(g,LAB,player);self.assertEqual(quote_cost(g.state,g.registry,copy).amount,0)
            self.assertEqual(len(g.state.players[player].cost_modifiers),1)
            g.apply(PlayCard(player,copy.id));self.assertEqual(g.state.play_history[-1].cost,0)
            self.assertFalse(g.state.players[player].cost_modifiers);self.portable(g)

    def test_next_discount_applies_to_existing_held_provider_and_ignores_other_plays(self):
        g = self.game((STUDIES,BLOOD,UNIT));self.play(g,STUDIES);self.pick(g)
        self.assertEqual((self.cost(g,BLOOD),self.cost(g,LAB),self.cost(g,UNIT)),(1,0,2))
        self.play(g,UNIT);self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        self.play(g,BLOOD);self.assertEqual(g.state.play_history[-1].cost,1)
        self.assertFalse(g.state.players[1].cost_modifiers);self.assertEqual(self.cost(g,LAB),1);self.portable(g)

    def test_studies_stack_and_unspent_next_discount_survives_turn_changes(self):
        g = self.game((STUDIES,STUDIES,BLOOD),deck=(PLAIN,)*3)
        for _ in range(2):self.play(g,STUDIES);self.pick(g)
        self.assertEqual(self.cost(g,BLOOD),0);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(self.cost(g,BLOOD),0);self.play(g,BLOOD)
        self.assertEqual(g.state.play_history[-1].cost,0);self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)

    def test_empty_discovery_and_automatic_studies_still_create_exactly_one_next_modifier(self):
        g = self.game((STUDIES,BLOOD),mode='empty_discovery');rng = g._rng.getstate();self.play(g,STUDIES)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.cost(g,BLOOD),1);self.portable(g)
        g = self.game((AUTO_STUDIES,));self.play(g,AUTO_STUDIES)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual((g.state.players[1].mana,len(g.state.players[1].cost_modifiers)),(20,1));self.portable(g)

    def test_discovery_delivery_wait_installs_next_modifier_only_after_original_acquisition(self):
        g = self.game((STUDIES,),board=(ACQUIRE_WAIT,));self.play(g,STUDIES);self.pick(g)
        self.assertFalse(g.state.players[1].cost_modifiers);other = self.portable(g);before = other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other)
        self.assertEqual((len(other.state.players[1].cost_modifiers),self.cost(other,LAB)),(1,0));self.portable(other)

    def test_burned_discovery_still_grants_the_next_price(self):
        g = self.game((STUDIES,)+(PLAIN,)*9,board=(FILL_WAIT,));self.play(g,STUDIES);self.pick(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        self.assertTrue(any(e.kind == 'card_burned'for e in g.events));self.portable(g)

    def test_current_granted_copy_qualifies_and_frozen_quote_rejects_missing_original_ability(self):
        g = self.game((STUDIES,GRANT_COPY),board=(UNIT,));self.play(g,STUDIES);self.pick(g);self.play(g,GRANT_COPY)
        copy = self.entity(g,UNIT);self.assertEqual(quote_cost(g.state,g.registry,copy).amount,1)
        self.assertFalse(matches_ability(CardAbilityCondition('spell_damage',basis='printed'),g.registry.card(UNIT),copy))
        g.apply(PlayCard(1,copy.id));receipt = g.state.play_history[-1].submitted_cost.quote
        self.assertEqual(receipt.amount,1);validate_cost_quote_fact(g.registry,receipt)
        changed = replace(receipt,quote_input=replace(receipt.quote_input,abilities=tuple(a for a in receipt.quote_input.abilities if a.kind != 'spell_damage')))
        with self.assertRaises(ValueError):validate_cost_quote_fact(g.registry,changed)
        self.portable(g)

    def test_silenced_current_copy_does_not_borrow_its_printed_spell_damage(self):
        g = self.game((STUDIES,SILENCE_COPY),board=(LAB,));self.play(g,SILENCE_COPY);self.play(g,STUDIES);self.pick(g,BLOOD)
        copy = self.entity(g,LAB);self.assertEqual(quote_cost(g.state,g.registry,copy).amount,1)
        self.assertTrue(matches_ability(CardAbilityCondition('spell_damage',basis='printed'),g.registry.card(LAB),copy))
        g.apply(PlayCard(1,copy.id));self.assertEqual(len(g.state.players[1].cost_modifiers),1);self.portable(g)

    def test_conditional_school_and_generated_quotes_use_the_same_structural_presence(self):
        g = self.game((STUDIES,SCHOOL,CONDITIONAL));self.play(g,STUDIES);self.pick(g)
        self.assertEqual((self.cost(g,SCHOOL),self.cost(g,CONDITIONAL)),(2,0))
        modifiers = deepcopy(g.state.players[1].cost_modifiers)
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,LAB).amount,0)
        self.assertEqual(g.state.players[1].cost_modifiers,modifiers);self.portable(g)
        with self.assertRaises(ValueError):matches_cost_values(native.NEXT_COST,g.registry.card(LAB),True)
        with self.assertRaises(ValueError):PoolQuery(ability=CardAbilityCondition('spell_damage'))

    def test_unknown_eligible_minion_is_not_removed_to_make_studies_work(self):
        g = self.game((STUDIES,),mode='unknown_minion');before = g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,STUDIES)
        self.assertEqual(g.snapshot(),before)

    def test_deck_both_actors_pay_five_and_create_one_semantic_batch_of_five_new_scrolls(self):
        for player in (1,2):
            g = self.game((DECK,),deck=(PLAIN,PLAIN),player=player);old = set(g.state.entities)
            source = self.play(g,DECK,player=player);deck = g.state.players[player].deck
            scrolls = [i for i in deck if g.state.entities[i].card_id == SCROLL]
            self.assertEqual((g.state.players[player].mana,len(deck),len(scrolls)),(15,7,5))
            self.assertEqual(len(set(scrolls)-old),5);self.assertFalse(g.state.draw_history)
            row, = g.state.deck_shuffle_history;self.assertEqual((row.actor_id,row.player_id,row.declared_count,row.profile),(player,player,5,'semantic'))
            self.assertEqual(row.source.entity_id,source);self.portable(g)

    def test_deck_shuffle_wait_preserves_whole_original_batch_and_rolls_back_bad_reaction(self):
        g = self.game((DECK,),board=(SHUFFLE_WAIT,));self.play(g,DECK)
        self.assertEqual(len(g.state.players[1].deck),5);other = self.portable(g);before = other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before)
        while other.state.pending_choice is not None:self.choose(other)
        self.assertEqual(len(other.state.players[1].deck),5);self.assertEqual(len(other.state.deck_shuffle_history),1);self.portable(other)

    def test_two_automatic_decks_have_independent_five_card_operations_without_extra_payment(self):
        g = self.game((AUTO_DECK,));self.play(g,AUTO_DECK)
        self.assertEqual((g.state.players[1].mana,len(g.state.players[1].deck)),(20,10))
        self.assertEqual([row.declared_count for row in g.state.deck_shuffle_history],[5,5]);self.portable(g)

    def test_scroll_actual_draw_casts_foreign_class_spell_then_replaces_original_once(self):
        for player in (1,2):
            g = self.game((DRAW,),deck=(SCROLL,PLAIN),player=player);original = g.state.players[player].deck[0]
            self.play(g,DRAW,player=player)
            self.assertEqual([(row.card_id,row.parent_id)for row in g.state.draw_history],[(SCROLL,None),(PLAIN,1)])
            self.assertEqual(g.state.draw_history[0].entity_id,original);self.assertTrue(all(row.completed for row in g.state.draw_history))
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[player].hand],[PLAIN])
            self.assertEqual((g.state.entities[g.state.players[player].hero_id].armor,g.state.players[player].mana),(3,20))
            self.assertEqual(len([row for row in g.state.cast_history if row.card_id == FOREIGN]),1);self.portable(g)

    def test_chained_real_scrolls_finish_each_original_cast_before_replacement(self):
        g = self.game((DRAW,),deck=(SCROLL,SCROLL,SCROLL,PLAIN));self.play(g,DRAW)
        self.assertEqual([row.parent_id for row in g.state.draw_history],[None,1,2,3])
        self.assertTrue(all(row.completed for row in g.state.draw_history));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,9)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[PLAIN]);self.portable(g)

    def test_empty_random_spell_pool_still_finishes_original_scroll_and_replaces_without_rng(self):
        g = self.game((DRAW,),deck=(SCROLL,PLAIN),mode='empty_scroll');rng = g._rng.getstate();self.play(g,DRAW)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual([row.card_id for row in g.state.draw_history],[SCROLL,PLAIN])
        self.assertFalse(any(row.card_id == FOREIGN for row in g.state.cast_history));self.portable(g)

    def test_full_hand_burns_scroll_without_random_cast_or_replacement(self):
        g = self.game((FILL_DRAW,)+(PLAIN,)*9,deck=(SCROLL,PLAIN));self.play(g,FILL_DRAW)
        self.assertEqual([row.outcome for row in g.state.draw_history],['burned'])
        self.assertFalse(any(row.card_id in (SCROLL,FOREIGN)for row in g.state.cast_history));self.portable(g)

    def test_manual_scroll_and_ordinary_transfer_do_not_forge_draw_replacement(self):
        g = self.game((MOVE,),deck=(SCROLL,PLAIN));self.play(g,MOVE)
        self.assertFalse(g.state.draw_history);self.assertFalse(any(row.card_id == FOREIGN for row in g.state.cast_history))
        self.play(g,SCROLL);self.assertEqual(g.state.players[1].mana,15)
        self.assertFalse(g.state.draw_history);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3);self.portable(g)

    def test_original_draw_wait_preserves_pending_cast_rng_and_failed_reaction(self):
        g = self.game((DRAW,),deck=(SCROLL,PLAIN),board=(DRAW_WAIT,));self.play(g,DRAW)
        self.assertEqual(g.state.draw_history[0].phase,'pending_cast');self.assertFalse(any(row.card_id == SCROLL for row in g.state.cast_history))
        other = self.portable(g);before = other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other)
        self.assertEqual([row.card_id for row in other.state.draw_history],[SCROLL,PLAIN]);self.assertTrue(all(row.completed for row in other.state.draw_history));self.portable(other)

    def test_unknown_random_spell_rolls_back_physical_scroll_draw_instead_of_pruning(self):
        g = self.game((DRAW,),deck=(SCROLL,PLAIN),mode='unknown_spell');before = g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,DRAW)
        self.assertEqual(g.snapshot(),before)

    def test_private_cost_operands_and_old_schema_are_not_player_contracts(self):
        g = self.game((STUDIES,BLOOD));self.play(g,STUDIES);self.pick(g);self.portable(g)
        for player in (1,2):
            text = json.dumps(g.for_player(player).observe())
            for field in ('rng_state','resolution_frame','submitted_cost','contributions','card_ids','spell_damage_eligibility_records'):
                self.assertNotIn('"'+field+'"',text)
        old = g.snapshot();old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(ValueError):Game.from_snapshot(old,registry())

    def test_last_bad_scroll_metadata_rejects_before_partial_registration(self):
        target = 'hs_sim.cards.past_arcane_studies_scrolls.register_past_arcane_studies_scrolls'
        r = batch.registration_prefix(build_registry,target,native.register_past_arcane_studies_scrolls)
        data = deepcopy(native.load_batch());data['dependencies'][-1]['record']['cost'] = 6
        before = (dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=data),self.assertRaises(TargetValidationError):native.register_past_arcane_studies_scrolls(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)
