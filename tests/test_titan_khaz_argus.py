"""Real Titan skills, source-relative keyword recipients and actual combat."""
from copy import deepcopy
from dataclasses import asdict,fields,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import titan_khaz_argus as native
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,ResolutionError,Scenario,TriggerSpec,UseMinionAbility)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.keyword_auras import GrantKeywordAura
from hs_sim.engine.minion_abilities import remaining_abilities
from hs_sim.engine.model import CardMetadata,KeywordAuraSpec,Rarity,TargetSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k610.'
PLAIN,OTHER,BIG,WEAPON,SPELL,NOOP,SILENCE,BOUNCE,CONTROL,COPY,WOUND,WAIT,FAIL,LOC,D1,D2,FOREIGN=(
    P+x for x in('plain','other','big','weapon','spell','noop','silence','bounce','control','copy','wound','wait','fail','location','d1','d2','foreign'))
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def context():return GenerationContext(P+'explicit-complete','experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry();r.register_behavior(NOOP,lambda c:())
    for cid,cost,attack,health,meta in((PLAIN,4,2,12,META),(OTHER,1,1,6,META),(BIG,5,3,50,META),
            (D1,5,1,4,replace(META,classes=(CardClass.MAGE,))),(D2,3,1,4,META),
            (FOREIGN,5,1,4,replace(META,classes=(CardClass.PALADIN,)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=meta,
            deathrattle=NOOP if cid in(D1,D2,FOREIGN)else None))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=2,attack=1,durability=2,metadata=META))
    r.register_card(CardDefinition(LOC,LOC,CardType.LOCATION,durability=2,on_use=NOOP))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,cost=5,on_play=NOOP,metadata=META))
    for cid,body in((NOOP,lambda c:()),(SILENCE,lambda c:(Silence(c.target_id),)),
            (BOUNCE,lambda c:(ReturnToHand(c.target_id),)),(CONTROL,lambda c:(ChangeControl(c.target_id,3-c.player_id),)),
            (COPY,lambda c:(CopyMinion(c.target_id,c.player_id),)),(WOUND,lambda c:(Damage(c.target_id,6,c.source_id),))):
        if cid!=NOOP:r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            **({'targeting':TargetSpec()}if cid==WOUND else {'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if cid!=NOOP else {})))
    def fault(c):raise ResolutionError('K610 deliberate ability failure')
    r.register_behavior(P+'fault',fault)
    def watch(c):
        event=c.event
        if event.source_id is None or c.state.entities[event.source_id].card_id!=native.KHAZ:return ()
        if c.source.card_id==FAIL:return(InvokeBehavior(P+'fault',c.source_id,c.player_id),)
        if c.source.card_id==WAIT:return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('kill','Destroy original',(Destroy(event.source_id,c.source_id),)),
            ChoiceOption('fault','Fail',(InvokeBehavior(P+'fault',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    for cid,event in((WAIT,'minion_ability_started'),(FAIL,'minion_ability_used')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,triggers=(TriggerSpec(event,P+'watch'),)))
    r.register_pool(PoolDefinition(native.POOL,P+'whole-v1',context().target_id,'experimental',
        tuple(PoolMember(cid)for cid in(D1,D2,FOREIGN,PLAIN)),complete=True))
    r.validate();return r


class TitanKhazArgusTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_board=(),deck=None,player=1):
        if deck is None:deck=(NOOP,)*5
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else (),board=board if p==player else enemy_board,
            deck=deck if p==player else (NOOP,)*5,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=610,generation_context=context()),registry())

    def use(self,g,cid,skill,player=1):
        entity=self.entity(g,cid,player,'board');mana=g.state.players[player].mana;casts=len(g.state.cast_history)
        g.apply(UseMinionAbility(player,entity.id,skill))
        self.assertEqual(g.state.players[player].mana,mana);self.assertEqual(len(g.state.cast_history),casts)
        return entity.id

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def test_twenty_full_rows_forty_primary_faces_and_six_nonphysical_skills(self):
        d=native.load_batch();rows={r['record']['id']:r for k in('cards','dependencies','existing_dependencies','evidence_only')for r in d[k]}
        self.assertEqual((len(rows),len(d['official_observations'])),(20,40))
        for obs in d['official_observations']:batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'],numeric_normalizations=d['numeric_normalizations'].get(obs['card_id']))
        self.assertEqual(len(d['inventory']['candidate_ids']),12);self.assertEqual(d['inventory']['weights'],[1]*12)
        self.assertFalse(d['inventory']['runtime_bound']);self.assertFalse(d['formal_pool_complete'])
        self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(d['new_token_ids'])
        for cid in native.SKILLS:
            c=registry().card(cid);self.assertTrue(c.choice_only);self.assertFalse(c.hand_playable);self.assertNotIn(cid,registry().pool_cards)
            self.assertIsNone(rows[cid]['record']['cost']);self.assertEqual(c.cost,0)
        for row in d['existing_dependencies']:self.assertEqual(batch.canonical(asdict(registry().card(row['record']['id']))),row['definition_sha256'])

    def test_real_paid_titan_immediately_uses_forge_grows_and_draws_original_weapon_before_immune_combat_both_seats(self):
        for player in(1,2):
            g=self.game((native.KHAZ,),deck=(NOOP,WEAPON),enemy_board=(BIG,),player=player)
            top=next(i for i in g.state.players[player].deck if g.state.entities[i].card_id==WEAPON);mana=g.state.players[player].mana
            source=self.play(g,native.KHAZ,player=player);self.assertEqual(g.state.players[player].mana,mana-6)
            self.use(g,native.KHAZ,native.KHAZ_SKILLS[0],player)
            e=g.state.entities[source];self.assertEqual((e.attack,e.health,e.attacks_this_turn),(6,7,1))
            self.assertIn(top,g.state.players[player].hand);self.assertIn(Keyword.IMMUNE,e.keywords)
            self.assertEqual(self.entity(g,BIG,3-player,'board').health,44)

    def test_temper_gives_permanent_titan_attack_and_temporary_hero_attack(self):
        g=self.game(board=(native.KHAZ,),enemy_board=(BIG,));self.use(g,native.KHAZ,native.KHAZ_SKILLS[1])
        self.assertEqual(self.entity(g,native.KHAZ,zone='board').attack,9);self.assertEqual(self.hero(g).attack,5)
        self.assertEqual(self.entity(g,BIG,2,'board').health,41);g.apply(EndTurn(1));g.apply(EndTurn(2))
        source=self.entity(g,native.KHAZ,zone='board');self.assertEqual(source.attack,9)
        self.assertNotIn(Keyword.IMMUNE,source.keywords);self.assertEqual(self.hero(g).attack,0)

    def test_burning_heart_gives_titan_health_and_hero_armor_without_combat_damage(self):
        g=self.game(board=(native.KHAZ,),enemy_board=(BIG,));self.use(g,native.KHAZ,native.KHAZ_SKILLS[2])
        e=self.entity(g,native.KHAZ,zone='board');self.assertEqual((e.attack,e.health),(4,10));self.assertEqual(self.hero(g).armor,5)
        self.assertEqual(self.entity(g,BIG,2,'board').health,46);self.portable(g)

    def test_empty_enemy_board_keeps_immunity_without_rng_or_fatigue_on_missing_weapon(self):
        g=self.game(board=(native.KHAZ,),deck=());rng=g.snapshot()['rng_state'];self.use(g,native.KHAZ,native.KHAZ_SKILLS[0])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.hero(g).health,30)
        self.assertIn(Keyword.IMMUNE,self.entity(g,native.KHAZ,zone='board').keywords)

    def test_each_skill_consumes_one_titan_action_and_force_attack_never_consumes_second(self):
        g=self.game(board=(native.KHAZ,),enemy_board=(BIG,),deck=(WEAPON,NOOP,NOOP))
        for index,skill in enumerate(native.KHAZ_SKILLS):
            self.use(g,native.KHAZ,skill);e=self.entity(g,native.KHAZ,zone='board')
            self.assertEqual(e.attacks_this_turn,1);self.assertEqual(len(remaining_abilities(e)),2-index)
            if index<2:g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(len([e for e in g.events if e.kind=='attack_declared']),3);self.portable(g)

    def test_ability_wait_preserves_consumed_skill_and_later_combat_without_repay_or_resample(self):
        g=self.game(board=(native.KHAZ,WAIT),enemy_board=(BIG,),deck=(WEAPON,NOOP));self.use(g,native.KHAZ,native.KHAZ_SKILLS[0])
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.entity(g,native.KHAZ,zone='board').attack,4)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K610 deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.entity(g,BIG,2,'board').health,44)

    def test_original_dies_before_skill_body_draw_still_finishes_but_no_after_ability_combat(self):
        g=self.game(board=(native.KHAZ,WAIT),enemy_board=(BIG,),deck=(WEAPON,));self.use(g,native.KHAZ,native.KHAZ_SKILLS[0])
        self.choose(g,'kill');self.assertFalse(any(g.state.entities[i].card_id==native.KHAZ for i in g.state.players[1].board))
        self.assertEqual(self.entity(g,BIG,2,'board').health,50);self.assertEqual(len(g.state.players[1].hand),1)

    def test_after_ability_failure_rolls_back_skill_growth_draw_combat_rng_and_consumption(self):
        g=self.game(board=(native.KHAZ,FAIL),enemy_board=(BIG,),deck=(WEAPON,));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K610 deliberate'):self.use(g,native.KHAZ,native.KHAZ_SKILLS[0])
        self.assertEqual(g.snapshot(),before)

    def test_argus_grants_all_minions_on_each_physical_side_and_spans_locations(self):
        g=self.game(board=(PLAIN,OTHER,native.ARGUS,LOC,PLAIN,OTHER),enemy_board=(PLAIN,))
        ids=g.state.players[1].board
        for i in ids[:2]:self.assertIn(Keyword.RUSH,g.state.entities[i].keywords);self.assertNotIn(Keyword.LIFESTEAL,g.state.entities[i].keywords)
        for i in ids[4:]:self.assertIn(Keyword.LIFESTEAL,g.state.entities[i].keywords);self.assertNotIn(Keyword.RUSH,g.state.entities[i].keywords)
        self.assertFalse(g.state.entities[ids[2]].keywords & {Keyword.RUSH,Keyword.LIFESTEAL})
        self.assertNotIn(Keyword.LIFESTEAL,g.state.entities[ids[3]].keywords)
        self.assertFalse(self.entity(g,PLAIN,2,'board').keywords & {Keyword.RUSH,Keyword.LIFESTEAL})

    def test_argus_actual_left_rush_attack_and_right_lifesteal_heal(self):
        g=self.game((PLAIN,WOUND),board=(native.ARGUS,OTHER),enemy_board=(BIG,))
        self.play(g,WOUND,self.hero(g).id);source=self.entity(g,PLAIN).id;g.apply(PlayCard(1,source,position=0))
        g.apply(Attack(1,source,self.entity(g,BIG,2,'board').id))
        self.assertEqual(self.entity(g,BIG,2,'board').health,48)
        g.apply(Attack(1,self.entity(g,OTHER,zone='board').id,self.hero(g,2).id));self.assertEqual(self.hero(g).health,25)

    def test_argus_silence_bounce_and_control_refresh_source_relative_contributions(self):
        for action in(SILENCE,BOUNCE,CONTROL):
            g=self.game((action,),board=(PLAIN,native.ARGUS,OTHER));self.play(g,action,self.entity(g,native.ARGUS,zone='board').id)
            self.assertNotIn(Keyword.RUSH,self.entity(g,PLAIN,zone='board').keywords)
            self.assertNotIn(Keyword.LIFESTEAL,self.entity(g,OTHER,zone='board').keywords)

    def test_argus_copy_preserves_used_abilities_and_contributes_from_its_own_current_position(self):
        g=self.game((COPY,),board=(PLAIN,native.ARGUS,OTHER));self.use(g,native.ARGUS,native.ARGUS_SKILLS[1])
        original=self.entity(g,native.ARGUS,zone='board').id;self.play(g,COPY,original)
        copies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==native.ARGUS]
        self.assertEqual([len(remaining_abilities(e))for e in copies],[2,2])
        self.assertIn(Keyword.RUSH,g.state.entities[original].keywords);self.assertIn(Keyword.LIFESTEAL,copies[1].keywords)
        self.portable(g)

    def test_argus_deathrattle_discovery_keeps_full_current_class_pool_and_discount_through_restore(self):
        g=self.game(board=(native.ARGUS,));self.use(g,native.ARGUS,native.ARGUS_SKILLS[0])
        choice=g.state.pending_choice;self.assertEqual({o.card_id for o in choice.options},{D1,D2})
        other=self.portable(g);option=next(o.id for o in choice.options if o.card_id==D1)
        self.choose(g,option);self.choose(other,option);self.assertEqual(g.snapshot(),other.snapshot())
        e=self.entity(g,D1);self.assertEqual(quote_cost(g.state,g.registry,e).amount,2)
        before=g.state.players[1].mana;self.play(g,D1);self.assertEqual(g.state.players[1].mana,before-2)

    def test_argus_hand_discount_changes_only_actual_minions_and_has_zero_floor(self):
        g=self.game((PLAIN,OTHER,SPELL),board=(native.ARGUS,));self.use(g,native.ARGUS,native.ARGUS_SKILLS[1])
        self.assertEqual([quote_cost(g.state,g.registry,self.entity(g,cid)).amount for cid in(PLAIN,OTHER,SPELL)],[2,0,5])
        self.portable(g)

    def test_argus_army_uses_four_independent_named_summons_and_live_side_auras(self):
        g=self.game(board=(native.ARGUS,));self.use(g,native.ARGUS,native.ARGUS_SKILLS[2])
        children=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==native.TOKEN]
        self.assertEqual(len(children),4);self.assertEqual(len({e.id for e in children}),4)
        self.assertTrue(all((e.attack,e.health)==(2,2)and {Keyword.TAUNT,Keyword.LIFESTEAL}<=e.keywords for e in children))
        roots=g.state.card_summon_history;self.assertEqual(len(roots),4)
        self.assertTrue(all(r.request.cause.source.card_id==native.ARGUS and r.request.cause.origin=='card_effect'for r in roots))
        self.portable(g)

    def test_argus_army_partial_and_full_board_never_overfills_or_requires_extra_slot_to_use(self):
        for count,expected in((4,2),(6,0)):
            g=self.game(board=(native.ARGUS,)+(PLAIN,)*count);self.use(g,native.ARGUS,native.ARGUS_SKILLS[2])
            self.assertEqual(len(g.state.players[1].board),7)
            self.assertEqual(sum(g.state.entities[i].card_id==native.TOKEN for i in g.state.players[1].board),expected)

    def test_relative_aura_declarations_are_finite_native_only_and_keep_original_fields(self):
        self.assertEqual([f.name for f in fields(KeywordAuraSpec)],['keyword','target','include_self','adjacent_only','condition','tribes_any','card_ids'])
        for spec in(native.LEFT,native.RIGHT):
            with self.assertRaises(ValueError):GrantKeywordAura(1,spec)
            for change in({'include_self':True},{'adjacent_only':True},{'condition':'controller_turn'},{'tribes_any':('elemental',)},
                    {'keyword':Keyword.TAUNT},{'card_ids':('x',)}):
                with self.subTest(change=change),self.assertRaises(ValueError):replace(spec,**change)

    def test_new_side_scopes_do_not_leak_original_definitions_rng_or_private_frames_to_player(self):
        g=self.game(board=(PLAIN,native.ARGUS,OTHER));self.portable(g)
        public=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for value in('keyword_aura','native_scope','rng_state','resolution_frame','state_hash'):self.assertNotIn('"'+value+'"',public)

    def test_last_bad_source_cannot_partially_register_cards_metadata_or_behaviors(self):
        d=deepcopy(native.load_batch());d['dependencies'][-1]['record']['collectible']=True
        r=batch.registration_prefix(build_registry,'hs_sim.cards.titan_khaz_argus.register_titan_khaz_argus',native.register_titan_khaz_argus)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=d):
            with self.assertRaises(TargetValidationError):native.register_titan_khaz_argus(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)


if __name__=='__main__':unittest.main()
