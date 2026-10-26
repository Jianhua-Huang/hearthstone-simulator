"""Native settled damage gates and independently borrowed assembly bodies."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_damage_health_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, GainArmor, GrantKeyword,
    Heal, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_death_shield_inspire_followups import fixture as base_fixture
from test_assemble_attack_finished_followups import DUMMY
from test_assemble_card_play_followups import META, N, KILL, MUTE, COIN, WAR, CURATOR, LOOT, END, START

PREY, PAIN, TOWER, WASP, TORTOLLA, DESTROYER, HOURGLASS = cards.SOURCES
P='k427.'
PING, LETHAL, ZERO, HEAL, SHIELD, ALL, PRE, WATCH, FAIL = (
    P+x for x in ('ping','lethal','zero','heal','shield','all','pre','watch','fail'))
CTX=GenerationContext('k427-explicit-reviewed-damage-sources','experimental')
DECK=(COIN,)*24


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('normal',role);r._version+='.k427.'+mode
    for cid,body in (
            (PING,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.MINION_ABILITY),)),
            (LETHAL,lambda c:(Damage(c.target_id,40,c.source_id,DamageKind.MINION_ABILITY),)),
            (ZERO,lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.MINION_ABILITY),)),
            (HEAL,lambda c:(Heal(c.target_id,5,c.source_id),)),
            (SHIELD,lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),))):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=10,battlecry=cid,
            targeting=TargetSpec(),metadata=META))
    r.register_behavior(ALL,lambda c:(DamageBatch(tuple(Damage(e,1,c.source_id,DamageKind.EFFECT)
        for p in (1,2)for e in c.state.players[p].board)),))
    r.register_card(CardDefinition(ALL,ALL,CardType.SPELL,on_play=ALL,metadata=META))
    def fail(c):
        raise ResolutionError('K427 deliberate continuation failure')
    def pre(c):
        return (Summon(2,DUMMY),) if c.event.target_id==c.state.players[1].board[1] else ()
    def watch(c):
        if c.event.player_id!=1:return ()
        return (RequestChoice(1,(ChoiceOption('go','Continue'),ChoiceOption('bad','Fail',
            (GainArmor(1,1),InvokeBehavior(FAIL,c.source_id,1)))),c.source_id),)
    for cid,body in ((FAIL,fail),(PRE,pre),(WATCH,watch)):r.register_behavior(cid,body)
    r.register_card(CardDefinition(PRE,PRE,CardType.MINION,health=40,metadata=META,
        triggers=(TriggerSpec('damage_dealt',PRE),)))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,metadata=META,
        triggers=(TriggerSpec('card_drawn',WATCH),)))
    if mode in ('assemble','unsupported'):
        if mode=='unsupported':
            # This negative fixture deliberately withholds the reaction-body
            # review. Production CURATOR now has that reviewed capability.
            template=r._assemble_templates[CURATOR]
            r._assemble_templates[CURATOR]=replace(template,suffix=replace(template.suffix,
                allowed_timings=('battlecry','deathrattle','end_turn')))
        ids=(PAIN,WASP,PREY if mode=='assemble' else CURATOR)
        r.register_pool(PoolDefinition(POOL_ID,'k427-low-neutral-primary-two-high-donors',
            CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in ids),complete=True))
    r.validate();return r


class AssembleDamageHealthTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),active=1,armor=0,mode='normal',deck=DECK,hero='HERO_11'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=30,max_mana=30,
                mana_cap=30,armor=armor),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=DECK,mana=30,max_mana=30,mana_cap=30)),
            active_player=active,seed=427,generation_context=CTX),fixture(mode))

    def eid(self,g,cid,player=1,zone='board'):
        return next(e for e in getattr(g.state.players[player],zone)if g.state.entities[e].card_id==cid)

    def play(self,g,cid,target=None):
        p=g.state.active_player;e=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,e,target));return e

    def pick(self,g,key):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def count(self,g,cid,player=1,zone='board'):
        return sum(g.state.entities[e].card_id==cid for e in getattr(g.state.players[player],zone))

    def draws(self,g):
        return [x for x in g.state.draw_history if x.player_id==1]

    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));r=fixture(mode,'reader')
        self.assertIsNot(r,g.registry);restored=Game.from_snapshot(saved,r)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','condition_id','accepted_card_id'):
                self.assertNotIn('"'+key+'"',text)
        return restored

    def test_a_complete_ten_rows_twenty_primary_faces_original_bridges_and_all_reviewed_contexts(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(rows),10);self.assertEqual(len(d['official_observations']),20)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256'])
            check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            old=r.card(cid);new=r.card(AssembleRecipe(cid,cid,'bottom').card_id)
            self.assertEqual((new.cost,new.attack,new.health,new.keywords,new.metadata),
                (old.cost,old.attack,old.health,old.keywords,old.metadata))
            self.assertEqual(r.assemble_reaction_sources[cid].original_behavior_id,old.triggers[0].behavior_id)
            self.assertEqual(len(r.assemble_templates[cid].suffix.allowed_timings),20)

    def test_b_four_original_and_self_damage_sources_ignore_other_targets_zero_and_healing(self):
        for original in cards.SOURCES[:4]:
            for cid in (original,AssembleRecipe(original,original,'bottom').card_id):
                g=self.game((PING,ZERO,HEAL),(cid,N),enemy=(DUMMY,));source=self.eid(g,cid)
                before=g.snapshot()['rng_state'];self.play(g,PING,self.eid(g,N));self.play(g,ZERO,source);self.play(g,HEAL,source)
                self.assertEqual(len(self.draws(g)),0);self.assertEqual(self.count(g,cards.GHOUL),0)
                self.assertEqual(self.count(g,cards.STINGER,zone='hand'),0)
                self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].zone,Zone.BOARD)
                self.assertEqual(g.snapshot()['rng_state'],before)

    def test_c_actual_and_lethal_positive_damage_keep_four_native_rewards(self):
        for original in cards.SOURCES[:4]:
            for cid in (original,AssembleRecipe(original,original,'bottom').card_id):
                for driver in (PING,LETHAL):
                    g=self.game((driver,),(cid,),enemy=(DUMMY,));source=self.eid(g,cid);enemy=self.eid(g,DUMMY,2)
                    self.play(g,driver,source)
                    self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD if driver==LETHAL else Zone.BOARD)
                    if original==PREY:self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)
                    elif original==PAIN:self.assertEqual(len(self.draws(g)),1)
                    elif original==TOWER:self.assertEqual(self.count(g,cards.GHOUL),2)
                    else:self.assertEqual(self.count(g,cards.STINGER,zone='hand'),1)

    def test_d_shield_prevention_does_not_count_as_actual_damage(self):
        for original in (PAIN,TOWER,WASP):
            cid=AssembleRecipe(original,original,'bottom').card_id
            g=self.game((SHIELD,PING),(cid,));source=self.eid(g,cid)
            self.play(g,SHIELD,source);self.play(g,PING,source)
            self.assertEqual(g.state.entities[source].damage,0)
            self.assertEqual(len(self.draws(g)),0);self.assertEqual(self.count(g,cards.GHOUL),0)
            self.assertEqual(self.count(g,cards.STINGER,zone='hand'),0)

    def test_e_tower_uses_capacity_and_native_charge_ghoul_end_lifecycle(self):
        cid=AssembleRecipe(TOWER,TOWER,'bottom').card_id
        g=self.game((PING,),(cid,));self.play(g,PING,self.eid(g,cid))
        ghoul=self.eid(g,cards.GHOUL);self.assertIn(Keyword.CHARGE,g.state.entities[ghoul].keywords)
        g.apply(EndTurn(1));self.assertEqual(self.count(g,cards.GHOUL),0)
        g=self.game((PING,),(cid,N,N,N,N));self.play(g,PING,self.eid(g,cid))
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.count(g,cards.GHOUL),1)

    def test_f_generated_stinger_is_paid_spell_and_summons_exact_original_rush_grub(self):
        cid=AssembleRecipe(WASP,WASP,'bottom').card_id
        g=self.game((PING,),(cid,),enemy=(N,));self.play(g,PING,self.eid(g,cid))
        target=self.eid(g,N,2);mana=g.state.players[1].mana
        self.play(g,cards.STINGER,target)
        self.assertEqual(g.state.players[1].mana,mana-1);self.assertEqual(g.state.entities[target].damage,2)
        grub=g.state.entities[self.eid(g,cards.GRUB)]
        self.assertEqual((grub.attack,grub.health),(2,1));self.assertIn(Keyword.RUSH,grub.keywords)

    def test_g_tortolla_original_and_self_keep_armor_attack_after_positive_and_lethal_damage(self):
        for cid in (TORTOLLA,AssembleRecipe(TORTOLLA,TORTOLLA,'bottom').card_id):
            g=self.game((PING,ZERO,HEAL,LETHAL),(cid,));source=self.eid(g,cid)
            self.play(g,PING,source);self.assertEqual(g.state.entities[source].attack,2)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
            self.play(g,ZERO,source);self.play(g,HEAL,source)
            self.assertEqual(g.state.entities[source].attack,2)
            self.play(g,LETHAL,source)
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)

    def test_h_destroyer_original_and_self_use_actual_own_hero_damage_during_owner_turn(self):
        for cid in (DESTROYER,AssembleRecipe(DESTROYER,DESTROYER,'bottom').card_id):
            for target_player,active,armor in ((1,1,0),(2,1,0),(1,2,0),(1,1,5)):
                g=self.game((PING,),(cid,),enemy=(DUMMY,),enemy_hand=(PING,),active=active,armor=armor)
                target=self.eid(g,DUMMY,2);self.play(g,PING,g.state.players[target_player].hero_id)
                self.assertEqual(g.state.entities[target].damage,3 if target_player==active==1 else 0)
                if armor:self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_i_hourglass_original_and_self_swap_remaining_health_and_attack_only_after_survival(self):
        for cid in (HOURGLASS,AssembleRecipe(HOURGLASS,HOURGLASS,'bottom').card_id):
            g=self.game((PING,PING),(cid,));source=self.eid(g,cid)
            self.play(g,PING,source);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(8,4))
            self.play(g,PING,source);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,8))
            g=self.game((LETHAL,),(cid,));source=self.eid(g,cid);self.play(g,LETHAL,source)
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            self.assertFalse(any(e.kind=='stats_changed' and dict(e.data).get('operation')=='SwapStats'for e in g.events))

    def test_j_borrowed_prefixes_draw_only_and_omit_each_original_subject(self):
        for original in cards.SOURCES:
            cid=AssembleRecipe(original,WAR,'bottom').card_id
            g=self.game((PING,),(cid,),enemy=(DUMMY,));source=self.eid(g,cid)
            self.play(g,PING,g.state.players[1].hero_id if original==DESTROYER else source)
            self.assertEqual(len(self.draws(g)),1)
            self.assertEqual(g.state.entities[source].attack,g.registry.card(original).attack)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
            self.assertEqual(self.count(g,cards.GHOUL),0);self.assertEqual(self.count(g,cards.STINGER,zone='hand'),0)
            self.assertEqual(g.state.entities[self.eid(g,DUMMY,2)].damage,0)

    def test_k_independent_bodies_at_battlecry_do_not_need_original_damage_event(self):
        for suffix in cards.SOURCES:
            cid=AssembleRecipe(CURATOR,suffix,'bottom').card_id
            g=self.game((cid,),enemy=(DUMMY,));target=self.eid(g,DUMMY,2);source=self.play(g,cid)
            if suffix==PREY:self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
            elif suffix==PAIN:self.assertEqual(len(self.draws(g)),1)
            elif suffix==TOWER:self.assertEqual(self.count(g,cards.GHOUL),2)
            elif suffix==WASP:self.assertEqual(self.count(g,cards.STINGER,zone='hand'),1)
            elif suffix==TORTOLLA:
                self.assertEqual(g.state.entities[source].attack,g.registry.card(CURATOR).attack+1)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
            elif suffix==DESTROYER:self.assertEqual(g.state.entities[target].damage,3)
            else:self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),
                (g.registry.card(CURATOR).health,g.registry.card(CURATOR).attack))

    def test_l_independent_natural_death_bodies_deliver_without_reviving_removed_source(self):
        for suffix in cards.SOURCES:
            cid=AssembleRecipe(LOOT,suffix,'bottom').card_id
            g=self.game((cid,KILL),enemy=(DUMMY,));target=self.eid(g,DUMMY,2)
            source=self.play(g,cid);self.play(g,KILL,source)
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            if suffix==PREY:self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
            elif suffix==PAIN:self.assertEqual(len(self.draws(g)),1)
            elif suffix==TOWER:self.assertEqual(self.count(g,cards.GHOUL),2)
            elif suffix==WASP:self.assertEqual(self.count(g,cards.STINGER,zone='hand'),1)
            elif suffix==TORTOLLA:self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
            elif suffix==DESTROYER:self.assertEqual(g.state.entities[target].damage,3)
            else:self.assertFalse(any(e.kind=='stats_changed'and e.target_id==source for e in g.events))

    def test_m_end_start_borrowed_subjects_keep_shared_effect_execution(self):
        cid=AssembleRecipe(END,TORTOLLA,'bottom').card_id
        g=self.game(board=(cid,));source=self.eid(g,cid);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[source].attack,g.registry.card(END).attack+1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        cid=AssembleRecipe(START,HOURGLASS,'bottom').card_id
        g=self.game(board=(cid,));source=self.eid(g,cid);g.apply(EndTurn(1));g.apply(EndTurn(2))
        changed=next(e for e in g.events if e.kind=='stats_changed'and e.target_id==source
            and dict(e.data).get('operation')=='SwapStats')
        self.assertEqual((dict(changed.data)['attack'],dict(changed.data)['health']),(7,0))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_n_prey_keeps_captured_candidates_when_earlier_observer_summons_new_enemy(self):
        for cid in (PREY,AssembleRecipe(PREY,PREY,'bottom').card_id):
            g=self.game((PING,),(PRE,cid),enemy=(N,));target=self.eid(g,N,2);source=self.eid(g,cid)
            self.play(g,PING,source)
            choices=[e for e in g.events if e.kind=='random_choice'and e.source_id==source]
            self.assertEqual(len(choices),1);self.assertEqual(dict(choices[0].data)['candidates'],(target,))
            self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
            self.assertEqual(self.count(g,DUMMY,2),1)

    def test_o_real_damage_draw_wait_restores_replays_rolls_back_bad_choice_and_hides_private_work(self):
        cid=AssembleRecipe(TOWER,WAR,'bottom').card_id
        g=self.game((PING,),(cid,WATCH));self.play(g,PING,self.eid(g,cid))
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K427 deliberate'):self.pick(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.pick(g,'go');self.pick(other,'go');self.assertEqual(g.snapshot(),other.snapshot())

    def test_p_real_mismatch_offer_uses_pain_prefix_stinger_subject_and_original_cost(self):
        cid=AssembleRecipe(PAIN,WASP,'bottom').card_id
        g=self.game((MISMATCH,PING),mode='assemble',hero='HERO_10');self.play(g,MISMATCH)
        self.pick(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
        mana=g.state.players[1].mana;source=self.play(g,cid)
        self.assertEqual(g.state.players[1].mana,mana-3);self.play(g,PING,source)
        self.assertEqual(self.count(g,cards.STINGER,zone='hand'),1);self.assertEqual(len(self.draws(g)),0)

    def test_q_unknown_eligible_context_refuses_whole_offer_without_pruning_or_spending(self):
        g=self.game((MISMATCH,),mode='unsupported',hero='HERO_10');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'explicitly unimplemented'):self.play(g,MISMATCH)
        self.assertEqual(g.snapshot(),saved)

    def test_r_wrong_event_or_missing_settled_result_cannot_supply_native_condition(self):
        g=self.game(board=(PAIN,));source=self.eid(g,PAIN)
        for key in ('self_damage','self_health_damage','own_hero_damage_own_turn','surviving_self_damage'):
            with self.assertRaises(ResolutionError):
                g.registry.trigger_condition(cards.PREFIX+key)(RuleContext(g.state,source,1))

    def test_s_full_source_dependency_and_economy_step_drift_reject_before_partial_installation(self):
        with patch('hs_sim.cards.assemble_damage_health_followups.register_assemble_damage_health_followups',lambda r:None):r=build_registry()
        before=r.fingerprint()
        for cid in (PREY,cards.GRUB):
            old=r._cards[cid];r._cards[cid]=replace(old,health=old.health+1)
            with self.assertRaises(TargetValidationError):cards.register_assemble_damage_health_followups(r)
            self.assertFalse(any(cid in r.assemble_templates for cid in cards.SOURCES));r._cards[cid]=old
        f=r.behavior(r.card(PAIN).triggers[0].behavior_id);defaults=f.__defaults__
        f.__defaults__=((replace(defaults[0][0],amount=2),),*defaults[1:])
        with self.assertRaisesRegex(TargetValidationError,'economy steps'):cards.register_assemble_damage_health_followups(r)
        self.assertFalse(any(cid in r.assemble_templates for cid in cards.SOURCES))
        f.__defaults__=defaults;self.assertEqual(r.fingerprint(),before)
