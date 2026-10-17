"""Original finite-trigger grants and the actual Soulrest Ceremony consumer."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_ceremony_cards import CEREMONY,PREFIX,load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,Zone)
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.limited_triggers import GrantLimitedTrigger
from hs_sim.engine.model import EndTurnSpec,LimitedTriggerSpec,RewindSpec,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='k136.';YETI='CORE_CS2_182';TWO='CORE_GVG_085';PLAIN='CORE_CS2_179'


def registry(mode=None):
    r=build_registry()
    def reenter(c):
        e=c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e),e.controller),)
    def defer(c):
        e=c.state.entities[c.target_id];ref=MinionReference.capture(e)
        spec=LimitedTriggerSpec('turn_ended',PREFIX+'destroy',condition_id=PREFIX+'caster1',end_turn=EndTurnSpec('either'))
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Grant original timer',(
            GrantLimitedTrigger(e.id,spec,c.source_id,recipient=ref),)),),c.source_id),)
    def copy(c,mode):return (CopyMinion(capture_board_presence(c.state,c.target_id),c.player_id,mode=mode),)
    def fail(c):raise ResolutionError('K136 deliberate continuation failure')
    bodies=dict(reenter=reenter,fail=fail,defer=defer,
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        transform=lambda c:(Transform(c.target_id,PLAIN),),control=lambda c:(ChangeControl(c.target_id,2),),
        current=lambda c:copy(c,'current'),base=lambda c:copy(c,'base'),
        summon=lambda c:(Summon(c.player_id,TWO),),enemy_cast=lambda c:(CastSpell(2,CEREMONY,c.source_id),),
        rewind_cast=lambda c:(CastSpell(c.player_id,CEREMONY,c.source_id),))
    for name,body in bodies.items():
        r.register_behavior(TEST+name,body)
        if name in('reenter','fail'):continue
        kwargs=dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))if name in(
            'defer','silence','bounce','transform','control','current','base')else{}
        if name=='rewind_cast':kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec())
        r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,**kwargs))
    r.register_card(CardDefinition(TEST+'reborn','Ordinary original Reborn',CardType.MINION,attack=2,health=2,keywords=(Keyword.REBORN,)))
    r.register_card(CardDefinition(TEST+'dormant','Physical sleeping body',CardType.MINION,attack=1,health=3,dormant_turns=2))
    if mode:
        def eligible(c):
            e=c.event
            if mode in('end','death'):
                i=e.source_id if mode=='end'else e.target_id
                return i is not None and c.state.entities[i].card_id==YETI
            return (e.target_id is not None and c.state.entities[e.target_id].card_id==YETI and
                e.source_id is not None and c.state.entities[e.source_id].card_id==CEREMONY)
        def watch(c):
            if mode=='direct_fail':return (InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)
            if mode=='death':return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
                    InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),),c.source_id),)
            current=next(i for i,e in c.state.entities.items()if e.card_id==YETI and e.zone==Zone.BOARD)
            later=next((i for i in c.state.players[1].board if c.state.entities[i].card_id==TWO),current)
            options=[ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
                InvokeBehavior(TEST+'fail',c.source_id,c.player_id),))]
            for name,target in(('cycle',later),('cycle_first',current)):
                options.append(ChoiceOption(name,'Return and reenter original body',(
                    ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,target))))
            options.extend((ChoiceOption('transform','Transform later original',(Transform(later,PLAIN),)),
                ChoiceOption('control','Transfer later original',(ChangeControl(later,2),)),
                ChoiceOption('new','Summon a later body',(Summon(1,PLAIN),))))
            return (RequestChoice(c.player_id,tuple(options),c.source_id),)
        event={'grant':'ability_granted','end':'limited_trigger_used','death':'minion_died'}.get(mode,'stats_changed')
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Original reaction witness',CardType.MINION,health=12,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r


@lru_cache(maxsize=None)
def shared(mode):return registry(mode)


class NativeCeremonyTests(unittest.TestCase):
    def game(self,hand=(CEREMONY,),board=(YETI,TWO),enemy=(YETI,),mode=None):
        self.mode=mode
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40)),seed=136),shared(mode))
    def eid(self,g,cid,p=1,zone='board'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CEREMONY,target=None):
        i=self.eid(g,cid,zone='hand');g.apply(PlayCard(1,i,target,position=len(g.state.players[1].board)
            if g.state.entities[i].kind==CardType.MINION else None));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def timers(self,g,i):
        return [a for a in g.state.entities[i].abilities if a.kind=='limited_trigger'and a.limited_trigger.behavior_id==PREFIX+'destroy']
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return other
    def nodes(self,value):
        if isinstance(value,dict):
            if value.get('type','').endswith('.GrantLimitedTrigger'):yield value['fields']
            for v in value.values():yield from self.nodes(v)
        elif isinstance(value,list):
            for v in value:yield from self.nodes(v)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(s,shared(self.mode))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_real_shadow_spell_metadata_and_one_mana_source(self):
        d=load_batch();row,=d['cards'];raw=row['record'];card=shared(None).card(CEREMONY)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual((card.cost,card.spell_school.value),(1,'shadow'))
        self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual(len(d['official_observations']),2)
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_actual_paid_spell_grants_each_original_minion_and_destroys_at_caster_end(self):
        g=self.game();ids=tuple(g.state.players[1].board);enemy=self.eid(g,YETI,2);source=self.play(g)
        self.assertEqual(g.state.players[1].mana,39)
        for i in ids:
            e=g.state.entities[i];self.assertEqual(e.attack,shared(None).card(e.card_id).attack+1);self.assertIn(Keyword.RUSH,e.keywords)
            timer,=self.timers(g,i);self.assertEqual((timer.source_id,timer.uses_remaining,timer.expires_turn),(source,1,None))
        self.assertEqual(g.state.entities[enemy].attack,4);g.apply(EndTurn(1))
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in ids));self.assertEqual(g.state.entities[enemy].zone,Zone.BOARD)

    def test_rush_allows_new_minion_combat_but_does_not_allow_hero_attack(self):
        g=self.game((YETI,CEREMONY),board=())
        i=self.play(g,YETI);self.play(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,i,g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(),saved);g.apply(Attack(1,i,self.eid(g,YETI,2)))
        self.assertEqual(g.state.entities[i].attacks_this_turn,1)

    def test_empty_board_and_dormant_occupants_are_not_granted(self):
        for board in((),(TEST+'dormant',)):
            with self.subTest(board=board):
                g=self.game(board=board);rng=g._rng.getstate();self.play(g);self.assertEqual(g._rng.getstate(),rng)
                for i in g.state.players[1].board:
                    self.assertFalse(self.timers(g,i));self.assertNotIn(Keyword.RUSH,g.state.entities[i].keywords)

    def test_later_summons_are_outside_the_original_group(self):
        g=self.game((CEREMONY,TEST+'summon'),board=(YETI,));old=self.eid(g,YETI);self.play(g);self.play(g,TEST+'summon')
        later=self.eid(g,TWO);g.apply(EndTurn(1));self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[later].zone,Zone.BOARD);self.assertFalse(self.timers(g,later))

    def test_original_later_recipient_same_id_reentry_does_not_receive_any_old_grant(self):
        g=self.game(mode='buff');old=g.state.entities[self.eid(g,TWO)];self.play(g);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x,'cycle')
        self.assertEqual(g.snapshot(),other.snapshot());e=g.state.entities[old.id]
        self.assertNotEqual(e.board_presence_id,old.board_presence_id);self.assertEqual((e.attack,e.health),(1,2))
        self.assertNotIn(Keyword.RUSH,e.keywords);self.assertFalse(self.timers(g,e.id));g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[e.id].zone,Zone.BOARD)

    def test_wait_after_rush_cannot_attach_the_timer_to_a_reentered_first_recipient(self):
        g=self.game(mode='grant');old=g.state.entities[self.eid(g,YETI)];self.play(g);self.assertIsNotNone(g.state.pending_choice)
        self.choose(g,'cycle_first');e=g.state.entities[old.id]
        self.assertNotEqual(e.board_presence_id,old.board_presence_id);self.assertEqual(e.attack,4)
        self.assertFalse(self.timers(g,e.id));self.assertNotIn(Keyword.RUSH,e.keywords)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[e.id].zone,Zone.BOARD)

    def test_original_recipient_transform_or_control_before_grant_is_not_rebound(self):
        for key in('transform','control'):
            with self.subTest(key=key):
                g=self.game(mode='buff');i=self.eid(g,TWO);self.play(g);self.choose(g,key)
                self.assertFalse(self.timers(g,i));self.assertNotIn(Keyword.RUSH,g.state.entities[i].keywords)
                g.apply(EndTurn(1));self.assertEqual(g.state.entities[i].zone,Zone.BOARD)

    def test_already_attached_timer_tracks_original_caster_after_control_change(self):
        g=self.game((CEREMONY,TEST+'control'));i=self.eid(g,TWO);self.play(g);self.play(g,TEST+'control',i)
        self.assertEqual(g.state.entities[i].controller,2);self.assertEqual(len(self.timers(g,i)),1)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)

    def test_out_of_turn_indirect_cast_waits_for_its_original_caster_end(self):
        g=self.game((TEST+'enemy_cast',),board=());i=self.eid(g,YETI,2);self.play(g,TEST+'enemy_cast')
        timer,=self.timers(g,i);self.assertEqual(timer.limited_trigger.condition_id,PREFIX+'caster2')
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[i].zone,Zone.BOARD);self.assertEqual(len(self.timers(g,i)),1)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)

    def test_silence_transform_and_bounce_retire_granted_lifecycle(self):
        for name in('silence','transform','bounce'):
            with self.subTest(name=name):
                g=self.game((CEREMONY,TEST+name),board=(YETI,));i=self.eid(g,YETI);self.play(g);self.play(g,TEST+name,i)
                self.assertFalse(self.timers(g,i));g.apply(EndTurn(1))
                self.assertEqual(g.state.entities[i].zone,Zone.HAND if name=='bounce'else Zone.BOARD)

    def test_current_copy_retains_timer_while_base_copy_does_not(self):
        g=self.game((CEREMONY,TEST+'current',TEST+'base'),board=(YETI,));i=self.eid(g,YETI);self.play(g)
        self.play(g,TEST+'current',i);self.play(g,TEST+'base',i);ids=g.state.players[1].board
        self.assertEqual([len(self.timers(g,j))for j in ids],[1,1,0]);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].board,[ids[-1]])

    def test_reborn_is_a_new_base_body_without_old_grants(self):
        g=self.game(board=(TEST+'reborn',));old=self.eid(g,TEST+'reborn');self.play(g);g.apply(EndTurn(1))
        i=self.eid(g,TEST+'reborn');self.assertNotEqual(i,old);e=g.state.entities[i]
        self.assertEqual((e.attack,e.health),(2,1));self.assertFalse(self.timers(g,i));self.assertNotIn(Keyword.RUSH,e.keywords)

    def test_consumed_end_timer_wait_does_not_destroy_same_id_new_residence(self):
        g=self.game(mode='end');old=g.state.entities[self.eid(g,YETI)];self.play(g);g.apply(EndTurn(1));other=self.portable(g)
        for x in(g,other):self.choose(x,'cycle_first')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[old.id].zone,Zone.BOARD)
        self.assertNotEqual(g.state.entities[old.id].board_presence_id,old.board_presence_id)

    def test_end_death_wait_restore_replay_and_bad_resume_keep_accepted_group(self):
        g=self.game(mode='death');self.play(g);g.apply(EndTurn(1));other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(g.state.players[1].board)

    def test_failed_reaction_rolls_back_all_partial_grants_and_original_payment(self):
        g=self.game(mode='direct_fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_native_rewind_restores_grants_before_indirect_retry(self):
        g=self.game((TEST+'rewind_cast',),board=(YETI,));i=self.eid(g,YETI);self.play(g,TEST+'rewind_cast')
        self.assertEqual(g.state.entities[i].attack,5);self.choose(g,'retry')
        self.assertEqual(g.state.entities[i].attack,5);self.assertEqual(len(self.timers(g,i)),1)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)

    def test_pending_finite_grant_rejects_future_unknown_wrong_kind_or_mismatched_recipient(self):
        g=self.game((TEST+'defer',));self.play(g,TEST+'defer',self.eid(g,TWO));self.portable(g)
        for mutation in('future_epoch','future_order','unknown','wrong_kind','mismatch','missing'):
            with self.subTest(mutation=mutation):
                s=deepcopy(g.snapshot());nodes=list(self.nodes(s['resolution_frame']));self.assertTrue(nodes)
                for node in nodes:
                    f=node['recipient']['fields']
                    if mutation=='future_epoch':f['zone_epoch']=999999
                    elif mutation=='future_order':f['entered_order']=999999
                    elif mutation=='unknown':node['target_id']=f['entity_id']=999999
                    elif mutation=='wrong_kind':f['card_id']='HERO_08'
                    elif mutation=='mismatch':f['entity_id']=g.state.players[1].hero_id
                    else:node.pop('recipient')
                self.reject(s)

    def test_public_request_requires_typed_matching_reference_and_keeps_bare_api(self):
        g=self.game();i=self.eid(g,TWO);ref=MinionReference.capture(g.state.entities[i]);spec=LimitedTriggerSpec('turn_ended',PREFIX+'destroy')
        with self.assertRaises(ValueError):GrantLimitedTrigger(i,spec,recipient='integer-id-is-not-a-reference')
        with self.assertRaises(ValueError):GrantLimitedTrigger(i+1,spec,recipient=ref)
        GrantLimitedTrigger(i,spec).validate_in_state(g.state)

    def test_private_group_and_original_reference_do_not_enter_player_projection(self):
        g=self.game(mode='buff');self.play(g)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('MinionReference','resolution_frame','zone_epoch','entered_order','rng_state','condition_id'):
                self.assertNotIn('"'+key+'"',public)

    def test_actual_old_schema_is_rejected_and_existing_full_definitions_stay_identical(self):
        g=self.game();old=g.snapshot();old['schema_version']=343
        with self.assertRaisesRegex(SnapshotError,f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):Game.from_snapshot(old,shared(None))
        with patch('hs_sim.cards.native_ceremony_cards.register_native_ceremony_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{CEREMONY})
        for cid,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(cid)))
        self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools))
        self.assertEqual(dict(before.generation_families),dict(after.generation_families))


if __name__=='__main__':unittest.main()
