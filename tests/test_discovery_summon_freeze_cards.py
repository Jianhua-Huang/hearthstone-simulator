"""Glaciate joins its actual selected summon delivery to ordinary Freeze."""
from copy import deepcopy
from dataclasses import replace
import json,re,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.discovery_summon_freeze_cards import GLACIATE,POOL_ID,BODY,load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,SpellSchool,Zone)
from hs_sim.engine.discovery_summons import FreezeDiscoveredMinion
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,Rarity,SummonQuantitySpec
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.targets import canonical_digest

P='k112.test.';NEUTRAL='CORE_UNG_848';SHAMAN='CORE_NEW1_010';FOREIGN='CATA_151';YETI='CORE_CS2_182';UNKNOWN=P+'unknown'
CTX=GenerationContext('k112-explicit-experiment','experimental');MEMBERS=(NEUTRAL,SHAMAN,FOREIGN,YETI,GLACIATE)
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


def registry(members=MEMBERS,mode=None,pool=True):
    r=build_registry()
    if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,8,
        CardMetadata(True,(CardClass.SHAMAN,),Rarity.COMMON,tribes=(),factions=(),subtypes=())))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k112-explicit-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_card(CardDefinition(P+'double','Spell summon doubler',CardType.MINION,health=7,metadata=META,
        summon_quantities=(SummonQuantitySpec(2,(CardType.SPELL,)),)))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K112 deliberate followup failure')))
    if mode:
        def eligible(c):
            if mode=='fail':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==GLACIATE
            roots=c.state.discovery_summon_history
            if not roots or not roots[-1].entry_root_ids:return False
            child=next(x for x in c.state.card_summon_history if x.id==roots[-1].entry_root_ids[-1])
            return bool(child.deliveries and child.deliveries[0].entity is not None and child.deliveries[0].entity.entity_id==c.event.target_id)
        def watch(c):
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,1),)
            if mode=='kill':return(Destroy(c.event.target_id,c.source_id),)
            if mode=='reenter':return(ReturnToHand(c.event.target_id),Summon(1,NEUTRAL))
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Actual first delivery reaction',CardType.MINION,health=5,metadata=META,
            limited_triggers=(LimitedTriggerSpec('frozen'if mode=='fail'else'minion_summoned',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class DiscoverySummonFreezeTests(unittest.TestCase):
    def game(self,board=(),members=MEMBERS,mode=None,pool=True,context=CTX,hero='HERO_02'):
        self.config=(members,mode,pool)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=(GLACIATE,),board=board,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=112,generation_context=context),registry(*self.config))
    def play(self,g):
        source=g.state.players[1].hand[0];g.apply(PlayCard(1,source));return source
    def pick(self,g,cid=NEUTRAL):
        q=g.state.pending_choice;option=next(o for o in q.options if o.card_id==cid);g.apply(SelectChoice(1,q.id,(option.id,)))
    def bodies(self,g,cid=NEUTRAL):return[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==cid]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(*self.config));self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for field in('discovery_summon_history','freeze_acceptances','FreezeDiscoveredMinion','freeze_summoned','resolution_frame','rng_state'):
                self.assertNotIn('"'+field+'"',public)
        return other
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(*self.config))

    def test_complete_two_raw_rows_two_primary_faces_and_current_frost_spell(self):
        d=load_batch();r=registry();raw=d['cards'][0]['record'];c=r.card(GLACIATE)
        self.assertEqual((c.cost,c.spell_school,c.on_play),(6,SpellSchool.FROST,BODY));self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity='AV_107'))
        self.assertEqual(len(d['cards']+d['evidence_only']),2);self.assertEqual(len(d['official_observations']['observations']),2)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        norm=lambda x:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',x)
        for o in d['official_observations']['observations']:
            face=o['face'];en=o['locale']=='en_US';self.assertEqual(face['name'],raw['name_en'if en else'name']);self.assertEqual(norm(face['text']),norm(raw['text_en'if en else'text']));self.assertEqual(face['manaCost'],6)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_paid_discovery_filters_printed_eight_minions_current_class_then_freezes_actual_body(self):
        g=self.game();source=self.play(g);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{NEUTRAL,SHAMAN})
        self.assertFalse(self.bodies(g));self.assertEqual(g.state.players[1].mana,14);self.portable(g);self.pick(g)
        body,=self.bodies(g);self.assertTrue(body.frozen);self.assertNotEqual(body.id,source);self.assertFalse(g.state.battlecry_history)
        root,=g.state.discovery_summon_history;child,=g.state.card_summon_history
        self.assertEqual(root.freeze_acceptances,(0,));self.assertEqual(root.status,'completed');self.assertEqual(child.deliveries[0].entity.entity_id,body.id)
        self.assertTrue(any(e.kind=='frozen'and e.source_id==source and e.target_id==body.id for e in g.events));self.portable(g)

    def test_offers_and_selection_restore_without_extra_random_or_payment(self):
        g=self.game();self.play(g);other=self.portable(g);rng=g._rng.getstate()
        for game in(g,other):self.pick(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,14);self.portable(g)

    def test_same_face_preexisting_body_is_not_frozen(self):
        g=self.game(board=(NEUTRAL,));old=self.bodies(g)[0].id;self.play(g);self.pick(g)
        bodies=self.bodies(g);self.assertEqual(len(bodies),2);self.assertFalse(g.state.entities[old].frozen)
        self.assertTrue(next(x for x in bodies if x.id!=old).frozen);self.portable(g)

    def test_summon_quantity_extra_is_not_the_original_freeze_recipient(self):
        g=self.game(board=(P+'double',));self.play(g);self.pick(g)
        child,=g.state.card_summon_history;self.assertEqual(child.plan.total,2)
        self.assertEqual([g.state.entities[d.entity.entity_id].frozen for d in child.deliveries],[True,False]);self.portable(g)

    def test_full_board_keeps_discovery_and_acknowledges_failed_original_without_freeze(self):
        g=self.game(board=(YETI,)*7);self.play(g);self.assertIsNotNone(g.state.pending_choice);self.pick(g)
        self.assertFalse(self.bodies(g));self.assertFalse(any(e.kind=='frozen'for e in g.events))
        self.assertEqual(g.state.discovery_summon_history[0].freeze_acceptances,(0,));self.portable(g)

    def test_empty_pool_has_no_choice_delivery_freeze_or_rng(self):
        g=self.game(members=(YETI,));rng=g._rng.getstate();self.play(g)
        self.assertEqual(g._rng.getstate(),rng);self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_summon_history)
        self.assertEqual(g.state.discovery_summon_history[0].freeze_acceptances,());self.portable(g)

    def test_original_dies_in_summon_reaction_and_is_not_replaced_by_other_body(self):
        g=self.game(board=(NEUTRAL,),mode='kill');old=self.bodies(g)[0].id;self.play(g);self.pick(g)
        self.assertEqual([e.id for e in self.bodies(g)],[old]);self.assertFalse(g.state.entities[old].frozen)
        self.assertFalse(any(e.kind=='frozen'for e in g.events));self.portable(g)

    def test_departed_original_and_new_same_face_body_do_not_transfer_freeze(self):
        g=self.game(mode='reenter');self.play(g);self.pick(g)
        child,=g.state.card_summon_history;old=child.deliveries[0].entity.entity_id;new,=self.bodies(g)
        self.assertNotEqual(new.id,old);self.assertEqual(g.state.entities[old].zone,Zone.HAND);self.assertFalse(new.frozen);self.portable(g)

    def test_summon_reaction_wait_precedes_freeze_and_restores_exact_owed_control(self):
        g=self.game(mode='wait');self.play(g);self.pick(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(self.bodies(g)[0].frozen);self.assertEqual(g.state.discovery_summon_history[0].freeze_acceptances,())
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(self.bodies(g)[0].frozen);self.portable(g)

    def test_freeze_trigger_failure_rolls_back_selected_delivery_and_keeps_original_offer(self):
        g=self.game(mode='fail');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),saved)

    def test_missing_context_pool_or_eligible_unknown_rejects_paid_action_before_random(self):
        for pool,context,members in((False,CTX,MEMBERS),(True,None,MEMBERS),(True,CTX,(NEUTRAL,UNKNOWN))):
            with self.subTest(pool=pool,context=context,members=members):
                g=self.game(pool=pool,context=context,members=members);saved=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g)
                self.assertEqual(g.snapshot(),saved)

    def test_removed_or_reordered_freeze_work_cannot_restore_mid_summon_wait(self):
        g=self.game(mode='wait');self.play(g);self.pick(g)
        for wrong in(False,True):
            with self.subTest(wrong=wrong):
                bad=g.clone();frame=bad._frame;found=sum(type(w)is FreezeDiscoveredMinion for w in(*frame.prefix,*frame.continuation));self.assertEqual(found,1)
                def change(work):return tuple(replace(w,index=1)if type(w)is FreezeDiscoveredMinion and wrong else w for w in work if wrong or type(w)is not FreezeDiscoveredMinion)
                bad._frame=replace(frame,prefix=change(frame.prefix),continuation=change(frame.continuation))
                with self.assertRaises((ValueError,SnapshotError)):Game.from_snapshot(bad.snapshot(),registry(*self.config))

    def test_removed_acceptance_receipt_cannot_restore_completed_freeze(self):
        g=self.game();self.play(g);self.pick(g);saved=g.snapshot()
        self.assertTrue(any(e['kind']=='discovery_summon_freeze_started'for e in saved['events']))
        saved['events']=[e for e in saved['events']if e['kind']!='discovery_summon_freeze_started'];self.reject(saved)

    def test_freeze_declaration_is_finite_strict_and_requires_attributed_board_minion(self):
        from hs_sim.engine.registry import RuleContext
        g=self.game();self.play(g);root=g.state.discovery_summon_history[0];spec=root.spec
        for changes in(dict(freeze_summoned=1),dict(destination='hand'),dict(cause=None),dict(source_id=None),dict(discoveries=2),dict(delivery='after_all'),dict(query=replace(spec.query,kinds=(CardType.SPELL,))),dict(heal_hero_by_printed_cost=True)):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):replace(spec,**changes)
        self.assertFalse(DiscoverFromPool(1,POOL_ID).freeze_summoned)

    def test_default_311_fingerprint_and_previous_schema_rejected(self):
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
        g=self.game();saved=g.snapshot();self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,324);saved['schema_version']=323
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))


if __name__=='__main__':unittest.main()
