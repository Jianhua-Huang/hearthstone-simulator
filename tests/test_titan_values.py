"""Native Titan values use shared damage/healing, prices, caps and physical draws."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json,unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import titan_values as native
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,
    PlayerSetup,ResolutionError,Scenario,TriggerSpec,UseMinionAbility)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,
    InvokeBehavior,RequestChoice,Silence)
from hs_sim.engine.model import DamageKind,TargetSpec,Zone
from hs_sim.engine.minion_abilities import remaining_abilities
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k612.'
UNIT,BIG,NOOP,WOUND,AOE,MANY,SILENCE,CONTROL,WATCH,FAIL,POWER=(P+x for x in
    ('unit','big','noop','wound','aoe','many','silence','control','watch','fail','power'))
FROST='CS2_024'


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry();r.register_behavior(NOOP,lambda c:())
    for cid,cost,attack,health in((UNIT,4,4,10),(BIG,8,8,50),(POWER,1,1,5)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,spell_damage=5 if cid==POWER else 0))
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,cost=5,on_play=NOOP))
    scripts={WOUND:lambda c:(Damage(c.target_id,6,c.source_id),),
        AOE:lambda c:(DamageBatch(tuple(Damage(i,6,c.source_id)for i in c.state.players[c.player_id].board)),),
        MANY:lambda c:(DamageBatch(tuple(Damage(c.target_id,6,c.source_id)for _ in range(3))),),
        SILENCE:lambda c:(Silence(c.target_id),),CONTROL:lambda c:(ChangeControl(c.target_id,3-c.player_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        extra={}if cid==AOE else {'targeting':TargetSpec()if cid==WOUND else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}
        r.register_card(CardDefinition(cid,cid,CardType.MINION if cid in(SILENCE,CONTROL)else CardType.SPELL,
            **({'battlecry':cid,'health':1}if cid in(SILENCE,CONTROL)else{'on_play':cid}),**extra))
    def fault(c):raise ResolutionError('K612 deliberate native failure')
    r.register_behavior(FAIL,fault)
    def watch(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id not in native.ROOTS:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('kill','Destroy original',(Destroy(c.event.source_id,c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('minion_ability_started',WATCH),)))
    r.validate();return r


class TitanValueTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_board=(),deck=(),player=1):
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else (),board=board if p==player else enemy_board,
            deck=deck if p==player else (),mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=612),registry())

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def use(self,g,cid,skill,target=None,player=1):
        e=self.entity(g,cid,player,'board');mana=g.state.players[player].mana;casts=len(g.state.cast_history)
        g.apply(UseMinionAbility(player,e.id,skill,target));self.assertEqual(g.state.players[player].mana,mana)
        self.assertEqual(len(g.state.cast_history),casts);return e.id

    def test_eight_complete_rows_six_skills_sixteen_primary_faces_and_all98_original_overload_facts(self):
        d=native.load_batch();rows={r['record']['id']:r for key in('cards','dependencies')for r in d[key]}
        self.assertEqual((len(rows),len(d['official_observations'])),(8,16))
        for o in d['official_observations']:batch.check_face(rows[o['card_id']]['record'],o['face'],o['locale'],numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        for cid in native.SKILLS:
            card=registry().card(cid);self.assertTrue(card.choice_only);self.assertFalse(card.hand_playable);self.assertNotIn(cid,registry().pool_cards)
            self.assertIsNone(rows[cid]['record']['cost']);self.assertEqual(card.cost,0)
        facts=native.overload_facts();self.assertEqual(len(facts['printed_overload_ids']),98)
        self.assertTrue(all(r['record']['tags']['OVERLOAD']>0 for r in facts['evidence_only']))
        self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(d['new_token_ids']);self.assertFalse(d['source_scope_bound'])

    def test_paid_golganneth_first_spell_price_is_live_and_only_first_hand_admission_each_turn_both_seats(self):
        for p in(1,2):
            g=self.game((native.GOLG,FROST,FROST),player=p);self.play(g,native.GOLG,player=p)
            self.assertEqual(g.state.players[p].mana,24);self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FROST,p)).amount,0)
            self.play(g,FROST,self.hero(g,3-p).id,p);self.assertEqual(self.hero(g,3-p).health,27)
            self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FROST,p)).amount,2)
            g.apply(EndTurn(p));g.apply(EndTurn(3-p));self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FROST,p)).amount,0)

    def test_spells_before_golganneth_entry_are_not_refunded_and_nonspell_source_removal_refreshes_quote(self):
        g=self.game((FROST,native.GOLG,FROST));self.play(g,FROST,self.hero(g,2).id);self.play(g,native.GOLG)
        self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FROST)).amount,2)
        g=self.game((SILENCE,FROST),board=(native.GOLG,));self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FROST)).amount,0)
        self.play(g,SILENCE,self.entity(g,native.GOLG,zone='board').id)
        self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FROST)).amount,2)

    def test_storm_damages_all_enemies_and_heals_friendly_hero_and_minions_without_spell_damage(self):
        g=self.game((WOUND,WOUND,WOUND),board=(native.GOLG,UNIT,POWER),enemy_board=(UNIT,))
        for target in(self.hero(g).id,self.entity(g,native.GOLG,zone='board').id,self.entity(g,UNIT,zone='board').id):self.play(g,WOUND,target)
        self.use(g,native.GOLG,native.GOLG_SKILLS[0]);self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,27))
        self.assertEqual(self.entity(g,UNIT,zone='board').health,10);self.assertEqual(self.entity(g,native.GOLG,zone='board').health,7)
        self.assertEqual(self.entity(g,UNIT,2,'board').health,7);self.portable(g)

    def test_twenty_damage_can_target_another_friendly_or_enemy_minion_and_ignores_spell_damage(self):
        for p in(1,2):
            g=self.game(board=(native.GOLG,BIG,POWER),enemy_board=(BIG,));target=self.entity(g,BIG,p,'board').id
            self.use(g,native.GOLG,native.GOLG_SKILLS[1],target);self.assertEqual(g.state.entities[target].health,30)
        g=self.game(board=(native.GOLG,));source=self.entity(g,native.GOLG,zone='board').id;before=g.snapshot()
        for target in(None,source,self.hero(g,2).id):
            with self.assertRaises(IllegalAction):g.apply(UseMinionAbility(1,source,native.GOLG_SKILLS[1],target))
            self.assertEqual(g.snapshot(),before)

    def test_overload_tutor_moves_three_original_physical_cards_and_skips_nonmatching_without_fatigue(self):
        ids=tuple(cid for cid in native.overload_facts()['printed_overload_ids']if cid in registry().cards)[:3]
        self.assertEqual(len(ids),3);g=self.game(board=(native.GOLG,),deck=(NOOP,)+ids)
        original={i for i in g.state.players[1].deck if g.state.entities[i].card_id in ids};self.use(g,native.GOLG,native.GOLG_SKILLS[2])
        self.assertEqual(set(g.state.players[1].hand),original);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[NOOP])
        self.assertEqual(self.hero(g).health,30);self.portable(g)
        g=self.game(board=(native.GOLG,),deck=(NOOP,));rng=g.snapshot()['rng_state'];self.use(g,native.GOLG,native.GOLG_SKILLS[2])
        self.assertFalse(g.state.players[1].hand);self.assertEqual(self.hero(g).health,30);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_paid_amitus_caps_own_and_friendly_minion_packets_but_not_heroes_or_enemies_both_seats(self):
        for p in(1,2):
            g=self.game((native.AMITUS,WOUND,WOUND,WOUND,WOUND),board=(UNIT,),enemy_board=(UNIT,),player=p)
            source=self.play(g,native.AMITUS,player=p);self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)
            self.assertEqual(g.state.players[p].mana,23)
            for target in(source,self.entity(g,UNIT,p,'board').id,self.entity(g,UNIT,3-p,'board').id,self.hero(g,p).id):self.play(g,WOUND,target,p)
            self.assertEqual(g.state.entities[source].health,6);self.assertEqual(self.entity(g,UNIT,p,'board').health,8)
            self.assertEqual(self.entity(g,UNIT,3-p,'board').health,4);self.assertEqual(self.hero(g,p).health,24)

    def test_amitus_caps_each_packet_and_atomic_aoe_keeps_original_cap_when_source_dies(self):
        g=self.game((MANY,),board=(native.AMITUS,UNIT));self.play(g,MANY,self.entity(g,UNIT,zone='board').id)
        self.assertEqual(self.entity(g,UNIT,zone='board').health,4)
        g=self.game((WOUND,)*4+(AOE,),board=(native.AMITUS,UNIT));source=self.entity(g,native.AMITUS,zone='board').id
        for _ in range(3):self.play(g,WOUND,source)
        self.assertEqual(g.state.entities[source].health,2);self.play(g,AOE)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.entity(g,UNIT,zone='board').health,8)
        self.play(g,WOUND,self.entity(g,UNIT,zone='board').id);self.assertEqual(self.entity(g,UNIT,zone='board').health,2);self.portable(g)

    def test_amitus_silence_or_control_refreshes_live_packet_recipients(self):
        g=self.game((SILENCE,WOUND),board=(native.AMITUS,UNIT));self.play(g,SILENCE,self.entity(g,native.AMITUS,zone='board').id)
        self.play(g,WOUND,self.entity(g,UNIT,zone='board').id);self.assertEqual(self.entity(g,UNIT,zone='board').health,4)
        g=self.game((CONTROL,WOUND,WOUND),board=(native.AMITUS,UNIT),enemy_board=(UNIT,));self.play(g,CONTROL,self.entity(g,native.AMITUS,zone='board').id)
        self.play(g,WOUND,self.entity(g,UNIT,zone='board').id);self.play(g,WOUND,self.entity(g,UNIT,2,'board').id)
        self.assertEqual((self.entity(g,UNIT,zone='board').health,self.entity(g,UNIT,2,'board').health),(4,8))

    def test_reinforcement_draws_two_original_minions_sets_stats_and_cost_then_real_payment(self):
        g=self.game(board=(native.AMITUS,),deck=(NOOP,UNIT,BIG));original={i for i in g.state.players[1].deck if g.state.entities[i].kind==CardType.MINION}
        self.use(g,native.AMITUS,native.AMITUS_SKILLS[0]);self.assertEqual(set(g.state.players[1].hand),original)
        for i in original:
            e=g.state.entities[i];self.assertEqual((e.attack,e.health,quote_cost(g.state,g.registry,e).amount),(2,2,2))
        mana=g.state.players[1].mana;self.play(g,UNIT);self.assertEqual(g.state.players[1].mana,mana-2)
        self.assertEqual((self.entity(g,UNIT,zone='board').attack,self.entity(g,UNIT,zone='board').health),(2,2));self.portable(g)

    def test_reinforcement_empty_or_full_hand_uses_existing_skip_and_burn_policies(self):
        g=self.game(board=(native.AMITUS,),deck=(NOOP,));self.use(g,native.AMITUS,native.AMITUS_SKILLS[0])
        self.assertEqual(self.hero(g).health,30);self.assertFalse(g.state.players[1].hand)
        g=self.game((NOOP,)*10,board=(native.AMITUS,),deck=(UNIT,BIG));self.use(g,native.AMITUS,native.AMITUS_SKILLS[0])
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(g.state.players[1].deck)

    def test_empower_excludes_source_and_enemies_and_peace_clears_damage_to_two(self):
        g=self.game(board=(native.AMITUS,UNIT),enemy_board=(UNIT,));source=self.use(g,native.AMITUS,native.AMITUS_SKILLS[1])
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(1,8))
        self.assertEqual((self.entity(g,UNIT,zone='board').attack,self.entity(g,UNIT,zone='board').health),(6,12))
        self.assertEqual(self.entity(g,UNIT,2,'board').health,10)
        g=self.game((WOUND,),board=(native.AMITUS,UNIT),enemy_board=(UNIT,'CORE_EX1_028'))
        self.play(g,WOUND,self.entity(g,UNIT,2,'board').id);self.use(g,native.AMITUS,native.AMITUS_SKILLS[2])
        for i in g.state.players[2].board:self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(2,2))
        self.assertEqual(self.entity(g,UNIT,zone='board').health,10);self.portable(g)

    def test_native_draw_wait_restores_independently_failed_resume_rolls_back_and_source_death_does_not_cancel_draw(self):
        g=self.game(board=(native.AMITUS,WATCH),deck=(UNIT,BIG));source=self.use(g,native.AMITUS,native.AMITUS_SKILLS[0])
        restored=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K612 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'kill');self.choose(restored,'kill')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),2);self.portable(g)

    def test_complete_real_local_host_paid_titans_can_use_all_six_skills_and_roundtrip(self):
        fmt=build_cn37_local_pool_format()
        for cid,skills in((native.GOLG,native.GOLG_SKILLS),(native.AMITUS,native.AMITUS_SKILLS)):
            for skill in skills:
                g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),deck=('CORE_EX1_028',)*3,mana=10,max_mana=10),
                    PlayerSetup('HERO_08',board=('TTN_737t2',))),seed=612,generation_context=fmt.context),fmt.registry)
                source=self.play(g,cid);target=self.entity(g,'TTN_737t2',2,'board').id if skill==native.GOLG_SKILLS[1]else None
                g.apply(UseMinionAbility(1,source,skill,target));self.assertFalse(g.state.cast_history)
                saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,fmt.registry).snapshot(),saved)

    def test_player_projection_hides_effect_frames_prices_and_captured_physical_draw_material(self):
        g=self.game(board=(native.AMITUS,WATCH),deck=(UNIT,BIG));self.use(g,native.AMITUS,native.AMITUS_SKILLS[0])
        for player in(1,2):
            raw=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())
            for key in('resolution_frame','rng_state','submitted_cost','entered_order','hand_cursor'):self.assertNotIn('"'+key+'"',raw)
        self.choose(g);self.portable(g)

    def test_bad_last_descriptor_fails_preflight_without_partial_registration(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.titan_values.register_titan_values',lambda r:None)
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['type']='MINION';before=r.fingerprint()
        with patch.object(native,'load_batch',lambda:data),self.assertRaises(TargetValidationError):native.register_titan_values(r)
        self.assertEqual(r.fingerprint(),before)


if __name__=='__main__':unittest.main()
