"""Complete real past Secret source, ordinary casts and original-instance cleanup."""
from dataclasses import asdict
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import build_registry,disco_past_secrets as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardDefinition,CardType,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.secret_expirations import KEY,QUERY,ExpireSecret,validate_value
from hs_sim.engine.secrets import RemoveSecret,SetSecret
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

CARD=native.CARD;BARRIER='EX1_289';YETI='CORE_CS2_182';P='k647.'
WATCH,FILL,REMOVE,REPLACE,AUTO,FAIL=(P+x for x in('watch','fill','remove','replace','auto','fail'))
OLD=('EX1_287',BARRIER,'EX1_130','EX1_294','EX1_610')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original K647 deployment/cleanup')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    f=build_cn37_local_pool_format();r=f.registry;context=f.context
    if mode!='normal':
        # An isolated weighted fixture retains all 72 candidates. Production's
        # original pool, weight-one inventory and scope remain untouched.
        context=GenerationContext(f.context.target_id+'.fixture.'+mode,f.context.mode)
        pool=PoolDefinition(native.POOL,'k647.full72-weighted-fixture',context.target_id,context.mode,
            tuple(PoolMember(cid,10**12 if cid==BARRIER else 1)for cid in native.load_batch()[0]['member_ids']),complete=True)
        r.register_pool(pool);r.register_generation_scope(GenerationScope('k647.'+mode,native.POOL,
            context.target_id,context.mode,CARD,None,QUERY,pool_digest(pool)))
    def fail(c):raise ValueError('K647 deliberate failure')
    r.register_behavior(FAIL,fail)
    def remove(c):
        target=next((i for i in c.state.players[c.player_id].secrets if c.state.entities[i].secret_expiry is not None),None)
        return ()if target is None else(RemoveSecret(target),)
    for cid,body in((FILL,lambda c:tuple(SetSecret(c.player_id,cid)for cid in OLD)),(REMOVE,remove),
            (REPLACE,lambda c:(SetSecret(c.player_id,BARRIER),)),(AUTO,lambda c:(CastSpell(1,CARD,c.source_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def watch(c):
        e=c.event
        if e.kind=='secret_set':
            target=c.state.entities.get(e.source_id)
            if target is None or target.secret_expiry is None:return ()
            if mode=='set_fail':return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
            if mode=='set_wait':return (prompt(c),)
        if e.kind=='secret_removed'and mode=='expiry_wait':return (prompt(c),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        metadata=metadata(tribes=()),triggers=(TriggerSpec('secret_set',WATCH),TriggerSpec('secret_removed',WATCH))))
    return r,context


def registry(mode='normal',role='writer'):return fixture(mode,role)[0]


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for v in value.values():result.extend(wires(v,name))
    elif isinstance(value,list):
        for v in value:result.extend(wires(v,name))
    return result


class DiscoPastSecretsTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,mode='normal',hand=(CARD,),watch=False,enemy_hand=()):
        self.mode=mode;r,context=fixture(mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=(WATCH,)if watch else(),
            deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_05',hand=enemy_hand,
            deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30)),seed=647,generation_context=context),r)

    def cast(self,g):return self.play(g,CARD)

    def marks(self,g):return tuple(e.secret_expiry for e in g.state.entities.values()if e.secret_expiry is not None)

    def children(self,g,source):return tuple(c for c in g.state.cast_history if c.caster_id==source and c.iteration==1)

    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_complete_source_faces_native_pins_and_original_evidence(self):
        d,ref=native.load_batch();self.assertEqual(d['member_ids'],ref['candidate_ids']);self.assertEqual(len(d['member_ids']),72)
        self.assertEqual(d['source_record']['record']['id'],CARD);self.assertEqual(d['evidence_only'][0]['record']['id'],'WON_040e')
        self.assertEqual(len(d['official_observations']),2);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        self.assertFalse(d['membership_uses_executable_coverage']);self.assertFalse(d['new_standard_roots'])

    def test_actual_bound_pool_keeps_all_72_original_members_weights_and_shared_identity_order(self):
        r,c=fixture();d,_=native.load_batch();pool=r.pool(native.POOL,c)
        self.assertEqual([v.card_id for v in pool.members],d['member_ids']);self.assertTrue(all(v.weight==1 for v in pool.members))
        actual=resolve_candidates(r,c,native.POOL,QUERY,source_card_id=CARD,exclude_source_by_rule=True)
        self.assertEqual([v.card_id for v in actual],sorted(d['member_ids'],key=lambda cid:r.pool_card(cid).generation_identity))
        self.assertEqual(len(actual),72);self.assertTrue(all(v.weight==1 for v in actual))

    def test_missing_default_metadata_is_exactly_reused_from_unchanged_complete_definitions(self):
        r,_=fixture();d,_=native.load_batch();pins={v['card_id']:v for v in d['native_pins']}
        for cid in native.METADATA_IDS:
            self.assertEqual(canonical_digest(asdict(r.card(cid))),pins[cid]['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),pins[cid]['pool_card_sha256'])

    def test_real_host_paid_root_creates_five_ordinary_free_secret_casts(self):
        g=self.game();source=self.cast(g);children=self.children(g,source)
        self.assertEqual(len(children),5);self.assertTrue(all(c.origin=='effect'and c.completed and c.payload_started for c in children))
        self.assertTrue(all(g.registry.card(c.card_id).secret is not None for c in children))
        self.assertEqual(g.state.players[1].mana,24);self.assertEqual(len(g.state.play_history),1)
        parent=next(c.id for c in g.state.cast_history if c.source_id==source and c.card_id==CARD)
        self.assertTrue(self.marks(g));self.assertTrue(all(v.parent_cast_id==parent for v in self.marks(g)))

    def test_duplicate_attempts_remain_real_casts_without_phantom_deployments(self):
        g=self.game(mode='weighted');source=self.cast(g)
        self.assertEqual([c.card_id for c in self.children(g,source)],[BARRIER]*5)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(len(self.marks(g)),1)
        self.assertEqual(len([e for e in g.events if e.kind=='secret_set_failed']),4);self.portable(g)

    def test_preexisting_same_secret_is_not_marked_or_removed(self):
        g=self.game(mode='weighted',hand=(BARRIER,CARD));old=self.play(g,BARRIER);source=self.cast(g)
        self.assertEqual(len(self.children(g,source)),5);self.assertFalse(self.marks(g));self.assertIsNone(g.state.entities[old].secret_expiry)
        self.cycle(g);self.assertEqual(g.state.entities[old].zone,Zone.SECRET)

    def test_full_shared_secret_area_still_attempts_five_casts_and_does_not_mark_old_secrets(self):
        g=self.game(mode='weighted',hand=(FILL,CARD));self.play(g,FILL);before=tuple(g.state.players[1].secrets);source=self.cast(g)
        self.assertEqual(len(self.children(g,source)),5);self.assertEqual(tuple(g.state.players[1].secrets),before)
        self.assertFalse(self.marks(g));self.cycle(g);self.assertEqual(tuple(g.state.players[1].secrets),before)

    def test_original_marked_instance_expires_on_next_owner_start_not_opponent_start(self):
        g=self.game(mode='weighted');self.cast(g);mark=self.marks(g)[0];target=mark.card.entity_id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].zone,Zone.SECRET)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertFalse(self.marks(g))
        self.assertTrue(any(e.kind=='secret_removed'and e.source_id==target for e in g.events));self.portable(g)

    def test_consumed_secret_does_not_remove_a_later_same_named_redeployment(self):
        g=self.game(mode='weighted',hand=(CARD,REMOVE,REPLACE));self.cast(g);old=self.marks(g)[0].card.entity_id
        self.play(g,REMOVE);self.play(g,REPLACE);new=g.state.players[1].secrets[0];self.assertNotEqual(old,new)
        self.cycle(g);self.assertEqual(g.state.entities[new].zone,Zone.SECRET);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)

    def test_multiple_real_producers_do_not_extend_an_existing_original_deadline(self):
        g=self.game(mode='weighted',hand=(CARD,CARD));first=self.cast(g);mark=self.marks(g)[0];second=self.cast(g)
        self.assertEqual(len(self.children(g,first)),5);self.assertEqual(len(self.children(g,second)),5)
        self.assertEqual(self.marks(g),(mark,));self.cycle(g);self.assertFalse(g.state.players[1].secrets)

    def test_automatic_root_on_opponents_turn_keeps_original_caster_owner_clock(self):
        g=self.game(mode='weighted',hand=(),enemy_hand=(AUTO,));g.apply(EndTurn(1));self.play(g,AUTO,player=2)
        self.assertTrue(self.marks(g));self.assertTrue(all(v.deadline.player_id==1 for v in self.marks(g)))
        g.apply(EndTurn(2));self.assertFalse(self.marks(g));self.assertFalse(g.state.players[1].secrets)

    def test_deployment_wait_preserves_remaining_casts_mark_before_notifications_and_replay(self):
        g=self.game(mode='set_wait',watch=True);source=self.cast(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.children(g,source)),1);self.assertEqual(len(self.marks(g)),1)
        g=self.portable(g);self.choose(g);self.assertEqual(len(self.children(g,source)),5);self.portable(g)

    def test_cleanup_wait_resumes_before_start_events_without_removing_other_instances(self):
        g=self.game(mode='expiry_wait',watch=True);self.cast(g);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.active_player,1);self.assertFalse(self.marks(g))
        g=self.portable(g);self.choose(g);self.assertFalse(g.state.players[1].secrets);self.portable(g)

    def test_action_and_choice_failures_roll_back_casts_allocations_deadlines_payment_and_rng(self):
        g=self.game(mode='set_fail',watch=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(mode='set_wait',watch=True);self.cast(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g)

    def test_unbound_source_fails_explicitly_and_rolls_back_instead_of_omitting_candidates(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),mana=10,max_mana=10),PlayerSetup('HERO_08')),seed=647),build_registry())
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g)
        self.assertEqual(g.snapshot(),before)

    def test_rehashed_active_marker_cannot_be_dropped_or_borrow_future_instance_or_owner_clock(self):
        g=self.game(mode='weighted');self.cast(g);target=self.marks(g)[0].card.entity_id
        for key,value in(('instance_id',10**8),('parent_cast_id',10**8),('deadline',None),('card',None)):
            with self.subTest(key=key):
                saved=json.loads(json.dumps(g.snapshot()));saved['state']['entities'][str(target)]['secret_expiry'][key]=value
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('weighted','independent-reader'))
        saved=json.loads(json.dumps(g.snapshot()));saved['state']['entities'][str(target)]['secret_expiry']=None
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('weighted','independent-reader'))

    def test_rehashed_deployment_receipt_cannot_change_accepted_cast_or_instance(self):
        g=self.game(mode='weighted');self.cast(g);saved=json.loads(json.dumps(g.snapshot()))
        event=next(e for e in saved['events']if KEY in e['data']);payload=json.loads(event['data'][KEY]);payload['instance_id']+=1;event['data'][KEY]=json.dumps(payload)
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('weighted','independent-reader'))

    def test_waiting_pool_request_cannot_shrink_original_five_cast_count(self):
        g=self.game(mode='set_wait',watch=True);self.cast(g);saved=json.loads(json.dumps(g.snapshot()))
        nodes=wires(saved['resolution_frame'],'ContinuePoolCasts');self.assertTrue(nodes)
        for node in nodes:node['fields']['spec']['fields']['count']=4
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('set_wait','independent-reader'))

    def test_early_cleanup_request_rejects_original_future_deadline(self):
        g=self.game(mode='weighted');self.cast(g);value=self.marks(g)[0];validate_value(g.state,g.registry,value)
        with self.assertRaises(ValueError):ExpireSecret(value).validate_in_state(g.state,g.registry,g.events)

    def test_players_do_not_receive_private_deadlines_complete_candidates_or_cast_ancestry(self):
        g=self.game(mode='set_wait',watch=True);self.cast(g)
        for pid in(1,2):
            view=json.dumps(g.for_player(pid).observe())
            for key in(KEY,'secret_expiry','parent_cast_id','SecretExpiry','resolution_frame','rng_state'):self.assertNotIn(key,view)
        self.assertNotIn(BARRIER,json.dumps(g.for_player(2).observe()))


if __name__=='__main__':unittest.main()
