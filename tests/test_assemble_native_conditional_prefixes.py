"""Actual deck gates, continuous hand witnesses and conditional native arrows."""
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest

from hs_sim.cards import assemble_native_conditional_prefixes as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,
    Rarity,Runes,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import ChoiceOption,Destroy,Draw,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha

BRUISER,HELD=cards.SOURCES
RUST,PHOENIX,NECRO,FOOT,NATURE,PAL_A,PAL_B,TROGG,DRAKE=cards.DEPENDENCIES
P='k448.'
N,KILL,DRAW,COPY,BASE,WATCH,FAIL,UNKNOWN=(P+x for x in('n','kill','draw','copy','base','watch','fail','unknown'))
COIN='GAME_005';META=CardMetadata(False,(CardClass.NEUTRAL,),None,runes=Runes(),tribes=())
CTX=GenerationContext('k448-reviewed-complete-native-conditional-domains','experimental')


def recipe(a,b=None,half='bottom'):return AssembleRecipe(a,b or a,half).card_id


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=build_registry();r._version+='.k448.'+mode
    r.register_card(CardDefinition(N,N,CardType.MINION,health=20,metadata=META))
    def fail(c):raise ResolutionError('K448 deliberate late selected-body failure')
    r.register_behavior(FAIL,fail)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        COPY:lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),1,source_id=c.source_id),),
        BASE:lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),1,mode='base',source_id=c.source_id),)}
    for cid,fn in scripts.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid==KILL else
                TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid in(COPY,BASE)else None))
    if mode in('draw_neutral','death_wait','held_wait'):
        def watch(c):
            if mode=='draw_neutral':return(Draw(1,1,c.source_id),)
            on_go=(Draw(1,1,c.source_id),)if mode=='death_wait'else ()
            return(RequestChoice(1,(ChoiceOption('go','Continue',on_go),
                ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,1),))),c.source_id),)
        event='hand_progressed'if mode=='held_wait'else'minion_died'
        r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,WATCH),)))
    members=[BRUISER,PAL_A,PAL_B]
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,1,replace(META,collectible=True,classes=(CardClass.PALADIN,),rarity=Rarity.COMMON)))
        members.append(UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards','k448-complete-declared-Paladin-domain',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    domains={'bruiser_offer':(BRUISER,TROGG,DRAKE),'held_offer':(HELD,TROGG,DRAKE)}
    if mode in domains:r.register_pool(PoolDefinition(POOL_ID,'k448-three-exact-eligible-fragments',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in domains[mode]),complete=True))
    original=r.behavior(r.card(RUST).battlecry)
    def audited(c):
        if mode=='suffix_fail'and c.source.card_id.startswith('assemble:'):
            raise ResolutionError('K448 actual selected suffix failure')
        return original(c)
    r._behaviors[r.card(RUST).battlecry]=audited;r.validate();return r


