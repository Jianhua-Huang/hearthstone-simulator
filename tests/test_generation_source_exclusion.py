"""Ordinary collectible generation bans self; edition links never merge weights."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import replace
import json,unittest
from unittest.mock import patch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,
    Rarity,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,UnsupportedDefinitionError)
from hs_sim.engine.effects import AddToHand
from hs_sim.engine.pools import (DiscoverFromPool,GenerateFromPool,GenerationContext,PoolCard,
    PoolDefinition,PoolMember,PoolQuery,resolve_candidates)
from hs_sim.engine.replay import build_replay,replay

CTX=GenerationContext('source-rule-experiment','experimental');POOL='pool'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def registry(mode='discover',members=('core','old','other'),missing=(),collectible=True,family=True):
    r=Registry('self-exclusion-fixtures-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30,
        metadata=replace(META,collectible=False,classes=(CardClass.MAGE,))))
    def body(c):
        if mode=='named':return(AddToHand(c.player_id,'core',c.source_id),)
        effect=DiscoverFromPool if mode=='discover'else GenerateFromPool
        return(effect(c.player_id,POOL,PoolQuery(kinds=(CardType.MINION,)),source_id=c.source_id),)
    r.register_behavior('source',body)
    for cid in sorted(set(members)|{'core','old','other'}):
        card=CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=2,
            battlecry='source'if cid=='core'else None,metadata=replace(META,collectible=collectible if cid in('core','old')else True))
        if cid not in missing:r.register_card(card)
        r.register_pool_card(PoolCard.from_definition(card))
    if family:r.register_generation_family(('core','old'))
    r.register_pool(PoolDefinition(POOL,'explicit-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid,3 if cid=='core'else 7 if cid=='old'else 2)for cid in members),complete=True))
    r.validate();return r


class GenerationSourceExclusionTests(unittest.TestCase):
    def game(self,**config):
        self.config=config
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=('core',),mana=5,max_mana=5),
            PlayerSetup('hero')),seed=111,generation_context=CTX),registry(**config))
    def play(self,g):
        source=g.state.players[1].hand[0];g.apply(PlayCard(1,source,position=0));return source
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(**self.config))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(**self.config)).snapshot(),saved)
        return other
    def candidates(self,r,**kwargs):
        return resolve_candidates(r,CTX,POOL,PoolQuery(),player_id=1,**kwargs)

    def test_reviewed_links_keep_both_original_copy_tags_and_no_prefix_guess(self):
        from hs_sim.cards.generation_source_families import load_batch,BATCH_HASH
        from hs_sim.targets import canonical_digest
        d=load_batch();self.assertEqual(canonical_digest(d),BATCH_HASH)
        self.assertEqual((len(d['edges']),len(d['families']),len(d['records'])),(262,258,520))
        records={row['record']['id']:row['record']for row in d['records']}
        for row in d['records']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        peddler=next(f for f in d['families']if 'CORE_WON_096'in f)
        self.assertEqual(set(peddler),{'CORE_WON_096','LOE_023','WON_096'})
        self.assertEqual(records['CORE_WON_096']['tags']['858'],2895)
        self.assertEqual(records['CORE_WON_096']['tags']['DECK_RULE_COUNT_AS_COPY_OF_CARD_ID'],102639)
        self.assertNotIn('CORE_EDR_001',records);self.assertNotIn('EDR_001',records)
        self.assertEqual(len(d['official_observations']['observations']),8)
        self.assertEqual(len(d['official_rule_observations']),3)

    def test_public_family_registration_rejects_bad_or_overlapping_groups_atomically(self):
        r=Registry('family-registration');r.register_generation_family(('a','b'))
        for bad in (['c','d'],('c',),('d','c'),('c','c'),('','c'),('b','c')):
            with self.subTest(bad=bad):
                before=dict(r.generation_families)
                with self.assertRaises(ValueError):r.register_generation_family(bad)
                self.assertEqual(dict(r.generation_families),before)
        self.assertEqual(r.generation_family('b'),('a','b'));self.assertEqual(r.generation_family('unreviewed'),('unreviewed',))

    def test_family_map_is_readonly_and_freeze_rejects_later_declarations(self):
        r=registry()
        with self.assertRaises(TypeError):r.generation_families['x']=('x','y')
        r.freeze()
        with self.assertRaises(ValueError):r.register_generation_family(('x','y'))

    def test_family_membership_enters_registry_identity(self):
        self.assertNotEqual(registry().fingerprint(),registry(family=False).fingerprint())

    def test_validation_rejects_corrupt_derived_family_index(self):
        r=registry();r._generation_family_members['old']='other'
        with self.assertRaisesRegex(ValueError,'lookup'):r.validate()

    def test_pure_query_preserves_each_edition_weight_and_generation_identity(self):
        r=registry();rows=self.candidates(r,source_card_id='core')
        self.assertEqual([(m.card_id,m.weight)for m in rows],[('core',3),('old',7),('other',2)])
        self.assertNotEqual(r.pool_card('core').generation_identity,r.pool_card('old').generation_identity)

    def test_generation_rule_excludes_whole_reviewed_family_without_weight_mutation(self):
        r=registry();rows=self.candidates(r,source_card_id='core',exclude_source_by_rule=True)
        self.assertEqual(rows,(PoolMember('other',2),));self.assertEqual(len(r.pool(POOL,CTX).members),3)

    def test_unreviewed_editions_are_not_inferred_from_names_or_prefix(self):
        rows=self.candidates(registry(family=False),source_card_id='core',exclude_source_by_rule=True)
        self.assertEqual([m.card_id for m in rows],['old','other'])

    def test_rule_flag_is_strict_and_unbound_host_query_has_no_invented_source(self):
        r=registry();self.assertEqual(len(self.candidates(r,exclude_source_by_rule=True)),3)
        with self.assertRaises(ValueError):self.candidates(r,exclude_source_by_rule=1)
        with self.assertRaises(ValueError):resolve_candidates(r,CTX,POOL,PoolQuery(exclude_source=True))

    def test_excluded_edition_missing_execution_is_skipped_but_other_unknown_is_not(self):
        r=registry(missing=('old',));self.assertEqual(self.candidates(r,source_card_id='core',exclude_source_by_rule=True),(PoolMember('other',2),))
        with self.assertRaises(UnsupportedDefinitionError):self.candidates(r)
        r=registry(members=('core','old','unknown'),missing=('unknown',))
        with self.assertRaises(UnsupportedDefinitionError):self.candidates(r,source_card_id='core',exclude_source_by_rule=True)

    def test_noncollectible_named_inventory_retains_separate_policy(self):
        rows=self.candidates(registry(collectible=False),source_card_id='core',exclude_source_by_rule=True)
        self.assertEqual([m.card_id for m in rows],['core','old','other'])
        g=self.game(mode='named');source=self.play(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['core'])
        self.assertNotEqual(g.state.players[1].hand[0],source);self.portable(g)

    def test_native_discovery_filters_before_sampling_and_receipt_restores(self):
        g=self.game();self.play(g);q=g.state.pending_choice
        self.assertEqual([o.card_id for o in q.options],['other']);other=self.portable(g)
        for game in(g,other):
            pick=game.state.pending_choice;game.apply(SelectChoice(1,pick.id,(pick.options[0].id,)))
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_native_random_generation_excludes_source_and_alias(self):
        g=self.game(mode='generate',missing=('old',));source=self.play(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['other'])
        self.assertTrue(any(e.kind=='card_added_to_hand'and e.source_id==source for e in g.events));self.portable(g)

    def test_only_source_family_is_empty_without_rng_or_fallback(self):
        for mode in('discover','generate'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,members=('core','old'),missing=('old',));rng=g._rng.getstate();self.play(g)
                self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.players[1].hand)
                self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_unknown_other_candidate_rejects_before_rng_with_complete_rollback(self):
        g=self.game(members=('core','old','unknown'),missing=('unknown',));saved=g.snapshot()
        with patch('random.Random.randrange',side_effect=AssertionError('RNG before unknown validation'))as rng:
            with self.assertRaises(ResolutionError):self.play(g)
            rng.assert_not_called()
        self.assertEqual(g.snapshot(),saved)

    def test_changed_family_cannot_restore_accepted_offer(self):
        g=self.game();self.play(g);saved=g.snapshot()
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(family=False))

    def test_default_311_fingerprint_and_bookcase_distinct_copy_identity(self):
        from hs_sim.engine.representative import build_registry as default
        from hs_sim.cards import build_registry
        self.assertEqual(default().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
        r=build_registry();self.assertEqual(r.card('CORE_EDR_001').metadata.deck_identity,'CORE_EDR_001')
        self.assertEqual(r.generation_family('CORE_EDR_001'),('CORE_EDR_001',))
        self.assertEqual(set(r.generation_family('CORE_LOE_039')),{'CORE_LOE_039','LOE_039'})


if __name__=='__main__':unittest.main()
