"""Real death, shield and power subjects retain exact native predicates."""
import unittest
from dataclasses import asdict, replace
from functools import lru_cache
import json
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_death_shield_inspire_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, Draw, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Resource, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes, has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_attack_finished_followups import fixture as base_fixture, DUMMY
from test_assemble_card_play_followups import META, N, KILL, MUTE, COIN, WAR, CURATOR, LOOT, END, START

IRONBORN, DRAGONBANE, ACOLYTE, BOLVAR, DIREHORN, BARKSHIELD, ROACH, RESCUER = cards.SOURCES
P = 'k426.'
HURT, UNDEAD, SHIELD, PRE, WATCH, FAIL = (P+x for x in ('hurt','undead','shield','pre','watch','fail'))
MAKE_UNDEAD = P+'make_undead'
CTX = GenerationContext('k426-explicit-reviewed-sources', 'experimental')
DECK = (COIN,)*24


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role)
    r._version += '.k426.'+mode
    r.register_behavior(HURT, lambda c: (Damage(c.target_id, 1, c.source_id),))
    r.register_card(CardDefinition(HURT, HURT, CardType.SPELL, on_play=HURT,
        targeting=r.card(KILL).targeting, metadata=META))
    r.register_behavior(MAKE_UNDEAD, lambda c: (ChangeMinionTribes(
        MinionReference.capture(c.state.entities[c.target_id]), TribeChangeSpec('set', ('undead',)), c.source_id),))
    r.register_card(CardDefinition(MAKE_UNDEAD, MAKE_UNDEAD, CardType.SPELL, on_play=MAKE_UNDEAD,
        targeting=r.card(KILL).targeting, metadata=META))
    r.register_card(CardDefinition(UNDEAD, UNDEAD, CardType.MINION, health=2,
        metadata=replace(META, tribes=('undead',))))
    r.register_card(CardDefinition(SHIELD, SHIELD, CardType.MINION, health=10,
        keywords=(Keyword.DIVINE_SHIELD,), metadata=META))
    def fail(c):
        raise ResolutionError('K426 deliberate continuation failure')
    def pre(c):
        if mode == 'shield_draw':
            return (Draw(1, source_id=c.source_id),) if c.state.entities[c.event.target_id].controller==1 else ()
        if c.event.player_id != 1:
            return ()
        if mode == 'power_late':
            return (Summon(2, DUMMY),)
        return ()
    def watch(c):
        if c.event.player_id != 1:
            return ()
        return (RequestChoice(1, (
            ChoiceOption('go', 'Continue'),
            ChoiceOption('bounce', 'Return accepted source', (ReturnToHand(c.state.players[1].board[0]),)),
            ChoiceOption('bad', 'Fail', (GainArmor(1, 1), InvokeBehavior(FAIL, c.source_id, 1)))), c.source_id),)
    r.register_behavior(FAIL, fail)
    r.register_behavior(PRE, pre)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(PRE, PRE, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('shield_lost' if mode=='shield_draw' else 'hero_power_used', PRE),)))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    if mode in ('assemble','unsupported'):
        r.register_pool(PoolDefinition(POOL_ID, 'k426-original-low-primary-two-five-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in
                (ROACH, IRONBORN, WAR if mode=='assemble' else CURATOR)), complete=True))
    r.validate()
    return r


class AssembleDeathShieldInspireTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode='normal',
            active=1, mana=10, corpses=0, deck=DECK, hero='HERO_08'):
        power = 'HERO_06bp' if hero=='HERO_06' else 'HERO_08bp'
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=deck, mana=mana, max_mana=10,
                mana_cap=10, corpses=corpses, hero_power_card_id=power),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=DECK, mana=10,
                max_mana=10, mana_cap=10, hero_power_card_id='HERO_08bp')),
            active_player=active, seed=426, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, player=1, zone='board'):
        return next(e for e in getattr(g.state.players[player], zone) if g.state.entities[e].card_id==cid)

    def play(self, g, cid, target=None):
        player=g.state.active_player; source=self.eid(g,cid,player,'hand')
        g.apply(PlayCard(player,source,target)); return source

    def pick(self,g,key):
        c=g.state.pending_choice; g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def power(self,g):
        p=g.state.active_player
        target=None if g.state.entities[g.state.players[p].hero_id].card_id=='HERO_06' else g.state.players[3-p].hero_id
        g.apply(UseHeroPower(p,g.state.players[p].hero_power_id,target_id=target))

    def bank(self,g):
        return g.state.players[1].resources[Resource.CORPSES]

    def draws(self,g):
        return [x for x in g.state.draw_history if x.player_id==1]

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot())); r=fixture(mode,'reader')
        self.assertIsNot(r,g.registry)
        restored=Game.from_snapshot(saved,r)
        self.assertEqual(restored.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for player in (1,2):
            public=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('rng_state','resolution_frame','condition_id','accepted_card_id'):
                self.assertNotIn('"'+key+'"',public)
        return restored

    def test_a_complete_nine_sources_eighteen_faces_exact_bridges_and_reconstruction(self):
        data=cards.load_batch();r=fixture()
        self.assertEqual(len(data['official_observations']),18)
        rows={x['record']['id']:x for x in data['existing_dependencies']}
        for obs in data['official_observations']:
            self.assertEqual(sha(obs['response_file']),obs['response_sha256'])
            check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'])
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            old=r.card(cid);new=r.card(AssembleRecipe(cid,cid,'bottom').card_id)
            self.assertEqual((new.cost,new.attack,new.health,new.keywords,new.metadata),
                (old.cost,old.attack,old.health,old.keywords,old.metadata))
            self.assertEqual(r.assemble_reaction_sources[cid].original_behavior_id,old.triggers[0].behavior_id)
        self.assertEqual(canonical_digest(asdict(r.player_effect(data['recruit_profile']['id']))),data['recruit_profile_sha256'])

    def test_b_ironborn_original_and_self_only_enemy_death_during_owners_turn(self):
        for cid in (IRONBORN,AssembleRecipe(IRONBORN,IRONBORN,'bottom').card_id):
            for victim_player,active in ((2,1),(1,1),(2,2)):
                with self.subTest(cid=cid,victim=victim_player,active=active):
                    g=self.game((KILL,), (cid,N) if victim_player==1 else (cid,),
                        enemy=(N,) if victim_player==2 else (), enemy_hand=(KILL,),active=active)
                    source=self.eid(g,cid);victim=self.eid(g,N,victim_player)
                    before=g.snapshot()['rng_state'];self.play(g,KILL,victim)
                    earned=victim_player==2 and active==1
                    self.assertEqual(g.state.entities[source].attack,g.registry.card(IRONBORN).attack+2*earned)
                    self.assertEqual(g.state.entities[source].max_health,g.registry.card(IRONBORN).health+2*earned)
                    self.assertEqual(g.snapshot()['rng_state']==before,not earned)

    def test_c_acolyte_original_and_self_only_friendly_frozen_undead_deaths(self):
        for cid in (ACOLYTE,AssembleRecipe(ACOLYTE,ACOLYTE,'bottom').card_id):
            for victim,owner in ((UNDEAD,1),(N,1),(UNDEAD,2)):
                g=self.game((KILL,), (cid,victim) if owner==1 else (cid,), enemy=(victim,) if owner==2 else ())
                self.play(g,KILL,self.eid(g,victim,owner))
                self.assertEqual(len(self.draws(g)),int(victim==UNDEAD and owner==1))
            g=self.game((MAKE_UNDEAD,KILL),(cid,N));victim=self.eid(g,N)
            self.play(g,MAKE_UNDEAD,victim);self.play(g,KILL,victim)
            self.assertEqual(len(self.draws(g)),1)
            self.assertTrue(has_any_tribe(g.registry,g.state.death_history[-1],('undead',)))
            self.assertNotIn('undead',g.registry.card(N).metadata.tribes)

    def test_d_direhorn_original_and_self_pay_exactly_three_only_when_missing_reborn(self):
        for cid in (DIREHORN,AssembleRecipe(DIREHORN,DIREHORN,'bottom').card_id):
            for initial in (0,2,5):
                g=self.game((KILL,KILL),(cid,N,N),corpses=initial)
                source=self.eid(g,cid);self.play(g,KILL,self.eid(g,N))
                paid=initial>=2
                self.assertEqual(Keyword.REBORN in g.state.entities[source].keywords,paid)
                self.assertEqual(self.bank(g),initial+1-3*paid)
                self.play(g,KILL,self.eid(g,N))
                self.assertEqual(self.bank(g),initial+2-3*paid)

    def test_e_bolvar_original_and_self_accept_friendly_and_self_shields_only(self):
        for cid in (BOLVAR,AssembleRecipe(BOLVAR,BOLVAR,'bottom').card_id):
            for victim,owner in ((SHIELD,1),(cid,1),(SHIELD,2)):
                g=self.game((HURT,N),(cid,SHIELD),enemy=(SHIELD,))
                target=self.eid(g,victim,owner);held=self.eid(g,N,zone='hand')
                self.play(g,HURT,target)
                self.assertEqual(g.state.entities[held].attack,1+5*(owner==1))
                self.assertEqual(g.state.entities[held].max_health,12+5*(owner==1))

    def test_f_bolvar_reward_samples_current_hand_after_earlier_shield_observer(self):
        cid=AssembleRecipe(BOLVAR,BOLVAR,'bottom').card_id
        g=self.game((HURT,),(PRE,cid,SHIELD),mode='shield_draw',deck=(N,))
        self.play(g,HURT,self.eid(g,SHIELD));held=self.eid(g,N,zone='hand')
        self.assertEqual(g.state.entities[held].attack,6)

    def test_g_rescuer_original_and_self_only_own_shield_permanently_upgrades_all_live_zones(self):
        for cid in (RESCUER,AssembleRecipe(RESCUER,RESCUER,'bottom').card_id):
            g=self.game((HURT,HURT,KILL,cards.RECRUIT),(cid,SHIELD,cards.RECRUIT),deck=(cards.RECRUIT,))
            self.play(g,HURT,self.eid(g,SHIELD))
            self.assertEqual(g.state.entities[self.eid(g,cards.RECRUIT)].max_health,1)
            source=self.eid(g,cid);self.play(g,HURT,source);self.play(g,KILL,source)
            for zone in ('board','hand','deck'):
                self.assertEqual(g.state.entities[self.eid(g,cards.RECRUIT,zone=zone)].max_health,2)
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_h_power_original_and_self_keep_owner_gates_stats_refresh_and_damage(self):
        for original in (DRAGONBANE,BARKSHIELD,ROACH):
            for cid in (original,AssembleRecipe(original,original,'bottom').card_id):
                g=self.game(board=(cid,),mana=5);source=self.eid(g,cid)
                self.power(g)
                self.assertEqual(g.state.players[1].mana,5 if original==ROACH else 3)
                self.assertEqual(g.state.entities[source].max_health,g.registry.card(original).health+2*(original==BARKSHIELD))
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24 if original==DRAGONBANE else 29)
                before=g.state.entities[source].max_health
                g.apply(EndTurn(1));self.power(g)
                self.assertEqual(g.state.entities[source].max_health,before)
                self.assertEqual(g.state.players[1].mana,5 if original==ROACH else 3)

    def test_i_dragonbane_preserves_late_inner_current_enemy_query(self):
        for cid in (DRAGONBANE,AssembleRecipe(DRAGONBANE,DRAGONBANE,'bottom').card_id):
            g=self.game(board=(PRE,cid),mode='power_late');source=self.eid(g,cid)
            self.power(g)
            hits=[e for e in g.events if e.kind=='damage_dealt' and e.source_id==source]
            self.assertEqual(len(hits),1);self.assertEqual(hits[0].amount,5)
            self.assertIn(hits[0].target_id,(g.state.players[2].hero_id,self.eid(g,DUMMY,2)))
            choices=[e for e in g.events if e.kind=='random_choice' and e.source_id==source]
            self.assertEqual(len(choices),1)
            self.assertEqual(dict(choices[0].data)['candidates'],
                (g.state.players[2].hero_id,self.eid(g,DUMMY,2)))

    def test_j_borrowed_death_prefix_draw_omits_old_bonus_and_filters_friendly(self):
        cid=AssembleRecipe(IRONBORN,WAR,'bottom').card_id
        g=self.game((KILL,KILL),(cid,N),enemy=(N,));source=self.eid(g,cid)
        self.play(g,KILL,self.eid(g,N));self.assertEqual(len(self.draws(g)),0)
        self.play(g,KILL,self.eid(g,N,2));self.assertEqual(len(self.draws(g)),1)
        self.assertEqual(g.state.entities[source].attack,g.registry.card(IRONBORN).attack)

    def test_k_borrowed_power_prefix_draw_has_no_original_damage_health_or_refresh(self):
        for original in (DRAGONBANE,BARKSHIELD,ROACH):
            cid=AssembleRecipe(original,WAR,'bottom').card_id
            g=self.game(board=(cid,),mana=5);source=self.eid(g,cid);self.power(g)
            self.assertEqual(len(self.draws(g)),1);self.assertEqual(g.state.players[1].mana,3)
            self.assertEqual(g.state.entities[source].max_health,g.registry.card(original).health)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29)

    def test_l_independent_bodies_execute_at_battlecry_without_old_event_guard(self):
        for suffix in cards.SOURCES:
            cid=AssembleRecipe(CURATOR,suffix,'bottom').card_id
            g=self.game((cid,N,cards.RECRUIT),enemy=(DUMMY,),mana=10,corpses=3)
            held=self.eid(g,N,zone='hand');source=self.play(g,cid)
            if suffix==IRONBORN:self.assertEqual(g.state.entities[source].attack,g.registry.card(CURATOR).attack+2)
            elif suffix==DRAGONBANE:self.assertTrue(any(e.kind=='damage_dealt' and e.source_id==source and e.amount==5 for e in g.events))
            elif suffix==ACOLYTE:self.assertEqual(len(self.draws(g)),1)
            elif suffix==BOLVAR:
                self.assertEqual(sum(g.state.entities[e].attack-g.registry.card(g.state.entities[e].card_id).attack for e in g.state.players[1].hand),5)
            elif suffix==DIREHORN:
                self.assertEqual(self.bank(g),0);self.assertIn(Keyword.REBORN,g.state.entities[source].keywords)
            elif suffix==BARKSHIELD:self.assertEqual(g.state.entities[source].max_health,g.registry.card(CURATOR).health+2)
            elif suffix==ROACH:self.assertEqual(g.state.players[1].mana,10-g.registry.card(CURATOR).cost+2)
            else:self.assertEqual(g.state.entities[self.eid(g,cards.RECRUIT,zone='hand')].max_health,2)

    def test_m_dead_self_bodies_do_not_resurrect_or_spend_but_refresh_and_program_continue(self):
        for suffix in (IRONBORN,DIREHORN,BARKSHIELD,ROACH,RESCUER):
            cid=AssembleRecipe(LOOT,suffix,'bottom').card_id
            g=self.game((cid,KILL,cards.RECRUIT),corpses=5,mana=5)
            source=self.play(g,cid);mana=g.state.players[1].mana;self.play(g,KILL,source)
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            self.assertEqual(self.bank(g),6)
            self.assertEqual(g.state.players[1].mana,mana+2*(suffix==ROACH))
            self.assertEqual(g.state.entities[self.eid(g,cards.RECRUIT,zone='hand')].max_health,1+(suffix==RESCUER))

    def test_n_end_start_contexts_use_public_refresh_and_health_effects(self):
        cid=AssembleRecipe(END,ROACH,'bottom').card_id
        g=self.game(board=(cid,),mana=0);g.apply(EndTurn(1));self.assertEqual(g.state.players[1].mana,2)
        cid=AssembleRecipe(START,BARKSHIELD,'bottom').card_id
        g=self.game(board=(cid,));source=self.eid(g,cid)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[source].max_health,g.registry.card(START).health+2)

    def test_o_real_druid_mismatch_offer_draws_after_power_without_refresh(self):
        cid=AssembleRecipe(ROACH,WAR,'bottom').card_id
        g=self.game((MISMATCH,),mode='assemble',hero='HERO_06');self.play(g,MISMATCH)
        self.pick(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
        self.play(g,cid);mana=g.state.players[1].mana;self.power(g)
        self.assertEqual(g.state.players[1].mana,mana-2);self.assertEqual(len(self.draws(g)),1)

    def test_p_unreviewed_eligible_suffix_does_not_prune_offer_and_rolls_back_whole_root(self):
        g=self.game((MISMATCH,),mode='unsupported',hero='HERO_06');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'explicitly unimplemented'):
            self.play(g,MISMATCH)
        self.assertEqual(g.snapshot(),saved)

    def test_q_real_death_draw_wait_restore_clone_replay_failure_and_player_privacy(self):
        cid=AssembleRecipe(IRONBORN,WAR,'bottom').card_id
        g=self.game((KILL,),(cid,WATCH),enemy=(N,));self.play(g,KILL,self.eid(g,N,2))
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K426 deliberate'):
            self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.pick(g,'go');self.pick(other,'go');self.assertEqual(g.snapshot(),other.snapshot())

    def test_r_missing_or_forged_original_death_and_power_facts_are_rejected(self):
        cid=AssembleRecipe(ACOLYTE,ACOLYTE,'bottom').card_id
        g=self.game((KILL,),(cid,UNDEAD));source=self.eid(g,cid);self.play(g,KILL,self.eid(g,UNDEAD))
        event=next(e for e in g.events if e.kind=='minion_died')
        condition=g.registry.trigger_condition(cards.PREFIX+'friendly_undead_death')
        for forged in (None,replace(event,target_id=source),replace(event,data=(('death_id',True),))):
            with self.assertRaises(ResolutionError):
                condition(RuleContext(g.state,source,1,event=forged))
        own=g.registry.trigger_condition(cards.PREFIX+'own_manual_power')
        with self.assertRaises(ValueError):
            own(RuleContext(g.state,source,1,event=replace(event,kind='hero_power_used',data=(('power_id',True),))))

    def test_s_preflight_rejects_original_definition_program_and_inner_behavior_drift(self):
        with patch('hs_sim.cards.assemble_death_shield_inspire_followups.register_assemble_death_shield_inspire_followups',lambda r:None):
            r=build_registry()
        before=r.fingerprint()
        for kind in ('definition','program','inner','profile'):
            if kind=='definition':
                cid=IRONBORN;old=r._cards[cid];r._cards[cid]=replace(old,health=old.health+1)
            elif kind in ('program','inner'):
                key=cards.load_batch()['recruit_profile']['id'] if kind=='program' else cards.load_batch()['original_dragonbane_inner']
                old=r._behaviors.pop(key)
            else:
                key=cards.load_batch()['recruit_profile']['id'];old=r._player_effects[key]
                r._player_effects[key]=replace(old,auras=(replace(old.auras[0],health=2),))
            with self.assertRaises((TargetValidationError,ValueError,KeyError)):
                cards.register_assemble_death_shield_inspire_followups(r)
            self.assertFalse(any(x in r.assemble_templates for x in cards.SOURCES))
            if kind=='definition':r._cards[cid]=old
            elif kind in ('program','inner'):r._behaviors[key]=old
            else:r._player_effects[key]=old
        self.assertEqual(r.fingerprint(),before)


