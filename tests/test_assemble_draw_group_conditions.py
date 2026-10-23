"""Actual pair-of-draw qualifiers, independent suffixes and saved original facts."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_draw_group_conditions as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_assemble_entry_cards import NURTURER, POOL_ID
from hs_sim.cards.assemble_source_exception_cards import THAW
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CastWhenDrawnSpec,
    Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.assemble_draw_groups import AssembleDrawGroupSource
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChoiceOption, Destroy, Draw, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha

MAGE, HOG = cards.SOURCES
WATER, RUST, MAZE, PHOENIX = cards.DEPENDENCIES
ANN, CUB, COIN, MISMATCH = 'CORE_GVG_085', 'CATA_130', 'GAME_005', 'BE_045'
CURATOR, CLEANER = 'CORE_KAR_061', 'CORE_REV_946'
DRAW_TRIBES = (CUB, 'CATA_464', 'TLC_427')
P = 'k443.'
N, WEAPON, WATCH, FAIL, PORTAL, REENTER = (P+x for x in ('n','weapon','watch','fail','portal','reenter'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('k443-complete-reviewed-draw-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


def nodes(value, name):
    if isinstance(value, dict):
        if str(value.get('type', '')).endswith('.'+name): yield value
        for child in value.values(): yield from nodes(child, name)
    elif isinstance(value, list):
        for child in value: yield from nodes(child, name)


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version += '.k443.'+mode
    r.register_card(CardDefinition(N,N,CardType.MINION,attack=1,health=20,metadata=META))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=1,durability=2,metadata=META))
    def fail(c): raise ResolutionError('K443 deliberate original draw reward failure')
    r.register_behavior(FAIL,fail)
    r.register_behavior(PORTAL,lambda c:())
    r.register_card(CardDefinition(PORTAL,PORTAL,CardType.SPELL,metadata=META,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(),on_play=PORTAL))
    def reenter(c):
        e=next(c.state.entities[i] for i in c.state.players[1].hand
            if c.state.entities[i].card_id.startswith('assemble:'))
        return (SummonStoredCard(CardReference.capture(e),1),)
    r.register_behavior(REENTER,reenter)
    def watch(c):
        if c.event.player_id!=1:return ()
        if mode in ('body_wait','body_fail'):
            if c.state.entities[c.event.target_id].card_id!=ANN:return ()
            if mode=='body_fail':raise ResolutionError('K443 explicit actual summon failure')
        else:
            source=c.state.entities.get(c.event.source_id)
            if source is None or not source.card_id.startswith('assemble:'):return ()
        hero=c.state.entities[c.state.players[1].hero_id]
        if hero.armor:return ()
        marker=GainArmor(1,1)
        if mode=='extra':return marker,Draw(1,1,c.source_id)
        if mode=='kill':return marker,Destroy(c.event.source_id,c.source_id)
        if mode in ('bounce','reenter'):
            return (marker,ReturnToHand(c.event.source_id),*((InvokeBehavior(REENTER,c.source_id,1),)if mode=='reenter'else()))
        return marker,RequestChoice(1,(ChoiceOption('go','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,1),))),c.source_id)
    if mode in ('draw_wait','body_wait','body_fail','extra','kill','bounce','reenter'):
        event='minion_summoned' if mode.startswith('body_') else 'card_drawn'
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            triggers=(TriggerSpec(event,WATCH),)))
    r.register_pool(PoolDefinition('constructed.cards','k443-one-exact-native-summon',
        CTX.target_id,CTX.mode,(PoolMember(ANN),),complete=True))
    if mode in ('mage_offer','hog_offer'):
        r.register_pool(PoolDefinition(POOL_ID,'k443-exact-three-native-members',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid) for cid in ((MAGE,CURATOR,CLEANER)if mode=='mage_offer'else(RUST,HOG,CLEANER))),complete=True))
    r.validate();return r


class AssembleDrawGroupTests(unittest.TestCase):
    def game(self,hand=(),deck=(COIN,COIN),mode='normal',enemy=(),weapon=False):
        board=(WATCH,)if mode in ('draw_wait','body_wait','body_fail','extra','kill','bounce','reenter')else()
        hero='HERO_03'if mode=='hog_offer'else'HERO_08'
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=deck,
            mana=20,max_mana=20,mana_cap=40),PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,
                weapon_card_id=WEAPON if weapon else None)),seed=3,generation_context=CTX),fixture(mode))

    def ids(self,g,cid,zone='board',p=1):
        return [i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]

    def play(self,g,cid,target=None):
        source=self.ids(g,cid,'hand')[0];g.apply(PlayCard(1,source,target));return source

    def pick(self,g,key='go'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader');self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        self.assertEqual(g.snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','draw_group','arrivals','hand_cursor'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a_six_complete_rows_ten_faces_and_exact_original_self_battlecries(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows),6);self.assertEqual(len(d['official_observations']),10)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            original=asdict(r.card(cid));new=asdict(r.card(recipe(cid)));new['id']=cid
            self.assertEqual(original,new);self.assertEqual(recipe_options(r,cid,cid),())

    def test_b_raw_and_self_mage_keep_two_draws_and_each_original_non_minion_water(self):
        for cid in (MAGE,recipe(MAGE)):
            for deck,count in (((COIN,COIN),2),((COIN,N),1),((N,N),0)):
                g=self.game((cid,),deck);self.play(g,cid)
                self.assertEqual((len(g.state.draw_history),len(self.ids(g,WATER))),(2,count))

    def test_c_raw_and_self_hog_keep_whole_original_pair_charge_condition(self):
        for cid in (HOG,recipe(HOG)):
            for deck,charged in (((N,N),True),((COIN,N),False),((N,),False)):
                g=self.game((cid,),deck);source=self.play(g,cid)
                self.assertEqual(Keyword.CHARGE in g.state.entities[source].keywords,charged)
                self.assertEqual(len(g.state.draw_history),2)

    def test_d_mage_prefix_repeats_selected_growth_per_qualifying_root_without_waters(self):
        cid=recipe(MAGE,CUB);g=self.game((cid,),(COIN,COIN));source=self.play(g,cid)
        base=g.registry.card(MAGE);e=g.state.entities[source]
        self.assertEqual((e.attack,e.health),(base.attack+2,base.health+2));self.assertEqual(self.ids(g,WATER),[])

    def test_e_hog_prefix_summons_selected_water_once_only_when_both_originals_are_minions(self):
        cid=recipe(HOG,MAGE)
        for deck,count in (((N,N),1),((COIN,N),0),((N,),0)):
            g=self.game((cid,),deck);source=self.play(g,cid)
            self.assertEqual((len(self.ids(g,WATER)),Keyword.CHARGE in g.state.entities[source].keywords),(count,False))
            self.assertEqual(len(g.state.draw_history),2)

    def test_f_new_suffixes_under_plain_battlecry_do_not_keep_old_draw_or_qualifier(self):
        for cid,charged,waters in ((recipe(HOG,RUST,'top'),True,0),(recipe(MAGE,RUST,'top'),False,1)):
            g=self.game((cid,),deck=());source=self.play(g,cid)
            self.assertEqual((Keyword.CHARGE in g.state.entities[source].keywords,len(self.ids(g,WATER))),(charged,waters))
            self.assertEqual(g.state.draw_history,[])

    def test_g_mage_prefix_can_deliver_charge_suffix_without_native_water_reward(self):
        cid=recipe(MAGE,HOG);g=self.game((cid,),(COIN,N));source=self.play(g,cid)
        self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords);self.assertEqual(self.ids(g,WATER),[])

    def test_h_extra_reaction_draw_is_not_a_third_qualifying_original_slot(self):
        cid=recipe(MAGE,CUB);g=self.game((cid,),(COIN,COIN,N),mode='extra');source=self.play(g,cid)
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(g.state.entities[source].attack,g.registry.card(MAGE).attack+1)

    def test_i_draw_cast_replacement_does_not_reclassify_original_two_attempts(self):
        for cid,waters in ((recipe(MAGE,CUB),0),(recipe(HOG,MAGE),0)):
            g=self.game((cid,),(PORTAL,N,N));source=self.play(g,cid)
            self.assertEqual(len(g.state.draw_history),3);self.assertEqual(len(self.ids(g,WATER)),waters)
            self.assertEqual(g.state.entities[source].attack,g.registry.card(MAGE if cid==recipe(MAGE,CUB)else HOG).attack+(1 if cid==recipe(MAGE,CUB)else 0))

    def test_j_burned_originals_still_qualify_but_fatigue_has_no_card(self):
        cid=recipe(MAGE,CUB);g=self.game((cid,)+(COIN,)*9,(COIN,COIN));source=self.play(g,cid)
        self.assertEqual([row.outcome for row in g.state.draw_history],['hand','burned'])
        self.assertEqual(g.state.entities[source].attack,g.registry.card(MAGE).attack+2)
        g=self.game((cid,),());source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].attack,g.registry.card(MAGE).attack);self.assertEqual(len(g.state.draw_history),2)

    def test_k_two_original_draws_finish_before_any_selected_reward_and_restore_once(self):
        cid=recipe(MAGE,CUB);g=self.game((cid,),(COIN,COIN),mode='draw_wait');source=self.play(g,cid)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(g.state.entities[source].attack,g.registry.card(MAGE).attack)
        reader=self.portable(g,'draw_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.pick(g);self.pick(reader)
        self.assertEqual(g.snapshot(),reader.snapshot());self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(g.state.entities[source].attack,g.registry.card(MAGE).attack+2)

    def test_l_selected_target_is_retained_for_both_qualified_followups(self):
        cid=recipe(MAGE,PHOENIX);g=self.game((cid,),(COIN,COIN),enemy=(N,));target=self.ids(g,N,p=2)[0]
        self.play(g,cid,target);self.assertEqual(g.state.entities[target].health,14)
        self.assertEqual(self.ids(g,WATER),[]);self.portable(g)

    def test_m_dead_original_source_does_not_cancel_a_nonself_selected_body(self):
        cid=recipe(MAGE,RUST);g=self.game((cid,),(COIN,N),mode='kill',weapon=True);source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.players[2].weapon_id)
        self.assertEqual(len(g.state.draw_history),2)

    def test_n_charge_reward_cannot_attach_to_a_later_residence_of_same_physical_source(self):
        cid=recipe(MAGE,HOG);g=self.game((cid,),(COIN,COIN),mode='reenter');source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords)
        self.assertEqual(len(g.state.draw_history),2);self.portable(g,'reenter')

    def test_o_first_selected_body_wait_keeps_remaining_original_reward_and_draw_facts(self):
        cid=recipe(MAGE,MAZE);g=self.game((cid,),(COIN,COIN),mode='body_wait');self.play(g,cid)
        self.assertEqual((len(g.state.draw_history),len(self.ids(g,ANN))),(2,1));reader=self.portable(g,'body_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.pick(g);self.pick(reader);self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual((len(g.state.draw_history),len(self.ids(g,ANN))),(2,2));self.portable(g,'body_wait')

    def test_p_late_selected_body_failure_rolls_back_payment_draws_and_all_created_material(self):
        cid=recipe(MAGE,MAZE);g=self.game((cid,),(COIN,COIN),mode='body_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)

    def test_q_true_thaw_offer_uses_five_cost_mage_and_selected_curator_draw_body(self):
        cid=recipe(MAGE,CURATOR);g=self.game((THAW,),(COIN,COIN)+DRAW_TRIBES,mode='mage_offer');self.play(g,THAW)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.portable(g,'mage_offer')
        self.pick(g,next(o.id for o in q.options if o.card_id==cid));self.play(g,cid)
        self.assertEqual(len(g.state.draw_history),5);self.assertEqual(self.ids(g,WATER),[])
        for card in DRAW_TRIBES:self.assertEqual(len(self.ids(g,card,'hand')),1)
        self.portable(g,'mage_offer')

    def test_r_true_mismatch_offer_preserves_hog_pair_gate_on_low_cost_viper_primary(self):
        cid=recipe(RUST,HOG,'top');g=self.game((MISMATCH,),(N,N),mode='hog_offer',weapon=True);self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.portable(g,'hog_offer')
        self.pick(g,next(o.id for o in q.options if o.card_id==cid));source=self.play(g,cid)
        self.assertEqual(len(g.state.draw_history),2);self.assertIsNone(g.state.players[2].weapon_id)
        self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords)
        self.assertEqual(g.state.players[1].mana,20-g.registry.card(MISMATCH).cost-g.registry.card(RUST).cost);self.portable(g,'hog_offer')

    def test_s_profiles_are_complete_unique_readonly_frozen_and_cannot_mask_another_prefix(self):
        r=fixture.__wrapped__();profile=r.assemble_draw_group_sources[MAGE]
        with self.assertRaises(TypeError):r.assemble_draw_group_sources[MAGE]=profile
        with self.assertRaises(ValueError):r.register_assemble_draw_group_source(profile)
        with self.assertRaises(ValueError):r.register_assemble_draw_group_source(replace(profile,qualifier='invented'))
        with self.assertRaises(ValueError):r.register_assemble_draw_group_source(AssembleDrawGroupSource(RUST,profile.original_battlecry_id,'each_non_minion',profile.original_reward_behavior_id))
        r.freeze()
        with self.assertRaises(ValueError):r.register_assemble_draw_group_source(profile)

    def test_t_reward_shapes_and_rehashed_pending_frames_cannot_borrow_future_original_material(self):
        with self.assertRaises(ValueError):DrawGroupReward('none',target_id=1)
        reward=DrawGroupReward('qualified_both_minions_followup',behavior_id=cards.PREFIX+'water')
        with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,(DrawGroupSlot(),),reward)
        cid=recipe(MAGE,MAZE);g=self.game((cid,),(COIN,COIN),mode='body_wait');self.play(g,cid);saved=g.snapshot()
        calls=[n for n in nodes(saved,'RuleContext')if n['fields'].get('draw_group') is not None]
        self.assertTrue(calls)
        for change in ('future_source','wrong_target','incomplete_pair','other_callback'):
            bad=deepcopy(saved);context=next(n for n in nodes(bad,'RuleContext')if n['fields'].get('draw_group') is not None)
            group=context['fields']['draw_group'];fields=group['fields']
            if change=='future_source':fields['reward']['fields']['source']['fields']['presence_id']=g.state.next_order+100
            elif change=='wrong_target':context['fields']['target_id']=g.state.players[2].hero_id
            elif change=='incomplete_pair':fields['index']=1
            else:fields['reward']['fields']['behavior_id']=cards.PREFIX+'charge'
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('body_wait','reader'))

    def test_u_changed_complete_native_plan_is_rejected_before_any_new_draw(self):
        r=fixture.__wrapped__();native=r.card(MAGE).battlecry
        r._behaviors[native]=lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)),)
        cid=recipe(MAGE,MAZE);g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),deck=(COIN,COIN),mana=10,max_mana=10),PlayerSetup('HERO_08')),generation_context=CTX),r);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)

    def test_v_missing_original_dependency_and_changed_definition_pins_fail_explicitly(self):
        r=fixture.__wrapped__();r._cards[WATER]=replace(r.card(WATER),health=7)
        with self.assertRaises(TargetValidationError):cards.register_assemble_draw_group_conditions(r)
        r=fixture.__wrapped__();del r._cards[WATER]
        with self.assertRaises(ValueError):cards.register_assemble_draw_group_conditions(r)


if __name__=='__main__':unittest.main()
