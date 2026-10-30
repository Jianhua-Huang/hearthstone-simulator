"""Original payment facts, cast/hand-play distinction and complete discoveries."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_shaman_ranks_overload import fixture as prior_fixture,A,B,DORMANT,POWER,SHIELD,IMMUNE
from hs_sim.cards import build_registry,past_shaman_history_prices as native
from hs_sim.engine.costs import capture_cost_input,capture_quote_fact
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import (AddCostModifier,ChoiceOption,Damage,InvokeBehavior,RandomDamage,RequestChoice,UnlockOverload)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,PlayerOverloadCostSpec,PlayerSpellCountCostSpec,SpellSchool,TargetSpec,TriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

CHORD,CALL,CRASH=native.ROOTS
BOLT,ELEMENTAL='EX1_238','AT_051'
P='k676.'
NATURE,FIRE,UNLOCK,DISCOUNT,HURT,WATCH,FAIL,AUTO,COUNTER=(P+x for x in
    ('nature','fire','unlock','discount','hurt','watch','fail','auto','counter'))
CTX=GenerationContext('k676-complete-tier-fixture','experimental')
TIERS=tuple(P+'tier'+str(i)for i in range(1,12))
PRE_ENTRY=P+'pre_entry'


@lru_cache(None)
def original(role):return build_registry()


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=prior_fixture('k676-'+role);native.register_past_shaman_history_prices(r)
    source=original(role);card=source.card(BOLT)
    r.register_behavior(card.on_play,source.behavior(card.on_play));r.register_card(card)
    if BOLT not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(card))
    for cost,cid in enumerate(TIERS,1):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=20,
            battlecry=P+'reward',metadata=metadata(tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(P+'reward',lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id),))
    r.register_pool(PoolDefinition('constructed.cards','k676-whole-tier-fixture',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in TIERS),complete=True))
    bodies={NATURE:lambda c:(),FIRE:lambda c:(),UNLOCK:lambda c:(UnlockOverload(c.player_id),),
        DISCOUNT:lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.SPELL,)),source_id=c.source_id),),
        HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,20,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            spell_school=SpellSchool.NATURE if cid==NATURE else SpellSchool.FIRE if cid==FIRE else None,
            metadata=metadata(collectible=False)))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,BOLT,c.source_id,target_id=c.state.players[3-c.player_id].hero_id,targeting='explicit'),)
        if c.event.player_id==c.player_id else())
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,health=30,
        triggers=(TriggerSpec('turn_started',AUTO),),metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].card_id==BOLT else())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=30,
        triggers=(TriggerSpec('card_committed',COUNTER),),metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K676 deliberate rollback')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in(CHORD,CRASH):return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Unlock',(UnlockOverload(c.player_id),)),
            ChoiceOption('fault','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('damage_dealt',WATCH),),metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(PRE_ENTRY,lambda c:(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),)
        if c.event.player_id==c.player_id and c.state.entities[c.event.source_id].kind==CardType.MINION else())
    r.register_card(CardDefinition(PRE_ENTRY,PRE_ENTRY,CardType.MINION,health=30,
        triggers=(TriggerSpec('card_committed',PRE_ENTRY),),metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


class ShamanHistoryPriceTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(B,),enemy_hand=(),deck=('card.1',)*14,owed=0,locked=0):
        self.mode='small'
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,mana=10-locked,max_mana=10,overload_owed=owed,overload_locked=locked),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy,deck=('card.2',)*14,mana=10,max_mana=10)),seed=676,generation_context=CTX),fixture('writer'))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def price(self,g,cid):return capture_quote_fact(g.state,g.registry,capture_cost_input(self.entity(g,cid)))
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            key=g.state.pending_choice.options[0].id
            self.choose(g,key);n+=1;self.assertLess(n,20)
    def summoned(self,g):return [g.state.entities[e].card_id for e in g.state.players[1].board if g.state.entities[e].card_id in TIERS]

    def test_three_original_faces_fourteen_primary_faces_and_full_source_overload_classification(self):
        d=native.load_batch();r=fixture('writer');known,rows=native.printed_overload_source()
        self.assertEqual((len(d['cards']),len(d['official_observations']),len(rows),len(known)),(3,14,98,23452))
        overload={v['id']for v in rows};self.assertNotIn(CHORD,overload);self.assertNotIn(CALL,overload)
        self.assertIn(BOLT,overload);self.assertIn(ELEMENTAL,overload)
        self.assertTrue(overload-set(r.cards));self.assertFalse(d['membership_uses_executable_coverage'])
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])

    def test_chord_ordinary_price_six_damage_and_native_lifesteal(self):
        g=self.game((HURT,CHORD));self.play(g,HURT);target=g.state.players[2].board[0]
        self.assertEqual(self.price(g,CHORD).amount,5);self.play(g,CHORD,target)
        self.assertEqual((g.state.players[1].mana,self.hero(g).health,g.state.entities[target].health),(5,16,24))
        self.portable(g)

    def test_chord_pending_overload_discounts_three_before_actual_next_turn_lock(self):
        g=self.game((BOLT,CHORD));self.play(g,BOLT,self.hero(g,2).id)
        self.assertEqual((g.state.players[1].overload_owed,g.state.players[1].overload_locked),(1,0))
        quote=self.price(g,CHORD);fact=quote.intrinsic.player_overload
        self.assertEqual(g.quote_cost(self.entity(g,CHORD).id).amount,quote.amount)
        self.assertEqual((quote.amount,fact.quantity,fact.current_owed,fact.current_locked),(2,3,1,0))
        self.play(g,CHORD,g.state.players[2].board[0]);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_chord_locked_only_account_discounts_and_unlock_removes_discount_despite_old_history(self):
        g=self.game((BOLT,CHORD,UNLOCK));self.play(g,BOLT,self.hero(g,2).id);self.cycle(g)
        self.assertEqual((g.state.players[1].overload_owed,g.state.players[1].overload_locked),(0,1))
        self.assertEqual(self.price(g,CHORD).amount,2);self.play(g,UNLOCK)
        self.assertEqual(self.price(g,CHORD).amount,5);self.assertEqual(len(g.state.overload_history),1);self.portable(g)

    def test_chord_initial_scenario_accounts_qualify_without_inventing_historical_overload(self):
        for owed,locked in((2,0),(0,2),(1,2)):
            g=self.game((CHORD,),owed=owed,locked=locked)
            self.assertEqual(g.state.overload_history,[]);self.assertEqual(self.price(g,CHORD).amount,2)
            self.play(g,CHORD,g.state.players[2].board[0]);self.portable(g)

    def test_chord_many_crystals_still_flat_three_and_player_cost_modifiers_apply_after_intrinsic(self):
        g=self.game((ELEMENTAL,CHORD,DISCOUNT));self.play(g,ELEMENTAL)
        self.assertEqual(self.price(g,CHORD).amount,2);self.play(g,DISCOUNT)
        self.assertEqual(self.price(g,CHORD).amount,0);self.play(g,CHORD,g.state.players[2].board[0]);self.portable(g)

    def test_enemy_overload_does_not_discount_current_players_chord(self):
        g=self.game((CHORD,),enemy_hand=(BOLT,));g.apply(EndTurn(1));self.play(g,BOLT,self.hero(g).id,player=2);g.apply(EndTurn(2))
        self.assertEqual(self.price(g,CHORD).amount,5)

    def test_chord_rejects_hero_and_dormant_targets_before_payment(self):
        for which in('hero','dormant'):
            g=self.game((CHORD,),enemy=(DORMANT,B));before=g.snapshot()
            target=self.hero(g,2).id if which=='hero'else g.state.players[2].board[0]
            with self.assertRaises(IllegalAction):self.play(g,CHORD,target)
            self.assertEqual(g.snapshot(),before)

    def test_paid_current_overload_fact_survives_wait_unlock_new_price_and_failed_resume(self):
        g=self.game((BOLT,CHORD,CHORD),board=(WATCH,));self.play(g,BOLT,self.hero(g,2).id)
        self.play(g,CHORD,g.state.players[2].board[0]);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(self.price(g,CHORD).amount,5)
        paid=next(v for v in g.state.play_history if v.card_id==CHORD).submitted_cost.quote.intrinsic.player_overload
        self.assertEqual((paid.current_owed,paid.current_locked,paid.quantity),(1,0,3));self.portable(g)

    def test_crash_counts_only_own_actual_nature_casts_and_does_not_include_own_future_payload(self):
        g=self.game((NATURE,FIRE,CRASH));self.assertEqual(self.price(g,CRASH).amount,5)
        self.play(g,FIRE);self.assertEqual(self.price(g,CRASH).amount,5)
        self.play(g,NATURE);self.assertEqual(self.price(g,CRASH).amount,4)
        fact=self.price(g,CRASH).intrinsic.player_spells;self.assertEqual((fact.quantity,fact.turn),(1,g.state.turn))
        self.play(g,CRASH);self.assertEqual(g.state.players[1].mana,6)
        paid=g.state.play_history[-1].submitted_cost.quote.intrinsic.player_spells;self.assertEqual(paid.quantity,1)
        self.portable(g)

    def test_crash_current_turn_counts_reset_on_any_turn_change_and_opponent_casts_do_not_count(self):
        g=self.game((NATURE,CRASH),enemy_hand=(NATURE,));self.play(g,NATURE)
        self.assertEqual(self.price(g,CRASH).amount,4);g.apply(EndTurn(1))
        self.assertEqual(self.price(g,CRASH).amount,5);self.play(g,NATURE,player=2)
        self.assertEqual(self.price(g,CRASH).amount,5);g.apply(EndTurn(2));self.assertEqual(self.price(g,CRASH).amount,5)
        self.portable(g)

    def test_crash_real_automatic_bolt_counts_but_countered_nature_hand_attempt_does_not(self):
        g=self.game((CRASH,),board=(AUTO,));self.cycle(g)
        self.assertEqual([c.origin for c in g.state.cast_history],['effect'])
        self.assertEqual(self.price(g,CRASH).amount,4)
        g=self.game((BOLT,CRASH),enemy=(COUNTER,));self.play(g,BOLT,self.hero(g,2).id)
        self.assertEqual(g.state.cast_history[0].failure,'countered');self.assertEqual(self.price(g,CRASH).amount,5)
        self.portable(g)

    def test_five_actual_nature_casts_floor_crash_at_zero(self):
        g=self.game((NATURE,)*5+(CRASH,))
        for _ in range(5):self.play(g,NATURE)
        self.assertEqual(self.price(g,CRASH).amount,0);self.play(g,CRASH)
        self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_crash_hits_only_all_enemy_active_characters_with_shared_spell_damage(self):
        g=self.game((CRASH,),board=(POWER,A),enemy=(B,DORMANT,SHIELD,IMMUNE))
        ordinary,dormant,shield,immune=g.state.players[2].board;self.play(g,CRASH)
        self.assertEqual(self.hero(g,2).health,25);self.assertEqual(g.state.entities[ordinary].health,25)
        self.assertEqual([g.state.entities[e].health for e in(dormant,shield,immune)],[30,30,30])
        self.assertEqual([g.state.entities[e].health for e in g.state.players[1].board],[30,30]);self.portable(g)

    def test_crash_paid_turn_prefix_stays_frozen_after_wait_and_remaining_same_turn_price_uses_later_cast(self):
        g=self.game((NATURE,CRASH,CRASH),board=(WATCH,));self.play(g,NATURE);self.play(g,CRASH)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.finish(g)
        paid=next(v for v in g.state.play_history if v.card_id==CRASH).submitted_cost.quote.intrinsic.player_spells
        self.assertEqual(paid.quantity,1);self.assertEqual(self.price(g,CRASH).amount,3)
        self.cycle(g);self.assertEqual(self.price(g,CRASH).amount,5);self.portable(g)

    def test_call_initial_tier_one_is_discovered_directly_to_board_without_battlecry_or_hand_arrival(self):
        g=self.game((CALL,),enemy=());self.play(g,CALL);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana,7);g=self.portable(g);self.finish(g)
        self.assertEqual(self.summoned(g),[TIERS[0]]);self.assertEqual(self.hero(g,2).health,30)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].hand,[]);self.portable(g)

    def test_call_two_actual_overload_cards_raise_two_tiers_regardless_three_crystals(self):
        g=self.game((BOLT,ELEMENTAL,CALL));self.play(g,BOLT,self.hero(g,2).id);self.play(g,ELEMENTAL)
        self.assertEqual(sum(v.amount for v in g.state.overload_history),3)
        self.play(g,CALL);self.finish(g);self.assertEqual(self.summoned(g),[TIERS[2]]);self.portable(g)

    def test_call_countered_actual_overload_card_counts_despite_no_added_crystals(self):
        g=self.game((BOLT,CALL),enemy=(COUNTER,));self.play(g,BOLT,self.hero(g,2).id)
        self.assertEqual(g.state.overload_history,[]);self.play(g,CALL);self.finish(g)
        self.assertEqual(self.summoned(g),[TIERS[1]]);self.portable(g)

    def test_call_actual_automatic_overload_cast_is_not_an_overload_card_play(self):
        g=self.game((CALL,),board=(AUTO,),enemy=());self.cycle(g)
        self.assertEqual(len(g.state.overload_history),1);self.assertEqual(g.state.play_history,[])
        self.play(g,CALL);self.finish(g);self.assertEqual(self.summoned(g),[TIERS[0]]);self.portable(g)

    def test_call_related_nature_spell_and_its_own_original_play_are_not_overload_cards(self):
        g=self.game((CHORD,CALL));self.play(g,CHORD,g.state.players[2].board[0]);self.play(g,CALL);self.finish(g)
        self.assertEqual(self.summoned(g),[TIERS[0]]);self.portable(g)

    def test_call_caps_tier_at_ten_after_ten_actual_overload_cards(self):
        g=self.game((BOLT,)*10,enemy=(B,),deck=(CALL,'card.1'))
        for _ in range(10):self.play(g,BOLT,g.state.players[2].board[0])
        self.cycle(g);self.cycle(g)
        self.assertEqual(len([v for v in g.state.play_history if v.card_id==BOLT]),10)
        self.play(g,CALL);self.finish(g);self.assertEqual(self.summoned(g),[TIERS[9]]);self.portable(g)

    def test_call_unknown_original_classification_is_explicit_and_whole_action_rolls_back(self):
        g=self.game((NATURE,CALL));self.play(g,NATURE);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CALL)
        self.assertEqual(g.snapshot(),before)

    def test_new_price_operands_reject_wrong_profile_future_turn_bool_accounts_and_wrong_quantity(self):
        g=self.game((BOLT,CHORD,CRASH));self.play(g,BOLT,self.hero(g,2).id)
        chord=self.price(g,CHORD).intrinsic.player_overload;crash=self.price(g,CRASH).intrinsic.player_spells
        for value in(True,-1,None):
            with self.assertRaises(ValueError):replace(chord,current_owed=value)
        with self.assertRaises(ValueError):replace(chord,quantity=1)
        with self.assertRaises(ValueError):replace(chord,current_locked=True)
        with self.assertRaises(ValueError):replace(chord,spec=PlayerOverloadCostSpec())
        with self.assertRaises(ValueError):replace(crash,turn=0)
        with self.assertRaises(ValueError):replace(crash,spec=PlayerSpellCountCostSpec())
        with self.assertRaises(ValueError):replace(self.price(g,CRASH).intrinsic,player_spells=replace(crash,turn=crash.turn+1))

    def test_current_codec_roundtrip_uses_new_fields_and_rejects_previous_schema(self):
        g=self.game((BOLT,CHORD,CRASH));self.play(g,BOLT,self.hero(g,2).id);self.play(g,CHORD,g.state.players[2].board[0]);self.play(g,CRASH)
        self.portable(g);saved=g.snapshot()
        self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION);self.assertEqual(saved['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        old=deepcopy(saved);old['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,fixture('independent-reader'))

    def test_original_minion_play_enters_after_real_commit_choice_on_later_resume_action(self):
        g=self.game((TIERS[0],),board=(PRE_ENTRY,));source=self.play(g,TIERS[0])
        self.assertIsNotNone(g.state.pending_choice);self.assertIsNone(g.state.play_history[-1].minion_entry)
        g=self.portable(g);self.finish(g)
        play=g.state.play_history[-1];event=next(e for e in g.events if e.kind=='minion_play_accepted')
        self.assertGreater(event.action,play.action);self.assertEqual(event.source_id,source)
        self.assertEqual(play.minion_entry.reference.entity_id,source);self.assertEqual(self.hero(g,2).health,29)
        self.portable(g)

    def test_minion_entry_still_rejects_preplay_action_wrong_source_owner_target_and_duplicate(self):
        from hs_sim.engine.minion_play_entries import validate_boundary
        g=self.game((TIERS[0],));self.play(g,TIERS[0]);index=next(i for i,e in enumerate(g.events)if e.kind=='minion_play_accepted')
        original=g.events[index];play=g.state.play_history[-1]
        for changed in(replace(original,action=play.action-1),replace(original,source_id=self.hero(g,2).id),
                replace(original,player_id=2),replace(original,target_id=self.hero(g,2).id)):
            altered=g.clone();altered._events[index]=changed
            with self.assertRaises(ValueError):validate_boundary(altered)
        altered=g.clone();altered._events.append(original)
        with self.assertRaises(ValueError):validate_boundary(altered)

    def test_real_standard_host_discovers_complete_current_tier_and_plays_both_original_cost_consumers(self):
        self.mode='host';h=host('writer');deck=('CORE_EX1_169',)*12
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(BOLT,CHORD,CALL,CRASH),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('LOOT_077t',),deck=deck,mana=10,max_mana=10)),seed=676,generation_context=h.context),h.registry)
        self.play(g,BOLT,g.state.players[2].hero_id);self.assertEqual(self.price(g,CHORD).amount,2)
        self.play(g,CHORD,g.state.players[2].board[0]);self.assertEqual(self.price(g,CRASH).amount,3)
        self.play(g,CALL);g=self.portable(g);self.finish(g)
        self.assertTrue(g.state.players[1].board);self.assertEqual(g.state.entities[g.state.players[1].board[0]].base_cost,2)
        self.cycle(g);self.play(g,CRASH);self.portable(g)
