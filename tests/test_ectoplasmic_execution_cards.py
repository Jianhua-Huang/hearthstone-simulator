"""Actual destroy-all, native spell material and ordinary base resurrection."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.ectoplasmic_execution_cards import ECTOPLASM, SLIME, load_batch, register_ectoplasmic_execution_cards
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.destruction_resummon_spells import (CompleteResummonSpells, DestroyedSpellGroup,
    DestroyForResummonSpells, SpellResummonValue, validate_value)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, DestroyBatch, Draw, GainArmor,
    InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.native_spell_values import bound_value
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest

P='ectoplasm.test.'
A,B,C,D=(P+x for x in ('a','b','c','d'))


def registry(mode=None):
    r=Registry('ectoplasm-native-tests-v1')
    register_ectoplasmic_execution_cards(r)
    r.register_card(CardDefinition(P+'hero','Hero',CardType.HERO,health=100))
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,7),))
    r.register_behavior(P+'death',lambda c:(Summon(c.player_id,D),))
    r.register_behavior(P+'fill',lambda c:(Draw(c.player_id,1,c.source_id),))
    for cid,attack,health in ((A,2,3),(B,4,5),(C,6,7),(D,1,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health))
    r.register_card(CardDefinition(P+'r','Reborn',CardType.MINION,attack=1,health=2,keywords=(Keyword.REBORN,)))
    r.register_card(CardDefinition(P+'dr','Native death',CardType.MINION,attack=2,health=2,
        battlecry=P+'armor',deathrattle=P+'death'))
    r.register_card(CardDefinition(P+'fill','Fill',CardType.MINION,attack=1,health=1,deathrattle=P+'fill'))
    r.register_card(CardDefinition(P+'dormant','Dormant',CardType.MINION,attack=1,health=4,dormant_turns=20))
    r.register_card(CardDefinition(P+'location','Location',CardType.LOCATION,durability=2,on_use=P+'armor'))
    def target_token(c):
        return next(c.state.entities[i] for i in c.state.players[2].hand if c.state.entities[i].card_id==ECTOPLASM)
    def whole(c):
        excluded=tuple(p.id for p in c.state.play_history if p.id<c.play.id and p.card_id!=ECTOPLASM)
        return (ReplayWholeCards(c.player_id,c.source_id,
            WholeCardHistoryQuery(c.player_id,c.play.id,exclude_play_ids=excluded)),)
    scripts={
        'buff':lambda c:(Buff(c.target_id,5,6),Damage(c.target_id,2,c.source_id)),
        'front':lambda c:(Summon(c.player_id,C,position=0),),
        'kill':lambda c:(DestroyBatch(tuple(c.state.players[c.player_id].board),c.source_id),),
        'copy':lambda c:(CopyCard(CardReference.capture(target_token(c)),c.player_id,mode='current',source_id=c.source_id),),
        'steal':lambda c:(MoveCard(CardReference.capture(target_token(c)),c.player_id,Zone.HAND,source_id=c.source_id),),
        'base':lambda c:(CopyCard(CardReference.capture(target_token(c)),c.player_id,mode='base',source_id=c.source_id),),
        'recast':lambda c:(RecastSpell(c.player_id,next(x.id for x in c.state.cast_history if x.card_id==ECTOPLASM),c.source_id),),
        'whole':whole,
        'fail':lambda c:(AddToHand(c.player_id,'missing.ectoplasm'),),
    }
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            requires_target=name=='buff'))
    if mode:
        def watch(c):
            e=c.event;target=c.state.entities.get(e.target_id)
            if target is None:return ()
            if mode=='death' and target.card_id!=P+'dr':return ()
            if mode in ('created','fail_second') and target.card_id!=ECTOPLASM:return ()
            if mode=='created' and e.player_id!=1:return ()
            if mode=='fail_second':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),) if e.player_id==2 else ()
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        event={'death':'minion_died','created':'card_created','fail_second':'card_created','summon':'minion_resurrected'}[mode]
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=10,dormant_turns=20,
            dormant_triggers=(TriggerSpec(event,P+'watch'),)))
    return r


class EctoplasmicExecutionTests(unittest.TestCase):
    def game(self,board=(A,B),enemy=(C,),*,hand=(SLIME,),enemy_hand=(),mode=None,active=1):
        self.mode=mode
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(P+'hero',hand=hand,board=board,deck=(D,)*10,
            mana=30,max_mana=30,mana_cap=30),PlayerSetup(P+'hero',hand=enemy_hand,board=enemy,deck=(D,)*10,
            mana=30,max_mana=30,mana_cap=30)),seed=269,active_player=active),registry(mode))
    def play(self,g,cid=SLIME,pid=1,target=None):
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target));return eid
    def token(self,g,pid=1):
        return next(g.state.entities[i] for i in g.state.players[pid].hand if g.state.entities[i].card_id==ECTOPLASM)
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def faces(self,g,pid=1):
        return [g.state.entities[i].card_id for i in g.state.players[pid].board if g.state.entities[i].active]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(self.mode)
        other=Game.from_snapshot(saved,r);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('spell_resummon_value','first_death_id','victims','causes','resolution_frame'):
                self.assertNotIn('"'+field+'"',public)
        return other

    def test_a00_complete_two_sources_metadata_and_central_registration(self):
        d=load_batch();r=build_registry()
        for row in (*d['cards'],*d['dependencies']):
            raw=row['record'];card=r.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(card.metadata,metadata_from_record(raw))
            self.assertEqual(card.spell_school,SpellSchool.SHADOW)
        self.assertEqual((r.card(SLIME).cost,r.card(ECTOPLASM).cost),(4,3))
        self.assertEqual(len(d['official_observations']),4);self.assertFalse(d['cn_calibrated'])

    def test_a01_actual_paid_clear_creates_both_bound_spells_and_resummons_only_own_side(self):
        g=self.game();old=set(g.state.players[1].board);source=self.play(g)
        self.assertEqual(g.state.players[1].mana,26);self.assertEqual(self.faces(g),[])
        self.assertEqual(self.faces(g,2),[]);self.assertEqual(len(g.state.death_history),3)
        own=bound_value(self.token(g));enemy=bound_value(self.token(g,2))
        self.assertEqual((own.recipient_id,enemy.recipient_id),(1,2));self.assertEqual(own.group,enemy.group)
        self.assertTrue(all(c.source_id==source for c in own.group.causes))
        self.play(g,ECTOPLASM);self.assertEqual(g.state.players[1].mana,23)
        self.assertEqual(self.faces(g),[A,B]);self.assertTrue(old.isdisjoint(g.state.players[1].board))
        self.assertEqual(self.faces(g,2),[]);self.portable(g)

    def test_a02_opponent_receives_its_own_original_group_and_pays_three(self):
        g=self.game();self.play(g);g.apply(EndTurn(1));mana=g.state.players[2].mana
        self.play(g,ECTOPLASM,pid=2)
        self.assertEqual(self.faces(g,2),[C]);self.assertEqual(g.state.players[2].mana,mana-3)

    def test_a03_empty_board_still_gives_two_complete_empty_spells_without_rng(self):
        g=self.game((),());rng=g._rng.getstate();self.play(g)
        for pid in (1,2):self.assertEqual(bound_value(self.token(g,pid)).group.causes,())
        self.play(g,ECTOPLASM);self.assertEqual(self.faces(g),[]);self.assertEqual(g._rng.getstate(),rng)

    def test_a04_printed_resurrection_does_not_restore_old_buffs_or_damage(self):
        g=self.game((A,),(),hand=(SLIME,P+'buff'));old=g.state.players[1].board[0]
        self.play(g,P+'buff',target=old);self.assertEqual(g.state.entities[old].health,7)
        self.play(g);self.play(g,ECTOPLASM);body=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((body.attack,body.max_health,body.health),(2,3,3))

    def test_a05_original_left_to_right_is_not_death_timestamp_order(self):
        g=self.game(enemy=(),hand=(SLIME,P+'front'));self.play(g,P+'front')
        self.assertEqual(self.faces(g),[C,A,B]);self.play(g)
        self.assertEqual([d.card_id for d in g.state.death_history],[A,B,C])
        self.play(g,ECTOPLASM);self.assertEqual(self.faces(g),[C,A,B])

    def test_a06_dormant_and_location_are_not_destroyed_or_added_to_the_group(self):
        g=self.game((A,P+'dormant',P+'location'),());self.play(g)
        self.assertEqual([r.card_id for r in bound_value(self.token(g)).group.victims],[A])
        self.assertEqual(len(g.state.players[1].board),2);self.play(g,ECTOPLASM)
        self.assertEqual(self.faces(g),[P+'location',A])

    def test_b00_reborn_and_deathrattle_summons_do_not_join_the_original_group(self):
        g=self.game((P+'r',P+'dr'),());self.play(g)
        self.assertEqual(len(bound_value(self.token(g)).group.victims),2)
        self.assertEqual(self.faces(g),[P+'r',D]);self.play(g,ECTOPLASM)
        self.assertEqual(self.faces(g),[P+'r',D,P+'r',P+'dr'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_b01_later_deaths_do_not_replace_or_extend_the_captured_group(self):
        g=self.game((P+'dr',),(),hand=(SLIME,P+'kill'));self.play(g)
        self.assertEqual(self.faces(g),[D]);self.play(g,P+'kill');self.play(g,ECTOPLASM)
        self.assertEqual(self.faces(g),[P+'dr']);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_b02_current_copy_of_opponents_spell_keeps_its_group_and_new_attachment_identity(self):
        g=self.game((A,),(C,),hand=(SLIME,P+'copy'));self.play(g)
        original=self.token(g,2);old=next(a.id for a in original.abilities if a.kind=='spell_resummon_value')
        value=bound_value(original);self.play(g,P+'copy')
        copy=next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==ECTOPLASM and bound_value(g.state.entities[i]).recipient_id==2)
        self.assertEqual(bound_value(copy),value)
        self.assertNotEqual(next(a.id for a in copy.abilities if a.kind=='spell_resummon_value'),old)
        g.apply(PlayCard(1,copy.id));self.assertEqual(self.faces(g),[C]);self.portable(g)

    def test_b03_physical_theft_preserves_original_side_but_summons_for_current_caster(self):
        g=self.game((A,),(C,),hand=(SLIME,P+'steal'));self.play(g)
        original=self.token(g,2);self.play(g,P+'steal');g.apply(PlayCard(1,original.id))
        self.assertEqual(self.faces(g),[C]);self.assertEqual(self.faces(g,2),[]);self.portable(g)

    def test_b04_base_copy_and_direct_unbound_spell_are_explicitly_unsupported(self):
        g=self.game((A,),(C,),hand=(SLIME,P+'base'));self.play(g);self.play(g,P+'base')
        unbound=next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==ECTOPLASM and bound_value(g.state.entities[i]) is None)
        saved=g.snapshot()
        with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):g.apply(PlayCard(1,unbound.id))
        self.assertEqual(g.snapshot(),saved)
        g=self.game((),(),hand=(ECTOPLASM,));saved=g.snapshot()
        with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):self.play(g,ECTOPLASM)
        self.assertEqual(g.snapshot(),saved)

    def test_b05_full_recipient_hands_use_normal_burn_with_complete_bound_material(self):
        g=self.game((P+'fill',),(C,),hand=(SLIME,)+(P+'front',)*9,enemy_hand=(P+'front',)*10)
        self.play(g);created=[e for e in g.state.entities.values() if e.card_id==ECTOPLASM]
        self.assertEqual(len(created),2)
        self.assertTrue(all(e.zone==Zone.GRAVEYARD and bound_value(e) is not None for e in created))
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),2);self.portable(g)

    def test_b06_resummon_capacity_uses_real_current_board_and_never_resurrects_enemy_group(self):
        g=self.game((P+'r',)*4,(C,));self.play(g)
        self.assertEqual(len(g.state.players[1].board),4);self.play(g,ECTOPLASM)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertTrue(all(cid==P+'r' for cid in self.faces(g)))

    def test_b07_spell_history_and_whole_card_replay_inherit_original_resummoning_material(self):
        for command in ('recast','whole'):
            with self.subTest(command=command):
                g=self.game((A,),(C,),hand=(SLIME,P+command));self.play(g);self.play(g,ECTOPLASM)
                self.play(g,P+command);self.assertEqual(self.faces(g),[A,A])
                casts=[c for c in g.state.cast_history if c.card_id==ECTOPLASM]
                self.assertEqual(len(casts),2)
                self.assertEqual(casts[0].native_spell_value.spell_resummon_value,casts[1].native_spell_value.spell_resummon_value)
                self.portable(g)

    def test_c00_death_reaction_wait_retains_original_group_and_delivery_continuation(self):
        g=self.game((P+'dr',),(C,),mode='death');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(bound_value(self.token(g)).group.victims),2)
        self.play(g,ECTOPLASM);self.assertEqual(self.faces(g),[D,P+'dr'])

    def test_c01_first_creation_wait_has_complete_values_and_recovers_second_delivery_once(self):
        g=self.game((A,),(C,),mode='created');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(bound_value(self.token(g)).recipient_id,1)
        self.assertFalse(any(g.state.entities[i].card_id==ECTOPLASM for i in g.state.players[2].hand))
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(sum(e.card_id==ECTOPLASM for e in g.state.entities.values()),2)

    def test_c02_failed_choice_restores_same_original_pending_group_and_rng(self):
        g=self.game((A,),(C,),mode='created');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(bound_value(self.token(g,2)).recipient_id,2)

    def test_c03_failed_second_delivery_rolls_back_entire_paid_destruction(self):
        g=self.game((A,),(C,),mode='fail_second');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_c04_mid_resummon_wait_recovers_remaining_original_order_without_new_sampling(self):
        g=self.game((A,B),(C,),mode='summon');self.play(g);self.play(g,ECTOPLASM)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.faces(g),[A]);other=self.portable(g)
        while g.state.pending_choice:self.choose(g)
        while other.state.pending_choice:self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.faces(g),[A,B]);self.portable(g)

    def test_c05_original_second_player_receives_first_without_changing_group_side(self):
        g=self.game((A,),(C,),hand=(),enemy_hand=(SLIME,),active=2);self.play(g,pid=2)
        created=[e.player_id for e in g.events if e.kind=='card_created' and g.state.entities[e.target_id].card_id==ECTOPLASM]
        self.assertEqual(created,[2,1]);self.play(g,ECTOPLASM,pid=2);self.assertEqual(self.faces(g,2),[C])

    def test_d00_complete_group_rejects_cropped_causes_foreign_sources_and_wrong_boundaries(self):
        g=self.game();self.play(g);value=bound_value(self.token(g))
        with self.assertRaises(ValueError):replace(value.group,causes=value.group.causes[:-1])
        for group in (replace(value.group,first_death_id=g.state.next_death_id+1),
                      replace(value.group,cast_id=999999)):
            with self.assertRaises((ValueError,ResolutionError)):validate_value(g.state,g.registry,replace(value,group=group))
        cause=replace(value.group.causes[0],source_card_id=P+'kill')
        bad=replace(value.group,causes=(cause,*value.group.causes[1:]))
        with self.assertRaises(ValueError):validate_value(g.state,g.registry,replace(value,group=bad))

    def test_d01_modified_saved_material_rejects_even_with_recomputed_state_hash(self):
        g=self.game();self.play(g);saved=json.loads(json.dumps(g.snapshot()));eid=self.token(g).id
        ability=next(a for a in saved['state']['entities'][str(eid)]['abilities'] if a['kind']=='spell_resummon_value')
        ability['spell_resummon_value']['group']['causes'].pop()
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode))

    def test_d02_strict_effect_value_codec_and_old_schema_rejection(self):
        g=self.game();self.play(g);value=bound_value(self.token(g));codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(value)),value)
        with self.assertRaises(ValueError):SpellResummonValue(ECTOPLASM,True,value.group)
        with self.assertRaises(ValueError):CompleteResummonSpells(ECTOPLASM,value.group,True)
        with self.assertRaises(ValueError):DestroyForResummonSpells(True,ECTOPLASM)
        saved=deepcopy(g.snapshot());saved['schema_version']=441
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode))


if __name__=='__main__':unittest.main()
