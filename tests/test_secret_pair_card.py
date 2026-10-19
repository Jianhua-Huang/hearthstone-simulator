"""Faceless Enigma: contextual two-Secret review and two genuine spell casts."""
from copy import deepcopy
from dataclasses import replace
import json
import random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.secret_pair_card import CARD, POOL_ID, QUERY, load_batch, register_secret_pair_card
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Rarity, Registry, Scenario, SecretSpec, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy, InvokeBehavior,
    RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pool_offers import ChooseFromPools, PoolOfferGroup
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
    resolve_candidates, sample_candidates)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

P = 'enigma.test.'
A, B, C = (P+x for x in ('a','b','c'))
CTX = GenerationContext('enigma-explicit-experiment','experimental')


def registry(mode=None, pool=(A,B), unknown=False):
    r = Registry('faceless-enigma-tests-v1.'+str((mode,pool,unknown)))
    register_secret_pair_card(r)
    r.register_card(CardDefinition(P+'avatar','Hero',CardType.HERO,health=50,
        metadata=CardMetadata(False,(CardClass.WARRIOR,),Rarity.NONE)))
    r.register_secret_condition(P+'never',lambda c:False)
    r.register_behavior(P+'noop',lambda c:())
    def secret(cid,klass,collectible=True):
        d = CardDefinition(cid,cid,CardType.SPELL,cost=3,keywords=(Keyword.SECRET,),
            metadata=CardMetadata(collectible,(klass,),Rarity.COMMON),
            secret=SecretSpec(cid,('card_committed',),P+'never',P+'noop'))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    for cid,klass in ((A,CardClass.HUNTER),(B,CardClass.PALADIN),(C,CardClass.MAGE)):
        secret(cid,klass)
    for i in range(5):secret(P+'fill'+str(i),CardClass.MAGE,False)
    secret(P+'token',CardClass.MAGE,False)
    r.register_card(CardDefinition(P+'plain','Plain spell',CardType.SPELL,on_play=P+'noop',
        metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON)))
    r.register_pool_card(PoolCard.from_definition(r.card(P+'plain')))
    r.register_card(CardDefinition(P+'minion','Minion',CardType.MINION,health=5,
        metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON)))
    r.register_pool_card(PoolCard.from_definition(r.card(P+'minion')))
    def setup(c):
        recipient=3-c.player_id if mode in ('other_duplicate','other_full') else c.player_id
        names=(P+'fill'+str(i) for i in range(5)) if mode in ('full','other_full') else (A,)
        return tuple(SetSecret(recipient,cid) for cid in names)
    r.register_behavior(P+'setup',setup)
    r.register_card(CardDefinition(P+'setup','Setup',CardType.SPELL,on_play=P+'setup'))
    r.register_card(CardDefinition(P+'summon','Summoner',CardType.SPELL,on_play=P+'summon'))
    r.register_behavior(P+'summon',lambda c:(Summon(c.player_id,CARD,c.source_id),))
    def fail(c):raise ResolutionError('Enigma deliberate reaction failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if mode in ('kill','control'):
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=CARD:return ()
            return (Destroy(source.id,c.source_id),) if mode=='kill' else (ChangeControl(source.id,3-c.player_id),)
        if c.event.player_id!=c.player_id:return ()
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=10,
        triggers=(TriggerSpec('choice_selected' if mode in ('kill','control') else 'secret_set',P+'watch'),)))
    members=(*pool,P+'token',P+'plain',P+'minion')
    if unknown:
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,3,
            CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON),keywords=(Keyword.SECRET,)))
        members=(*members,P+'unknown')
    r.register_pool(PoolDefinition(POOL_ID,'enigma-fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid) for cid in members),complete=True))
    r.validate();return r


class SecretPairTests(unittest.TestCase):
    def game(self,mode=None,pool=(A,B),unknown=False,pid=1,seed=29,hand_cap=10):
        self.mode,self.pool,self.unknown,self.pid=mode,pool,unknown,pid
        actor=PlayerSetup(P+'avatar',hand=(CARD,P+'setup',P+'summon') if hand_cap>1 else (CARD,),
            board=(P+'watch',) if mode in ('wait','fail','kill','control') else (),
            mana=10,max_mana=10,hand_cap=hand_cap)
        other=PlayerSetup(P+'avatar',mana=10,max_mana=10,hand_cap=hand_cap)
        return Game.from_scenario(Scenario((actor,other) if pid==1 else (other,actor),
            active_player=pid,seed=seed,generation_context=CTX),registry(mode,pool,unknown))

    def play(self,g,cid=CARD):
        eid=next(i for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,eid));return eid

    def select(self,g,cid=None,key=None):
        q=g.state.pending_choice
        opt=next(o for o in q.options if key is not None and o.id==key or key is None and (cid is None or o.card_id==cid))
        g.apply(SelectChoice(q.player_id,q.id,(opt.id,)));return opt.card_id

    def secrets(self,g,pid):
        return [g.state.entities[i].card_id for i in g.state.players[pid].secrets]

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(s,registry(self.mode,self.pool,self.unknown))
        self.assertEqual(restored.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(self.mode,self.pool,self.unknown)).snapshot(),s)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('eligible_ids','resolution_frame','rng_state','PoolOfferReceipt'):
                self.assertNotIn('"'+field+'"',visible)
        return restored

    def test_a00_complete_root_and_all_eleven_existing_secret_sources(self):
        data=load_batch();r=build_registry();root=r.card(CARD);raw=data['cards'][0]['record']
        self.assertEqual((root.cost,root.attack,root.health),(2,2,2))
        self.assertEqual(root.metadata,metadata_from_record(raw));self.assertEqual(raw['name_en'],'Faceless Enigma')
        self.assertEqual(len(data['official_observations']),2)
        self.assertEqual(len(data['existing_dependencies']),11)
        for row in data['existing_dependencies']:
            raw=row['record'];d=r.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256'])
            expected=replace(metadata_from_record(raw),deck_identity=raw['id'].removeprefix('CORE_'))
            self.assertEqual(d.metadata,expected);self.assertEqual(d.secret.key,expected.deck_identity)
        self.assertEqual(QUERY.class_mode,'any')

    def test_a01_actual_two_cost_body_reviews_two_distinct_secrets_without_payment(self):
        g=self.game(pool=(A,B,C));eid=self.play(g);q=g.state.pending_choice
        self.assertEqual((g.state.entities[eid].zone,g.state.players[1].mana),(Zone.BOARD,8))
        self.assertEqual((q.player_id,q.source_id,q.min_count,q.max_count,q.purpose.value),(1,eid,1,1,'effect'))
        self.assertEqual(len({o.card_id for o in q.options}),2)
        self.assertEqual(g.state.cast_history,[])
        self.assertTrue(all(o.preview.cost==3 for o in q.options))

    def test_a02_either_selection_casts_for_original_chooser_then_opponent(self):
        for cid in (A,B):
            with self.subTest(cid=cid):
                g=self.game();eid=self.play(g);self.select(g,cid)
                other=B if cid==A else A
                self.assertEqual(self.secrets(g,1),[cid]);self.assertEqual(self.secrets(g,2),[other])
                casts=g.state.cast_history
                self.assertEqual([(c.card_id,c.player_id,c.origin,c.caster_id) for c in casts],
                    [(cid,1,'effect',eid),(other,2,'effect',eid)])
                self.assertTrue(all(c.completed and c.failure is None for c in casts))
                self.assertEqual((g.state.players[1].mana,g.state.players[2].mana),(8,10))
                self.assertEqual(len(g.state.play_history),1)
                self.assertEqual(g.state.card_discovery_history,[])
                self.assertTrue(all(c.source_id!=eid for c in casts))

    def test_a03_full_sampling_rng_is_reproducible_and_not_resampled_on_selection(self):
        g=self.game(pool=(A,B,C));rng=random.Random();rng.setstate(g._rng.getstate())
        rows=resolve_candidates(g.registry,CTX,POOL_ID,QUERY,source_card_id=CARD,player_id=1,exclude_source_by_rule=True)
        expected=sample_candidates(rng,rows,2,replacement=False)
        self.play(g);self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),expected)
        self.assertEqual(g._rng.getstate(),rng.getstate());before=g.snapshot()['rng_state'];self.select(g)
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_a04_private_review_and_own_secret_do_not_leak_to_other_player(self):
        g=self.game();self.play(g)
        actor=json.dumps(g.for_player(1).observe());other=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertIn(json.dumps(A),actor);self.assertIn(json.dumps(B),actor)
        self.assertNotIn(json.dumps(A),other);self.assertNotIn(json.dumps(B),other)
        self.select(g,A)
        self.assertNotIn(json.dumps(A),json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2)))
        self.assertIn(json.dumps(B),json.dumps(g.for_player(2).observe()))
        # The chooser's original menu remains legitimate knowledge of both cards.
        self.assertIn(json.dumps(B),json.dumps(g.player_events(1)))

    def test_a05_existing_self_secret_remains_in_pool_and_other_cast_still_executes(self):
        g=self.game(mode='duplicate');self.play(g,P+'setup');self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{A,B})
        self.select(g,A);self.assertEqual(self.secrets(g,1),[A]);self.assertEqual(self.secrets(g,2),[B])
        self.assertEqual([c.card_id for c in g.state.cast_history[-2:]],[A,B])

    def test_a06_full_secret_zone_does_not_filter_offer_or_prevent_other_cast(self):
        g=self.game(mode='full');self.play(g,P+'setup');self.play(g);self.select(g,A)
        self.assertEqual(len(self.secrets(g,1)),5);self.assertEqual(self.secrets(g,2),[B])
        self.assertEqual([c.card_id for c in g.state.cast_history[-2:]],[A,B])

    def test_a07_opponent_capacity_or_duplicate_failure_preserves_selected_self_cast(self):
        for mode in ('other_full','other_duplicate'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.play(g,P+'setup');self.play(g);self.select(g,B)
                self.assertEqual(self.secrets(g,1),[B])
                self.assertEqual(len(self.secrets(g,2)),5 if mode=='other_full' else 1)
                self.assertEqual([c.card_id for c in g.state.cast_history[-2:]],[B,A])

    def test_a08_cast_delivery_never_needs_hand_space(self):
        g=self.game(hand_cap=1);self.play(g);self.select(g,A)
        self.assertEqual(self.secrets(g,1),[A]);self.assertEqual(self.secrets(g,2),[B])
        self.assertFalse(g.state.players[1].hand);self.assertFalse(g.state.players[2].hand)

    def test_a09_empty_pool_is_noop_without_rng_or_choice(self):
        g=self.game(pool=());before=g.snapshot()['rng_state'];self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertFalse(g.state.cast_history);self.assertEqual(g.state.players[1].mana,8)

    def test_a10_single_secret_does_not_invent_an_opponent_card(self):
        g=self.game(pool=(B,));self.play(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[B]);self.select(g,B)
        self.assertEqual(self.secrets(g,1),[B]);self.assertFalse(self.secrets(g,2))
        self.assertEqual(len(g.state.cast_history),1)

    def test_a11_unknown_eligible_secret_fails_before_sampling_and_rolls_back_root(self):
        g=self.game(unknown=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_a12_review_and_between_cast_wait_restore_clone_and_replay(self):
        g=self.game(mode='wait');self.play(g);restored=self.portable(g)
        for match in (g,restored):self.select(match,A)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.secrets(g,1),[A])
        self.assertFalse(self.secrets(g,2));self.assertEqual(len(g.state.cast_history),1)
        restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,key='bad')
        self.assertEqual(g.snapshot(),before)
        for match in (g,restored):self.select(match,key='ok')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.secrets(g,2),[B]);self.portable(g)

    def test_a13_source_death_or_control_change_keeps_original_recipients(self):
        for mode in ('kill','control'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);eid=self.play(g);self.select(g,A)
                self.assertEqual(self.secrets(g,1),[A]);self.assertEqual(self.secrets(g,2),[B])
                self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD if mode=='kill' else Zone.BOARD)
                self.assertEqual(g.state.entities[eid].controller,1 if mode=='kill' else 2)

    def test_a14_failure_after_first_secret_rolls_back_only_selection_to_review(self):
        g=self.game(mode='fail');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,A)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,8)
        self.assertFalse(g.state.cast_history);self.assertFalse(self.secrets(g,1));self.portable(g)

    def test_a15_summoning_root_does_not_fire_a_battlecry(self):
        g=self.game();before=g.snapshot()['rng_state'];self.play(g,P+'summon')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual([(c.card_id,c.origin) for c in g.state.cast_history],[(P+'summon','hand')])
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_a16_second_seat_uses_original_player_and_other_seat(self):
        g=self.game(pid=2);eid=self.play(g);self.select(g,B)
        self.assertEqual(self.secrets(g,2),[B]);self.assertEqual(self.secrets(g,1),[A])
        self.assertEqual([(c.player_id,c.caster_id) for c in g.state.cast_history],[(2,eid),(1,eid)])

    def test_a17_narrow_pair_declaration_rejects_unrelated_modes(self):
        spec=ChooseFromPools(1,(PoolOfferGroup(POOL_ID,QUERY,2),),delivery='secret_pair')
        for changes in ({'delivery':'arbitrary'},{'affordable':True},{'temporary_until':1},
                {'groups':(PoolOfferGroup(POOL_ID,QUERY,3),)},
                {'groups':(PoolOfferGroup(POOL_ID,count=2),)},
                {'groups':(PoolOfferGroup(POOL_ID,QUERY,2),PoolOfferGroup(POOL_ID,QUERY,2))}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(spec,**changes)

    def test_a18_rehashed_receipt_cannot_drop_candidate_or_change_selected_identity(self):
        g=self.game();self.play(g);original=g.snapshot()
        for typename,field,value in (('CapturedOfferGroup','eligible_ids',[A]),
                ('ResolvePoolOffer','card_id',C),('ChooseFromPools','delivery','wrong')):
            s=deepcopy(original)
            def change(v):
                if isinstance(v,dict):
                    if v.get('type','').endswith('.'+typename):v['fields'][field]=value
                    for x in v.values():change(x)
                elif isinstance(v,list):
                    for x in v:change(x)
            change(s)
            s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.subTest(typename=typename),self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_a19_complete_current_candidate_secret_pool_uses_existing_real_definitions(self):
        r=build_registry();names=tuple(row['record']['id'] for row in load_batch()['existing_dependencies'])
        r.register_pool(PoolDefinition(POOL_ID,'cn37-root-secret-experiment-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid) for cid in names),complete=True))
        rows=resolve_candidates(r,CTX,POOL_ID,QUERY,source_card_id=CARD,player_id=1,exclude_source_by_rule=True)
        self.assertEqual({m.card_id for m in rows},set(names));self.assertEqual(len(rows),11)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=(CARD,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',mana=10,max_mana=10)),generation_context=CTX,seed=29),r)
        eid=g.state.players[1].hand[0];g.apply(PlayCard(1,eid));q=g.state.pending_choice
        first,second=(o.card_id for o in q.options)
        g.apply(SelectChoice(1,q.id,(q.options[0].id,)))
        self.assertEqual([(c.card_id,c.player_id,c.caster_id) for c in g.state.cast_history],
            [(first,1,eid),(second,2,eid)])
        self.assertTrue(all(c.completed for c in g.state.cast_history))
        self.assertEqual(g.state.players[1].mana,8)


if __name__=='__main__':unittest.main()
