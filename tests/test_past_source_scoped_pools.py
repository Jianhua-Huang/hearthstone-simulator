"""Complete known past views through real local-host discovery and recursion."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_source_scoped_pools import load_batch,QUERIES
from hs_sim.engine import (Attack,CardDefinition,CardType,Game,PlayerSetup,ResolutionError,
    Scenario,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Transform
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.pools import (GenerateFromPool,GenerationPolicy,PoolQuery,resolve_candidates,sample_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.model import CardClass,Keyword
from hs_sim.local_pool_format import build_cn37_local_pool_format,load_bindings
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.targets import canonical_digest
from tools import card_batch as batch

S='k568.';UNIT,WATCH,FAULT,UNKNOWN=(S+x for x in ('unit','watch','fault','unknown'))
TEACHER,PUPIL,FRONTIER,NEPT='TIME_704','TIME_704t','GDB_857','TID_712'


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=build_cn37_local_pool_format();r=fmt.registry
    def fail(c):raise ResolutionError('k568 deliberate resume failure')
    def watch(c):
        e=c.event;target=c.state.entities.get(e.target_id)
        if target is None or e.kind!='card_added_to_hand':return ()
        if target.card_id==PUPIL and mode in ('transform_teacher','bounce_teacher','kill_teacher'):
            parent=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==TEACHER)
            return {'transform_teacher':(Transform(parent.id,UNIT),),'bounce_teacher':(ReturnToHand(parent.id),),
                    'kill_teacher':(Destroy(parent.id,c.source_id),)}[mode]
        if target.card_id!=(PUPIL if mode=='wait_student' else NEPT if mode=='wait_recipient' else ''):return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',
            (InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(FAULT,fail);r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=5,health=40,dormant_turns=0))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('card_added_to_hand',WATCH),)))
    r.register_behavior(UNKNOWN,lambda c:(GenerateFromPool(c.player_id,'constructed.past.cards',
        QUERIES['current_class_collectible_minion_exactly_ten'],source_id=c.source_id),))
    r.register_card(CardDefinition(UNKNOWN,UNKNOWN,CardType.SPELL,on_play=UNKNOWN))
    if mode=='missing':r._cards.pop('OG_141') # Vanilla member removed; inventory remains intact.
    r.validate();return fmt


def members(fmt,source):
    scope=next(s for s in fmt.registry.generation_scopes.values()if s.source_card_id==source)
    return resolve_candidates(fmt.registry,fmt.context,scope.pool_id,scope.query,current_class=scope.current_class,
        source_card_id=source,player_id=1,exclude_source_by_rule=True)


def seed_for(source,card_id):
    candidates=members(fixture(),source)
    return next(seed for seed in range(10000)if card_id in sample_candidates(Random(seed),candidates,3,replacement=False))


class PastSourceScopedPoolTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand,*,mode='normal',hero='HERO_06',player=1,seed=1):
        self.mode=mode;fmt=fixture(mode)
        own=PlayerSetup(hero,hand=hand,board=(WATCH,)if mode.startswith('wait_')or mode.endswith('_teacher')else(),deck=(UNIT,)*12,
            mana=60,max_mana=60,mana_cap=60)
        other=PlayerSetup('HERO_08',board=(UNIT,),deck=(UNIT,)*12,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if player==1 else(other,own),active_player=player,
            seed=seed,generation_context=fmt.context),fmt.registry)

    def pick_card(self,g,cid):self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))

    def test_complete_original_references_records_and_exact_native_definition_pins(self):
        data=load_batch();raw={r['id']:r for r in batch.read(data['source'])};fmt=fixture()
        self.assertEqual(len(data['cards']+data['existing_dependencies']),56)
        for row in data['cards']+data['existing_dependencies']:
            cid=row['record']['id'];self.assertEqual(row['record'],raw[cid])
            self.assertEqual(canonical_digest(asdict(fmt.registry.card(cid))),row['definition_sha256'])
        for face in data['official_faces']:batch.check_face(raw[face['card_id']],face['face'],face['locale'],{})
        for reference in data['reviewed_sources']:
            self.assertEqual(batch.sha(reference['path']),reference['sha256'])
            self.assertEqual(batch.read(reference['path']),reference['reference'])
        self.assertEqual([len(i['member_ids'])for i in data['inventories']],[21,34])
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_all_known_members_weights_and_scopes_preserved_without_executable_filter(self):
        fmt=fixture()
        for item in load_batch()['inventories']:
            pool=fmt.registry.pool(item['id'],fmt.context)
            self.assertEqual([m.card_id for m in pool.members if m.card_id in item['member_ids']],item['member_ids'])
            self.assertEqual(len(pool.members),72 if item['id']=='constructed.past.cards' else 44)
            self.assertTrue(all(m.weight==1 for m in pool.members));self.assertTrue(pool.complete)
            self.assertEqual([m.card_id for m in members(fmt,item['source_card_id'])],sorted(item['member_ids']))
        self.assertTrue({TEACHER,FRONTIER}<={s.source_card_id for s in fmt.registry.generation_scopes.values()})

    def test_old_ordinary_inventory_and_every_member_native_remain_unchanged(self):
        fmt=fixture();old=build_cn37_launch_candidate_format()
        self.assertEqual(fmt.root_card_ids,old.root_card_ids)
        for pool_id in ('constructed.cards','constructed.minions'):
            current=fmt.registry.pool(pool_id,fmt.context);previous=old.registry.pool(pool_id,old.context)
            self.assertEqual((current.members,current.excluded_card_ids,current.complete),(previous.members,previous.excluded_card_ids,previous.complete))
            self.assertTrue(all(m.card_id in fmt.registry.cards for m in current.members))
        for pool_id in ('constructed.past.cards','constructed.past.spells'):
            with self.assertRaises(UnsupportedDefinitionError):old.registry.pool(pool_id,old.context)

    def test_pure_queries_are_read_only_and_unknown_source_class_query_or_policy_rejected(self):
        fmt=fixture();scope=next(s for s in fmt.registry.generation_scopes.values()if s.source_card_id==FRONTIER)
        before=fmt.registry.fingerprint()
        self.assertEqual(len(resolve_candidates(fmt.registry,fmt.context,scope.pool_id,scope.query,current_class=CardClass.DRUID)),34)
        cases=[dict(current_class=CardClass.MAGE),dict(source_card_id=TEACHER),dict(query=PoolQuery(kinds=(CardType.MINION,))),
            dict(source_card_id=None),dict(policy=GenerationPolicy((Keyword.OLD_GOD,)))]
        for changed in cases:
            args=dict(current_class=CardClass.DRUID,source_card_id=FRONTIER,query=scope.query,policy=GenerationPolicy(),exclude_source_by_rule=True)
            args.update(changed);query=args.pop('query')
            with self.subTest(changed=changed),self.assertRaises(UnsupportedDefinitionError):resolve_candidates(fmt.registry,fmt.context,scope.pool_id,query,**args)
        self.assertEqual(fmt.registry.fingerprint(),before)

    def test_actual_full_frontier_offer_restore_one_cost_neptulon_and_real_hand_combat(self):
        g=self.game((FRONTIER,),seed=seed_for(FRONTIER,NEPT));self.play(g,FRONTIER)
        self.assertEqual(len(g.state.pending_choice.options),3);restored=self.portable(g)
        for game in (g,restored):
            self.pick_card(game,NEPT);source=self.play(game,NEPT)
            self.assertEqual(game.state.play_history[-1].cost,1)
            target=self.entity(game,UNIT,2,'board').id;game.apply(Attack(1,source,target))
            self.assertEqual(game.state.entities[target].damage,8)
            self.assertEqual(next(r for r in game.state.character_attack_history if r.source_card_id==NEPT).terminal.status,'replaced')
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_actual_teacher_student_frontier_recursive_generation_uses_both_full_scopes(self):
        g=self.game((TEACHER,),seed=seed_for(TEACHER,FRONTIER));self.play(g,TEACHER)
        self.assertEqual(len(g.state.pending_choice.options),3);self.pick_card(g,FRONTIER)
        student=self.entity(g,PUPIL);self.assertEqual(next(a.carved_spell_id for a in student.abilities if a.kind=='battlecry'),FRONTIER)
        restored=self.portable(g)
        for game in (g,restored):
            sid=self.play(game,PUPIL)
            casts=[c for c in game.state.cast_history if c.card_id==FRONTIER]
            self.assertEqual(len(casts),1);self.assertEqual(casts[0].caster_id,sid);self.assertEqual(casts[0].origin,'effect')
            generated=[game.state.entities[i]for i in game.state.players[1].hand if game.state.entities[i].card_id in {m.card_id for m in members(fixture(),FRONTIER)}]
            self.assertEqual(len(generated),1);self.assertEqual(quote_unselected_cost(game.state,game.registry,generated[0]).amount,1)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_teacher_creation_and_frontier_recipient_waits_restore_without_reselecting(self):
        for mode,source,chosen in (('wait_student',TEACHER,FRONTIER),('wait_recipient',FRONTIER,NEPT)):
            with self.subTest(mode=mode):
                g=self.game((source,),mode=mode,seed=seed_for(source,chosen));self.play(g,source)
                if mode=='wait_recipient':self.pick_card(g,chosen)
                restored=self.portable(g);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'fault')
                self.assertEqual(g.snapshot(),before)
                for game in (g,restored):
                    self.choose(game)
                    if mode=='wait_student':self.pick_card(game,chosen)
                self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_accepted_teacher_identity_survives_source_transform_bounce_and_death(self):
        for mode in ('transform_teacher','bounce_teacher','kill_teacher'):
            with self.subTest(mode=mode):
                g=self.game((TEACHER,),mode=mode,seed=seed_for(TEACHER,FRONTIER));source=self.play(g,TEACHER)
                self.assertEqual(len(g.state.pending_choice.options),3);self.pick_card(g,FRONTIER)
                student=self.entity(g,PUPIL)
                self.assertEqual(next(a.carved_spell_id for a in student.abilities if a.kind=='battlecry'),FRONTIER)
                self.assertEqual(next(b for b in g.state.battlecry_history if b.source_id==source).payload.card_id,TEACHER)
                if mode=='transform_teacher':self.portable(g)

    def test_real_unknown_hero_views_and_other_producers_fail_atomically_before_selection(self):
        for source,hero in ((TEACHER,'HERO_03'),(FRONTIER,'HERO_08'),('TIME_861','HERO_08'),(UNKNOWN,'HERO_06')):
            with self.subTest(source=source,hero=hero):
                g=self.game((source,),hero=hero);before=g.snapshot()
                with self.assertRaisesRegex(ResolutionError,'Unreviewed generation scope'):self.play(g,source)
                self.assertEqual(g.snapshot(),before)

    def test_missing_executable_member_rejects_full_pool_instead_of_trimming_offer(self):
        g=self.game((FRONTIER,),mode='missing');before=g.snapshot()
        self.assertEqual(len(fixture('missing').registry.pool('constructed.past.cards',fixture('missing').context).members),72)
        with self.assertRaises(ResolutionError):self.play(g,FRONTIER)
        self.assertEqual(g.snapshot(),before)

    def test_second_seat_real_discovery_and_player_projection_do_not_expose_scope_inventory(self):
        g=self.game((FRONTIER,),player=2,seed=seed_for(FRONTIER,NEPT));self.play(g,FRONTIER,player=2)
        self.assertEqual(g.state.pending_choice.player_id,2);self.pick_card(g,NEPT);self.play(g,NEPT,player=2)
        self.assertEqual(g.state.play_history[-1].cost,1)
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for private in ('generation_scopes','inventory_sha256','source_scope_templates'):self.assertNotIn(private,view)
        self.portable(g)

    def test_scope_registry_identity_and_wrong_inventory_digest_are_rejected(self):
        fmt=build_cn37_local_pool_format();scope=next(iter(fmt.registry.generation_scopes.values()))
        with self.assertRaises(ValueError):fmt.registry.register_generation_scope(replace(scope,id=scope.id+'.duplicate'))
        with self.assertRaises(ValueError):fmt.registry.register_generation_scope(replace(scope,id=scope.id+'.wrong',inventory_sha256='0'*64))
        with self.assertRaises(ValueError):replace(scope,current_class=CardClass.NEUTRAL)
        g=self.game((FRONTIER,),seed=seed_for(FRONTIER,NEPT));self.play(g,FRONTIER);saved=g.snapshot()
        fresh=fixture('normal','different-scope').registry
        fresh._generation_scopes.clear()
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fresh)

    def test_remaining_special_domains_and_unknown_past_views_are_explicitly_recorded(self):
        manifest=load_bindings();self.assertEqual(set(manifest['partially_scoped_pool_ids']),{'constructed.past.cards','constructed.past.spells'})
        self.assertEqual(manifest['unresolved_pool_ids'],[])
        self.assertEqual(set(manifest['zombeast_binding']['pool_ids']),{'crafted.zombeast.first','crafted.zombeast.second'})
        self.assertEqual(manifest['partial_inventory_pool_ids'],['constructed.assemble.rajh'])
        self.assertEqual(manifest['pack_binding']['pool_id'],'constructed.standard_pack')
        self.assertFalse(manifest['pack_binding']['formal_pool_complete'])
        self.assertTrue(load_batch()['version_alignment_deferred']);self.assertTrue(load_batch()['rule_boundaries_deferred'])
        self.assertTrue(any('arena' in u for u in load_batch()['uncertainties']))


if __name__=='__main__':unittest.main()