class NativeRefreshOwnerRegressionTests(unittest.TestCase):
    def test_refresh_two_does_not_credit_opponent_use_when_owner_has_spent_crystals(self):
        registry=build_registry();calls=[]
        original=registry.behavior('cards.recruits.refresh_two')
        def recorded(context):
            effects=original(context)
            if effects:calls.append((context.event.player_id,context.player_id))
            return effects
        registry._behaviors['cards.recruits.refresh_two']=recorded
        game=Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',board=('END_008',),deck=('GAME_005',)*8,
                hero_power_card_id='HERO_08bp',mana=0,max_mana=10,mana_cap=10),
            PlayerSetup('HERO_08',deck=('GAME_005',)*8,hero_power_card_id='HERO_08bp',
                mana=10,max_mana=10,mana_cap=10))),registry)
        game.apply(EndTurn(1))
        game.apply(UseHeroPower(2,game.state.players[2].hero_power_id,
            target_id=game.state.players[1].hero_id))
        self.assertEqual(game.state.players[1].mana,0)
        self.assertEqual(game.state.players[2].mana,8)
        self.assertEqual(calls,[])
        game.apply(EndTurn(2))
        game.apply(UseHeroPower(1,game.state.players[1].hero_power_id,
            target_id=game.state.players[2].hero_id))
        self.assertEqual(game.state.players[1].mana,10)
        self.assertEqual(calls,[(1,1)])