class AssembleNativeConditionalTests(unittest.TestCase):
    def game(self,hand=(),board=(),deck=(PAL_A,)*8,enemy=(),mode='normal',hero='HERO_04',weapon=False):
        if mode in('draw_neutral','death_wait','held_wait'):board=board+(WATCH,)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=deck,
            mana=30,max_mana=30,mana_cap=40),PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*16,
                weapon_card_id='CS2_091'if weapon else None)),seed=6,generation_context=CTX),fixture(mode))
    def ids(self,g,cid,p=1,zone='board'):return[i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        source=self.ids(g,cid,zone='hand')[0];g.apply(PlayCard(1,source,target));return source
    def choose(self,g,key='go'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def ready(self,g,entity_id):
        a=progress_ability(g.state.entities[entity_id]);return None if a is None else a.progress_completions
    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader');self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);self.assertEqual(g.snapshot(),saved)
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in('deathrattle_followup','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',text)
        return other

    def test_a_eleven_complete_rows_twenty_faces_and_exact_original_self_definitions(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual((len(rows),len(d['official_observations'])),(11,20))
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'],
                d['display_normalizations'].get(o['card_id']),numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            new=asdict(r.card(recipe(cid)));new['id']=cid;self.assertEqual(new,asdict(r.card(cid)));self.assertEqual(recipe_options(r,cid,cid),())

    def test_b_raw_self_death_keep_current_no_neutral_random_class_and_actual_discount(self):
        for cid in(BRUISER,recipe(BRUISER)):
            for deck,yes in(((PAL_A,),True),((N,),False),((),True)):
                g=self.game((KILL,),(cid,),deck=deck);self.play(g,KILL,self.ids(g,cid)[0])
                hand=g.state.players[1].hand;self.assertEqual(len(hand),int(yes))
                if yes:
                    e=g.state.entities[hand[0]];self.assertIn(CardClass.PALADIN,g.registry.card(e.card_id).metadata.classes)
                    self.assertEqual(quote_cost(g.state,g.registry,e).amount,max(0,g.registry.card(e.card_id).cost-2))

    def test_c_borrowed_death_prefix_gates_weapon_body_and_drops_original_generation(self):
        cid=recipe(RUST,BRUISER,'top')
        for deck,yes in(((PAL_A,),True),((N,),False)):
            g=self.game((KILL,),(cid,),deck=deck,weapon=True);self.play(g,KILL,self.ids(g,cid)[0])
            self.assertEqual(g.state.players[2].weapon_id is None,yes);self.assertFalse(g.state.players[1].hand)
        self.portable(g)

    def test_d_replacing_death_prefix_keeps_free_class_reward_even_with_neutral_deck(self):
        cid=recipe(BRUISER,RUST,'top');g=self.game((cid,),deck=(N,),weapon=True);self.play(g,cid)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertIsNotNone(g.state.players[2].weapon_id);self.assertIsNone(g.registry.card(cid).deathrattle)

    def test_e_actual_death_reaction_draws_last_neutral_before_original_deck_request(self):
        cid=recipe(BRUISER,RUST);g=self.game((KILL,),(cid,),deck=(N,),mode='draw_neutral',weapon=True)
        self.play(g,KILL,self.ids(g,cid)[0]);self.assertFalse(g.state.players[1].deck);self.assertIsNone(g.state.players[2].weapon_id);self.portable(g,'draw_neutral')

    def test_f_unknown_eligible_generation_is_skipped_on_false_gate_and_rolls_back_true_death(self):
        g=self.game((KILL,),(BRUISER,),deck=(N,),mode='unknown');self.play(g,KILL,self.ids(g,BRUISER)[0]);self.assertFalse(g.state.players[1].hand)
        g=self.game((KILL,),(BRUISER,),mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,KILL,self.ids(g,BRUISER)[0])
        self.assertEqual(g.snapshot(),saved)

    def test_g_selected_real_necromancer_suffix_retains_original_death_and_pays_once(self):
        cid=recipe(BRUISER,NECRO);g=self.game((KILL,),(cid,));self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual(len(self.ids(g,FOOT)),1);self.assertEqual(len(g.state.corpse_spend_history),1);self.portable(g)

    def test_h_dead_source_skips_only_held_reward_buff_and_still_draws_original_physical_card(self):
        cid=recipe(BRUISER,HELD);g=self.game((KILL,),(cid,),deck=(PAL_A,));original=g.state.players[1].deck[0];self.play(g,KILL,self.ids(g,cid)[0])
        self.assertIn(original,g.state.players[1].hand);self.assertEqual(len(g.state.draw_history),1);self.portable(g)

    def test_i_raw_self_held_fact_ignores_coin_and_uses_actual_nature_then_buff_and_draw(self):
        for cid in(HELD,recipe(HELD)):
            g=self.game((cid,COIN,NATURE));held=self.ids(g,cid,zone='hand')[0];self.play(g,COIN);self.assertEqual(self.ready(g,held),0)
            self.play(g,NATURE);self.assertEqual(self.ready(g,held),1);source=self.play(g,cid)
            self.assertEqual(g.state.entities[source].attack,g.registry.card(HELD).attack+1);self.assertEqual(len(g.state.draw_history),1)

    def test_j_borrowed_held_prefix_carries_complete_original_progress_and_only_selected_body(self):
        cid=recipe(RUST,HELD,'top');g=self.game((cid,NATURE),weapon=True);held=self.ids(g,cid,zone='hand')[0]
        self.assertEqual(g.registry.card(cid).hand_progress,g.registry.card(HELD).hand_progress);self.assertEqual(self.ready(g,held),0)
        self.play(g,NATURE);self.play(g,cid);self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(len(g.state.draw_history),0);self.portable(g)

    def test_k_replacing_held_prefix_removes_progress_and_keeps_free_buff_draw(self):
        cid=recipe(HELD,RUST,'top');g=self.game((cid,),weapon=True);held=self.ids(g,cid,zone='hand')[0]
        self.assertIsNone(g.registry.card(cid).hand_progress);self.assertIsNone(self.ready(g,held));source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].attack,g.registry.card(HELD).attack+1);self.assertEqual(len(g.state.draw_history),1);self.assertIsNotNone(g.state.players[2].weapon_id)

    def test_l_conditional_arrow_is_absent_before_held_fact_and_uses_character_domain_after(self):
        cid=recipe(HELD,PHOENIX);g=self.game((cid,NATURE));source=self.ids(g,cid,zone='hand')[0];hero=g.state.players[2].hero_id;saved=g.snapshot()
        actions=[a for a in g.legal_actions()if isinstance(a,PlayCard)and a.entity_id==source];self.assertEqual([a.target_id for a in actions],[None]);self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(IllegalAction):self.play(g,cid,hero)
        self.assertEqual(g.snapshot(),saved);self.play(g,NATURE);self.play(g,cid,hero);self.assertEqual(g.state.entities[hero].health,27);self.assertEqual(len(g.state.draw_history),0);self.portable(g)

    def test_m_spell_cast_before_physical_hand_entry_is_not_a_held_witness(self):
        cid=recipe(HELD,RUST);g=self.game((NATURE,DRAW),deck=(cid,),weapon=True);self.play(g,NATURE);self.play(g,DRAW)
        self.assertEqual(self.ready(g,self.ids(g,cid,zone='hand')[0]),0);self.play(g,cid);self.assertIsNotNone(g.state.players[2].weapon_id)

    def test_n_current_hand_copy_retains_original_fact_base_copy_starts_fresh(self):
        cid=recipe(HELD,RUST);g=self.game((cid,NATURE,COPY,BASE));source=self.ids(g,cid,zone='hand')[0]
        self.play(g,NATURE);self.play(g,COPY,source);self.play(g,BASE,source)
        self.assertEqual([self.ready(g,i)for i in self.ids(g,cid,zone='hand')],[1,1,0]);self.portable(g)

    def test_o_actual_progress_wait_recovers_original_alias_fact_then_runs_body_once(self):
        cid=recipe(HELD,RUST);g=self.game((cid,NATURE),mode='held_wait',weapon=True);self.play(g,NATURE);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,'held_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.choose(current);self.play(current,cid)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIsNone(g.state.players[2].weapon_id)

    def test_p_death_wait_rechecks_current_deck_after_resume_without_new_death_root(self):
        cid=recipe(BRUISER,RUST);g=self.game((KILL,),(cid,),deck=(N,),mode='death_wait',weapon=True);self.play(g,KILL,self.ids(g,cid)[0])
        other=self.portable(g,'death_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(len(g.state.draw_history),1)

    def test_q_true_paladin_offer_carries_conditional_death_and_native_drake_damage(self):
        cid=recipe(BRUISER,DRAKE);g=self.game((MISMATCH,KILL),enemy=(N,),mode='bruiser_offer');self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        source=self.play(g,cid);target=self.ids(g,N,2)[0];self.assertEqual(g.state.entities[target].health,20)
        self.play(g,KILL,source);self.assertEqual(g.state.entities[target].health,18);self.portable(g,'bruiser_offer')

    def test_r_true_shaman_offer_starts_new_hand_stay_then_uses_held_prefix_with_trogg_reward(self):
        cid=recipe(HELD,TROGG);g=self.game((NATURE,MISMATCH,NATURE),mode='held_offer',hero='HERO_02');self.play(g,NATURE);self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        self.assertEqual(self.ready(g,self.ids(g,cid,zone='hand')[0]),0);self.play(g,NATURE);source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].max_health,g.registry.card(HELD).health+6);self.assertEqual(g.state.draw_history,[]);self.portable(g,'held_offer')

    def test_s_sources_are_readonly_unique_frozen_and_original_definition_pins_strict(self):
        r=fixture.__wrapped__();death=r.assemble_conditional_death_sources[BRUISER];held=r.assemble_hand_progress_sources[HELD]
        with self.assertRaises(TypeError):r.assemble_hand_progress_sources[HELD]=held
        with self.assertRaises(ValueError):r.register_assemble_conditional_death_source(death)
        with self.assertRaises(ValueError):r.register_assemble_hand_progress_source(held)
        r.freeze()
        with self.assertRaises(ValueError):r.register_assemble_hand_progress_source(held)
        r=fixture.__wrapped__();del r._assemble_hand_progress_sources[HELD]
        with self.assertRaises(ValueError):r.card(recipe(RUST,HELD,'top'))
        r=fixture.__wrapped__();r._cards[HELD]=replace(r.card(HELD),attack=99)
        with self.assertRaises(TargetValidationError):cards.register_assemble_native_conditional_prefixes(r)

    def test_t_late_selected_body_failures_restore_death_and_actual_held_battlecry(self):
        cid=recipe(BRUISER,RUST);g=self.game((KILL,),(cid,),mode='suffix_fail',weapon=True);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,KILL,self.ids(g,cid)[0])
        self.assertEqual(g.snapshot(),saved)
        cid=recipe(HELD,RUST);g=self.game((cid,NATURE),mode='suffix_fail',weapon=True);self.play(g,NATURE);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
