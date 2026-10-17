"""Printed Outcast identity is independent of Discover results and activation."""
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
from hs_sim.cards.printed_outcast_study_cards import STUDIES, LEGACY, QUERY, NEXT_COST, PRINTED_OUTCAST, POOL_ID, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice)
from hs_sim.engine.card_conditions import matches_ability, matches_ability_values
from hs_sim.engine.costs import matches_cost, matches_cost_values, quote_generated_cost
from hs_sim.engine.effects import AddCostModifier, AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import CardAbilityCondition, LimitedTriggerSpec, Rarity, SpellRepeatSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import canonical_digest

P = 'k127.test.'
RUNNER, SIGHT, YETI = 'CORE_BT_480', 'CORE_BT_491', 'CORE_CS2_182'
FOREIGN, UNKNOWN, UNKNOWN_PLAIN = P+'foreign', P+'unknown', P+'unknown_plain'
MEMBERS = (RUNNER, SIGHT, YETI, FOREIGN, STUDIES)
CTX = GenerationContext('k127-complete-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = build_registry()
    card = replace(r.card(RUNNER), id=FOREIGN, metadata=replace(r.card(RUNNER).metadata, classes=(CardClass.MAGE,)))
    r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    for cid in (UNKNOWN, UNKNOWN_PLAIN):
        if cid in members:
            r.register_pool_card(PoolCard(cid,CardType.SPELL,2,
                CardMetadata(True,(CardClass.DEMON_HUNTER,),Rarity.COMMON,tribes=(),factions=(),subtypes=()),
                keywords=(Keyword.OUTCAST,) if cid==UNKNOWN else (),battlecry=False,deathrattle=False,choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID,'k127-explicit-complete-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):
        raise ResolutionError('K127 deliberate price continuation failure')
    scripts={
        'counter':lambda c:(SetSecret(2,'EX1_287'),),
        'fail':fail,
        'before':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('get','Install original printed condition',(AddCostModifier(c.player_id,NEXT_COST,1,c.source_id),)),
            ChoiceOption('skip','Skip')),c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,metadata=META,on_play=P+name))
    r.register_card(CardDefinition(P+'repeat','Existing spell repeat',CardType.MINION,health=8,metadata=META,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
    if mode:
        def watch(c):
            if mode=='fill':return tuple(AddToHand(c.player_id,YETI,c.source_id)for _ in range(10-len(c.state.players[c.player_id].hand)))
            if mode=='mod_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_trigger_condition(P+'eligible',lambda c:c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==STUDIES)
        event='choice_selected'if mode=='fill'else'card_created'if mode=='acquire_wait'else'cost_modifier_added'
        r.register_card(CardDefinition(P+'watch','Real discovery/price observer',CardType.MINION,health=8,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class PrintedOutcastStudyTests(unittest.TestCase):
    def game(self,hand=(STUDIES,),members=MEMBERS,mode=None,pool=True,context=CTX,board=(),hero='HERO_10'):
        self.config=(members,mode,pool)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=(RUNNER,),deck=(YETI,)*8)),seed=127,generation_context=context),registry(*self.config))

    def first(self,g,cid,player=1):
        return next(g.state.entities[i]for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)

    def play(self,g,cid):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id

    def choose(self,g,cid=None,key=None):
        q=g.state.pending_choice
        if key is None:key=next(o.id for o in q.options if cid is None or o.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def study(self,g,cid=None):
        source=self.play(g,STUDIES)
        if g.state.pending_choice:self.choose(g,cid)
        return source

    def mods(self,g):return g.state.players[1].cost_modifiers

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry.__wrapped__(*self.config))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(*self.config)).snapshot(),saved)
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('resolution_frame','rng_state','cost_modifiers','player_modifiers','consumable_ids','ability','basis'):
                self.assertNotIn('"'+key+'"',view)
        return other

    def test_complete_two_rows_two_faces_source_not_outcast_and_explicit_legacy_identity(self):
        data=load_batch();raw=data['cards'][0]['record'];old=data['evidence_only'][0]['record'];card=registry().card(STUDIES)
        self.assertEqual((raw['tags']['858'],old['dbf_id']),(61939,61939));self.assertEqual(old['id'],LEGACY)
        for row in data['cards']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        self.assertEqual(len(data['official_observations']['observations']),2)
        for ob in data['official_observations']['observations']:
            en=ob['locale']=='en_US';self.assertEqual(ob['face']['name'],raw['name_en'if en else'name']);self.assertEqual(norm(ob['face']['text']),norm(raw['text_en'if en else'text']))
        self.assertEqual((card.cost,card.kind,card.metadata.classes,card.metadata.deck_identity),(1,CardType.SPELL,(CardClass.DEMON_HUNTER,),LEGACY))
        self.assertFalse(card.keywords);self.assertIsNone(card.spell_school);self.assertNotIn(LEGACY,registry().cards)
        self.assertFalse(data['cn_calibrated']);self.assertFalse(data['formal_pool_complete'])

    def test_one_definition_all_old_facts_and_default_identity_preserved_except_verified_source_pool_identity(self):
        with patch('hs_sim.cards.printed_outcast_study_cards.register_printed_outcast_study_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{STUDIES})
        self.assertTrue(all(asdict(c)==asdict(after.card(cid))for cid,c in before.cards.items()))
        self.assertEqual({cid:c for cid,c in before.pool_cards.items()if cid!=STUDIES},{cid:c for cid,c in after.pool_cards.items()if cid!=STUDIES})
        self.assertEqual(replace(after.pool_card(STUDIES),metadata=before.pool_card(STUDIES).metadata),before.pool_card(STUDIES))
        self.assertEqual(after.pool_card(STUDIES).metadata.deck_identity,LEGACY)
        self.assertEqual(dict(after.pools),dict(before.pools));self.assertEqual(dict(after.generation_families),dict(before.generation_families))
        from hs_sim.engine.representative import build_registry as defaults
        self.assertEqual(defaults().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_native_offer_uses_existing_printed_keyword_and_modifier_installs_only_after_discovery(self):
        g=self.game();self.play(g,STUDIES)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{RUNNER,SIGHT});self.assertFalse(self.mods(g))
        self.assertEqual(QUERY.keywords_all,(Keyword.OUTCAST,));self.assertIsNone(QUERY.ability)
        self.choose(g,RUNNER);m,=self.mods(g);self.assertEqual((m.spec,m.uses_remaining,m.expires_turn),(NEXT_COST,1,None))
        self.assertEqual(g.state.players[1].mana,39);self.assertFalse(g.state.draw_history);self.assertEqual(len(g.state.cast_history),1)

    def test_next_modifier_can_be_consumed_by_older_middle_minion_not_selected_spell(self):
        g=self.game(hand=(STUDIES,YETI,RUNNER,YETI));old=self.first(g,RUNNER).id;self.study(g,SIGHT);m,=self.mods(g)
        self.assertEqual(g.state.players[1].hand.index(old),1);self.assertEqual(g.quote_cost(old).amount,0)
        self.play(g,RUNNER);self.assertFalse(g.state.play_history[-1].outcast);self.assertFalse(g.state.draw_history);self.assertFalse(self.mods(g))
        self.assertEqual(g.state.players[1].mana,39);self.assertEqual(g.quote_cost(self.first(g,SIGHT).id).amount,2)
        receipt=next(x for x in g.state.cost_use_history if x.origin=='payment'and x.source_id==old)
        self.assertEqual((receipt.amount,receipt.consumable_ids),(0,(m.id,)))

    def test_next_modifier_matches_middle_spell_without_activating_outcast(self):
        g=self.game(hand=(STUDIES,YETI,SIGHT,YETI));old=self.first(g,SIGHT).id;self.study(g,RUNNER)
        self.assertEqual(g.state.players[1].hand.index(old),1);self.assertEqual(g.quote_cost(old).amount,1)
        self.play(g,SIGHT);self.assertFalse(g.state.play_history[-1].outcast);self.assertFalse(self.mods(g))
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(g.state.draw_history),1)
        self.portable(g)

    def test_unrelated_play_keeps_next_outcast_and_opponent_never_borrows_it(self):
        from hs_sim.engine.costs import quote_cost
        g=self.game(hand=(STUDIES,YETI,RUNNER));self.study(g,SIGHT);m,=self.mods(g)
        self.assertEqual(quote_cost(g.state,g.registry,self.first(g,RUNNER,2)).amount,1);self.play(g,YETI)
        self.assertEqual([x.id for x in self.mods(g)],[m.id]);self.assertEqual(g.quote_cost(self.first(g,RUNNER).id).amount,0)

    def test_two_studies_stack_both_one_use_sources_and_zero_floor_consumes_both(self):
        g=self.game(hand=(STUDIES,STUDIES,YETI,SIGHT,YETI),members=(RUNNER,));self.study(g);first_id=self.mods(g)[0].id;self.study(g)
        mods=self.mods(g);self.assertEqual(len(mods),2);self.assertEqual(mods[0].id,first_id)
        old=self.first(g,SIGHT).id;quote=g.quote_cost(old);self.assertEqual(quote.amount,0);self.assertEqual(set(quote.consumable_ids),{m.id for m in mods})
        self.play(g,SIGHT);self.assertFalse(self.mods(g));self.assertEqual(g.state.players[1].mana,38)

    def test_discount_survives_natural_turns_until_the_next_matching_payment(self):
        g=self.game(hand=(STUDIES,RUNNER));self.study(g,SIGHT);m,=self.mods(g);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual([x.id for x in self.mods(g)],[m.id]);self.assertEqual(g.quote_cost(self.first(g,RUNNER).id).amount,0)

    def test_countered_studies_has_no_discovery_discount_or_context_requirement(self):
        g=self.game(hand=(P+'counter',STUDIES),pool=False,context=None);self.play(g,P+'counter');self.play(g,STUDIES)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.mods(g));self.assertEqual(g.state.cast_history[-1].failure,'countered')

    def test_countered_matching_spell_still_pays_discounted_price_and_consumes_once(self):
        g=self.game(hand=(STUDIES,P+'counter',SIGHT));self.study(g,RUNNER);self.play(g,P+'counter');self.play(g,SIGHT)
        self.assertFalse(self.mods(g));self.assertEqual(g.state.players[1].mana,38);self.assertEqual(g.state.cast_history[-1].failure,'countered')

    def test_original_wait_restores_same_offer_without_new_rng_or_extra_price_source(self):
        g=self.game();self.play(g,STUDIES);other=self.portable(g);rng=g._rng.getstate()
        for game in (g,other):self.choose(game,RUNNER)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.mods(g)),1)

    def test_acquisition_wait_preserves_owed_modifier_and_failed_resume_rolls_back(self):
        g=self.game(members=(RUNNER,),mode='acquire_wait');self.play(g,STUDIES);self.choose(g)
        self.assertFalse(self.mods(g));saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'K127 deliberate'):self.choose(g,key='bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):self.choose(game,key='ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.mods(g)),1)

    def test_installed_modifier_wait_restores_exact_price_and_pending_finish(self):
        g=self.game(hand=(STUDIES,RUNNER),members=(SIGHT,),mode='mod_wait');self.play(g,STUDIES);self.choose(g)
        self.assertEqual(len(self.mods(g)),1);self.assertEqual(g.quote_cost(self.first(g,RUNNER).id).amount,0)
        other=self.portable(g)
        for game in(g,other):self.choose(game,key='ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.play(g,RUNNER);self.assertFalse(self.mods(g))

    def test_late_modifier_install_failure_rolls_back_selection_creation_and_price(self):
        g=self.game(members=(RUNNER,),mode='mod_fail');self.play(g,STUDIES);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K127 deliberate'):self.choose(g)
        self.assertEqual(g.snapshot(),saved)

    def test_full_hand_burn_still_installs_independent_price_for_an_older_card(self):
        g=self.game(hand=(STUDIES,RUNNER)+(YETI,)*8,members=(SIGHT,),mode='fill');old=self.first(g,RUNNER).id;self.study(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(self.mods(g)),1);self.assertEqual(g.quote_cost(old).amount,0)
        self.assertTrue(any(e.kind=='card_burned'for e in g.events))

    def test_empty_and_foreign_current_class_pools_still_install_next_modifier_without_rng(self):
        for config in ({'members':(YETI,)},{'members':(RUNNER,), 'hero':'HERO_08'}):
            with self.subTest(config=config):
                g=self.game(**config);rng=g._rng.getstate();self.play(g,STUDIES)
                self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.mods(g)),1);self.assertEqual(g._rng.getstate(),rng)

    def test_unknown_qualified_and_missing_host_fail_before_rng_but_known_nonoutcast_is_excluded(self):
        for config in ({'members':(RUNNER,UNKNOWN)},{'pool':False},{'context':None}):
            with self.subTest(config=config):
                g=self.game(**config);saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete validation')):
                    with self.assertRaises(ResolutionError):self.play(g,STUDIES)
                self.assertEqual(g.snapshot(),saved)
        g=self.game(members=(RUNNER,UNKNOWN_PLAIN));self.study(g);self.assertEqual(len(self.mods(g)),1)

    def test_real_spell_repeat_uses_two_discoveries_and_price_sources_for_one_paid_play(self):
        g=self.game(members=(RUNNER,),board=(P+'repeat',));self.play(g,STUDIES);self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        self.assertEqual(len(self.mods(g)),2);self.assertEqual(len(g.state.cast_history),2);self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,39)

    def test_printed_condition_uses_definition_across_all_cost_readers_not_current_battlecry(self):
        r=registry()
        for cid,expected in ((RUNNER,True),(SIGHT,True),(YETI,False),(STUDIES,False)):
            with self.subTest(cid=cid):
                c=r.card(cid);self.assertEqual(matches_ability(PRINTED_OUTCAST,c),expected)
                self.assertEqual(matches_cost(NEXT_COST,c),expected);self.assertEqual(matches_cost_values(NEXT_COST,c,False),expected)
        with self.assertRaises(ValueError):CardAbilityCondition('outcast')
        with self.assertRaises(ValueError):PoolQuery(ability=PRINTED_OUTCAST)
        self.assertTrue(matches_ability_values(PRINTED_OUTCAST,printed=True,current=False))
        self.assertFalse(matches_ability_values(PRINTED_OUTCAST,printed=False,current=True))

    def test_nested_saved_condition_rejects_activation_unknown_name_and_nonboolean_presence(self):
        g=self.game(hand=(P+'before',));self.play(g,P+'before');self.portable(g)
        def nodes(node):
            if isinstance(node,dict):
                if node.get('type','').endswith('.CardAbilityCondition'):yield node['fields']
                for value in node.values():yield from nodes(value)
            elif isinstance(node,list):
                for value in node:yield from nodes(value)
        for key,value in (('basis','current'),('ability','combo'),('present',1)):
            saved=deepcopy(g.snapshot());next(nodes(saved))[key]=value
            saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))
        saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))


if __name__=='__main__':
    unittest.main()
