"""Real fact-backed ordinary predicates, native inner windows and fixed subjects."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_turn_draw_spell_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID as ASSEMBLE_POOL
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,TriggerSpec,UseHandAction,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import AddToHand,Draw,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CastWhenDrawnSpec,Keyword,Rarity,SpellSchool
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import RuleContext,UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_attack_finished_followups import DUMMY
from test_assemble_card_play_followups import META,N,KILL,MUTE,COIN,WAR,CURATOR,LOOT

TIGER,VARIANT,PAGE,EREDAR,ANTONIDAS,AUCTIONEER,BROLL,BLAZE,HERALD,WO=cards.SOURCES
P='k429.'
NOOP,FEL,FIRE,NATURE,DRAW,ADD,SUMMON,AUTO,ELEMENTAL,PRE,DRAWCAST,BURN,UNKNOWN=(
    P+x for x in ('noop','fel','fire','nature','draw','add','summon','auto','elemental','pre','drawcast','burn','unknown'))
CTX=GenerationContext('k429-explicit-native-source-domains','experimental')
DECK=(COIN,)*24
COMPANIONS=cards.DEPENDENCIES[2:]


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('normal',role);r._version+='.k429.'+mode
    neutral=replace(META,collectible=True,rarity=Rarity.COMMON)
    elem=replace(neutral,deck_identity=ELEMENTAL,tribes=('elemental',))
    r.register_card(CardDefinition(ELEMENTAL,ELEMENTAL,CardType.MINION,cost=5,health=40,metadata=elem))
    for cid,school,meta in ((NOOP,None,META),(FEL,SpellSchool.FEL,META),(FIRE,SpellSchool.FIRE,META),
            (NATURE,SpellSchool.NATURE,replace(neutral,classes=(CardClass.DRUID,),deck_identity=NATURE))):
        r.register_behavior(cid,lambda c:())
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,spell_school=school,metadata=meta))
    for cid in (ELEMENTAL,NATURE):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,body in ((DRAW,lambda c:(Draw(c.player_id,source_id=c.source_id),)),
            (ADD,lambda c:(AddToHand(c.player_id,COIN,c.source_id),)),
            (SUMMON,lambda c:(Summon(c.player_id,ELEMENTAL),)),
            (BURN,lambda c:(AddToHand(c.player_id,COIN,c.source_id),Draw(c.player_id,source_id=c.source_id)))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,NOOP,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,health=10,battlecry=AUTO,metadata=META))
    r.register_card(CardDefinition(DRAWCAST,DRAWCAST,CardType.SPELL,on_play=NOOP,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=False),metadata=META))
    def pre(c):
        target=c.state.entities[c.event.target_id]
        return (Summon(2,DUMMY),)if c.event.player_id==1 and target.card_id==ELEMENTAL else ()
    r.register_behavior(PRE,pre)
    r.register_card(CardDefinition(PRE,PRE,CardType.MINION,health=40,metadata=META,
        triggers=(TriggerSpec('minion_summoned',PRE),)))
    members=(ELEMENTAL,)
    past=(NATURE,)
    if mode in ('unknown_pool','unknown_past'):
        missing=(CardDefinition(UNKNOWN,UNKNOWN,CardType.MINION,cost=5,health=10,metadata=replace(elem,deck_identity=UNKNOWN))
            if mode=='unknown_pool'else CardDefinition(UNKNOWN,UNKNOWN,CardType.SPELL,cost=1,spell_school=SpellSchool.NATURE,
                metadata=replace(neutral,classes=(CardClass.DRUID,),deck_identity=UNKNOWN)))
        r.register_pool_card(PoolCard.from_definition(missing))
        if mode=='unknown_pool':members+=(UNKNOWN,)
        else:past+=(UNKNOWN,)
    if mode!='no_pool':
        for pool,ids in (('constructed.cards',members),('constructed.past.cards',past)):
            r.register_pool(PoolDefinition(pool,'k429-complete-explicit-experimental-domain',CTX.target_id,CTX.mode,
                tuple(PoolMember(cid)for cid in ids),complete=True))
    if mode=='assemble':
        r.register_pool(PoolDefinition(ASSEMBLE_POOL,'k429-real-low-neutral-two-five-plus-donors',CTX.target_id,
            CTX.mode,tuple(PoolMember(cid)for cid in (VARIANT,BROLL,WAR)),complete=True))
    r.validate();return r


class AssembleTurnDrawSpellTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode='normal',hero='HERO_06',deck=DECK,cap=None):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hand_cap=cap),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=DECK,mana=40,max_mana=40,mana_cap=40)),
            seed=429,generation_context=CTX),fixture(mode))

    def eid(self,g,cid,player=1,zone='board'):
        return next(i for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        p=g.state.active_player;e=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,e,target));return e

    def pick(self,g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))

    def count(self,g,cid,zone='board'):
        return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[1],zone))

    def pets(self,g):return sum(self.count(g,cid)for cid in COMPANIONS)

    def draws(self,g):return len([r for r in g.state.draw_history if r.player_id==1])

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));r=fixture(mode,'reader')
        self.assertIsNot(r,g.registry);other=Game.from_snapshot(saved,r)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','condition_id','accepted_card_id'):
                self.assertNotIn('"'+key+'"',text)
        return other

    def test_a_fifteen_complete_rows_thirty_faces_original_bridges_and_prepare_reconstruction(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows),15);self.assertEqual(len(d['official_observations']),30)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256'])
            check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            old=r.card(cid);new=r.card(AssembleRecipe(cid,cid,'bottom').card_id)
            self.assertEqual((new.cost,new.attack,new.health,new.metadata,new.keywords,new.hand_actions),
                (old.cost,old.attack,old.health,old.metadata,old.keywords,old.hand_actions))
            self.assertEqual(r.assemble_reaction_sources[cid].original_behavior_id,old.triggers[0].behavior_id)

    def test_b_tiger_original_and_self_attack_at_both_players_starts(self):
        for cid in (TIGER,AssembleRecipe(TIGER,TIGER,'bottom').card_id):
            g=self.game(board=(cid,),enemy=(DUMMY,));source=self.eid(g,cid)
            g.apply(EndTurn(1));g.apply(EndTurn(2))
            self.assertEqual(len([e for e in g.events if e.kind=='attack_declared'and e.source_id==source]),2)

    def test_c_variant_original_and_self_only_owner_start_transform_to_five(self):
        for cid in (VARIANT,AssembleRecipe(VARIANT,VARIANT,'bottom').card_id):
            g=self.game(board=(cid,));source=self.eid(g,cid)
            g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].card_id,cid)
            g.apply(EndTurn(2));self.assertEqual(g.state.entities[source].card_id,ELEMENTAL)

    def test_d_borrowed_transform_is_fixed_five_for_five_and_nine_cost_recipients(self):
        cid=AssembleRecipe(CURATOR,VARIANT,'bottom').card_id
        g=self.game((cid,));source=self.play(g,cid);self.assertEqual(g.state.entities[source].card_id,ELEMENTAL)
        cid=AssembleRecipe(AUCTIONEER,VARIANT,'bottom').card_id
        g=self.game((NOOP,),(cid,));source=self.eid(g,cid);self.play(g,NOOP)
        self.assertEqual(g.state.entities[source].card_id,ELEMENTAL)

    def test_e_pageturner_original_and_self_include_own_elemental_entry_and_effect_summon(self):
        for cid in (PAGE,AssembleRecipe(PAGE,PAGE,'bottom').card_id):
            g=self.game((cid,N,ELEMENTAL,SUMMON));target=g.state.players[2].hero_id
            source=self.play(g,cid);self.assertEqual(g.state.entities[target].health,27)
            self.play(g,N);self.assertEqual(g.state.entities[target].health,27)
            self.play(g,ELEMENTAL);self.assertEqual(g.state.entities[target].health,24)
            self.play(g,SUMMON);self.assertEqual(g.state.entities[target].health,21)

    def test_f_pageturner_preserves_late_inner_enemy_candidates(self):
        for cid in (PAGE,AssembleRecipe(PAGE,PAGE,'bottom').card_id):
            g=self.game((ELEMENTAL,),(PRE,cid));source=self.eid(g,cid);self.play(g,ELEMENTAL)
            choices=[e for e in g.events if e.kind=='random_choice'and e.source_id==source]
            self.assertEqual(len(choices),1)
            self.assertEqual(dict(choices[0].data)['candidates'],(g.state.players[2].hero_id,self.eid(g,DUMMY,2)))

    def test_g_eredar_original_and_self_only_actual_own_draw_not_add_or_opponent(self):
        for cid in (EREDAR,AssembleRecipe(EREDAR,EREDAR,'bottom').card_id):
            g=self.game((ADD,DRAW),(cid,));self.play(g,ADD);self.assertEqual(self.count(g,cards.DEMON),0)
            self.play(g,DRAW);self.assertEqual(self.count(g,cards.DEMON),1)
            token=g.state.entities[self.eid(g,cards.DEMON)]
            self.assertEqual((token.attack,token.health),(1,1));self.assertIn(Keyword.RUSH,token.keywords)
            g.apply(EndTurn(1));self.assertEqual(self.count(g,cards.DEMON),1)
            g.apply(EndTurn(2));self.assertEqual(self.count(g,cards.DEMON),2)

    def test_h_spell_starts_keep_original_hand_origin_and_owner_reward(self):
        for original in (ANTONIDAS,AUCTIONEER):
            for cid in (original,AssembleRecipe(original,original,'bottom').card_id):
                g=self.game((NOOP,),(cid,),enemy_hand=(NOOP,));self.play(g,NOOP)
                self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),int(original==ANTONIDAS))
                self.assertEqual(self.draws(g),int(original==AUCTIONEER))
                before=self.draws(g);g.apply(EndTurn(1));self.play(g,NOOP)
                self.assertEqual(self.draws(g),before)
                self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),int(original==ANTONIDAS))

    def test_i_automatic_spell_is_distinct_from_original_hand_only_antonidas_start(self):
        for original in (ANTONIDAS,AUCTIONEER):
            for cid in (original,AssembleRecipe(original,original,'bottom').card_id):
                g=self.game((AUTO,),(cid,));self.play(g,AUTO)
                self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),0)
                self.assertEqual(self.draws(g),int(original==AUCTIONEER))

    def test_j_completed_spell_sources_keep_school_filters_and_original_subjects(self):
        for original in (BROLL,BLAZE,HERALD):
            for cid in (original,AssembleRecipe(original,original,'bottom').card_id):
                g=self.game((NOOP,FEL,FIRE),(cid,),enemy=(DUMMY,));source=self.eid(g,cid)
                self.play(g,NOOP)
                if original==BROLL:self.assertEqual(self.pets(g),1)
                else:
                    self.assertEqual(g.state.entities[source].zone,Zone.BOARD)
                    self.assertEqual(self.count(g,ELEMENTAL,zone='hand'),0)
                    self.play(g,FEL if original==BLAZE else FIRE)
                    if original==BLAZE:
                        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
                        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
                        self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,2)
                    else:
                        self.assertEqual(self.count(g,ELEMENTAL,zone='hand'),1)
                        mana=g.state.players[1].mana;self.play(g,ELEMENTAL)
                        self.assertEqual(g.state.players[1].mana,mana-2)

    def test_k_real_past_nature_discovery_wait_restores_clones_replays_and_delivers(self):
        cid=AssembleRecipe(WO,WO,'bottom').card_id
        g=self.game((NOOP,),(cid,));self.play(g,NOOP);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g)
        for x in (g,other):self.pick(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.count(g,NATURE,zone='hand'),1)
        self.play(g,NATURE);self.assertIsNotNone(g.state.pending_choice);self.pick(g)

    def test_l_borrowed_prefixes_preserve_real_guards_without_old_transform_damage_or_discovery(self):
        cid=AssembleRecipe(VARIANT,ANTONIDAS,'bottom').card_id
        g=self.game(board=(cid,));source=self.eid(g,cid);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[source].card_id,cid);self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),1)
        cid=AssembleRecipe(EREDAR,ANTONIDAS,'bottom').card_id
        g=self.game((DRAW,),(cid,));self.play(g,DRAW)
        self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),1);self.assertEqual(self.count(g,cards.DEMON),0)
        for original,spell in ((BLAZE,FEL),(WO,NOOP)):
            cid=AssembleRecipe(original,WAR,'bottom').card_id
            g=self.game((spell,),(cid,),enemy=(DUMMY,));source=self.eid(g,cid);self.play(g,spell)
            self.assertEqual(self.draws(g),1);self.assertEqual(g.state.entities[source].zone,Zone.BOARD)
            self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,0);self.assertIsNone(g.state.pending_choice)

    def test_m_ten_guard_free_battlecry_subjects_do_not_need_old_event(self):
        for suffix in cards.SOURCES:
            cid=AssembleRecipe(CURATOR,suffix,'bottom').card_id
            g=self.game((cid,),enemy=(DUMMY,));source=self.play(g,cid)
            if suffix==TIGER:self.assertTrue(any(e.kind=='attack_declared'and e.source_id==source for e in g.events))
            elif suffix==VARIANT:self.assertEqual(g.state.entities[source].card_id,ELEMENTAL)
            elif suffix==PAGE:self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==source and e.amount==3 for e in g.events))
            elif suffix==EREDAR:self.assertEqual(self.count(g,cards.DEMON),1)
            elif suffix==ANTONIDAS:self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),1)
            elif suffix==AUCTIONEER:self.assertEqual(self.draws(g),1)
            elif suffix==BROLL:self.assertEqual(self.pets(g),1)
            elif suffix==BLAZE:
                self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
            elif suffix==HERALD:self.assertEqual(self.count(g,ELEMENTAL,zone='hand'),1)
            else:self.assertIsNotNone(g.state.pending_choice);self.pick(g);self.assertEqual(self.count(g,NATURE,zone='hand'),1)

    def test_n_dead_subjects_deliver_tail_rewards_but_do_not_attack_or_transform_graveyard(self):
        for suffix in (TIGER,VARIANT,EREDAR,ANTONIDAS,BROLL,BLAZE,HERALD,WO):
            cid=AssembleRecipe(LOOT,suffix,'bottom').card_id
            g=self.game((cid,KILL),enemy=(DUMMY,));source=self.play(g,cid);self.play(g,KILL,source)
            if g.state.pending_choice:self.pick(g)
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            if suffix==EREDAR:self.assertEqual(self.count(g,cards.DEMON),1)
            elif suffix==ANTONIDAS:self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),1)
            elif suffix==BROLL:self.assertEqual(self.pets(g),1)
            elif suffix==BLAZE:self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
            elif suffix==HERALD:self.assertEqual(self.count(g,ELEMENTAL,zone='hand'),1)
            elif suffix==WO:self.assertEqual(self.count(g,NATURE,zone='hand'),1)
            else:self.assertFalse(any(e.kind=='attack_declared'and e.source_id==source for e in g.events))

    def test_o_original_and_self_auctioneer_prepare_use_real_physical_hand_action(self):
        outcomes=[]
        for cid in (AUCTIONEER,AssembleRecipe(AUCTIONEER,AUCTIONEER,'bottom').card_id):
            g=self.game((cid,));source=self.eid(g,cid,zone='hand');before=g.state.players[1].mana
            quote=g.quote_hand_action(source,'prepare');self.assertEqual(quote.amount,8)
            g.apply(UseHandAction(1,source,'prepare'))
            self.assertEqual(g.state.players[1].mana,before-quote.amount)
            outcomes.append((g.state.entities[source].zone,len(g.state.players[1].hand),len(g.state.players[1].deck)))
        self.assertEqual(outcomes[0],outcomes[1])

    def test_p_unknown_eligible_transform_elemental_and_past_domains_rollback_whole_root(self):
        for original,mode,spell in ((VARIANT,'unknown_pool',None),(HERALD,'unknown_pool',FIRE),(WO,'unknown_past',NOOP)):
            cid=AssembleRecipe(original,original,'bottom').card_id
            g=self.game((spell,)if spell else (),board=(cid,),mode=mode)
            if original==VARIANT:g.apply(EndTurn(1))
            saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'unsupported|unimplemented'):
                g.apply(EndTurn(2))if original==VARIANT else self.play(g,spell)
            self.assertEqual(g.snapshot(),saved)

    def test_q_real_mismatch_low_variant_prefix_gets_companion_instead_of_transform(self):
        cid=AssembleRecipe(VARIANT,BROLL,'bottom').card_id
        g=self.game((MISMATCH,),mode='assemble',hero='HERO_05');self.play(g,MISMATCH)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(next(o.id for o in c.options if o.card_id==cid),)))
        mana=g.state.players[1].mana;source=self.play(g,cid);self.assertEqual(g.state.players[1].mana,mana-2)
        g.apply(EndTurn(1));self.assertEqual(self.pets(g),0)
        g.apply(EndTurn(2));self.assertEqual(self.pets(g),1);self.assertEqual(g.state.entities[source].card_id,cid)

    def test_r_missing_or_forged_original_cast_draw_summon_and_turn_events_are_rejected(self):
        g=self.game((NOOP,),(ANTONIDAS,));source=self.eid(g,ANTONIDAS)
        for suffix in ('any_turn','own_turn','own_elemental_summon','own_draw','own_hand_cast_start','own_cast_start',
                'own_finished_cast','own_finished_fel_cast','own_finished_fire_cast'):
            with self.assertRaises(ResolutionError):g.registry.trigger_condition(cards.PREFIX+suffix)(RuleContext(g.state,source,1))
        self.play(g,NOOP);event=next(e for e in g.events if e.kind=='spell_cast_started')
        with self.assertRaises(ResolutionError):
            g.registry.trigger_condition(cards.PREFIX+'own_hand_cast_start')(RuleContext(g.state,source,1,event=replace(event,source_id=source)))

    def test_s_full_dependency_query_family_and_inner_behavior_pins_precede_partial_installation(self):
        with patch('hs_sim.cards.assemble_turn_draw_spell_followups.register_assemble_turn_draw_spell_followups',lambda r:None):r=build_registry()
        before=r.fingerprint();old=r._cards[cards.FIREBALL];r._cards[cards.FIREBALL]=replace(old,cost=old.cost+1)
        with self.assertRaises(TargetValidationError):cards.register_assemble_turn_draw_spell_followups(r)
        self.assertFalse(any(cid in r.assemble_templates for cid in cards.SOURCES));r._cards[cards.FIREBALL]=old
        with patch.object(cards.native_herald,'QUERY',replace(cards.native_herald.QUERY,collectible=False)):
            with self.assertRaisesRegex(TargetValidationError,'generation query'):cards.register_assemble_turn_draw_spell_followups(r)
        behavior=r._behaviors.pop(cards.PAGE_INNER)
        with self.assertRaises(ValueError):cards.register_assemble_turn_draw_spell_followups(r)
        r._behaviors[cards.PAGE_INNER]=behavior;self.assertEqual(r.fingerprint(),before)

    def test_t_past_nature_uses_current_hero_class_instead_of_source_printed_class(self):
        cid=AssembleRecipe(WO,WO,'bottom').card_id
        g=self.game((NOOP,),(cid,),hero='HERO_08');before=g.snapshot()['rng_state'];self.play(g,NOOP)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_u_cast_when_drawn_is_an_actual_draw_but_burn_does_not_summon_demon(self):
        cid=AssembleRecipe(EREDAR,EREDAR,'bottom').card_id
        g=self.game((DRAW,),(cid,),deck=(DRAWCAST,));self.play(g,DRAW)
        self.assertEqual(self.count(g,cards.DEMON),1);self.assertEqual(g.state.draw_history[-1].outcome,'cast')
        g=self.game((BURN,),(cid,),cap=1);self.play(g,BURN)
        self.assertEqual(self.count(g,cards.DEMON),0)

    def test_v_real_counterspell_keeps_start_rewards_and_prevents_successful_finish_subject(self):
        ids=tuple(AssembleRecipe(cid,cid,'bottom').card_id for cid in (ANTONIDAS,AUCTIONEER,BROLL))
        g=self.game((NOOP,),ids,enemy_hand=('CORE_EX1_287',));g.apply(EndTurn(1));self.play(g,'CORE_EX1_287');g.apply(EndTurn(2))
        before=self.draws(g);self.play(g,NOOP)
        self.assertEqual(g.state.cast_history[-1].failure,'countered')
        self.assertEqual(self.count(g,cards.FIREBALL,zone='hand'),1);self.assertEqual(self.draws(g),before+1)
        self.assertEqual(self.pets(g),0)
