"""Real Kronn payment, individual minion sources and finite-residence delivery."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.kronn_impaler_card import CARD, load_batch, register_kronn_impaler_card
from hs_sim.engine import (BattlecryRepeatSpec, CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy, Freeze,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.minion_attack_damage import EachMinionDealsAttackDamage
from hs_sim.engine.model import BoardPresenceReference, CardClass, DamageKind, Rarity
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='fixture.kronn.'
A,B,FILL,NEW,MATERIAL,ZERO,POWER,LIFE,VENOM,SHIELD,IMMUNE,STEALTH,SLEEP,BIG,REPEAT,WATCH=(P+x for x in
    ('a','b','fill','new','material','zero','power','life','venom','shield','immune','stealth','sleep','big','repeat','watch'))


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in ('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_kronn_impaler_card(r)
    for cid,attack,health,options in (
            (A,3,20,{}),(B,4,20,{}),(FILL,2,40,{}),(NEW,9,40,{}),(MATERIAL,8,20,{}),
            (ZERO,0,20,{}),(POWER,0,20,dict(spell_damage=9)),
            (LIFE,3,20,dict(keywords=(Keyword.LIFESTEAL,))),
            (VENOM,1,20,dict(keywords=(Keyword.POISONOUS,))),
            (SHIELD,2,40,dict(keywords=(Keyword.DIVINE_SHIELD,))),
            (IMMUNE,2,40,dict(keywords=(Keyword.IMMUNE,))),
            (STEALTH,3,40,dict(keywords=(Keyword.STEALTH,Keyword.ELUSIVE))),
            (SLEEP,7,20,dict(dormant_turns=2)),(BIG,40,20,{}),
            (REPEAT,1,20,dict(battlecry_repeats=(BattlecryRepeatSpec(),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,**options))
    def fail(c):raise ResolutionError('Kronn deliberate failure')
    r.register_behavior(P+'fail',fail)
    operations={
        'freeze':lambda c:(Freeze(c.target_id),),
        'buff':lambda c:(Buff(c.target_id,5,0,c.source_id),),
        'hurt':lambda c:(Damage(c.state.players[c.player_id].hero_id,12,c.source_id),),
        'direct':lambda c:(EachMinionDealsAttackDamage(c.player_id,c.source_id),),
    }
    for name,body in operations.items():
        key=P+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in ('freeze','buff')else None))
    if mode:
        def watch(c):
            if c.event is None or c.state.entities[c.state.players[c.player_id].hero_id].armor:return()
            first=c.state.entities.get(c.event.source_id)
            if first is None or first.card_id!=A:return()
            player=3-c.player_id
            following=next((i for i in c.state.players[player].board if c.state.entities[i].card_id==B),None)
            root=next((e.id for e in c.state.entities.values()if e.card_id==CARD and e.zone==Zone.BOARD),None)
            def spawn(pid):return SummonByCard(pid,(SummonEntryMaterial(NEW),),SummonCause.capture(c))
            def bounce():return(ReturnToHand(following),SummonFromZone(player,zone=Zone.HAND,
                query=PoolQuery(card_ids=(B,)),selection='first'))
            work=(GainArmor(c.player_id,1),)
            if mode in ('wait','sample_wait'):
                return(*work,RequestChoice(c.player_id,(
                    ChoiceOption('ok','Continue'),
                    ChoiceOption('buff','Grow next',effects=(Buff(following,5,0,c.source_id),)),
                    ChoiceOption('buff_first','Grow accepted source',effects=(Buff(first.id,5,0,c.source_id),)),
                    ChoiceOption('kill_first','Remove accepted source',effects=(Destroy(first.id,c.source_id),)),
                    ChoiceOption('bounce','Return next',effects=bounce()),
                    ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),
                    source_id=c.source_id))
            actions={
                'buff_next':lambda:(Buff(following,5,0,c.source_id),),
                'transform_next':lambda:(Transform(following,MATERIAL),),
                'kill_next':lambda:(Destroy(following,c.source_id),),
                'bounce_next':bounce,
                'control_next':lambda:(ChangeControl(following,c.player_id),),
                'kill_root':lambda:(Destroy(root,c.source_id),),
                'spawn_ally':lambda:(spawn(player),),
                'spawn_enemy':lambda:(spawn(c.player_id),),
                'fail':lambda:(InvokeBehavior(P+'fail',c.source_id,c.player_id),),
            }
            return(*work,*actions[mode]())
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=60,
            triggers=(TriggerSpec('random_choice'if mode=='sample_wait'else'damage_dealt',P+'watch'),)))
    return r


class KronnImpalerTests(unittest.TestCase):
    def game(self,*,mode=None,board=(),enemy=(),hand=(CARD,),seat=1,seed=362):
        self.mode=mode;self.seat=seat
        if mode:enemy=(WATCH,*enemy)
        own=PlayerSetup('HERO_05',hand=hand,board=board,deck=(FILL,)*6,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',board=enemy,deck=(FILL,)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=seed),fixture(mode))

    def eid(self,g,cid,pid=None,zone='board'):
        return next(i for i in getattr(g.state.players[self.seat if pid is None else pid],zone)
            if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,target=None):
        pid=g.state.active_player;eid=self.eid(g,cid,pid,'hand');g.apply(PlayCard(pid,eid,target));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hero(self,g,pid=None):return g.state.entities[g.state.players[3-self.seat if pid is None else pid].hero_id]
    def randoms(self,g):return[e for e in g.events if e.kind=='random_choice']
    def damage(self,g,source=None):
        return[e for e in g.events if e.kind=='damage_dealt'and(source is None or e.source_id==source)]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in (g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original finite source/remaining residence/RNG must restore')
        return Game.from_snapshot(s,r)
    def target_game(self,source,enemy):
        for seed in range(20):
            g=self.game(board=(source,),enemy=(enemy,),seed=seed)
            ids=sorted((self.hero(g).id,*g.state.players[2].board));rng=Random();rng.setstate(g._rng.getstate())
            if rng.choice(ids)==self.eid(g,enemy,2):return g
        self.fail('Fixture could not select its real enemy minion')

    def test_complete_raw_primary_faces_hunter_elemental_legendary_and_central_definition(self):
        batch=load_batch();row=batch['cards'][0];raw=row['record'];self.assertEqual(raw['dbf_id'],130765)
        self.assertEqual(canonical_digest(raw),row['record_sha256'])
        self.assertEqual({o['locale']for o in batch['official_observations']},{'zh_CN','en_US'})
        for obs in batch['official_observations']:check_face(raw,obs['face'],obs['locale'])
        r=assembled();card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.classes,card.metadata.rarity,card.metadata.tribes),
            (10,6,6,(CardClass.HUNTER,),Rarity.LEGENDARY,('elemental',)))
        self.assertEqual(card,fixture().card(CARD));self.assertEqual(r.pool_card(CARD),fixture().pool_card(CARD))

    def test_real_ten_mana_play_includes_own_body_and_uses_each_physical_minion_source(self):
        g=self.game(board=(A,B));a,b=tuple(g.state.players[1].board);root=self.play(g)
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual(self.hero(g).damage,13)
        self.assertEqual([(e.source_id,e.amount)for e in self.damage(g)],[(a,3),(b,4),(root,6)])
        self.assertTrue(all(dict(e.data)['damage_kind']=='minion_ability'for e in self.damage(g)))
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_ability_is_not_combat_and_never_consumes_attack_readiness_or_causes_retaliation(self):
        g=self.game(board=(A,),enemy=(FILL,));a=self.eid(g,A);root=self.play(g)
        self.assertEqual((g.state.entities[a].attacks_this_turn,g.state.entities[root].attacks_this_turn),(0,0))
        self.assertEqual((g.state.entities[a].damage,g.state.entities[root].damage),(0,0))
        self.assertFalse(any(e.kind in ('attack_declared','attack_started','attack_finished')for e in g.events))

    def test_spell_damage_does_not_increase_any_minion_ability_hit(self):
        g=self.game(board=(A,POWER));a=self.eid(g,A);self.play(g)
        self.assertEqual(self.hero(g).damage,9);self.assertEqual([e.amount for e in self.damage(g,a)],[3])

    def test_each_original_physical_copy_has_independent_contribution(self):
        g=self.game(board=(A,A));ids=tuple(g.state.players[1].board);root=self.play(g)
        self.assertEqual([e.source_id for e in self.randoms(g)],[*ids,root]);self.assertEqual(self.hero(g).damage,12)

    def test_zero_attack_retains_ordinary_random_choice_but_deals_no_damage(self):
        g=self.game(board=(ZERO,));z=self.eid(g,ZERO);self.play(g)
        self.assertEqual(len([e for e in self.randoms(g)if e.source_id==z]),1)
        self.assertFalse(self.damage(g,z));self.assertEqual(self.hero(g).damage,6)

    def test_frozen_original_and_newborn_root_both_deal_ability_damage_without_thawing(self):
        g=self.game(board=(A,),hand=(P+'freeze',CARD));a=self.eid(g,A);self.play(g,P+'freeze',a);self.play(g)
        self.assertIsNotNone(g.state.entities[a].frozen_until_owner_turn);self.assertEqual([e.amount for e in self.damage(g,a)],[3])

    def test_dormant_and_location_carriers_are_not_participants_or_enemy_targets(self):
        g=self.game(board=(SLEEP,'SC_403'),enemy=(SLEEP,'SC_403'));root=self.play(g)
        self.assertEqual([e.source_id for e in self.randoms(g)],[root]);self.assertEqual(self.hero(g).damage,6)
        self.assertEqual(tuple(dict(self.randoms(g)[0].data)['candidates']),(self.hero(g).id,))

    def test_individual_lifesteal_heals_that_minions_controller_not_every_hit(self):
        g=self.game(board=(LIFE,),hand=(P+'hurt',CARD));i=self.eid(g,LIFE);self.play(g,P+'hurt');self.play(g)
        self.assertEqual(self.hero(g,1).damage,9)
        heal=[e for e in g.events if e.kind=='healed'];self.assertEqual([(e.source_id,e.amount)for e in heal],[(i,3)])

    def test_individual_poisonous_kills_selected_minion_and_later_hit_requeries_after_death(self):
        g=self.target_game(VENOM,FILL);i=self.eid(g,VENOM);victim=self.eid(g,FILL,2);root=self.play(g)
        self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD)
        self.assertEqual(self.damage(g,i)[0].amount,1)
        self.assertEqual(tuple(dict(next(e for e in self.randoms(g)if e.source_id==root).data)['candidates']),(self.hero(g).id,))

    def test_divine_shield_and_immunity_use_original_damage_prevention(self):
        for target in (SHIELD,IMMUNE):
            with self.subTest(target=target):
                g=self.target_game(VENOM,target);i=self.eid(g,VENOM);victim=self.eid(g,target,2);self.play(g)
                self.assertFalse(self.damage(g,i));self.assertEqual(g.state.entities[victim].zone,Zone.BOARD)
                self.assertTrue(any(e.kind=='damage_prevented'and e.source_id==i for e in g.events))

    def test_random_ability_targets_stealth_elusive_and_consumes_sources_stealth(self):
        g=self.target_game(STEALTH,STEALTH);i=self.eid(g,STEALTH);victim=self.eid(g,STEALTH,2);self.play(g)
        self.assertEqual(self.damage(g,i)[0].target_id,victim);self.assertNotIn(Keyword.STEALTH,g.state.entities[i].keywords)

    def test_later_original_reads_current_attack_after_earlier_damage_reaction(self):
        g=self.game(mode='buff_next',board=(A,B));b=self.eid(g,B);self.play(g)
        self.assertEqual([e.amount for e in self.damage(g,b)],[9])

    def test_later_original_transform_keeps_residence_and_uses_current_face_attack(self):
        g=self.game(mode='transform_next',board=(A,B));b=self.eid(g,B);ref=BoardPresenceReference.capture(g.state,b);self.play(g)
        self.assertEqual(g.state.entities[b].card_id,MATERIAL);self.assertEqual([e.amount for e in self.damage(g,b)],[8])
        self.assertEqual(BoardPresenceReference.capture(g.state,b),ref)

    def test_departed_or_changed_control_original_does_not_contribute(self):
        for mode in ('kill_next','bounce_next','control_next'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,board=(A,B));b=self.eid(g,B);before=BoardPresenceReference.capture(g.state,b);self.play(g)
                self.assertFalse(any(e.source_id==b for e in self.randoms(g)))
                if mode=='bounce_next':self.assertNotEqual(BoardPresenceReference.capture(g.state,b),before)

    def test_new_friendly_summon_never_joins_original_finite_inventory(self):
        g=self.game(mode='spawn_ally',board=(A,B));self.play(g);new=self.eid(g,NEW)
        self.assertFalse(any(e.source_id==new for e in self.randoms(g)));self.assertEqual(len(self.randoms(g)),3)

    def test_new_enemy_is_in_later_current_target_domain(self):
        g=self.game(mode='spawn_enemy',board=(A,B));a=self.eid(g,A);self.play(g);new=self.eid(g,NEW,2)
        self.assertTrue(all(new in dict(e.data)['candidates']for e in self.randoms(g)if e.source_id!=a))

    def test_battlecry_carrier_dying_does_not_cancel_other_original_participants(self):
        g=self.game(mode='kill_root',board=(A,B));b=self.eid(g,B);root=self.play(g)
        self.assertEqual(g.state.entities[root].zone,Zone.GRAVEYARD)
        self.assertEqual([e.amount for e in self.damage(g,b)],[4]);self.assertFalse(any(e.source_id==root for e in self.randoms(g)))

    def test_native_battlecry_repeat_accepts_a_fresh_whole_inventory_without_second_payment(self):
        g=self.game(board=(REPEAT,));repeat_id=self.eid(g,REPEAT);root=self.play(g)
        self.assertEqual([e.source_id for e in self.randoms(g)],[repeat_id,root,repeat_id,root])
        self.assertEqual(self.hero(g).damage,14);self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual(sum(e.kind=='card_played'and e.source_id==root for e in g.events),1);self.portable(g)

    def test_empty_original_group_has_no_rng_or_invented_participant(self):
        g=self.game(hand=(P+'direct',));before=g._rng.getstate();self.play(g,P+'direct')
        self.assertEqual(g._rng.getstate(),before);self.assertFalse(self.randoms(g))

    def test_wait_after_first_hit_restores_and_applies_changed_later_attack(self):
        g=self.game(mode='wait',board=(A,B));b=self.eid(g,B);self.play(g);other=self.portable(g)
        self.choose(g,'buff');self.choose(other,'buff');self.assertTrue(g.snapshot()==other.snapshot())
        self.assertEqual([e.amount for e in self.damage(g,b)],[9]);self.portable(g)

    def test_wait_after_random_acceptance_keeps_original_amount_despite_growth(self):
        g=self.game(mode='sample_wait',board=(A,B));a=self.eid(g,A);self.play(g)
        self.assertFalse(self.damage(g,a));other=self.portable(g);self.choose(g,'buff_first');self.choose(other,'buff_first')
        self.assertTrue(g.snapshot()==other.snapshot());self.assertEqual([e.amount for e in self.damage(g,a)],[3])

    def test_wait_after_random_acceptance_keeps_already_scheduled_hit_after_source_death(self):
        g=self.game(mode='sample_wait',board=(A,B));a=self.eid(g,A);self.play(g);self.choose(g,'kill_first')
        self.assertEqual(g.state.entities[a].zone,Zone.GRAVEYARD);self.assertEqual([e.amount for e in self.damage(g,a)],[3])

    def test_waiting_return_reentry_of_later_source_is_stale_after_json_restore(self):
        g=self.game(mode='wait',board=(A,B));b=self.eid(g,B);self.play(g);other=self.portable(g)
        self.choose(g,'bounce');self.choose(other,'bounce');self.assertTrue(g.snapshot()==other.snapshot())
        self.assertFalse(any(e.source_id==b for e in self.randoms(g)))

    def test_late_reaction_and_failed_choice_roll_back_full_resources_history_and_rng(self):
        g=self.game(mode='fail',board=(A,B));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertTrue(g.snapshot()==before)
        g=self.game(mode='wait',board=(A,B));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before);self.choose(g)

    def test_lethal_first_participant_stops_remaining_work(self):
        g=self.game(board=(BIG,B));first=self.eid(g,BIG);self.play(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual([e.source_id for e in self.randoms(g)],[first])

    def test_other_seat_wait_and_player_projection_do_not_expose_continuation_or_rng(self):
        g=self.game(mode='wait',board=(A,B),seat=2);self.play(g);before=g.snapshot();self.assertEqual(g.state.pending_choice.player_id,1)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in ('remaining','presence_id','EachMinionDealsAttackDamage','rng_state','resolution_frame'):
                self.assertNotIn('"'+key+'"',visible)
        self.assertTrue(g.snapshot()==before);self.choose(g);self.portable(g)

    def test_typed_codec_rejects_duplicate_unknown_future_and_boolean_source_even_at_empty_tail(self):
        g=self.game(board=(A,));a=self.eid(g,A);source=self.eid(g,CARD,zone='hand');ref=BoardPresenceReference.capture(g.state,a)
        effect=EachMinionDealsAttackDamage(1,source,(ref,));codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(effect)))),effect)
        with self.assertRaises(ValueError):replace(effect,remaining=(ref,ref))
        with self.assertRaises(ValueError):replace(effect,source_id=True)
        for bad in (replace(effect,source_id=g.state.next_entity_id+1,remaining=()),
                replace(effect,remaining=(replace(ref,presence_id=g.state.next_order),)),
                replace(effect,remaining=(replace(ref,entity_id=g.state.next_entity_id+1),))):
            with self.assertRaises(ValueError):bad.validate_in_state(g.state)
            with self.assertRaises(ValueError):codec.decode(codec.encode(bad))
