"""Reviewed constructed metadata must agree in live tribes and independent pools."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.constructed_metadata_catalog import load_batch,metadata_overrides,register_reviewed_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,
    TribeChangeSpec,has_any_tribe,tribe_state)
from hs_sim.engine.effects import (ChoiceOption,CopyMinion,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition
from hs_sim.engine.pools import GenerationContext,GenerateFromPool,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as default
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.targets import TargetValidationError,canonical_digest

ONYXIA='CATA_155';YETI='CORE_CS2_182';P='k108.test.';CTX=GenerationContext('k108-metadata-fixture','experimental')


def source_registry(legacy=False):
    # Isolate the historical 24-row increment from the later complete catalog.
    # This historical metadata increment excludes the later shared-class pool,
    # which requires the complete candidate catalog intentionally absent here.
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None), \
            patch('hs_sim.cards.assemble_shared_class_pool.register_assemble_shared_class_pool',lambda r:None), \
            patch('hs_sim.cards.assemble_extended_reference_pool.register_assemble_extended_reference_pool',lambda r:None):
        if not legacy:return build_registry()
        with patch('hs_sim.cards.constructed_metadata_catalog.metadata_overrides',lambda:()),patch('hs_sim.cards.constructed_metadata_catalog.register_reviewed_pool_metadata',lambda r:None):return build_registry()


def registry(legacy=False):
    r=source_registry(legacy)
    # Native Colossal appendages keep their original complete experimental pool;
    # the local metadata query context must not silently crop that dependency.
    for pool in tuple(r.pools.values()):
        if pool.id=='representative.herald-generation'and pool.mode==CTX.mode:
            r.register_pool(replace(pool,target_id=CTX.target_id))
            # Constructed soldier bodies now use this pool ID. Preserve every
            # member/weight of the original complete historical fixture pool.
            r.register_pool(replace(pool,id='constructed.cards',target_id=CTX.target_id))
    if ONYXIA not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(ONYXIA)))
    r.register_pool(PoolDefinition(P+'pool','k108-fixture-v1',CTX.target_id,CTX.mode,(PoolMember(ONYXIA),PoolMember(YETI)),complete=True))
    def source(c):return next(c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id==ONYXIA)
    def pause(c):return RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id)
    query=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('undead',))
    bodies=dict(generate=lambda c:(GenerateFromPool(1,P+'pool',query,source_id=c.source_id),),
        pending=lambda c:(pause(c),GenerateFromPool(1,P+'pool',query,source_id=c.source_id)),
        beast=lambda c:(ChangeMinionTribes(MinionReference.capture(source(c)),TribeChangeSpec('set',('beast',)),c.source_id),),
        silence=lambda c:(Silence(source(c).id),),bounce=lambda c:(ReturnToHand(source(c).id),),
        transform=lambda c:(Transform(source(c).id,ONYXIA),),
        copy=lambda c:(CopyMinion(source(c).id,1),),base=lambda c:(CopyMinion(source(c).id,1,mode='base'),),
        fail=lambda c:(_ for _ in()).throw(ResolutionError('K108 deliberate pending failure')))
    for name,body in bodies.items():r.register_behavior(P+name,body)
    for name in bodies:
        if name!='fail':r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    r.validate();return r


class ConstructedMetadataCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(ONYXIA,)):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50)),seed=108,generation_context=CTX),self.r)
    def first(self,g,cid=ONYXIA,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid):
        e=self.first(g,cid,'hand');g.apply(PlayCard(1,e.id,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def portable(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snapshot,registry());self.assertEqual(other.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot);self.assertEqual(replay(build_replay(g),registry()).snapshot(),snapshot)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('metadata_overrides','expected_metadata_sha256','rng_state','resolution_frame','pool_id','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def test_full_twenty_four_rows_source_metadata_and_secondary_undead_flag(self):
        d=load_batch();self.assertEqual(len(d['cards']),24);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        for x in d['cards']:
            raw=x['record'];cid=raw['id'];self.assertEqual(canonical_digest(raw),x['record_sha256']);self.assertEqual(canonical_digest(asdict(self.r.card(cid).metadata)),x['expected_metadata_sha256']);self.assertEqual(self.r.pool_card(cid),PoolCard.from_definition(self.r.card(cid)))
            if cid==ONYXIA:self.assertEqual((raw['tags']['CARDRACE'],raw['tags']['2534']),(24,1));self.assertEqual(self.r.card(cid).metadata,metadata_from_record(raw))

    def test_exact_one_existing_metadata_change_no_new_definitions_and_twenty_four_pool_rows(self):
        old=source_registry(True);new=source_registry();self.assertEqual(set(old.cards),set(new.cards));changed=[cid for cid in old.cards if asdict(old.card(cid))!=asdict(new.card(cid))];self.assertEqual(changed,[ONYXIA]);a=asdict(old.card(ONYXIA));a['metadata']['tribes']=('dragon','undead');self.assertEqual(a,asdict(new.card(ONYXIA)));self.assertEqual(set(new.pool_cards)-set(old.pool_cards),{x['record']['id']for x in load_batch()['cards']});self.assertTrue(all(old.pool_card(cid)==new.pool_card(cid)for cid in old.pool_cards))

    def test_default_bundle_is_unchanged_unless_explicit_metadata_projection_is_requested(self):
        old=default();self.assertEqual(len(old.cards),311);self.assertEqual(old.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertEqual(old.card(ONYXIA).metadata.tribes,('dragon',));projected=default(metadata_overrides=metadata_overrides());self.assertEqual(projected.card(ONYXIA).metadata.tribes,('dragon','undead'));self.assertTrue(all(asdict(old.card(cid))==asdict(projected.card(cid))for cid in old.cards if cid!=ONYXIA))

    def test_pool_metadata_installation_is_idempotent_and_adds_no_pool_definition(self):
        r=source_registry();before=dict(r.pool_cards);pools=dict(r.pools);register_reviewed_pool_metadata(r);self.assertEqual(dict(r.pool_cards),before);self.assertEqual(dict(r.pools),pools);self.assertFalse(any(p.mode=='standard'for p in r.pools.values()))

    def test_live_printed_identity_and_silence_retain_both_real_tribes(self):
        g=self.game((P+'silence',));entity=self.first(g);self.assertTrue(has_any_tribe(g.registry,entity,('undead',)));self.assertTrue(has_any_tribe(g.registry,entity,('dragon',)));self.play(g,P+'silence');self.assertEqual(tribe_state(g.registry,g.state.entities[entity.id]).members,('dragon','undead'));self.portable(g)

    def test_dynamic_tribe_set_is_separate_and_silence_restores_correct_printed_pair(self):
        g=self.game((P+'beast',P+'silence'));target=self.first(g).id;self.play(g,P+'beast');e=g.state.entities[target];self.assertEqual(tribe_state(g.registry,e).members,('beast',));self.assertTrue(has_any_tribe(g.registry,e,('undead',),basis='printed'));self.assertFalse(has_any_tribe(g.registry,e,('undead',)));self.play(g,P+'silence');self.assertEqual(tribe_state(g.registry,g.state.entities[target]).members,('dragon','undead'))

    def test_independent_pool_undead_query_includes_corrected_dragon_once(self):
        query=PoolQuery(kinds=(CardType.MINION,),tribes_any=('undead',));self.assertEqual(tuple(x.card_id for x in resolve_candidates(self.r,CTX,P+'pool',query)),(ONYXIA,));self.assertEqual(tuple(x.card_id for x in resolve_candidates(self.r,CTX,P+'pool',PoolQuery(tribes_any=('dragon','undead')))),(ONYXIA,));old=registry(True);self.assertEqual(resolve_candidates(old,CTX,P+'pool',query),())

    def test_actual_generation_acquires_fresh_card_with_correct_printed_pair(self):
        g=self.game((P+'generate',));old=self.first(g).id;source=self.play(g,P+'generate');card=self.first(g,ONYXIA,'hand');self.assertNotEqual(card.id,old);self.assertEqual(g.registry.card(card.card_id).metadata.tribes,('dragon','undead'));self.assertTrue(any(e.kind=='card_created'and e.target_id==card.id and e.source_id==source for e in g.events));self.portable(g)

    def test_current_copy_keeps_dynamic_type_base_copy_recovers_corrected_printed_types(self):
        g=self.game((P+'beast',P+'copy',P+'base'));original=self.first(g).id;self.play(g,P+'beast');self.play(g,P+'copy');self.play(g,P+'base');bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==ONYXIA];self.assertEqual(len(bodies),3);self.assertEqual([tribe_state(g.registry,e).members for e in bodies],[('beast',),('beast',),('dragon','undead')]);self.assertEqual(bodies[0].id,original);self.portable(g)

    def test_same_card_transform_resets_dynamic_type_to_corrected_printed_types(self):
        g=self.game((P+'beast',P+'transform'));old=self.first(g);self.play(g,P+'beast');self.play(g,P+'transform');e=g.state.entities[old.id];self.assertGreater(e.zone_epoch,old.zone_epoch);self.assertEqual(tribe_state(g.registry,e).members,('dragon','undead'));self.portable(g)

    def test_normal_return_and_replay_use_corrected_printed_metadata(self):
        g=self.game((P+'beast',P+'bounce'));old=self.first(g).id;self.play(g,P+'beast');self.play(g,P+'bounce');card=self.first(g,ONYXIA,'hand');self.assertEqual(card.id,old);self.assertEqual(tribe_state(g.registry,card).members,('dragon','undead'));self.play(g,ONYXIA);self.assertEqual(tribe_state(g.registry,g.state.entities[old]).members,('dragon','undead'));self.portable(g)

    def test_pending_generation_restores_replays_and_choice_failure_is_atomic(self):
        g=self.game((P+'pending',));self.play(g,P+'pending');other=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.first(g,ONYXIA,'hand').card_id,ONYXIA);self.portable(g)

    def test_previous_registry_identity_cannot_restore_new_metadata_snapshot(self):
        g=self.game();snapshot=g.snapshot()
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,registry(True))

    def test_bad_or_duplicate_metadata_override_inputs_are_rejected(self):
        pair=metadata_overrides()[0]
        for value in([pair],(pair,pair),(('CATA_155',{}),),(('',pair[1]),)):
            with self.subTest(value=type(value).__name__),self.assertRaises(ValueError):default(metadata_overrides=value)

    def test_unknown_or_uncompiled_metadata_override_cannot_be_silently_ignored(self):
        meta=metadata_overrides()[0][1]
        for cid in('k108.missing','test.hero'):
            with self.subTest(cid=cid),self.assertRaises(ValueError):default(metadata_overrides=((cid,meta),))

    def test_all_rows_checked_before_catalog_mutation_when_projection_is_absent(self):
        old=source_registry(True);before=dict(old.pool_cards)
        with self.assertRaises(TargetValidationError):register_reviewed_pool_metadata(old)
        self.assertEqual(dict(old.pool_cards),before)


if __name__=='__main__':unittest.main()
