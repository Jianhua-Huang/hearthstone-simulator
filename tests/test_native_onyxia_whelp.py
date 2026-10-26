"""Native Whelp presence, six real deliveries and ordinary immune combat."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.native_onyxia_whelp import CARD, WHELP, IMMUNITY, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    Game, Keyword, PlayerSetup, ResolutionError, Scenario, SnapshotError, TriggerSpec,
    TribeChangeSpec, UnsupportedDefinitionError, Zone)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, InvokeBehavior, RequestChoice,
    ReturnToHand, Transform)
from hs_sim.engine.keyword_auras import GrantKeywordAura
from hs_sim.engine.model import KeywordAuraSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes
from tools import card_batch as batch

S='k559.'
WATCH, UNKNOWN, NAMED, ALL=S+'watch',S+'unknown',S+'named',S+'all'
CTX=GenerationContext('k559-native-onyxia-whelp-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','native-onyxia-whelp-test-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    def fail(c):raise ResolutionError('k559 deliberate entry failure')
    def observe(c):
        e=c.state.entities.get(c.event.target_id)
        if mode=='entry' and e is not None and e.card_id==WHELP and c.event.player_id==c.player_id:
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_target_rule(S+'board',lambda c:(e:=c.state.entities.get(c.target_id))is not None and
        e.zone==Zone.BOARD and e.kind==CardType.MINION)
    scripts={
        'fail':fail,'sleep':lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        'wake':lambda c:tuple(AwakenMinion(i,c.source_id)for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==WHELP and c.state.entities[i].dormancy is not None),
        'steal':lambda c:(ChangeControl(c.target_id,2),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,FILLER),),
        'tribes':lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set',('beast',)),c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior(S+name,body)
        r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name,
            requires_target=name not in ('fail','wake'),target_rule=S+'board'if name!='fail'else 'any_character'))
    for cid,name,tribes,subtypes in ((NAMED,'Onyxian Whelp',('dragon',),()),(ALL,'All tribes',('all',),()),
            (UNKNOWN,'Unknown subtype',('dragon',),None)):
        r.register_card(CardDefinition(cid,name,CardType.MINION,attack=1,health=2,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes,subtypes=subtypes)))
    r.register_behavior(S+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Diagnostic Whelp delivery observer',CardType.WEAPON,durability=30,
        triggers=(TriggerSpec('minion_summoned',S+'observe'),)))
    r.validate();return replace(fmt,context=CTX)


class NativeOnyxiaWhelpTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand=(),*,board=(),enemy=(),mode='normal'):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=(FILLER,)*6,max_mana=10,mana=10,
                weapon_card_id=WATCH if mode=='entry'else None),
            PlayerSetup('HERO_08',board=enemy,deck=(FILLER,)*6)),seed=559,generation_context=CTX),fmt.registry)

    def immune(self,g,eid):return Keyword.IMMUNE in g.state.entities[eid].keywords
    def whelps(self,g):return [g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==WHELP]

    def test_complete_root_existing_whelp_four_primary_faces_and_printed_classification(self):
        data=load_batch();original={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256']);rows={x['record']['id']:x['record']
            for key in ('cards','existing_dependencies')for x in data[key]}
        for cid,raw in rows.items():self.assertEqual(raw,original[cid])
        for face in data['official_faces']:batch.check_face(rows[face['card_id']],face['face'],face['locale'])
        self.assertEqual(rows[CARD]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],rows[WHELP]['dbf_id'])
        r=fixture().registry;self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(10,8,8))
        self.assertEqual(r.card(CARD).keyword_auras,(IMMUNITY,));self.assertEqual(r.card(WHELP).metadata.subtypes,('whelp',))
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_real_ten_mana_play_delivers_six_exact_rush_whelps_and_immunity_without_rng(self):
        g=self.game((CARD,));rng=g.snapshot()['rng_state'];source=self.play(g,CARD);whelps=self.whelps(g)
        self.assertEqual((g.state.players[1].mana,len(whelps)),(0,6))
        self.assertEqual([(e.attack,e.health)for e in whelps],[(2,1)]*6)
        self.assertTrue(all(Keyword.RUSH in e.keywords for e in whelps));self.assertTrue(self.immune(g,source))
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,source)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_partial_and_full_capacity_use_actual_deliveries_for_presence(self):
        for count,expected in ((5,1),(6,0)):
            with self.subTest(count=count):
                g=self.game((CARD,),board=(FILLER,)*count);source=self.play(g,CARD)
                self.assertEqual(len(self.whelps(g)),expected);self.assertEqual(self.immune(g,source),bool(expected))
                self.assertEqual(len(g.state.players[1].board),7)

    def test_a_different_printed_whelp_qualifies_but_enemy_dragon_all_and_name_do_not(self):
        g=self.game(board=(CARD,'BRM_004'));source=self.entity(g,CARD,zone='board').id;self.assertTrue(self.immune(g,source))
        for board,enemy in (((CARD,),('BRM_004',)),((CARD,NAMED,ALL,'OG_141'),())):
            with self.subTest(board=board):
                g=self.game(board=board,enemy=enemy);self.assertFalse(self.immune(g,self.entity(g,CARD,zone='board').id))

    def test_whelp_silence_and_tribe_change_keep_subtype_but_transform_removes_presence(self):
        g=self.game((P+'quiet',S+'tribes',S+'transform'),board=(CARD,WHELP))
        source=self.entity(g,CARD,zone='board').id;whelp=self.entity(g,WHELP,zone='board').id
        self.play(g,P+'quiet',whelp);self.assertTrue(self.immune(g,source))
        self.play(g,S+'tribes',whelp);self.assertTrue(self.immune(g,source))
        self.play(g,S+'transform',whelp);self.assertFalse(self.immune(g,source))

    def test_dormancy_wake_and_last_whelp_death_recompute_without_keyword_grants(self):
        g=self.game((S+'sleep',S+'wake',P+'kill'),board=(CARD,WHELP));source=self.entity(g,CARD,zone='board').id
        whelp=self.entity(g,WHELP,zone='board').id;self.play(g,S+'sleep',whelp);self.assertFalse(self.immune(g,source))
        self.play(g,S+'wake');self.assertTrue(self.immune(g,source))
        self.play(g,P+'kill',whelp);self.assertFalse(self.immune(g,source));self.portable(g)

    def test_source_silence_and_return_remove_only_its_native_aura(self):
        g=self.game((P+'quiet',),board=(CARD,WHELP));source=self.entity(g,CARD,zone='board').id
        self.play(g,P+'quiet',source);self.assertFalse(self.immune(g,source));self.assertEqual(len(self.whelps(g)),1)
        g=self.game((S+'bounce',),board=(CARD,WHELP));source=self.entity(g,CARD,zone='board').id
        self.play(g,S+'bounce',source);self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertFalse(self.immune(g,source))

    def test_current_controller_and_its_actual_whelp_determine_presence(self):
        g=self.game((S+'steal',S+'steal'),board=(CARD,WHELP));source=self.entity(g,CARD,zone='board').id
        whelp=self.entity(g,WHELP,zone='board').id;self.play(g,S+'steal',source);self.assertFalse(self.immune(g,source))
        self.play(g,S+'steal',whelp);self.assertTrue(self.immune(g,source))

    def test_unknown_later_subtype_is_not_hidden_by_an_earlier_matching_whelp(self):
        g=self.game((CARD,),board=(WHELP,UNKNOWN));saved=g.snapshot()
        with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_actual_rush_attack_is_immune_and_real_whelp_attack_still_uses_retaliation(self):
        g=self.game((CARD,),enemy=('OG_141',));source=self.play(g,CARD);enemy=g.state.players[2].board[0]
        g.apply(Attack(1,source,enemy));self.assertEqual((g.state.entities[source].health,g.state.entities[enemy].health),(8,2))
        whelp=self.whelps(g)[0].id;g.apply(Attack(1,whelp,enemy))
        self.assertEqual((g.state.entities[whelp].zone,g.state.entities[enemy].zone),(Zone.GRAVEYARD,Zone.GRAVEYARD))
        self.assertTrue(self.immune(g,source))

    def test_delivery_wait_restore_replay_failure_and_each_body_resumes_once(self):
        g=self.game((CARD,),mode='entry');source=self.play(g,CARD)
        self.assertEqual(len(self.whelps(g)),1);self.assertTrue(self.immune(g,source));saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):
            while game.state.pending_choice is not None:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.whelps(g)),6)
        for player in (1,2):self.assertNotIn('controller_controls_whelp',json.dumps(g.for_player(player).observe()))

    def test_condition_is_closed_and_rehashed_foreign_aura_or_old_core_are_rejected(self):
        for change in ({'keyword':Keyword.RUSH},{'target':'friendly_hero'},{'include_self':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(IMMUNITY,**change)
        with self.assertRaises(ValueError):GrantKeywordAura(1,IMMUNITY)
        g=self.game((CARD,),mode='entry');source=self.play(g,CARD);saved=g.snapshot()
        edited=deepcopy(saved);ability=next(a for a in edited['state']['entities'][str(source)]['abilities']if a['kind']=='keyword_aura')
        ability['keyword_aura']['condition']='controller_no_other_minions'
        edited['state_hash']=canonical_hash({k:v for k,v in edited.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(edited,fixture('entry').registry)
        edited=deepcopy(saved);edited['mechanics_version']['version']='core-effects-v740'
        with self.assertRaises(SnapshotError):Game.from_snapshot(edited,fixture('entry').registry)

    def test_real_frontier_discovery_and_one_mana_native_battlecry_use_same_six_whelps(self):
        r=fixture().registry;rows=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual([m.card_id for m in rows],[CARD]);g=self.game(('GDB_857',));self.play(g,'GDB_857')
        self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==CARD));source=self.play(g,CARD)
        self.assertEqual(g.state.play_history[-1].cost,1);self.assertEqual(len(self.whelps(g)),6)
        self.assertTrue(self.immune(g,source))


if __name__=='__main__':unittest.main()
