"""Original physical programs and a fresh suffix rooted in accepted Deathrattle facts."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_native_programs as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_assemble_entry_cards import CARETAKER, POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, Zone)
from hs_sim.engine.assemble_death_programs import AssembleDeathContinuation
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, InvokeBehavior,
    RequestChoice, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec, Resource
from hs_sim.engine.pools import PoolDefinition, PoolMember, GenerationContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha

OHN, BEAST=cards.SOURCES
ELF,DOC,ELEMENT,PRIMORDIAL,AMBER,RUST,CLEANER,NECRO,FOOTMAN=cards.DEPENDENCIES
ROCK,COIN='BE_731','GAME_005'
P='k445.'
N,ARMOR,WAIT_SPELL,KILL,TRIGGER,TWICE,MUTE,WATCH,FAIL=(P+x for x in (
    'n','armor','wait_spell','kill','trigger','twice','mute','watch','fail'))
UNKNOWN=P+'unknown'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
CTX=GenerationContext('k445-complete-explicit-native-program-domains','experimental')


def recipe(primary,secondary=None,half='bottom'):
    return AssembleRecipe(primary,secondary or primary,half).card_id


def nodes(value,name):
    if isinstance(value,dict):
        if str(value.get('type','')).endswith('.'+name):yield value
        for child in value.values():yield from nodes(child,name)
    elif isinstance(value,list):
        for child in value:yield from nodes(child,name)


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
        if k not in('schema_version','events','events_hash','state_hash')})
    return saved


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=build_registry();r._version+='.k445.'+mode
    r.register_card(CardDefinition(N,N,CardType.MINION,attack=1,health=20,metadata=META))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K445 deliberate suffix failure')))
    r.register_behavior(ARMOR,lambda c:(GainArmor(c.player_id,2),))
    def choice(c):
        return (RequestChoice(c.player_id,(ChoiceOption('go','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WAIT_SPELL,choice)
    for cid in (ARMOR,WAIT_SPELL):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        TWICE:lambda c:(TriggerDeathrattles(c.target_id,c.source_id,2),),
        MUTE:lambda c:(Silence(c.target_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,
            on_play=cid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=META))
    if mode in ('wait','transform'):
        r.register_trigger_condition(P+'first_elf',lambda c:c.event.player_id==1 and c.state.entities[c.event.target_id].card_id==ELF)
        def watch(c):
            if mode=='transform':
                root=next(i for i in c.state.players[1].board if c.state.entities[i].card_id.startswith('assemble:'))
                return (Transform(root,N),)
            return choice(c)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            limited_triggers=(LimitedTriggerSpec('minion_summoned',WATCH,condition_id=P+'first_elf'),)))
    original=r.behavior(r.card(RUST).battlecry)
    def audited_rust(c):
        if c.deathrattle_followup is not None:
            material=c.deathrattle_followup
            if c.deathrattle!=material.accepted.deathrattle or c.source!=material.accepted.source:
                raise ResolutionError('Suffix lost its original root or execution-source view')
            if mode=='audit':
                old=sum(material.accepted.state.entities[i].card_id==ELF for i in material.accepted.state.players[1].board)
                now=sum(c.state.entities[i].card_id==ELF for i in c.state.players[1].board)
                if old!=0 or now!=2:raise ResolutionError('Suffix did not query the post-prefix execution view')
            if mode=='suffix_fail':raise ResolutionError('K445 late actual suffix failure')
        return original(c)
    r._behaviors[r.card(RUST).battlecry]=audited_rust
    members=()if mode=='empty'else(UNKNOWN,)if mode=='unknown'else(ELF,)
    if mode=='unknown':r.register_pool_card(replace(r.pool_cards[ELF],card_id=UNKNOWN))
    r.register_pool(PoolDefinition('constructed.minions','k445-exact-one-cost-domain',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    domains={'mismatch':(NECRO,BEAST,CLEANER),'ohn_offer':(OHN,PRIMORDIAL,AMBER)}
    if mode in domains:r.register_pool(PoolDefinition(POOL_ID,'k445-complete-three-fragments',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in domains[mode]),complete=True))
    r.validate();return r


class AssembleNativeProgramTests(unittest.TestCase):
    def game(self,hand=(),board=(),deck=(COIN,)*16,mode='normal',weapon=False):
        if mode in('wait','transform'):board=board+(WATCH,)
        hero='HERO_02'if mode=='ohn_offer'else'HERO_11'
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=deck,
            mana=20,max_mana=20,mana_cap=40),PlayerSetup('HERO_08',deck=(COIN,)*16,
                weapon_card_id='CS2_091'if weapon else None)),seed=5,generation_context=CTX),fixture(mode))

    def ids(self,g,cid,zone='board',p=1):
        return [i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]

    def play(self,g,cid,target=None,position=None):
        eid=self.ids(g,cid,'hand')[0];g.apply(PlayCard(1,eid,target,position));return eid

    def choose(self,g,key='go'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def corpse(self,g):return g.state.players[1].resources.get(Resource.CORPSES,0)

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader');self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        self.assertEqual(g.snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in('deathrattle_followup','AssembleDeathContinuation','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a_eleven_complete_rows_twenty_faces_and_exact_original_self_subjects(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual((len(rows),len(d['official_observations'])),(11,20))
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            old=asdict(r.card(cid));new=asdict(r.card(recipe(cid)));new['id']=cid
            self.assertEqual(old,new);self.assertEqual(recipe_options(r,cid,cid),())

    def test_b_raw_and_self_ohnahra_play_exact_three_original_cards_without_minion_battlecry(self):
        for cid in(OHN,recipe(OHN)):
            g=self.game(board=(cid,),deck=(ELF,ARMOR,ELF));original=list(g.state.players[1].deck)
            g.apply(EndTurn(1));self.assertEqual(self.ids(g,ELF),[original[0],original[2]])
            self.assertEqual(g.state.players[1].deck,[]);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_c_top_deck_suffix_borrowed_by_taunt_battlecry_has_no_old_end_listener(self):
        cid=recipe(OHN,PRIMORDIAL,'top');g=self.game((cid,),deck=(ELF,ARMOR,ELF));source=self.play(g,cid)
        self.assertEqual(len(self.ids(g,ELF)),2);self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)
        self.assertEqual(g.registry.card(cid).triggers,());self.assertEqual(g.state.players[1].mana,11);self.portable(g)

    def test_d_replaced_ohnahra_suffix_keeps_owner_end_but_does_not_play_old_top_program(self):
        cid=recipe(OHN,RUST);g=self.game((cid,),deck=(ELF,ARMOR,ELF),weapon=True);self.play(g,cid)
        g.apply(EndTurn(1));self.assertIsNone(g.state.players[2].weapon_id)
        self.assertEqual(len(g.state.players[1].deck),3);self.assertEqual(self.ids(g,ELF),[])

    def test_e_raw_and_self_beast_summon_two_then_buff_new_and_old_current_minions(self):
        for cid in(BEAST,recipe(BEAST)):
            g=self.game((KILL,),(cid,N));self.play(g,KILL,self.ids(g,cid)[0])
            self.assertEqual(len(self.ids(g,ELF)),2)
            self.assertEqual([g.state.entities[i].attack for i in self.ids(g,ELF)],[4,4])
            self.assertEqual(g.state.entities[self.ids(g,N)[0]].attack,4)

    def test_f_borrowed_battlecry_runs_only_current_buff_without_old_summons_or_death(self):
        cid=recipe(BEAST,RUST,'top');g=self.game((cid,),(N,));source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].attack,g.registry.card(BEAST).attack+3)
        self.assertEqual(g.state.entities[self.ids(g,N)[0]].attack,4)
        self.assertEqual(g.state.card_summon_history,[]);self.assertIsNone(g.registry.card(cid).deathrattle)

    def test_g_deferred_selected_body_sees_both_actual_summons_and_retains_original_root(self):
        cid=recipe(BEAST,RUST);g=self.game((KILL,),(cid,),mode='audit',weapon=True);self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual([g.state.entities[i].attack for i in self.ids(g,ELF)],[1,1])
        self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(len(g.state.deathrattle_history),1);self.portable(g,'audit')

    def test_h_empty_prefix_pool_still_runs_real_deathrattle_resource_suffix_without_rng(self):
        cid=recipe(NECRO,BEAST,'top');g=self.game((KILL,),(cid,),mode='empty');rng=g._rng.getstate()
        self.play(g,KILL,self.ids(g,cid)[0]);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(self.ids(g,FOOTMAN)),1);self.assertEqual(self.corpse(g),0)

    def test_i_suffix_resource_capacity_uses_new_scene_after_prefix_fills_last_space(self):
        cid=recipe(NECRO,BEAST,'top');g=self.game((KILL,),(cid,)+(N,)*6);self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual((len(g.state.players[1].board),len(self.ids(g,ELF)),len(self.ids(g,FOOTMAN))),(7,1,0))
        self.assertEqual(self.corpse(g),1)

    def test_j_normal_real_death_suffix_pays_once_after_both_prefix_deliveries(self):
        cid=recipe(NECRO,BEAST,'top');g=self.game((KILL,),(cid,));self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual((len(self.ids(g,ELF)),len(self.ids(g,FOOTMAN)),self.corpse(g)),(2,1,0))
        self.assertEqual(g.registry.card(cid).triggers,());self.assertEqual(len(g.state.deathrattle_history),1);self.portable(g)

    def test_k_first_summon_wait_restores_remaining_prefix_then_original_context_and_payment(self):
        cid=recipe(NECRO,BEAST,'top');g=self.game((KILL,),(cid,),mode='wait');self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual((len(self.ids(g,ELF)),len(self.ids(g,FOOTMAN)),self.corpse(g)),(1,0,1))
        reader=self.portable(g,'wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(reader);self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual((len(self.ids(g,ELF)),len(self.ids(g,FOOTMAN)),self.corpse(g)),(2,1,0))

    def test_l_late_selected_suffix_failure_rolls_back_death_corpses_rng_and_new_bodies(self):
        cid=recipe(BEAST,RUST);g=self.game((KILL,),(cid,),mode='suffix_fail',weapon=True);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual(g.snapshot(),saved)

    def test_m_rehashed_followup_cannot_change_selected_body_root_player_or_acceptance_kind(self):
        cid=recipe(NECRO,BEAST,'top');g=self.game((KILL,),(cid,),mode='wait');self.play(g,KILL,self.ids(g,cid)[0]);saved=g.snapshot()
        self.assertTrue(list(nodes(saved,'AssembleDeathContinuation')))
        for change in('body','prefix','player','recursive'):
            bad=deepcopy(saved);m=next(nodes(bad,'AssembleDeathContinuation'))['fields']
            if change=='body':m['behavior_id']=g.registry.card(RUST).battlecry
            elif change=='prefix':m['before_behavior_id']='k445.fabricated_prefix'
            elif change=='player':m['accepted']['fields']['player_id']=2
            else:m['accepted']['fields']['deathrattle_followup']={'invalid':True}
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('wait','reader'))

    def test_n_unknown_eligible_candidate_is_not_pruned_even_with_full_board(self):
        cid=recipe(BEAST,RUST);g=self.game((TRIGGER,),(cid,)+(N,)*6,mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,TRIGGER,self.ids(g,cid)[0])
        self.assertEqual(g.snapshot(),saved)

    def test_o_copied_program_uses_original_declaration_on_another_actual_carrier(self):
        cid=recipe(BEAST,RUST);g=self.game((ROCK,KILL),(cid,),weapon=True);carrier=self.play(g,ROCK,position=1)
        acquired=[a for a in g.state.entities[carrier].abilities if a.kind=='deathrattle']
        self.assertEqual(len(acquired),1);self.assertEqual(acquired[0].deathrattle_card_id,cid)
        self.play(g,KILL,carrier);self.assertEqual(len(self.ids(g,ELF)),2);self.assertIsNone(g.state.players[2].weapon_id);self.portable(g)

    def test_p_two_active_rounds_keep_original_declaration_after_first_prefix_transforms_carrier(self):
        cid=recipe(BEAST,RUST);g=self.game((TWICE,),(cid,),mode='transform',weapon=True);source=self.ids(g,cid)[0]
        self.play(g,TWICE,source);self.assertEqual(g.state.entities[source].card_id,N)
        self.assertEqual(len(self.ids(g,ELF)),4);self.assertEqual(len(g.state.deathrattle_history),2)
        self.assertTrue(all(row.completed for row in g.state.deathrattle_history))
        self.assertFalse(any(row.entity_id==source for row in g.state.death_history))
        self.portable(g,'transform')

    def test_q_true_low_cost_offer_carries_deferred_prefix_and_native_necromancer_suffix(self):
        cid=recipe(NECRO,BEAST,'top');g=self.game((MISMATCH,KILL),mode='mismatch');self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.portable(g,'mismatch')
        self.choose(g,next(o.id for o in q.options if o.card_id==cid));source=self.play(g,cid);self.play(g,KILL,source)
        self.assertEqual((len(self.ids(g,ELF)),len(self.ids(g,FOOTMAN)),self.corpse(g)),(2,1,0));self.portable(g,'mismatch')

    def test_r_true_beast_offer_borrows_battlecry_for_three_free_original_top_cards(self):
        cid=recipe(OHN,PRIMORDIAL,'top');g=self.game((CARETAKER,),deck=(ELF,ARMOR,ELF),mode='ohn_offer');self.play(g,CARETAKER)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        self.play(g,cid);self.assertEqual((len(self.ids(g,ELF)),len(g.state.players[1].deck)),(2,0))
        self.assertEqual(g.state.players[1].mana,9);self.portable(g,'ohn_offer')

    def test_s_top_program_wait_resumes_remaining_physical_cards_without_duplicate_play(self):
        cid=recipe(OHN,PRIMORDIAL,'top');g=self.game((cid,),deck=(ELF,ARMOR,ELF),mode='wait');self.play(g,cid)
        self.assertEqual(len(g.state.players[1].deck),2);reader=self.portable(g,'wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(reader);self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual((len(self.ids(g,ELF)),len(g.state.players[1].deck)),(2,0))

    def test_t_deferred_source_is_unique_readonly_frozen_and_original_pins_remain_strict(self):
        r=fixture.__wrapped__();p=r.assemble_deferred_death_sources[BEAST]
        with self.assertRaises(TypeError):r.assemble_deferred_death_sources[BEAST]=p
        with self.assertRaises(ValueError):r.register_assemble_deferred_death_source(p)
        with self.assertRaises(ValueError):r.register_assemble_deferred_death_source(replace(p,card_id=OHN))
        r.freeze()
        with self.assertRaises(ValueError):r.register_assemble_deferred_death_source(p)
        r=fixture.__wrapped__();r._cards[BEAST]=replace(r.card(BEAST),attack=99)
        with self.assertRaises(TargetValidationError):cards.register_assemble_native_programs(r)
