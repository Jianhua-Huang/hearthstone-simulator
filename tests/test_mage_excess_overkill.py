"""Actual entries, one source budget, physical blockers and original Overkill."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import mage_excess_overkill as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.adjacent_excess_damage import DamageMinionExcess,prepare_partition
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,InvokeBehavior,RequestChoice,ReturnToHand,Summon)
from hs_sim.engine.health_rules import rule_sources
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,DamageKind,HealthFlow,HealthLayer,
    HealthOp,HealthRule,Keyword,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

ROLLING,COMBUSTION,BLAST=native.LEAVES
P='k628.'
BIG,ONE,TWO,THREE,FOUR,SHIELD,IMMUNE,SLEEP,BONUS,DEATH,REBORN,LOCATION=(P+x for x in
    ('big','one','two','three','four','shield','immune','sleep','bonus','death','reborn','location'))
WAIT,FAIL,NOOP,MAGE1,MAGE2,FOREIGN,NEUTRAL,UNKNOWN,PLAN,STALE=(P+x for x in
    ('wait','fail','noop','mage1','mage2','foreign','neutral','unknown','plan','stale'))
AUTO=tuple(P+'auto_'+str(i) for i in range(3))
CONTEXT=GenerationContext('k628-actual-diagnostic','experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_mage_excess_overkill(r)
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(DEATH,lambda c:(Summon(c.player_id,FOUR),))
    for cid,hp,extra in ((BIG,30,{}),(ONE,1,{}),(TWO,2,{}),(THREE,3,{}),(FOUR,4,{}),
            (SHIELD,2,{'keywords':(Keyword.DIVINE_SHIELD,)}),(IMMUNE,2,{'keywords':(Keyword.IMMUNE,)}),
            (SLEEP,2,{'dormant_turns':2}),(BONUS,30,{'spell_damage':2}),
            (DEATH,2,{'deathrattle':DEATH}),(REBORN,2,{'keywords':(Keyword.REBORN,)})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=hp,
            metadata=metadata(tribes=()),**extra))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=NOOP))
    if mode in ('source_double','target_double','prevent'):
        rule=HealthRule(HealthFlow.DAMAGE,HealthOp.PREVENT if mode=='prevent' else HealthOp.SCALE,
            0 if mode=='prevent' else 2,layer=HealthLayer.SOURCE if mode=='source_double' else HealthLayer.TARGET,
            source_relation='friendly' if mode=='source_double' else 'any',
            target_kinds=(CardType.MINION,),damage_kinds=(DamageKind.SPELL,))
        r.register_card(CardDefinition(P+'rule',P+'rule',CardType.MINION,health=30,health_rules=(rule,),metadata=metadata(tribes=())))
    for cid,cls in ((MAGE1,CardClass.MAGE),(MAGE2,CardClass.MAGE),(FOREIGN,CardClass.WARRIOR),(NEUTRAL,CardClass.NEUTRAL)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=NOOP,metadata=metadata(cls,tribes=())))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    members=[MAGE1,MAGE2,FOREIGN,NEUTRAL]
    if mode=='empty':members=[FOREIGN,NEUTRAL]
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,metadata(CardClass.MAGE,tribes=())))
        members.append(UNKNOWN)
    r.register_pool(PoolDefinition(native.POOL,'k628-entire-fixture-'+mode,CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid) for cid in members),complete=True))
    def fail(c):raise ResolutionError('K628 deliberate continuation failure')
    r.register_behavior(FAIL,fail)
    def choices(c):
        return (ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),)))
    def watch(c):
        event=c.event;source=c.state.entities.get(event.source_id)
        if source is None or source.card_id not in native.LEAVES or event.target_id!=c.state.players[2].board[-1]:return ()
        return (RequestChoice(1,choices(c),c.source_id),)
    r.register_behavior(WAIT,watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=30,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('damage_dealt',WAIT),)))
    for auto,cid in zip(AUTO,native.LEAVES):
        def cast(c,cid=cid):
            target=None if cid==BLAST else c.state.players[2].board[0]
            return (CastSpell(1,cid,c.source_id,target_id=target,targeting='explicit' if target is not None else 'random'),)
        r.register_behavior(auto,cast)
        r.register_card(CardDefinition(auto,auto,CardType.SPELL,on_play=auto,metadata=metadata(tribes=())))
    def plan(c):
        ref=MinionReference.capture(c.state.entities[c.state.players[2].board[0]])
        return (RequestChoice(1,choices(c),c.source_id),DamageMinionExcess(ref,8,c.source_id,'rolling'))
    def stale(c):
        ref=MinionReference.capture(c.state.entities[c.state.players[2].board[0]])
        return (ReturnToHand(ref.entity_id),Summon(2,TWO),DamageMinionExcess(ref,8,c.source_id,'rolling'))
    for cid,body in ((PLAN,plan),(STALE,stale)):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=())))
    r.register_behavior(P+'wound',lambda c:(Damage(c.state.players[2].board[0],1,c.source_id),))
    r.register_card(CardDefinition(P+'wound',P+'wound',CardType.SPELL,on_play=P+'wound',metadata=metadata(tribes=())))
    r.validate();r.freeze();return r


class MageExcessOverkillTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,board=(),enemy=(TWO,FOUR),mode='normal',other_hand=(),seed=628):
        self.mode=mode
        if mode in ('source_double','target_double','prevent'):board=(*board,P+'rule')
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=(BIG,)*10,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(BIG,)*10,mana=10,max_mana=10)),
            seed=seed,generation_context=CONTEXT),registry(mode))
    def ids(self,g):return tuple(g.state.players[2].board)
    def hits(self,g,cid):return [row.health_result for row in g.state.damage_history if row.health_result.source_card_id==cid]
    def generated(self,g):return [g.state.entities[i].card_id for i in g.state.players[1].hand if g.state.entities[i].card_id in (MAGE1,MAGE2)]
    def direction_events(self,g):return [e for e in g.events if e.kind=='random_choice' and dict(e.data).get('reason')=='rolling_excess_direction']

    def test_complete_original_rows_primary_faces_and_raw_script_tags(self):
        d=native.load_batch();rows={x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual((rows[ROLLING]['tags']['349'],rows[COMBUSTION]['tags']['349']),(1,1))
        self.assertEqual(rows[BLAST]['tags']['OVERKILL'],1);self.assertFalse(d['formal_pool_complete'])

    def test_rolling_single_side_consumes_health_shares_in_original_order(self):
        g=self.game((ROLLING,),enemy=(TWO,TWO,FOUR,BIG));ids=self.ids(g);source=self.play(g,ROLLING,ids[0])
        hits=self.hits(g,ROLLING);self.assertEqual([(h.target_id,h.damage_dealt) for h in hits],list(zip(ids[:3],(2,2,4))))
        self.assertEqual(g.state.entities[ids[-1]].damage,0);self.assertEqual(g.state.players[1].mana,5)
        self.assertEqual(g.state.cast_history[0].source_id,source);self.assertFalse(self.direction_events(g));self.portable(g)

    def test_rolling_from_right_edge_only_moves_left(self):
        g=self.game((ROLLING,),enemy=(BIG,TWO,TWO));ids=self.ids(g);self.play(g,ROLLING,ids[-1])
        self.assertEqual([(h.target_id,h.damage_dealt) for h in self.hits(g,ROLLING)],[(ids[2],2),(ids[1],2),(ids[0],4)])

    def test_rolling_two_sides_choose_once_and_never_switch_back(self):
        for seed in (1,2,628):
            g=self.game((ROLLING,),enemy=(BIG,TWO,BIG),seed=seed);ids=self.ids(g);self.play(g,ROLLING,ids[1])
            events=self.direction_events(g);self.assertEqual(len(events),1)
            direction=dict(events[0].data)['selected'];self.assertEqual(tuple(dict(events[0].data)['candidates']),(-1,1))
            self.assertEqual([(h.target_id,h.damage_dealt) for h in self.hits(g,ROLLING)],[(ids[1],2),(ids[1+direction],6)])
            self.portable(g)

    def test_rolling_exact_health_needs_no_direction_or_neighbor_packet(self):
        g=self.game((ROLLING,),enemy=(TWO,BIG,TWO));ids=self.ids(g);self.play(g,ROLLING,ids[1])
        self.assertEqual(len(self.hits(g,ROLLING)),1);self.assertFalse(self.direction_events(g))

    def test_rolling_spell_bonus_enters_total_budget_once(self):
        g=self.game((ROLLING,),board=(BONUS,),enemy=(TWO,FOUR,BIG));ids=self.ids(g);self.play(g,ROLLING,ids[0])
        self.assertEqual([h.damage_dealt for h in self.hits(g,ROLLING)],[2,4,4])

    def test_rolling_divine_shield_consumes_only_original_health_share(self):
        g=self.game((ROLLING,),enemy=(SHIELD,BIG));ids=self.ids(g);self.play(g,ROLLING,ids[0])
        self.assertEqual(g.state.entities[ids[0]].damage,0);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[ids[0]].keywords)
        self.assertEqual(g.state.entities[ids[1]].damage,6)

    def test_rolling_immune_neighbor_consumes_share_without_reallocation(self):
        g=self.game((ROLLING,),enemy=(TWO,IMMUNE,BIG));ids=self.ids(g);self.play(g,ROLLING,ids[0])
        self.assertEqual([h.damage_dealt for h in self.hits(g,ROLLING)],[2,0,4])

    def test_rolling_target_multiplier_does_not_change_remaining_source_budget(self):
        g=self.game((ROLLING,),enemy=(TWO,BIG),mode='target_double');ids=self.ids(g);self.play(g,ROLLING,ids[0])
        self.assertEqual([h.damage_dealt for h in self.hits(g,ROLLING)],[4,12])

    def test_rolling_source_multiplier_scales_one_total_before_partition(self):
        g=self.game((ROLLING,),enemy=(FOUR,BIG),mode='source_double');ids=self.ids(g);self.play(g,ROLLING,ids[0])
        self.assertEqual([h.damage_dealt for h in self.hits(g,ROLLING)],[4,12])

    def test_rolling_dormant_and_location_slots_stop_the_path(self):
        for gap in (SLEEP,LOCATION):
            g=self.game((ROLLING,),enemy=(TWO,gap,BIG));ids=self.ids(g);self.play(g,ROLLING,ids[0])
            self.assertEqual([h.target_id for h in self.hits(g,ROLLING)],[ids[0]])
            self.assertEqual(g.state.entities[ids[2]].damage,0);self.portable(g)

    def test_rolling_never_joins_new_deathrattle_or_reborn_recipients(self):
        for cid in (DEATH,REBORN):
            g=self.game((ROLLING,),enemy=(cid,BIG));ids=self.ids(g);self.play(g,ROLLING,ids[0])
            self.assertEqual([h.target_id for h in self.hits(g,ROLLING)],list(ids))
            new=[i for i in g.state.players[2].board if i not in ids];self.assertEqual(len(new),1)
            self.assertEqual(g.state.entities[new[0]].health,1 if cid==REBORN else 4)

    def test_combustion_center_receives_full_amount_and_both_neighbors_same_excess(self):
        g=self.game((COMBUSTION,),enemy=(BIG,TWO,BIG));ids=self.ids(g);self.play(g,COMBUSTION,ids[1])
        self.assertEqual([(h.target_id,h.damage_dealt) for h in self.hits(g,COMBUSTION)],[(ids[1],4),(ids[0],2),(ids[2],2)])
        self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_combustion_spell_bonus_is_not_added_again_to_each_excess(self):
        g=self.game((COMBUSTION,),board=(BONUS,),enemy=(BIG,TWO,BIG));ids=self.ids(g);self.play(g,COMBUSTION,ids[1])
        self.assertEqual([h.damage_dealt for h in self.hits(g,COMBUSTION)],[6,4,4])

    def test_combustion_exact_health_has_no_zero_neighbor_packet(self):
        g=self.game((COMBUSTION,),enemy=(BIG,FOUR,BIG));ids=self.ids(g);self.play(g,COMBUSTION,ids[1])
        self.assertEqual([h.damage_dealt for h in self.hits(g,COMBUSTION)],[4])

    def test_combustion_center_shield_does_not_erase_original_excess(self):
        g=self.game((COMBUSTION,),enemy=(BIG,SHIELD,BIG));ids=self.ids(g);self.play(g,COMBUSTION,ids[1])
        self.assertEqual([h.damage_dealt for h in self.hits(g,COMBUSTION)],[0,2,2])

    def test_combustion_does_not_jump_illegal_immediate_neighbors(self):
        for gap in (SLEEP,LOCATION):
            g=self.game((COMBUSTION,),enemy=(BIG,gap,ONE,BIG));ids=self.ids(g);self.play(g,COMBUSTION,ids[2])
            self.assertEqual([(h.target_id,h.damage_dealt) for h in self.hits(g,COMBUSTION)],[(ids[2],4),(ids[3],3)])

    def test_spell_targets_reject_heroes_and_dormant_without_payment(self):
        for cid in (ROLLING,COMBUSTION):
            g=self.game((cid,),enemy=(SLEEP,));saved=g.snapshot()
            for target in (g.state.players[2].hero_id,self.ids(g)[0]):
                with self.assertRaises(IllegalAction):self.play(g,cid,target)
                self.assertEqual(g.snapshot(),saved)

    def test_both_targeted_spells_allow_ordinary_friendly_minions(self):
        for cid in (ROLLING,COMBUSTION):
            g=self.game((cid,),board=(TWO,FOUR));target=g.state.players[1].board[0];self.play(g,cid,target)
            self.assertEqual(self.hits(g,cid)[0].target_controller,1)

    def test_partition_preparation_is_pure_and_target_rule_independent(self):
        g=self.game((ROLLING,),enemy=(TWO,BIG),mode='target_double');ids=self.ids(g)
        source=self.entity(g,ROLLING).id;request=DamageMinionExcess(MinionReference.capture(g.state.entities[ids[0]]),8,source,'rolling',1)
        saved=g.snapshot();instructions,packets=prepare_partition(g.state,g.registry,request,rule_sources(g.state))
        self.assertEqual([i.amount for i in instructions],[2,6]);self.assertEqual([p.amount for p in packets],[4,12])
        self.assertEqual(g.snapshot(),saved)

    def test_request_rejects_unknown_policies_and_boolean_directions(self):
        g=self.game((ROLLING,));request=DamageMinionExcess(MinionReference.capture(g.state.entities[self.ids(g)[0]]),8,self.entity(g,ROLLING).id,'rolling')
        for changes in ({'spread':'invented'},{'spread':1},{'direction':True},{'direction':2},{'spread':'neighbors','direction':1},{'amount':True}):
            with self.assertRaises(ValueError):replace(request,**changes)

    def test_stale_original_reference_does_not_rebind_to_a_new_minion(self):
        g=self.game((STALE,),enemy=(TWO,));self.play(g,STALE)
        self.assertFalse(self.hits(g,STALE));self.assertEqual(g.state.entities[self.ids(g)[0]].damage,0);self.portable(g)

    def test_pending_partition_codec_restore_and_failed_choice_rollback(self):
        g=self.game((PLAN,),enemy=(TWO,BIG));self.play(g,PLAN);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual([h.damage_dealt for h in self.hits(g,PLAN)],[2,6]);self.portable(g)

    def test_actual_damage_reaction_wait_restores_after_all_original_packets(self):
        g=self.game((ROLLING,),board=(WAIT,),enemy=(TWO,BIG));ids=self.ids(g);self.play(g,ROLLING,ids[0])
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[ids[1]].damage,6)
        g=self.portable(g);self.choose(g);self.portable(g)

    def test_blast_wave_generates_once_for_each_actual_friendly_or_enemy_overkill(self):
        g=self.game((BLAST,),board=(ONE,),enemy=(ONE,TWO,ONE));self.play(g,BLAST)
        self.assertEqual(len(self.generated(g)),3);self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_blast_wave_shields_immunity_dormancy_and_exact_kills_do_not_count(self):
        g=self.game((BLAST,),enemy=(SHIELD,IMMUNE,SLEEP,TWO));self.play(g,BLAST)
        self.assertEqual(len(self.generated(g)),0);self.assertEqual(len(self.hits(g,BLAST)),3)

    def test_blast_wave_uses_spell_bonus_and_original_current_health(self):
        g=self.game((BLAST,),board=(BONUS,),enemy=(THREE,FOUR));self.play(g,BLAST)
        self.assertEqual(len(self.generated(g)),1);self.assertEqual([h.damage_dealt for h in self.hits(g,BLAST)][-2:],[4,4])

    def test_blast_wave_checks_current_health_after_prior_damage(self):
        g=self.game((P+'wound',BLAST),enemy=(TWO,));self.play(g,P+'wound');self.play(g,BLAST)
        self.assertEqual(len(self.generated(g)),1);self.assertEqual(self.hits(g,BLAST)[0].health_before,1)

    def test_target_prevention_does_not_reallocate_combustion_excess(self):
        g=self.game((COMBUSTION,),enemy=(BIG,TWO,BIG),mode='prevent');ids=self.ids(g);self.play(g,COMBUSTION,ids[1])
        self.assertEqual([h.damage_dealt for h in self.hits(g,COMBUSTION)],[0,0,0]);self.portable(g)

    def test_blast_wave_original_result_reward_survives_damage_reaction_choice(self):
        g=self.game((BLAST,),board=(WAIT,),enemy=(ONE,BIG));self.play(g,BLAST)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertEqual(len(self.generated(g)),1);self.portable(g)

    def test_blast_wave_on_opponents_turn_does_not_trigger_overkill(self):
        g=self.game((),other_hand=(AUTO[2],),enemy=(ONE,));g.apply(EndTurn(1));self.play(g,AUTO[2],player=2)
        self.assertEqual(len(self.generated(g)),0);self.assertEqual(len(self.hits(g,BLAST)),1);self.portable(g)

    def test_blast_wave_never_counts_new_reborn_minions_in_original_batch(self):
        g=self.game((BLAST,),board=(BONUS,),enemy=(REBORN,));self.play(g,BLAST)
        self.assertEqual(len(self.generated(g)),1);self.assertEqual(len(g.state.players[2].board),1)

    def test_blast_wave_full_hand_uses_ordinary_delivery_capacity(self):
        g=self.game((BLAST,)+(NEUTRAL,)*9,enemy=(ONE,ONE,ONE));self.play(g,BLAST)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(self.generated(g)),1)

    def test_blast_wave_empty_complete_mage_domain_does_not_invent_rewards(self):
        g=self.game((BLAST,),enemy=(ONE,),mode='empty');self.play(g,BLAST)
        self.assertFalse(self.generated(g));self.portable(g)

    def test_blast_wave_unknown_eligible_member_reports_unsupported_without_cropping(self):
        g=self.game((BLAST,),enemy=(ONE,),mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError) as error:self.play(g,BLAST)
        self.assertIn('unsupported',str(error.exception).lower());self.assertEqual(g.snapshot(),saved)

    def test_actual_automatic_spell_entries_and_one_cast_per_payload(self):
        for auto,cid in zip(AUTO,native.LEAVES):
            g=self.game((auto,),enemy=(ONE,BIG));self.play(g,auto)
            rows=[c for c in g.state.cast_history if c.card_id==cid];self.assertEqual(len(rows),1)
            self.assertTrue(rows[0].completed);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_complete_local_host_retains_full_past_source_and_real_damage_entries(self):
        fmt=build_cn37_local_pool_format();r=fmt.registry
        body=next(cid for cid,card in r.cards.items() if card.kind==CardType.MINION and card.health>=4 and
            not card.keywords and not card.deathrattle and not card.triggers and not card.interactable and not card.dormant_turns)
        for cid in native.LEAVES:
            self.assertIn(cid,r.cards);self.assertIn(cid,r.pool_cards)
            target='HERO_08';g=Game.from_scenario(Scenario((PlayerSetup(target,hand=(cid,),mana=10,max_mana=10),
                PlayerSetup(target,board=(body,))),generation_context=fmt.context,seed=628),r)
            self.play(g,cid,None if cid==BLAST else g.state.players[2].board[0])
            self.assertTrue(any(c.card_id==cid and c.completed for c in g.state.cast_history))


if __name__=='__main__':unittest.main()
