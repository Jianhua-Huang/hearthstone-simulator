"""Real mana debit pairs and native limited budgets on assembled faces."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_native_resource_reactions as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_assemble_entry_cards import NURTURER, POOL_ID
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.assemble_reactions import AssembleNativeReactionSource, AssembleReactionSource
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, DamageBatch,
    GainArmor, GrantKeyword, Heal, InvokeBehavior, RequestChoice, Silence, SpendMana)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, Event, Keyword
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha

CUB, RAIN = cards.SOURCES
MISMATCH = 'BE_045'
RUST, MAZE = cards.DONORS[:2]
ANN, FIRE, CURATOR, CLEANER = 'CORE_GVG_085', 'CORE_CS2_029', 'CORE_KAR_061', 'CORE_REV_946'
DECK_MINIONS = (CUB, 'CATA_464', 'TLC_427')
COIN = 'GAME_005'
P = 'k442.'
ONE, TWO, ZERO, EXHAUST, EXHAUST_ZERO, HIT, HEAL, EFFECT, SHIELD, BATCH, COPY, BASE_COPY, MUTE, N, WEAPON, WATCH, FAIL, OPP_TURN = (
    P+k for k in ('one','two','zero','exhaust','exhaust_zero','hit','heal','effect','shield',
        'batch','copy','base_copy','mute','n','weapon','watch','fail','opponent_turn'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
CTX = GenerationContext('k442-reviewed-native-resource-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version += '.k442.'+mode
    r.register_card(CardDefinition(N,N,CardType.MINION,health=20,metadata=META))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=1,durability=2,metadata=META))
    def fail(c): raise ResolutionError('K442 deliberate reaction continuation failure')
    r.register_behavior(FAIL,fail)
    def watch(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.target_id].card_id!=ANN:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('go','Continue'),
            ChoiceOption('bad','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('minion_summoned',WATCH),)))
    r.register_behavior(OPP_TURN,lambda c:(CastSpell(1,FIRE,c.source_id,
        c.state.players[2].hero_id,targeting='explicit'),) if c.event.player_id==2 else ())
    r.register_card(CardDefinition(OPP_TURN,OPP_TURN,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('turn_started',OPP_TURN),)))
    bodies={ONE:(1,lambda c:()),TWO:(2,lambda c:()),ZERO:(0,lambda c:()),
        EXHAUST:(0,lambda c:(SpendMana(c.player_id,None,c.source_id),)),
        EXHAUST_ZERO:(0,lambda c:(SpendMana(c.player_id,0,c.source_id),)),
        HIT:(0,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)),
        HEAL:(0,lambda c:(Heal(c.target_id,1,c.source_id),)),
        EFFECT:(0,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),)),
        SHIELD:(0,lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),)),
        BATCH:(0,lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)
            for i in (c.state.players[2].hero_id,*c.state.players[2].board))),)),
        COPY:(0,lambda c:(CopyMinion(c.target_id,c.player_id,mode='current'),)),
        BASE_COPY:(0,lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),)),
        MUTE:(0,lambda c:(Silence(c.target_id),))}
    for cid,(cost,body) in bodies.items():
        target=TargetSpec() if cid in (HIT,HEAL,EFFECT,SHIELD) else (
            TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if cid in (COPY,BASE_COPY,MUTE) else None)
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,targeting=target,metadata=META))
    if mode!='no_pool':
        r.register_pool(PoolDefinition('constructed.cards','k442-complete-one-two-cost-neutral',
            CTX.target_id,CTX.mode,(PoolMember(ANN),),complete=True))
    domains={'cub_offer':(CUB,RUST,MAZE),'rain_offer':(RAIN,CURATOR,CLEANER)}
    if mode in domains:
        r.register_pool(PoolDefinition(POOL_ID,'k442-complete-three-review-members',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid) for cid in domains[mode]),complete=True))
    r.validate(); return r


class AssembleNativeResourceTests(unittest.TestCase):
    def game(self,hand=(),board=(),mana=10,mode='normal',enemy=(),enemy_hand=(),weapon=False):
        hero='HERO_08' if mode=='rain_offer' else 'HERO_06'
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,
            deck=DECK_MINIONS+(COIN,)*24,mana=mana,max_mana=mana,mana_cap=50),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(COIN,)*24,
                weapon_card_id=WEAPON if weapon else None,mana=2,max_mana=2,mana_cap=50)),
            seed=1,generation_context=CTX),fixture(mode))

    def ids(self,g,cid,zone='board',p=1):
        return [i for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id==cid]

    def play(self,g,cid,target=None,p=1):
        source=self.ids(g,cid,'hand',p)[0];g.apply(PlayCard(p,source,target));return source

    def pick(self,g,key='go'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def end(self,g):g.apply(EndTurn(g.state.active_player))

    def budget(self,g,source):
        return next(a for a in g.state.entities[source].abilities if a.kind=='limited_trigger')

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader')
        self.assertIsNot(reader,g.registry);other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);self.assertEqual(g.snapshot(),saved)
        for player in (1,2):
            public=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('rng_state','resolution_frame','next_attachment_id','primary_candidates'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a_six_complete_rows_twelve_faces_and_exact_native_self_subjects(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows),6);self.assertEqual(len(d['official_observations']),12)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for cid in cards.SOURCES:
            original=asdict(r.card(cid));new=asdict(r.card(recipe(cid)));new['id']=cid
            self.assertEqual(new,original);self.assertEqual(recipe_options(r,cid,cid),())
        self.assertEqual(r.assemble_reaction_sources[CUB].events,('mana_spent','mana_consumed'))

    def test_b_raw_and_self_cub_keep_both_real_positive_debit_paths(self):
        for cid in (CUB,recipe(CUB)):
            for debit in (ONE,EXHAUST):
                g=self.game((debit,),(cid,),mana=1);source=self.ids(g,cid)[0];self.play(g,debit)
                self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,2))
                self.assertEqual(g.state.players[1].mana,0)

    def test_c_borrowed_weapon_body_uses_both_actual_event_kinds_without_old_growth(self):
        cid=recipe(CUB,RUST)
        for debit in (ONE,EXHAUST):
            g=self.game((debit,),(cid,),mana=1,weapon=True);source=self.ids(g,cid)[0];self.play(g,debit)
            self.assertIsNone(g.state.players[2].weapon_id)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(1,1))
            self.assertEqual(tuple(t.event for t in g.registry.card(cid).triggers),('mana_spent','mana_consumed'))

    def test_d_zero_remaining_mana_is_not_a_debit_and_opponent_consumption_is_not_yours(self):
        cid=recipe(CUB,RUST)
        for zero in (ZERO,EXHAUST_ZERO):
            g=self.game((zero,),(cid,),mana=0,weapon=True);self.play(g,zero)
            self.assertIsNotNone(g.state.players[2].weapon_id)
        g=self.game(board=(cid,),enemy_hand=(EXHAUST,),weapon=True);self.end(g)
        self.play(g,EXHAUST,p=2);self.assertIsNotNone(g.state.players[2].weapon_id)

    def test_e_borrowed_battlecry_keeps_self_growth_body_and_removes_old_mana_listeners(self):
        cid=recipe(CUB,RUST,'top');g=self.game((cid,),mana=2);source=self.play(g,cid)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,2))
        self.assertEqual(g.registry.card(cid).triggers,());self.assertEqual(g.registry.card(cid).limited_triggers,())

    def test_f_raw_and_self_rain_keep_native_paid_spell_and_once_per_turn_budget(self):
        for cid in (RAIN,recipe(RAIN)):
            g=self.game((FIRE,FIRE),(cid,));source=self.ids(g,cid)[0]
            for _ in range(2):self.play(g,FIRE,g.state.players[2].hero_id)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,4))
            self.assertEqual(self.budget(g,source).uses_remaining,0);self.assertEqual(g.state.players[1].mana,2)

    def test_g_limited_prefix_borrows_summon_and_never_adds_original_attack_reward(self):
        cid=recipe(RAIN,MAZE);g=self.game((HIT,HIT),(cid,));source=self.ids(g,cid)[0]
        for _ in range(2):self.play(g,HIT,g.state.players[2].hero_id)
        self.assertEqual(len(self.ids(g,ANN)),1);self.assertEqual(g.state.entities[source].attack,1)
        self.assertEqual(self.budget(g,source).uses_remaining,0);self.assertEqual(g.registry.card(cid).triggers,())

    def test_h_replacing_limited_prefix_clears_original_budget_and_uses_plain_battlecry(self):
        cid=recipe(RAIN,RUST,'top');g=self.game((cid,HIT));source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].attack,3);self.assertEqual(g.registry.card(cid).limited_triggers,())
        self.play(g,HIT,g.state.players[2].hero_id);self.assertEqual(g.state.entities[source].attack,3)

    def test_i_prevented_zero_healing_and_nonspell_packets_do_not_consume_new_prefix(self):
        cid=recipe(RAIN,MAZE);g=self.game((EFFECT,HEAL,SHIELD,HIT,HIT),(cid,));source=self.ids(g,cid)[0];hero=g.state.players[2].hero_id
        self.play(g,EFFECT,hero);self.play(g,HEAL,hero);self.play(g,SHIELD,hero);self.play(g,HIT,hero)
        self.assertEqual(self.budget(g,source).uses_remaining,1);self.assertEqual(self.ids(g,ANN),[])
        self.play(g,HIT,hero);self.assertEqual(len(self.ids(g,ANN)),1)

    def test_j_multiple_spell_damage_results_in_one_batch_consume_one_original_budget(self):
        cid=recipe(RAIN,MAZE);g=self.game((BATCH,),(cid,),enemy=(N,N));source=self.ids(g,cid)[0]
        self.play(g,BATCH);self.assertEqual((len(self.ids(g,ANN)),self.budget(g,source).uses_remaining),(1,0))

    def test_k_next_global_opponent_turn_resets_and_owner_automatic_spell_uses_new_budget(self):
        cid=recipe(RAIN,MAZE);g=self.game((HIT,),(cid,OPP_TURN));source=self.ids(g,cid)[0]
        self.play(g,HIT,g.state.players[2].hero_id);self.assertEqual(len(self.ids(g,ANN)),1)
        self.end(g);self.assertEqual(g.state.active_player,2)
        self.assertEqual((len(self.ids(g,ANN)),self.budget(g,source).uses_remaining),(2,0))

    def test_l_limited_wait_preserves_consumed_budget_before_delivery_and_failed_resume(self):
        cid=recipe(RAIN,MAZE);g=self.game((HIT,),(cid,WATCH));source=self.ids(g,cid)[0]
        self.play(g,HIT,g.state.players[2].hero_id);self.assertEqual(self.budget(g,source).uses_remaining,0)
        reader=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.pick(g);self.pick(reader);self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual((len(self.ids(g,ANN)),self.budget(g,source).uses_remaining),(1,0));self.portable(g)

    def test_m_multi_event_wait_restores_same_selected_summon_and_rng(self):
        cid=recipe(CUB,MAZE);g=self.game((EXHAUST,),(cid,WATCH),mana=2);self.play(g,EXHAUST)
        reader=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.pick(g);self.pick(reader);self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual(g.snapshot()['rng_state'],saved['rng_state']);self.assertEqual(len(self.ids(g,ANN)),1)

    def test_n_current_copy_keeps_spent_budget_and_base_copy_restores_printed_budget(self):
        cid=recipe(RAIN,MAZE);g=self.game((HIT,HIT,HIT,COPY,BASE_COPY),(cid,));source=self.ids(g,cid)[0];hero=g.state.players[2].hero_id
        self.play(g,HIT,hero);self.play(g,COPY,source);current=next(i for i in self.ids(g,cid) if i!=source)
        self.assertEqual(self.budget(g,current).uses_remaining,0);self.play(g,HIT,hero);self.assertEqual(len(self.ids(g,ANN)),1)
        self.play(g,BASE_COPY,source);base=next(i for i in self.ids(g,cid) if i not in (source,current))
        self.assertEqual(self.budget(g,base).uses_remaining,1);self.play(g,HIT,hero);self.assertEqual(len(self.ids(g,ANN)),2)

    def test_o_silence_removes_new_limited_listener_without_turn_reinstallation(self):
        cid=recipe(RAIN,MAZE);g=self.game((MUTE,HIT),(cid,));source=self.ids(g,cid)[0]
        self.play(g,MUTE,source);self.end(g);self.end(g);self.play(g,HIT,g.state.players[2].hero_id)
        self.assertEqual(self.ids(g,ANN),[]);self.assertEqual([a for a in g.state.entities[source].abilities if a.kind=='limited_trigger'],[])

    def test_p_real_nurturer_offer_uses_one_cost_cube_then_actual_last_mana_summon(self):
        cid=recipe(CUB,MAZE);g=self.game((NURTURER,TWO),mana=6,mode='cub_offer');self.play(g,NURTURER)
        self.portable(g,'cub_offer');q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options])
        self.pick(g,next(o.id for o in q.options if o.card_id==cid));source=self.play(g,cid)
        self.assertEqual(self.ids(g,ANN),[]);self.play(g,TWO)
        self.assertEqual((g.state.players[1].mana,len(self.ids(g,ANN)),g.state.entities[source].attack),(0,1,1));self.portable(g,'cub_offer')

    def test_q_real_mismatch_keeps_two_cost_rain_prefix_and_curator_draw_body_once(self):
        cid=recipe(RAIN,CURATOR);g=self.game((MISMATCH,HIT,HIT),mana=10,mode='rain_offer');self.play(g,MISMATCH)
        self.portable(g,'rain_offer');q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options])
        self.pick(g,next(o.id for o in q.options if o.card_id==cid));source=self.play(g,cid)
        self.assertEqual(g.state.players[1].mana,3);self.play(g,HIT,g.state.players[2].hero_id)
        for card in DECK_MINIONS:self.assertEqual(len(self.ids(g,card,'hand')),1)
        self.play(g,HIT,g.state.players[2].hero_id);self.assertEqual(self.budget(g,source).uses_remaining,0)
        self.assertEqual(g.state.entities[source].attack,1);self.portable(g,'rain_offer')

    def test_r_native_profile_is_complete_unique_readonly_and_does_not_mask_ordinary_source(self):
        r=fixture.__wrapped__();profile=r.assemble_reaction_sources[CUB]
        with self.assertRaises(TypeError):r.assemble_reaction_sources[CUB]=profile
        with self.assertRaises(ValueError):r.register_assemble_reaction_source(profile)
        with self.assertRaises(ValueError):r.register_assemble_reaction_source(replace(profile,events=('mana_spent',)))
        rain=r.assemble_reaction_sources[RAIN]
        with self.assertRaises(ValueError):r.register_assemble_reaction_source(replace(rain,limited=replace(rain.limited,uses=2)))
        with self.assertRaises(ValueError):r.register_assemble_reaction_source(AssembleReactionSource(RAIN,'health_resolved',rain.original_behavior_id,rain.condition_id))
        r.freeze()
        with self.assertRaises(ValueError):r.register_assemble_reaction_source(profile)

    def test_s_limited_wrapper_requires_real_consumed_attachment_and_complete_source_pins(self):
        cid=recipe(RAIN,MAZE);g=self.game(board=(cid,));source=self.ids(g,cid)[0]
        spec=g.registry.card(cid).limited_triggers[0]
        with self.assertRaises(ResolutionError):g.registry.behavior(spec.behavior_id)(RuleContext(g.state,source,1,event=Event(1,0,'health_resolved')))
        r=fixture.__wrapped__();r._cards[CUB]=replace(r.card(CUB),attack=2)
        with self.assertRaises(TargetValidationError):cards.register_assemble_native_resource_reactions(r)

    def test_t_unknown_mana_payload_scope_and_missing_secondary_event_never_silently_prune(self):
        with self.assertRaises(ValueError):fixture().card(recipe(CUB,'CORE_GIL_622'))
        r=fixture.__wrapped__();old=r._assemble_templates[RUST]
        r._assemble_templates[RUST]=replace(old,suffix=replace(old.suffix,allowed_timings=tuple(t for t in old.suffix.allowed_timings if t!='mana_consumed')))
        with self.assertRaises(ValueError):r.card(recipe(CUB,RUST))


if __name__=='__main__':unittest.main()
