"""The real local host discovers all original27 Mechs and executes native effects."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
import tempfile
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import past_colossal_source_pool as colossal
from hs_sim.cards import past_paladin_mech_source_pool as binding
from hs_sim.cards.simple_followup_p89_cards import QUERIES
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, Game,
    IllegalAction, Keyword, LaunchStarship, PlayCard, PlayerSetup, ResolutionError,
    Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.generation_scopes import pool_digest
from hs_sim.engine.model import PLAYABLE_CARD_CLASSES
from hs_sim.engine.pools import GenerationPolicy, PoolCard, PoolQuery, resolve_candidates, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.local_pool_format import build_cn37_local_pool_format, load_bindings
from hs_sim.targets import TargetValidationError, canonical_digest
from tools import card_batch as batch

SOURCE, POOL = binding.SOURCE, binding.POOL
UNIT, SECOND, OTHER, WATCH, KILL, FAULT = ('k588.'+v for v in ('unit','second','spell','watch','kill','fault'))
HELLION, HELLBAT, PIECE, SAVIOR = 'SC_412','SC_412t','SC_405','TSC_083'


@lru_cache(None)
def host(mode='normal', role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    def fail(c): raise ResolutionError('K588 deliberate generated card failure')
    def watch(c):
        e = c.event
        if e.player_id != c.player_id or e.target_id is None: return ()
        if c.state.entities[e.target_id].card_id not in binding.load_batch()['member_ids']: return ()
        if mode == 'failure': return (InvokeBehavior(FAULT,c.source_id,c.player_id),)
        if mode != 'waiting': return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(FAULT,fail); r.register_behavior(WATCH,watch)
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    for cid,attack,health,tribe in ((UNIT,1,3,'mech'),(SECOND,2,4,'beast')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,
            metadata=CardMetadata(False,(CardClass.PALADIN,),None,tribes=(tribe,))))
    r.register_card(CardDefinition(OTHER,OTHER,CardType.SPELL,
        metadata=CardMetadata(False,(CardClass.PALADIN,),None)))
    r.register_card(CardDefinition(KILL,KILL,CardType.SPELL,on_play=KILL,requires_target=True))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('card_added_to_hand',WATCH),)))
    if mode == 'missing': r._cards.pop('GVG_058')
    r.validate(); return f


def candidates():
    f = host()
    return resolve_candidates(f.registry,f.context,POOL,binding.QUERY,
        source_card_id=SOURCE,player_id=1,exclude_source_by_rule=True)


def seed_for(cid):
    rows = candidates()
    return next(n for n in range(1000) if cid in sample_candidates(Random(n),rows,3,replacement=False))


class PastPaladinMechSourcePoolTests(CardBatchTestMixin,unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode,role:host(mode,role).registry)

    def game(self,desired=SAVIOR,*,mode='normal',player=1,hero='HERO_04',hand=(),own=(),enemy=(),deck=None):
        self.mode = mode; f = host(mode)
        if mode in ('waiting','failure'): own = (WATCH,*own)
        own_deck = (UNIT,SECOND,OTHER)*4 if deck is None else deck
        players = tuple(PlayerSetup(hero if p == player else 'HERO_08',
            hand=(SOURCE,*hand) if p == player else (),board=own if p == player else enemy,
            deck=own_deck if p == player else (UNIT,)*12,mana=60,max_mana=60,mana_cap=60) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed_for(desired),
            generation_context=f.context),f.registry)

    def acquire(self,g,cid,player=1):
        before = set(g.state.players[player].hand)
        self.play(g,SOURCE,player=player)
        self.assertEqual(len(g.state.pending_choice.options),3)
        self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
        new = set(g.state.players[player].hand)-before
        self.assertEqual(len(new),1)
        return g.state.entities[new.pop()]

    def test_complete_original_records_main_faces_source_and_native_pins(self):
        data = binding.load_batch(); ref = batch.read(data['reference_document']); f = host()
        self.assertEqual(data['source_producer'],ref['source_producer'])
        self.assertEqual(data['member_ids'],ref['candidate_ids'])
        self.assertEqual(len(ref['candidate_records']),27)
        raw = {v['record']['id']:v['record'] for v in ref['candidate_records']}
        raw[SOURCE] = ref['source_producer']['record']
        self.assertEqual(len(ref['official_observations']),56)
        for face in ref['official_observations']:
            batch.check_face(raw[face['card_id']],face['face'],face['locale'],
                ref['display_normalizations'].get(face['card_id']),
                numeric_normalizations=ref['numeric_normalizations'].get(face['card_id']))
        for row in data['native_pins']:
            self.assertEqual(canonical_digest(asdict(f.registry.card(row['card_id']))),row['definition_sha256'])
        self.assertFalse(data['membership_uses_executable_coverage']); self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['cn_calibrated']); self.assertFalse(ref['runtime_bindings_added'])

    def test_full_union_preserves_old46_and_all_three_original_orders_identities_weights(self):
        f = host(); data = binding.load_batch(); pool = f.registry.pool(POOL,f.context)
        self.assertEqual([v.card_id for v in pool.members],data['merged_member_ids'])
        self.assertEqual(len(pool.members),72); self.assertTrue(pool.complete)
        self.assertTrue(all(v.weight == 1 for v in pool.members)); self.assertEqual(pool.excluded_card_ids,())
        self.assertEqual([v.card_id for v in pool.members if v.card_id in data['prior_member_ids']],data['prior_member_ids'])
        self.assertEqual([v.card_id for v in candidates()],data['member_ids'])
        for query,cl,ids in ((colossal.QUERY,None,colossal.load_batch()['member_ids']),
                (colossal.FRONTIER_QUERY,CardClass.DRUID,colossal.load_batch()['frontier_member_ids'])):
            self.assertEqual(colossal.projection(f.registry,pool.members,query,cl),ids)
        self.assertEqual(data['shared_ids'],['TSC_030'])
        self.assertEqual(sum(v.card_id == 'TSC_030' for v in candidates()),1)
        scopes=[s for s in f.registry.generation_scopes.values() if s.pool_key==pool.key]
        self.assertEqual(len(scopes),3)
        self.assertEqual({s.source_card_id for s in scopes},{'GDB_857','CATA_EVENT_000','TIME_016'})

    def test_fixed_paladin_query_is_independent_of_recipient_class_but_scope_is_exact(self):
        f = host(); scope = next(s for s in f.registry.generation_scopes.values() if s.source_card_id == SOURCE)
        self.assertIsNone(scope.current_class); self.assertEqual(scope.query,binding.QUERY)
        self.assertEqual(scope.inventory_sha256,pool_digest(f.registry.pool(POOL,f.context)))
        for hero_class in (None,*sorted(PLAYABLE_CARD_CLASSES)):
            rows = resolve_candidates(f.registry,f.context,POOL,binding.QUERY,current_class=hero_class,
                source_card_id=SOURCE,exclude_source_by_rule=True)
            self.assertEqual(rows,candidates())
        for query in (replace(binding.QUERY,class_mode='current',classes=()),
                replace(binding.QUERY,class_mode='other',classes=()),
                PoolQuery(any_of=(PoolQuery(class_mode='current'),PoolQuery(class_mode='specified',classes=(CardClass.PALADIN,))))):
            with self.assertRaises(ValueError): replace(scope,query=query)

    def test_real_source_all27_can_be_discovered_buffed_paid_and_played_without_cropping(self):
        for cid in binding.load_batch()['member_ids']:
            with self.subTest(card=cid):
                g = self.game(cid); probe = Random(); probe.setstate(g._rng.getstate())
                offered = sample_candidates(probe,candidates(),3,replacement=False)
                self.play(g,SOURCE)
                self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),offered)
                self.assertEqual(g._rng.getstate(),probe.getstate()); self.assertEqual(g.state.players[1].mana,57)
                self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
                e = self.entity(g,cid); definition = g.registry.card(cid)
                self.assertEqual((e.attack,e.max_health),(definition.attack+5,definition.health+5))
                price = quote_unselected_cost(g.state,g.registry,e).amount
                root = self.play(g,cid)
                for _ in range(12):
                    if g.state.pending_choice is None: break
                    self.choose(g,g.state.pending_choice.options[0].id)
                self.assertIsNone(g.state.pending_choice)
                self.assertEqual(g.state.play_history[-1].card_id,cid)
                self.assertEqual(g.state.play_history[-1].cost,price)
                self.assertEqual(g.state.entities[root].zone,Zone.BOARD)
        self.portable(g)

    def test_real_fixed_source_works_in_both_seats_with_other_hero_classes(self):
        for player,hero in ((1,'HERO_08'),(2,'HERO_03')):
            with self.subTest(player=player,hero=hero):
                g = self.game('GVG_058',player=player,hero=hero); e = self.acquire(g,'GVG_058',player)
                self.assertEqual((e.attack,e.max_health),(7,7))
                self.play(g,'GVG_058',player=player)
                self.assertEqual(g.state.players[player].mana,55)
                self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[e.id].keywords)
        self.portable(g)

    def test_generated_annoy_module_magnetizes_full_grant_once_with_real_keywords(self):
        g = self.game('BOT_911',own=(UNIT,)); e = self.acquire(g,'BOT_911')
        target = self.entity(g,UNIT,zone='board').id
        g.apply(PlayCard(1,e.id,position=0)); host_body = g.state.entities[target]
        self.assertEqual((host_body.attack,host_body.max_health),(8,12))
        self.assertTrue({Keyword.TAUNT,Keyword.DIVINE_SHIELD} <= set(host_body.keywords))
        self.assertEqual(g.state.entities[e.id].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.play_history[-1].magnetic_target_id,target)
        self.assertFalse(g.state.death_history); self.portable(g)

    def test_generated_savior_original_dredge_reward_wait_restores_and_executes(self):
        g = self.game(deck=(UNIT,SECOND,OTHER)); self.acquire(g,SAVIOR); self.play(g,SAVIOR)
        saved = g.snapshot(); restored = self.portable(g)
        with self.assertRaises(IllegalAction): self.choose(g,'not-a-dredged-card')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,restored):
            self.choose(current,next(o.id for o in current.state.pending_choice.options if o.card_id == UNIT))
            selected = current.state.entities[current.state.players[1].deck[0]]
            self.assertEqual((selected.card_id,selected.attack,selected.max_health),(UNIT,8,10))
        self.assertEqual(g.snapshot(),restored.snapshot()); self.portable(g)

    def test_generated_hellion_preserves_source_grant_after_real_launch_and_rush_combat(self):
        g = self.game(HELLION,hand=(PIECE,KILL),own=(UNIT,),enemy=(UNIT,)); e = self.acquire(g,HELLION)
        piece = self.play(g,PIECE); self.play(g,KILL,piece); ship = construction(g.state,1)
        self.assertIsNotNone(ship); g.apply(LaunchStarship(1,ship.id))
        self.assertEqual((g.state.entities[e.id].card_id,g.state.entities[e.id].attack,g.state.entities[e.id].max_health),(HELLBAT,9,9))
        self.play(g,HELLBAT); ally = self.entity(g,UNIT,zone='board'); target = self.entity(g,UNIT,2,'board')
        self.assertEqual(ally.attack,3); self.assertIn(Keyword.RUSH,ally.keywords)
        g.apply(Attack(1,ally.id,target.id)); self.assertEqual(g.state.entities[target.id].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_actual_source_pending_discovery_restore_clone_replay_and_invalid_choice_are_atomic(self):
        g = self.game(); self.play(g,SOURCE); saved = g.snapshot(); restored = self.portable(g)
        with self.assertRaises(IllegalAction): self.choose(g,'unknown-choice')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,restored):
            self.choose(current,next(o.id for o in current.state.pending_choice.options if o.card_id == SAVIOR))
        self.assertEqual(g.snapshot(),restored.snapshot()); self.portable(g)

    def test_generated_notification_wait_has_full_grant_and_resumes_without_redelivery(self):
        g = self.game(mode='waiting'); self.acquire(g,SAVIOR)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.entity(g,SAVIOR).attack,self.entity(g,SAVIOR).max_health),(7,7))
        saved = g.snapshot(); restored = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,restored): self.choose(current)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(g.state.players[1].hand),1); self.portable(g)

    def test_late_generation_failure_rolls_back_choice_delivery_grant_and_rng(self):
        g = self.game(mode='failure'); self.play(g,SOURCE); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate generated card failure'):
            self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id == SAVIOR))
        self.assertEqual(g.snapshot(),saved)

    def test_missing_eligible_native_rejects_before_rng_and_keeps_full_inventory(self):
        g = self.game(mode='missing'); saved = g.snapshot(); f = host('missing')
        self.assertEqual(len(f.registry.pool(POOL,f.context).members),72)
        self.assertTrue(any(v.card_id == 'GVG_058' for v in f.registry.pool(POOL,f.context).members))
        with self.assertRaisesRegex(ResolutionError,'GVG_058'): self.play(g,SOURCE)
        self.assertEqual(g.snapshot(),saved)

    def test_unknown_sources_broadened_queries_and_nondefault_policies_remain_closed(self):
        f = host()
        for source,query in QUERIES.items():
            if source in (SOURCE,colossal.SOURCE): continue
            with self.subTest(source=source), self.assertRaises(UnsupportedDefinitionError):
                resolve_candidates(f.registry,f.context,POOL,query,current_class=CardClass.MAGE,
                    source_card_id=source,exclude_source_by_rule=True)
        for changed in (dict(source_card_id='TIME_707'),dict(source_card_id=None),
                dict(query=PoolQuery(kinds=(CardType.MINION,))),dict(policy=GenerationPolicy((Keyword.OLD_GOD,)))):
            args=dict(query=binding.QUERY,source_card_id=SOURCE,exclude_source_by_rule=True); args.update(changed)
            query=args.pop('query')
            with self.assertRaises(UnsupportedDefinitionError): resolve_candidates(f.registry,f.context,POOL,query,**args)
        g = self.game(hand=('TIME_707',)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unreviewed generation scope'): self.play(g,'TIME_707')
        self.assertEqual(g.snapshot(),saved)

    def test_only_three_new_metadata_rows_no_standard_roots_or_ordinary_pool_changes(self):
        f = host(); launch = build_cn37_launch_candidate_format()
        self.assertEqual(tuple(v['card_id'] for v in binding.load_batch()['metadata_additions']),binding.METADATA_IDS)
        for cid in binding.METADATA_IDS:
            self.assertNotIn(cid,launch.registry.pool_cards)
            self.assertEqual(f.registry.pool_card(cid),PoolCard.from_definition(f.registry.card(cid)))
        self.assertEqual(f.root_card_ids,launch.root_card_ids)
        self.assertEqual(f.policy.allowed_card_ids,launch.policy.allowed_card_ids)
        self.assertEqual(f.policy.banned_card_ids,launch.policy.banned_card_ids)
        for pid in ('constructed.cards','constructed.minions'):
            a,b = f.registry.pool(pid,f.context),launch.registry.pool(pid,launch.context)
            self.assertEqual((a.members,a.excluded_card_ids,a.complete),(b.members,b.excluded_card_ids,b.complete))
        with self.assertRaises(UnsupportedDefinitionError): launch.registry.pool(POOL,launch.context)

    def test_predecessor_manifest_is_preserved_and_mutated_member_or_manifest_is_rejected(self):
        manifest = load_bindings(); prior = batch.read(manifest['previous_manifest']['path'])
        for key,value in prior.items():
            if key not in ('policy_id','accepted_on','previous_manifest'): self.assertEqual(manifest[key],value)
        self.assertEqual(canonical_digest(prior),manifest['previous_manifest']['canonical_sha256'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'changed.json'; value = deepcopy(binding.load_batch()); value['member_ids'].pop()
            path.write_text(json.dumps(value),encoding='utf8')
            with patch.object(binding,'BATCH_PATH',path), self.assertRaises(TargetValidationError): binding.load_batch()
            value = deepcopy(manifest); value['paladin_mech_binding']['merged_member_count'] = 71
            path.write_text(json.dumps(value),encoding='utf8')
            with patch('hs_sim.local_pool_format.MANIFEST_PATH',path), self.assertRaises(TargetValidationError): load_bindings()

    def test_late_native_or_metadata_error_does_not_half_install_new_metadata(self):
        from hs_sim.cards.one_cost_past_pool import local_pool
        f = build_cn37_launch_candidate_format(); r = f.registry; local_pool(r,f.context)
        last = binding.load_batch()['native_pins'][-1]['card_id']; r._cards[last] = replace(r.card(last),health=r.card(last).health+1)
        before = r.fingerprint()
        with self.assertRaises(TargetValidationError): binding.missing_metadata(r)
        self.assertEqual(r.fingerprint(),before)
        self.assertFalse(set(binding.METADATA_IDS) & set(r.pool_cards))
        f = build_cn37_launch_candidate_format(); r = f.registry; local_pool(r,f.context)
        r.register_pool_card(replace(host().registry.pool_card(PIECE),cost=3)); before = dict(r.pool_cards)
        with self.assertRaises(TargetValidationError): binding.missing_metadata(r)
        self.assertEqual(dict(r.pool_cards),before)
        self.assertNotIn('BOT_911',r.pool_cards); self.assertNotIn('DEEP_015',r.pool_cards)

    def test_unreviewed_physical_extension_cannot_use_old_projection_as_union_proof(self):
        f = host(); data = binding.load_batch(); pool = f.registry.pool(POOL,f.context)
        for altered in (replace(pool,members=pool.members[:-1]),
                replace(pool,members=(replace(pool.members[0],weight=2),*pool.members[1:])),
                replace(pool,complete=False),replace(pool,members=tuple(reversed(pool.members)))):
            with self.assertRaises(TargetValidationError): binding.validate_union(f.registry,data,altered)
        with self.assertRaises(TargetValidationError): colossal.validate_union(f.registry,colossal.load_batch(),pool)

    def test_faction_candidates_are_retained_under_explicit_uncertified_local_policy(self):
        data = binding.load_batch(); policy = data['faction_qualification']
        self.assertEqual(policy['local_mode'],'allow_full_reference_without_faction_gate')
        self.assertFalse(policy['hidden_gate_implemented']); self.assertFalse(policy['officially_certified'])
        self.assertTrue(set(policy['candidate_ids']) <= {v.card_id for v in candidates()})
        g = self.game(PIECE); self.assertFalse(set(policy['candidate_ids']) & set(g.state.players[1].original_deck))
        e = self.acquire(g,PIECE); self.assertEqual((e.attack,e.max_health),(6,6))
        self.play(g,PIECE); self.assertIn(Keyword.STARSHIP_PIECE,g.state.entities[e.id].keywords)

    def test_registry_scope_and_wrong_target_cannot_borrow_current_generation(self):
        g = self.game(hand=(SOURCE,)); self.acquire(g,SAVIOR); saved = g.snapshot()
        saved['generation_context']['target_id'] = 'cn37-local-special-pools-v10-fcf2d8cad9265296'
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        restored = Game.from_snapshot(saved,host('normal','independent-reader').registry); before = restored.snapshot()
        with self.assertRaises(ResolutionError): self.play(restored,SOURCE)
        self.assertEqual(restored.snapshot(),before)
        fresh = host('normal','scope-omitted').registry
        scope = next(s for s in fresh.generation_scopes.values() if s.source_card_id == SOURCE)
        with self.assertRaises(ValueError): fresh.register_generation_scope(replace(scope,id=scope.id+'.bad',inventory_sha256='0'*64))
        fresh._generation_scopes.pop(scope.id)
        with self.assertRaises(SnapshotError): Game.from_snapshot(g.snapshot(),fresh)

    def test_player_views_keep_hand_private_and_do_not_publish_inventory_or_qualification_proofs(self):
        g = self.game(player=2,hero='HERO_08'); self.acquire(g,SAVIOR,2)
        self.assertIn(SAVIOR,json.dumps(g.observe(2))); self.assertNotIn(SAVIOR,json.dumps(g.observe(1)))
        for player in (1,2):
            text = json.dumps(g.observe(player))
            for field in ('generation_scopes','inventory_sha256','merged_member_ids','native_pins','faction_qualification','rng_state'):
                self.assertNotIn('"'+field+'"',text)


if __name__ == '__main__': unittest.main()
