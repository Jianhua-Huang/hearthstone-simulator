"""Actual physical casts, persistent returns, growth and native Aura leaves."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p69_cards as cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p69_cards import (TIMEHOPPER, FATEBREAKER, VELOCIDRAKE,
    REINFORCEMENT, STAND, SPRITE, PHOENIX, BULB, GNOMISH, MEKKATORQUE, SHRED, ROOTS,
    PREFIX, POOL_ID, load_batch, register_simple_followup_p69_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, TargetSpec,
    UseHandAction, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='p69.test.'
M1,M2,M3,POWER,WATCH=(TEST+s for s in ('m1','m2','m3','power','watch'))
KILL,DRAW,HURT,NOOP,NEW,S1,S2,S3=(TEST+s for s in ('kill','draw','hurt','noop','new','s1','s2','s3'))
UNKNOWN=TEST+'unknown'
YETI='CORE_CS2_182'
CONTEXT=GenerationContext('p69-complete-explicit-fixture','experimental')
MEMBERS=((S1,1),(S2,1),(S3,1))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta():return CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p69_cards(r)
    elif not all(present):raise AssertionError('P69 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None,members=MEMBERS):
    r=batch_registry()
    for cid,cost,atk,hp in((M1,1,1,8),(M2,2,2,10),(M3,3,3,12)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=meta()))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=20,spell_damage=6,metadata=meta()))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        HURT:lambda c:tuple(Damage(i,6,c.source_id)for i in(c.state.players[c.player_id].hero_id,*c.state.players[c.player_id].board)),
        NOOP:lambda c:(),NEW:lambda c:(AddToHand(c.player_id,PHOENIX,c.source_id),),
        S1:lambda c:(GainArmor(c.player_id,1),),S2:lambda c:(GainArmor(c.player_id,2),),S3:lambda c:(GainArmor(c.player_id,3),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost={S1:1,S2:2,S3:3}.get(cid,0),
            on_play=cid,targeting=TargetSpec()if cid==KILL else None,metadata=meta()))
    r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,meta(),battlecry=False,deathrattle=False,choose_one=False))
    for cid,_ in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID,'p69-complete-finite-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid,w)for cid,w in members),complete=True))
    def fail(c):raise ResolutionError('P69 deliberate continuation failure')
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter)
    if mode:
        event={'shred':'spell_cast_finished','bulb':'spell_cast_finished','aura':'stats_changed'}[mode]
        def eligible(c):
            if mode=='aura':return c.event.target_id in c.state.players[1].board and c.state.entities[c.event.target_id].card_id==M1
            row=cast_record(c.state,dict(c.event.data)['cast_id'])
            return row.card_id==(SHRED if mode=='shred'else S1) and row.caster_id is not None
        def wait(c):
            options=[ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if mode=='shred':
                target=cast_record(c.state,dict(c.event.data)['cast_id']).caster_id
                options.extend((ChoiceOption('kill','Remove original',(Destroy(target,c.source_id),)),
                    ChoiceOption('cycle','Leave and reenter',(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target)))))
            elif mode=='aura':
                target=c.event.target_id
                options.append(ChoiceOption('cycle','Leave and reenter',(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))))
            return(RequestChoice(1,tuple(options),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'wait',wait)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),),metadata=meta()))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,members,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Incomplete immutable fixture key')
    r=registry(mode,members);r.freeze();return r


class SimpleFollowupP69Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(YETI,)*16,enemy_hand=(),mode=None,members=MEMBERS,active=1,cap=None):
        self.config=mode,members
        if mode=='aura':enemy=(WATCH,)+enemy
        elif mode:board=(WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_10',hand=hand,board=board,deck=deck,
            mana=40,max_mana=40,mana_cap=40,hand_cap=cap),PlayerSetup('HERO_10',hand=enemy_hand,
            board=enemy,deck=(YETI,)*16,mana=40,max_mana=40,mana_cap=40)),active_player=active,
            seed=6969,generation_context=CONTEXT),fixture_registry(mode,members,'writer',SOURCE_PIN))
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,pid=1):
        e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,
            position=len(g.state.players[pid].board)if e.kind in(CardType.MINION,CardType.LOCATION)else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hero(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id]
    def rounds(self,g,n=1):
        for _ in range(n):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def count(self,g,cid,zone='hand',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
    def portable(self,g):
        r=fixture_registry(*self.config,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,r);self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in('rng_state','resolution_frame','behavior_id','source_allocation','cast_history','hand_entries'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a0_actual_deck_shred_wait_restore_rollback_and_original_source_death(self):
        g=self.game((FATEBREAKER,),deck=(SHRED,YETI),mode='shred');source=self.play(g,FATEBREAKER)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].attack,4);self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.hero(g).health,27)
        self.assertFalse(g.state.draw_history);self.assertEqual(len(g.state.players[1].deck),1);self.portable(g)

    def test_a1_original_source_reentry_does_not_receive_delayed_buff_or_copy(self):
        for cid in(FATEBREAKER,VELOCIDRAKE):
            g=self.game((cid,),deck=(SHRED,YETI),mode='shred');source=self.play(g,cid);self.portable(g);self.choose(g,'cycle')
            self.assertEqual(self.count(g,cid,'board'),1)
            self.assertEqual(g.state.entities[source].attack,4 if cid==FATEBREAKER else 5);self.portable(g)

    def test_a2_fatebreaker_real_physical_deck_cast_no_draw_payment_or_lifesteal_inheritance(self):
        g=self.game((FATEBREAKER,),board=(POWER,),deck=(SHRED,SHRED,YETI));shreds=set(i for i in g.state.players[1].deck if g.state.entities[i].card_id==SHRED)
        source=self.play(g,FATEBREAKER);e=g.state.entities[source]
        self.assertEqual((e.attack,e.health),(7,7));self.assertEqual(self.hero(g).health,27)
        row=g.state.cast_history[0];self.assertIn(row.source_id,shreds)
        self.assertEqual((row.caster_id,row.from_zone,row.origin,row.completed),(source,Zone.DECK,'effect',True))
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,36)
        self.assertFalse(g.state.draw_history);self.assertEqual(self.count(g,SHRED,'deck'),1);self.portable(g)

    def test_a3_velocidrake_copy_uses_native_current_material_without_another_battlecry(self):
        g=self.game((VELOCIDRAKE,),deck=(SHRED,SHRED,YETI));source=self.play(g,VELOCIDRAKE)
        self.assertEqual(self.count(g,VELOCIDRAKE,'board'),2);self.assertEqual(self.count(g,SHRED,'deck'),1)
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(len(g.state.card_summon_history),1)
        self.assertEqual(g.state.card_summon_history[0].request.cause.source.entity_id,source);self.portable(g)

    def test_a4_empty_shred_deck_no_fabricated_cast_and_full_board_copy_still_casts(self):
        g=self.game((FATEBREAKER,VELOCIDRAKE));self.play(g,FATEBREAKER);self.play(g,VELOCIDRAKE)
        self.assertFalse(g.state.cast_history);self.assertEqual(len(g.state.players[1].board),2);self.portable(g)
        g=self.game((VELOCIDRAKE,),board=(M1,)*6,deck=(SHRED,YETI));self.play(g,VELOCIDRAKE)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.hero(g).health,27);self.assertEqual(self.count(g,SHRED,'deck'),0);self.portable(g)

    def test_b0_timehopper_one_semantic_two_card_shuffle_and_actual_draw_replacements(self):
        g=self.game((TIMEHOPPER,DRAW),deck=());self.play(g,TIMEHOPPER)
        self.assertEqual(self.count(g,SHRED,'deck'),2);self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.assertFalse(g.state.cast_history);self.play(g,DRAW)
        self.assertEqual(self.hero(g).health,23);self.assertEqual(len([r for r in g.state.cast_history if r.card_id==SHRED]),2)
        self.assertEqual(len(g.state.play_history),2);self.assertFalse(g.state.players[1].deck);self.portable(g)

    def test_c0_last_stand_repeat_owner_end_growth_distinct_targets_and_native_spell_damage(self):
        g=self.game((STAND,),enemy=(M1,M2,M3),board=(POWER,));self.rounds(g)
        self.assertEqual(progress_ability(self.first(g,STAND)).progress_completions,1)
        targets=list(g.state.players[2].board);self.play(g,STAND)
        dealt=[n-g.state.entities[i].health for i,n in zip(targets,(8,10,12))]
        # M1/M2/M3 started with 8/10/12 Health; two distinct physical targets take 3+6.
        self.assertEqual(sorted(dealt),[0,9,9]);self.portable(g)

    def test_c1_last_stand_empty_and_single_enemy_do_not_duplicate_damage(self):
        g=self.game((STAND,));self.play(g,STAND);self.assertEqual(self.hero(g,2).health,30);self.portable(g)
        g=self.game((STAND,),enemy=(M2,));target=self.first(g,M2,'board',2).id;self.play(g,STAND)
        self.assertEqual(g.state.entities[target].health,8);self.portable(g)

    def test_c2_sprite_creates_real_bulb_and_three_cast_budget_freezes_at_held_progress(self):
        g=self.game((SPRITE,));self.play(g,SPRITE);self.assertEqual(self.first(g,BULB).card_id,BULB)
        self.rounds(g,2);self.assertEqual(progress_ability(self.first(g,BULB)).progress_completions,2);source=self.play(g,BULB)
        rows=[r for r in g.state.cast_history if r.caster_id==source]
        self.assertEqual([r.card_id for r in rows],[S3]*3);self.assertEqual(self.hero(g).armor,9);self.portable(g)

    def test_c3_bulb_real_cast_wait_restore_and_unknown_complete_pool_rollback(self):
        g=self.game((BULB,),mode='bulb');source=self.play(g,BULB);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g)
        self.assertEqual([r.card_id for r in g.state.cast_history if r.caster_id==source],[S1]*3);self.portable(g)
        g=self.game((BULB,),members=((UNKNOWN,1),));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BULB)
        self.assertEqual(g.snapshot(),saved)

    def test_d0_reinforcement_three_own_ends_recruit_original_deck_entities_without_battlecries(self):
        g=self.game((REINFORCEMENT,),deck=(M1,TIMEHOPPER,M2,M3));eligible=set(g.state.players[1].deck[:3]);source=self.play(g,REINFORCEMENT)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,3)
        g.apply(EndTurn(1));first=g.state.players[1].board[0];self.assertIn(first,eligible)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,2);self.assertEqual(self.count(g,SHRED,'deck'),0)
        g.apply(EndTurn(2));self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,2)
        self.rounds(g,2);self.assertFalse(g.state.players[1].player_effects)
        self.assertTrue(set(g.state.players[1].board)<=eligible);self.assertFalse(g.state.cast_history[0].caster_id)
        self.assertTrue(all(x.request.cause.source.entity_id==source for x in g.state.card_summon_history));self.portable(g)

    def test_d1_empty_or_full_board_aura_still_consumes_native_owner_ticks(self):
        for board,deck in(((),(M3,)*8),((M1,)*7,(M2,)*8)):
            g=self.game((REINFORCEMENT,),board=board,deck=deck);self.play(g,REINFORCEMENT);self.rounds(g,3)
            self.assertFalse(g.state.players[1].player_effects);self.assertEqual(len(g.state.players[1].board),len(board));self.portable(g)

    def test_d2_gnomish_aura_heals_actual_all_friendly_characters_and_independent_instances(self):
        g=self.game((HURT,GNOMISH,GNOMISH),board=(M1,M2),enemy=(M3,));self.play(g,HURT)
        self.assertEqual(self.hero(g).health,24);self.play(g,GNOMISH);self.play(g,GNOMISH);g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).health,30);self.assertEqual(self.first(g,M1,'board').health,8)
        self.assertEqual(self.first(g,M2,'board').health,10);self.assertEqual(self.first(g,M3,'board',2).health,12)
        self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects],[2,2]);self.portable(g)

    def test_d3_mekkatorque_original_buff_recipient_reentry_skips_delayed_shield(self):
        g=self.game((MEKKATORQUE,),board=(M1,),mode='aura');target=self.first(g,M1,'board').id
        self.play(g,MEKKATORQUE);g.apply(EndTurn(1));self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[target].attack,5);self.portable(g);self.choose(g,'cycle')
        self.assertEqual(g.state.entities[target].attack,1);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords);self.portable(g)

    def test_d4_mekkatorque_selects_one_friendly_and_both_aura_leaves_retain_real_trade(self):
        g=self.game((MEKKATORQUE,),board=(M1,M2));self.play(g,MEKKATORQUE);g.apply(EndTurn(1))
        pairs=[(g.state.entities[i].attack,Keyword.DIVINE_SHIELD in g.state.entities[i].keywords)for i in g.state.players[1].board]
        self.assertEqual(sum(shield for _,shield in pairs),1);self.assertEqual(sum(a for a,_ in pairs),7);self.portable(g)
        for cid in(GNOMISH,MEKKATORQUE):
            g=self.game((cid,),deck=(M3,));source=self.first(g,cid).id;g.apply(UseHandAction(1,source,'trade'))
            self.assertEqual(g.state.players[1].mana,39);self.assertFalse(g.state.cast_history)
            self.assertFalse(g.state.players[1].player_effects);self.assertEqual(self.count(g,M3),1);self.assertEqual(self.count(g,cid,'deck'),1);self.portable(g)

    def test_e0_phoenix_native_turn_count_includes_earlier_plays_before_acquisition_and_resets(self):
        g=self.game((NOOP,NEW));self.play(g,NOOP);self.play(g,NEW)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,PHOENIX)).amount,2)
        self.rounds(g);self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,PHOENIX)).amount,4)
        self.play(g,PHOENIX);self.assertEqual(self.count(g,PHOENIX,'board'),1);self.portable(g)

    def test_e1_phoenix_deathrattles_return_independent_fresh_faces_once_on_either_end(self):
        g=self.game((KILL,KILL),board=(PHOENIX,PHOENIX));originals=list(g.state.players[1].board)
        for eid in originals:self.play(g,KILL,eid)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)
        g.apply(EndTurn(1));self.assertEqual(self.count(g,PHOENIX),2);self.assertFalse(g.state.players[1].player_effects)
        self.assertTrue(all(i not in originals for i in g.state.players[1].hand));g.apply(EndTurn(2));self.assertEqual(self.count(g,PHOENIX),2);self.portable(g)
        g=self.game(board=(PHOENIX,),enemy_hand=(KILL,),active=2);self.play(g,KILL,self.first(g,PHOENIX,'board').id,pid=2)
        g.apply(EndTurn(2));self.assertEqual(self.count(g,PHOENIX),1);self.assertFalse(g.state.players[1].player_effects);self.portable(g)

    def test_e2_phoenix_full_hand_burn_consumes_original_return_without_retry(self):
        g=self.game((NOOP,),board=(PHOENIX,),enemy_hand=(KILL,),active=2,cap=1)
        self.play(g,KILL,self.first(g,PHOENIX,'board').id,pid=2)
        g.apply(EndTurn(2));self.assertEqual(self.count(g,PHOENIX),0);self.assertFalse(g.state.players[1].player_effects)
        self.assertTrue(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_z0_complete_source_faces_existing_shred_and_all_old_definitions_are_preserved(self):
        from tools.card_batch import check_face
        d=load_batch();self.assertEqual(len(d['official_observations']),24);self.assertEqual(len(d['exact_parent_child_links']),12)
        raws={x['record']['id']:x['record']for k in('cards','dependencies','existing_dependencies','evidence_only')for x in d[k]}
        for o in d['official_observations']:check_face(raws[o['card_id']],o['face'],o['locale'],
            d['display_normalizations'].get(o['card_id']),numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(before.fabled,after.fabled);self.assertEqual(before.generation_families,after.generation_families)
        self.assertEqual(canonical_digest(asdict(after.card(SHRED))),d['existing_dependency_definition_pins'][SHRED]['sha256'])
        self.assertNotIn('TIME_009',after.cards)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
        self.assertTrue(set(ROOTS)<=set(after.cards))


if __name__=='__main__':unittest.main()
