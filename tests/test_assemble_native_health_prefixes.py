"""Original result windows, retained native arrows and real assembly entries."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest

from hs_sim.cards import assemble_native_health_prefixes as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import CopyMinion,Destroy,InvokeBehavior,RequestChoice,ChoiceOption,Silence,Transform
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import DamageKind,HealthFlow,HealthLayer,HealthOp,HealthRule,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha

TROGG,ARM=cards.SOURCES
RUST,CLEANER,PHOENIX,NECRO,FOOT=cards.DEPENDENCIES
P='k447.'
N,TINY,SHIELD,REBORN,WATCH,REDIRECT,KILL,MUTE,COPY,FAIL=(P+x for x in(
    'n','tiny','shield','reborn','watch','redirect','kill','mute','copy','fail'))
COIN='GAME_005';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
CTX=GenerationContext('k447-reviewed-complete-native-health-domains','experimental')


def recipe(a,b=None,half='bottom'):return AssembleRecipe(a,b or a,half).card_id


def nodes(value,name):
    if isinstance(value,dict):
        if str(value.get('type','')).endswith('.'+name):yield value
        for child in value.values():yield from nodes(child,name)
    elif isinstance(value,list):
        for child in value:yield from nodes(child,name)


def rehash(s):
    s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=build_registry();r._version+='.k447.'+mode
    for cid,health,keywords in((N,20,()),(TINY,2,()),(SHIELD,2,(Keyword.DIVINE_SHIELD,)),(REBORN,2,(Keyword.REBORN,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=health,keywords=keywords,metadata=META))
    r.register_card(CardDefinition(REDIRECT,REDIRECT,CardType.MINION,health=1,metadata=META,
        health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,
            target_relation='friendly',target_kinds=(CardType.MINION,),damage_kinds=(DamageKind.MINION_ABILITY,),redirect_to='self'),)))
    def fail(c):raise ResolutionError('K447 deliberate late health suffix failure')
    r.register_behavior(FAIL,fail)
    for cid,fn in((KILL,lambda c:(Destroy(c.target_id,c.source_id),)),(MUTE,lambda c:(Silence(c.target_id),)),
            (COPY,lambda c:(CopyMinion(c.target_id,c.player_id,mode='current'),))):
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    if mode in('wait','late_destroy','source_transform'):
        def watch(c):
            target=c.health_result.original_target_id
            if mode=='late_destroy':return(Destroy(target,c.source_id),)
            if mode=='source_transform':return(Transform(c.health_result.source_id,'CORE_CS2_182'),)
            return(RequestChoice(1,(ChoiceOption('go','Continue'),ChoiceOption('remove','Remove original target',
                (Destroy(target,c.source_id),)),ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,1),))),c.source_id),)
        r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
            metadata=META,limited_triggers=(LimitedTriggerSpec('health_resolved',WATCH),)))
    original=r.behavior(r.card(RUST).battlecry)
    def audited(c):
        if c.health_result is not None:
            if c.battlecry is None or c.target_id!=c.battlecry.target_id:
                raise ResolutionError('Selected health suffix lost its original Battlecry or target')
            if mode=='suffix_fail':raise ResolutionError('K447 actual selected suffix failure')
        return original(c)
    r._behaviors[r.card(RUST).battlecry]=audited
    domains={'armor_offer':(ARM,TROGG,CLEANER),'trogg_offer':(RUST,TROGG,CLEANER)}
    if mode in domains:r.register_pool(PoolDefinition(POOL_ID,'k447-three-complete-fragments',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in domains[mode]),complete=True))
    r.validate();return r


class AssembleNativeHealthTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',weapon=False,corpses=0):
        if mode in('wait','late_destroy','source_transform'):board=board+(WATCH,)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,deck=(COIN,)*16,
            mana=30,max_mana=30,mana_cap=40,corpses=corpses),PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*16,
                weapon_card_id='CS2_091'if weapon else None)),seed=6,generation_context=CTX),fixture(mode))
    def ids(self,g,cid,p=1,zone='board'):return[i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        source=self.ids(g,cid,zone='hand')[0];g.apply(PlayCard(1,source,target));return source
    def choose(self,g,key='go'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader');self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);self.assertEqual(g.snapshot(),saved)
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in('AssembleHealthContinuation','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',text)
        return other

    def test_a_seven_complete_rows_twelve_primary_faces_and_exact_original_self_programs(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual((len(rows),len(d['official_observations'])),(7,12))
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            new=asdict(r.card(recipe(cid)));new['id']=cid;self.assertEqual(new,asdict(r.card(cid)));self.assertEqual(recipe_options(r,cid,cid),())

    def test_b_raw_self_trogg_preserve_survivor_fatal_and_shield_results(self):
        for cid in(TROGG,recipe(TROGG)):
            for target,yes in((N,True),(TINY,False),(SHIELD,True)):
                g=self.game((cid,),enemy=(target,));source=self.play(g,cid,self.ids(g,target,2)[0])
                self.assertEqual(g.state.entities[source].max_health,14 if yes else 8)
                self.assertEqual(Keyword.TAUNT in g.state.entities[source].keywords,yes)

    def test_c_raw_self_armorer_preserve_actual_kill_reborn_and_shield_conditions(self):
        for cid in(ARM,recipe(ARM)):
            for target,yes in((N,False),(TINY,True),(REBORN,True),(SHIELD,False)):
                g=self.game((cid,),enemy=(target,));self.play(g,cid,self.ids(g,target,2)[0]);self.assertEqual(self.armor(g),5 if yes else 0)

    def test_d_native_minion_enemy_and_excluded_self_arrows_stay_with_prefix(self):
        for prefix in(TROGG,ARM):
            cid=recipe(prefix,RUST);g=self.game((cid,),board=(N,),enemy=(N,));saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid,g.state.players[2].hero_id)
            self.assertEqual(g.snapshot(),saved)
            if prefix==ARM:
                with self.assertRaises(IllegalAction):self.play(g,cid,self.ids(g,N)[0])
                self.assertEqual(g.snapshot(),saved)
            else:self.play(g,cid,self.ids(g,N)[0])

    def test_e_no_eligible_target_skips_original_damage_and_selected_reward(self):
        for prefix in(TROGG,ARM):
            cid=recipe(prefix,RUST);g=self.game((cid,),weapon=True);self.play(g,cid)
            self.assertIsNotNone(g.state.players[2].weapon_id);self.assertEqual(g.state.damage_history,[])

    def test_f_borrowed_survival_prefix_only_runs_selected_weapon_body_after_actual_survival(self):
        cid=recipe(RUST,TROGG,'top')
        for target,yes in((N,True),(TINY,False),(SHIELD,True)):
            g=self.game((cid,),enemy=(target,),weapon=True);source=self.play(g,cid,self.ids(g,target,2)[0])
            self.assertEqual(g.state.players[2].weapon_id is None,yes)
            self.assertEqual(g.state.entities[source].max_health,g.registry.card(RUST).health)
            self.assertNotIn(Keyword.TAUNT,g.state.entities[source].keywords)
        self.portable(g)

    def test_g_replacing_survival_prefix_retains_only_free_health_taunt_reward(self):
        cid=recipe(RUST,TROGG);g=self.game((cid,),enemy=(N,),weapon=True);source=self.play(g,cid)
        self.assertIsNotNone(g.state.players[2].weapon_id);self.assertEqual(g.state.entities[self.ids(g,N,2)[0]].health,20)
        self.assertEqual(g.state.entities[source].max_health,g.registry.card(RUST).health+6);self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)

    def test_h_replacing_kill_prefix_retains_only_free_armor_reward(self):
        cid=recipe(ARM,RUST,'top');g=self.game((cid,),enemy=(N,),weapon=True);self.play(g,cid)
        self.assertEqual(self.armor(g),5);self.assertEqual(g.state.damage_history,[]);self.assertIsNotNone(g.state.players[2].weapon_id)

    def test_i_original_packet_kill_reborn_unlocks_selected_body_without_original_armor(self):
        cid=recipe(ARM,RUST)
        for target,yes in((N,False),(TINY,True),(REBORN,True),(SHIELD,False)):
            g=self.game((cid,),enemy=(target,),weapon=True);self.play(g,cid,self.ids(g,target,2)[0])
            self.assertEqual(g.state.players[2].weapon_id is None,yes);self.assertEqual(self.armor(g),0)
        self.portable(g)

    def test_j_unrelated_later_destroy_cannot_satisfy_original_kill(self):
        cid=recipe(ARM,RUST);g=self.game((cid,),enemy=(N,),mode='late_destroy',weapon=True);target=self.ids(g,N,2)[0]
        self.play(g,cid,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertIsNotNone(g.state.players[2].weapon_id)
        self.portable(g,'late_destroy')

    def test_k_native_redirect_kill_is_not_original_target_kill_but_original_survival_still_counts(self):
        for prefix,yes in((ARM,False),(TROGG,True)):
            cid=recipe(prefix,RUST);g=self.game((cid,),enemy=(TINY,REDIRECT),weapon=True);target=self.ids(g,TINY,2)[0]
            self.play(g,cid,target);self.assertEqual(g.state.entities[target].health,2)
            self.assertEqual(g.state.players[2].weapon_id is None,yes)
        self.portable(g)

    def test_l_native_target_is_preserved_for_character_suffix_after_survival_gate(self):
        cid=recipe(TROGG,PHOENIX);g=self.game((cid,),enemy=(N,));target=self.ids(g,N,2)[0];self.play(g,cid,target)
        self.assertEqual(g.state.entities[target].health,11);self.assertEqual([dict(x.result)['base_amount']for x in g.state.damage_history],[6,3]);self.portable(g)

    def test_m_selected_suffix_receives_original_battlecry_for_real_corpse_summon(self):
        cid=recipe(TROGG,NECRO);g=self.game((cid,),enemy=(N,),corpses=1);self.play(g,cid,self.ids(g,N,2)[0])
        self.assertEqual(len(self.ids(g,FOOT)),1);self.assertEqual(len(g.state.corpse_spend_history),1);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_n_health_wait_preserves_native_accepted_survival_even_if_target_removed(self):
        cid=recipe(TROGG,RUST);g=self.game((cid,),enemy=(N,),mode='wait',weapon=True);target=self.ids(g,N,2)[0];self.play(g,cid,target)
        other=self.portable(g,'wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.choose(current,'remove')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.players[2].weapon_id)

    def test_o_health_wait_resumes_native_deferred_kill_gate_once_after_reborn(self):
        cid=recipe(ARM,RUST);g=self.game((cid,),enemy=(REBORN,),mode='wait',weapon=True);self.play(g,cid,self.ids(g,REBORN,2)[0])
        other=self.portable(g,'wait')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(self.armor(g),0)

    def test_p_late_selected_body_failure_rolls_back_damage_deaths_and_payments(self):
        cid=recipe(ARM,RUST);g=self.game((cid,),enemy=(TINY,),mode='suffix_fail',weapon=True);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid,self.ids(g,TINY,2)[0])
        self.assertEqual(g.snapshot(),saved)

    def test_q_rehashed_material_cannot_swap_root_player_body_or_callback_stage(self):
        cid=recipe(TROGG,RUST);g=self.game((cid,),enemy=(N,),mode='wait');self.play(g,cid,self.ids(g,N,2)[0]);saved=g.snapshot()
        self.assertTrue(list(nodes(saved,'ResolveAssembledHealthResult')))
        for change in('body','player','root','stage'):
            bad=deepcopy(saved);gate=next(nodes(bad,'ResolveAssembledHealthResult'))['fields'];m=gate['continuation']['fields']
            if change=='body':m['behavior_id']=cards.PREFIX+'kill_reward'
            elif change=='player':m['accepted']['fields']['player_id']=2
            elif change=='root':m['accepted']['fields']['battlecry']['fields']['id']=999
            else:gate['stage']=1
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('wait','reader'))

    def test_r_true_low_cost_offer_carries_kill_prefix_and_independent_health_taunt_reward(self):
        cid=recipe(ARM,TROGG);g=self.game((MISMATCH,),enemy=(TINY,),mode='armor_offer');self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.portable(g,'armor_offer')
        self.choose(g,next(o.id for o in q.options if o.card_id==cid));source=self.play(g,cid,self.ids(g,TINY,2)[0])
        self.assertEqual(g.state.entities[source].max_health,g.registry.card(ARM).health+6)
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.assertEqual(self.armor(g),0);self.portable(g,'armor_offer')

    def test_s_true_low_cost_primary_can_borrow_high_cost_survival_prefix_and_keep_native_target(self):
        cid=recipe(RUST,TROGG,'top');g=self.game((MISMATCH,),enemy=(N,),mode='trogg_offer',weapon=True);self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        source=self.play(g,cid,self.ids(g,N,2)[0]);self.assertIsNone(g.state.players[2].weapon_id)
        self.assertEqual(g.state.entities[source].max_health,g.registry.card(RUST).health);self.portable(g,'trogg_offer')

    def test_t_original_profiles_are_readonly_unique_frozen_and_complete_definition_pins_strict(self):
        r=fixture.__wrapped__();source=r.assemble_health_prefix_sources[TROGG]
        with self.assertRaises(TypeError):r.assemble_health_prefix_sources[TROGG]=source
        with self.assertRaises(ValueError):r.register_assemble_health_prefix_source(source)
        r.freeze()
        with self.assertRaises(ValueError):r.register_assemble_health_prefix_source(source)
        r=fixture.__wrapped__();r._cards[TROGG]=replace(r.card(TROGG),attack=99)
        with self.assertRaises(TargetValidationError):cards.register_assemble_native_health_prefixes(r)


if __name__=='__main__':unittest.main()
