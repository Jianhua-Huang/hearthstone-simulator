"""Actual native copies/removals/entries and echoed bodies with real damage sources."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import titan_copy_echo as native
from hs_sim.engine import (CardClass,CardDefinition,CardType,Game,IllegalAction,Keyword,
    PlayerSetup,ResolutionError,Scenario,SelectChoice,TriggerSpec,UseMinionAbility)
from hs_sim.engine.effects import ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice
from hs_sim.engine.model import CardMetadata,Rarity,TargetSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k613.'
UNIT,BIG,NOOP,WOUND,WATCH,FAIL,POISON,LIFE=(P+x for x in('unit','big','noop','wound','watch','fail','poison','life'))
LEGENDS=tuple(P+'legend'+str(i)for i in range(3));SIXES=(P+'six0',P+'six1');UNKNOWN=P+'unknown'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def context():return GenerationContext(P+'complete-explicit','experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry();r.register_behavior(NOOP,lambda c:())
    for cid,cost,attack,health,keywords,meta in(
            (UNIT,4,2,7,(),META),(BIG,8,1,50,(),META),
            (POISON,2,1,7,(Keyword.POISONOUS,),META),(LIFE,2,1,7,(Keyword.LIFESTEAL,),META),
            *tuple((cid,3+i,2,5,(),replace(META,rarity=Rarity.LEGENDARY,classes=(klass,)))for i,(cid,klass)in enumerate(zip(LEGENDS,(CardClass.NEUTRAL,CardClass.WARRIOR,CardClass.DRUID)))),
            *tuple((cid,6,4,8,(),META)for cid in SIXES)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,keywords=keywords,
            spell_damage=5 if cid==LIFE else 0,metadata=meta))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,on_play=NOOP))
    r.register_behavior(WOUND,lambda c:(Damage(c.target_id,10,c.source_id),))
    r.register_card(CardDefinition(WOUND,WOUND,CardType.SPELL,on_play=WOUND,targeting=TargetSpec()))
    def fail(c):raise ResolutionError('K613 deliberate continuation failure')
    r.register_behavior(FAIL,fail)
    def watch(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id not in native.ROOTS:return ()
        return(RequestChoice(c.event.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('kill','Destroy original',(Destroy(c.event.source_id,c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('minion_ability_started',WATCH),)))
    members=(*LEGENDS,*SIXES,UNIT,native.AMAN,native.VOLTRON)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,5,replace(META,rarity=Rarity.LEGENDARY)));members=(*members,UNKNOWN)
    r.register_pool(PoolDefinition(native.POOL,P+'full-v1',context().target_id,'experimental',tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


class TitanCopyEchoTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_board=(),deck=(NOOP,)*4,player=1,mode='normal',seed=613):
        self.mode=mode
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else (),board=board if p==player else enemy_board,
            deck=deck if p==player else (NOOP,)*4,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=seed,generation_context=context()),registry(mode))

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def use(self,g,cid,skill,target=None,player=1):
        source=self.entity(g,cid,player,'board').id;mana=g.state.players[player].mana;casts=len(g.state.cast_history)
        g.apply(UseMinionAbility(player,source,skill,target));self.assertEqual(g.state.players[player].mana,mana)
        self.assertEqual(len(g.state.cast_history),casts);return source

    def discover(self,g):
        choice=g.state.pending_choice;self.assertIsNotNone(choice)
        self.assertEqual({o.card_id for o in choice.options},set(LEGENDS));self.choose(g,choice.options[0].id)

    def test_eight_original_faces_six_descriptors_and_sixteen_full_primary_observations(self):
        d=native.load_batch();rows={r['record']['id']:r for key in('cards','dependencies')for r in d[key]}
        self.assertEqual((len(rows),len(d['official_observations'])),(8,16))
        for o in d['official_observations']:batch.check_face(rows[o['card_id']]['record'],o['face'],o['locale'],numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        for cid in native.SKILLS:
            c=registry().card(cid);self.assertTrue(c.choice_only);self.assertFalse(c.hand_playable);self.assertNotIn(cid,registry().pool_cards)
            self.assertEqual(c.cost,0);self.assertIsNone(rows[cid]['record']['cost'])
        self.assertIn('Clay Howell',d['rule_sources'][0]['author']);self.assertFalse(d['cn_calibrated'])
        self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(d['new_token_ids'])

    def test_paid_aman_copies_either_side_with_plus_two_and_discovers_all_classes_both_seats(self):
        for player in(1,2):
            for own in(True,False):
                g=self.game((native.AMAN,),board=(UNIT,)if own else(),enemy_board=()if own else(UNIT,),player=player)
                self.play(g,native.AMAN,player=player);self.assertEqual(g.state.players[player].mana,23)
                target=self.entity(g,UNIT,player if own else 3-player,'board').id
                self.use(g,native.AMAN,native.AMAN_SKILLS[0],target,player);self.discover(g)
                copies=[g.state.entities[i]for i in g.state.players[player].board if g.state.entities[i].card_id==UNIT and i!=target]
                self.assertEqual(len(copies),1);self.assertEqual((copies[0].attack,copies[0].health),(4,9))
                self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(2,7))

    def test_copy_rejects_titans_heroes_and_missing_target_without_spending_action(self):
        g=self.game(board=(native.AMAN,),enemy_board=(native.VOLTRON,));source=self.entity(g,native.AMAN,zone='board').id;before=g.snapshot()
        for target in(None,source,self.entity(g,native.VOLTRON,2,'board').id,self.hero(g,2).id):
            with self.assertRaises(IllegalAction):g.apply(UseMinionAbility(1,source,native.AMAN_SKILLS[0],target))
            self.assertEqual(g.snapshot(),before)

    def test_full_board_copy_creates_nothing_but_still_finishes_and_discovers(self):
        g=self.game(board=(native.AMAN,)+(UNIT,)*6);before=g.state.next_entity_id
        self.use(g,native.AMAN,native.AMAN_SKILLS[0],self.entity(g,UNIT,zone='board').id)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.next_entity_id,before)
        self.discover(g);self.assertEqual(g.state.next_entity_id,before+1)

    def test_two_distinct_original_enemies_are_removed_together_without_death_or_reborn(self):
        g=self.game(board=(native.AMAN,),enemy_board=('TTN_737t2',UNIT,BIG));self.use(g,native.AMAN,native.AMAN_SKILLS[1])
        choice=g.state.pending_choice;self.assertEqual((choice.min_count,choice.max_count),(2,2))
        selected=choice.options[:2];original=g.snapshot();self.portable(g)
        with self.assertRaises(ValueError):g.apply(SelectChoice(1,choice.id,(selected[0].id,selected[0].id)))
        self.assertEqual(g.snapshot(),original)
        g.apply(SelectChoice(1,choice.id,tuple(o.id for o in selected)))
        self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(len(g.state.death_history),0)
        for item in selected:self.assertEqual(g.state.entities[item.entity_id].zone,Zone.SETASIDE)
        self.discover(g);self.portable(g)

    def test_remove_one_or_empty_enemy_board_preserves_after_skill_discovery(self):
        for enemy in((),(UNIT,)):
            g=self.game(board=(native.AMAN,),enemy_board=enemy);self.use(g,native.AMAN,native.AMAN_SKILLS[1])
            if enemy:
                self.assertEqual(g.state.pending_choice.min_count,1);self.choose(g,g.state.pending_choice.options[0].id)
            self.discover(g);self.assertFalse(g.state.players[2].board)

    def test_six_cost_summon_uses_complete_domain_and_pre_entry_taunt_lifesteal(self):
        g=self.game(board=(native.AMAN,));self.use(g,native.AMAN,native.AMAN_SKILLS[2])
        summoned=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id in SIXES]
        self.assertEqual(len(summoned),1);self.assertTrue({Keyword.TAUNT,Keyword.LIFESTEAL}<=summoned[0].keywords)
        self.assertEqual(summoned[0].attack,4);self.discover(g);self.portable(g)

    def test_unknown_eligible_legendary_rolls_back_copy_allocation_choice_rng_and_usage(self):
        g=self.game(board=(native.AMAN,UNIT),mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g,native.AMAN,native.AMAN_SKILLS[0],self.entity(g,UNIT,zone='board').id)
        self.assertEqual(g.snapshot(),before)

    def test_aman_two_arrow_and_later_discovery_waits_restore_without_reselecting_originals(self):
        g=self.game(board=(native.AMAN,),enemy_board=(UNIT,BIG));self.use(g,native.AMAN,native.AMAN_SKILLS[1])
        other=self.portable(g);choice=g.state.pending_choice;keys=tuple(o.id for o in choice.options)
        for game in(g,other):game.apply(SelectChoice(1,choice.id,keys))
        self.assertEqual(g.snapshot(),other.snapshot());other=self.portable(g)
        key=g.state.pending_choice.options[0].id;self.choose(g,key);self.choose(other,key);self.assertEqual(g.snapshot(),other.snapshot())

    def test_paid_voltron_draw_executes_two_complete_bodies_and_only_one_native_action_both_seats(self):
        for p in(1,2):
            g=self.game((native.VOLTRON,),board=(UNIT,),player=p);self.play(g,native.VOLTRON,player=p)
            source=self.use(g,native.VOLTRON,native.VOLTRON_SKILLS[1],player=p)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,7))
            self.assertEqual((self.entity(g,UNIT,p,'board').attack,self.entity(g,UNIT,p,'board').health),(3,9))
            self.assertEqual(len(g.state.players[p].hand),2);self.assertEqual(g.state.entities[source].attacks_this_turn,1)
            self.assertEqual(self.entity(g,UNIT,p,'board').attacks_this_turn,0)
            self.assertEqual(len([e for e in g.events if e.kind=='minion_ability_used']),1);self.assertEqual(g.state.players[p].mana,24)

    def test_alone_voltron_does_not_invent_echo_or_consume_rng_for_draw_and_elusive(self):
        for skill in native.VOLTRON_SKILLS[1:]:
            g=self.game(board=(native.VOLTRON,));rng=g.snapshot()['rng_state'];self.use(g,native.VOLTRON,skill)
            self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(any(e.kind=='random_choice'for e in g.events))
            self.assertEqual(len(g.state.players[1].hand),1 if skill==native.VOLTRON_SKILLS[1]else 0)

    def test_elusive_and_health_repeat_on_exactly_one_other_friendly_receiver(self):
        g=self.game(board=(UNIT,native.VOLTRON,BIG),enemy_board=(UNIT,));self.use(g,native.VOLTRON,native.VOLTRON_SKILLS[2])
        source=self.entity(g,native.VOLTRON,zone='board');self.assertEqual(source.health,8);self.assertIn(Keyword.ELUSIVE,source.keywords)
        others=[g.state.entities[i]for i in g.state.players[1].board if i!=source.id]
        self.assertEqual(sum(Keyword.ELUSIVE in e.keywords for e in others),1);self.assertNotIn(Keyword.ELUSIVE,self.entity(g,UNIT,2,'board').keywords)
        event=next(e for e in g.events if e.kind=='random_choice'and dict(e.data).get('producer')=='effect_branch')
        self.assertEqual(set(dict(event.data)['candidates']),{str(e.id)for e in others});self.portable(g)

    def test_cannons_echo_damage_is_from_receiver_and_uses_its_poisonous(self):
        g=self.game(board=(native.VOLTRON,POISON),enemy_board=(BIG,),seed=1)
        receiver=self.entity(g,POISON,zone='board').id;victim=self.entity(g,BIG,2,'board').id
        self.use(g,native.VOLTRON,native.VOLTRON_SKILLS[0]);self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD)
        self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==receiver and e.target_id==victim and e.amount==4 for e in g.events))
        self.assertEqual((g.state.entities[receiver].attack,g.state.entities[receiver].health),(3,8));self.portable(g)

    def test_cannons_echo_lifesteal_uses_receiver_owner_and_native_damage_not_spell_bonus(self):
        g=self.game((WOUND,),board=(native.VOLTRON,LIFE),enemy_board=(BIG,));self.play(g,WOUND,self.hero(g).id)
        receiver=self.entity(g,LIFE,zone='board').id;self.use(g,native.VOLTRON,native.VOLTRON_SKILLS[0])
        self.assertEqual(self.hero(g).health,24)
        self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==receiver and e.amount==4 for e in g.events));self.portable(g)

    def test_voltron_wait_preserves_whole_accepted_echo_and_failed_resume_does_not_spend_rng_or_action_again(self):
        g=self.game((native.VOLTRON,),board=(UNIT,WATCH));self.play(g,native.VOLTRON)
        source=self.use(g,native.VOLTRON,native.VOLTRON_SKILLS[1]);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K613 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].hand),2)
        self.assertEqual(g.state.entities[source].attacks_this_turn,1);self.portable(g)

    def test_accepted_draw_echo_continues_under_recorded_local_policy_after_original_source_death(self):
        g=self.game(board=(native.VOLTRON,UNIT,WATCH));source=self.use(g,native.VOLTRON,native.VOLTRON_SKILLS[1]);self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].hand),2);self.portable(g)

    def test_actual_full_local_host_all_six_skills_have_closed_candidate_definitions_and_restore(self):
        fmt=build_cn37_local_pool_format()
        for cid,skills in((native.AMAN,native.AMAN_SKILLS),(native.VOLTRON,native.VOLTRON_SKILLS)):
            for skill in skills:
                g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),board=('TTN_737t2',),deck=('CORE_EX1_028',)*3,mana=10,max_mana=10),
                    PlayerSetup('HERO_08',board=('TTN_737t2',))),seed=613,generation_context=fmt.context),fmt.registry)
                source=self.play(g,cid);target=self.entity(g,'TTN_737t2',2,'board').id if skill==native.AMAN_SKILLS[0]else None
                g.apply(UseMinionAbility(1,source,skill,target))
                while g.state.pending_choice:
                    saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,fmt.registry).snapshot(),saved)
                    choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,tuple(o.id for o in choice.options[:choice.min_count])))
                self.assertFalse(g.state.cast_history);self.assertEqual(Game.from_snapshot(g.snapshot(),fmt.registry).snapshot(),g.snapshot())
        for query in(native.SIXES,native.LEGENDS):
            pool=resolve_candidates(fmt.registry,fmt.context,native.POOL,query,current_class=CardClass.MAGE,source_card_id=native.AMAN,player_id=1)
            self.assertTrue(pool);self.assertTrue(all(p.card_id in fmt.registry.cards for p in pool))

    def test_player_boundary_hides_original_removal_keys_frames_and_echo_rng(self):
        g=self.game(board=(native.AMAN,),enemy_board=(UNIT,BIG));self.use(g,native.AMAN,native.AMAN_SKILLS[1])
        for p in(1,2):
            raw=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('zone_epoch','entered_order','resolution_frame','rng_state','target_facts'):self.assertNotIn('"'+key+'"',raw)
        self.portable(g)

    def test_bad_final_face_cannot_half_register_any_native_card_or_target_rule(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.titan_copy_echo.register_titan_copy_echo',lambda r:None)
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['type']='MINION';before=r.fingerprint()
        with patch.object(native,'load_batch',lambda:data),self.assertRaises(TargetValidationError):native.register_titan_copy_echo(r)
        self.assertEqual(r.fingerprint(),before)


if __name__=='__main__':unittest.main()
