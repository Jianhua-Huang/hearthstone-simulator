"""Real Burndown over original physical draw roots and shared hand deadlines."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import burndown_card as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import ChoiceOption,Draw,GainArmor,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.model import CardDefinition,CardType,CastWhenDrawnSpec,Keyword,SpellSchool,TriggerSpec,Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARD=native.CARD;P='k649.'
WATCH,CYCLE,CHANGE,CWD,FAIL=(P+s for s in ('watch','cycle','change','cwd','fail'))
A,B,C,OTHER='card.1','card.2','card.3','card.40'


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
        InvokeBehavior(FAIL,c.source_id,c.player_id)))),source_id=c.source_id,prompt='Original Burndown reaction')


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_burndown_card(r)
    def fail(c):raise ValueError('K649 deliberate failure')
    r.register_behavior(FAIL,fail)
    r.register_behavior(CWD,lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(CWD,CWD,CardType.SPELL,on_play=CWD,keywords=(Keyword.CASTS_WHEN_DRAWN,),
        cast_when_drawn=CastWhenDrawnSpec(),metadata=metadata()))
    def cycle(c):
        entity=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==A)
        return (MoveCard(CardReference.capture(entity),c.player_id,Zone.DECK,position='top',source_id=c.source_id),Draw(c.player_id,1,c.source_id))
    def change(c):
        entity=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==A)
        return (TransformStoredCard(CardReference.capture(entity),OTHER,c.source_id),)
    for cid,body in ((CYCLE,cycle),(CHANGE,change)):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if source is None or source.card_id!=CARD or e.player_id!=c.player_id:return ()
        roots=[v for v in c.state.draw_history if v.source_id==source.id and v.parent_id is None]
        if e.kind=='card_drawn'and len(roots)==1:
            if mode=='extra':return (Draw(c.player_id,1,c.source_id),)
            if mode=='draw_wait':return (prompt(c),)
            if mode=='draw_fail':return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if e.kind=='hand_deadline_armed'and mode=='armed_wait':return (prompt(c),)
        if e.kind=='card_destroyed_in_hand'and mode=='destroy_wait':return (prompt(c),)
        if e.kind=='card_destroyed_in_hand'and mode=='destroy_fail':return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=metadata(),
        triggers=tuple(TriggerSpec(event,WATCH)for event in ('card_drawn','hand_deadline_armed','card_destroyed_in_hand'))))
    return r


@lru_cache(maxsize=1)
def host():return build_cn37_local_pool_format()


def wires(value,name):
    rows=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):rows.append(value)
        for v in value.values():rows.extend(wires(v,name))
    elif isinstance(value,list):
        for v in value:rows.extend(wires(v,name))
    return rows


class BurndownTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,deck=(A,B,C)+(OTHER,)*10,hand=(CARD,),mode='normal',watch=False,actor=1):
        self.mode=mode
        own=PlayerSetup('mage.hero',hand=hand,deck=deck,board=(WATCH,)if watch else(),mana=10,max_mana=10)
        other=PlayerSetup('mage.hero',deck=(OTHER,)*12,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if actor==1 else(other,own),active_player=actor,seed=649),registry(mode))

    def end(self,g,count=1):
        for _ in range(count):g.apply(EndTurn(g.state.active_player))

    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')});return s

    def test_complete_original_spell_three_evidence_rows_and_two_primary_faces(self):
        data=native.load_batch();card=registry().card(CARD)
        self.assertEqual((card.cost,card.kind,card.spell_school),(3,CardType.SPELL,SpellSchool.FIRE))
        self.assertEqual(len(data['evidence_only']),3);self.assertEqual(len(data['official_observations']),2)
        self.assertFalse(data['new_standard_roots']);self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])
        self.assertTrue(all(v['record']['id']not in registry().cards for v in data['evidence_only']))

    def test_draws_three_original_roots_and_deadline_excludes_existing_same_face(self):
        g=self.game(hand=(CARD,A));existing=self.entity(g,A).id;source=self.play(g,CARD)
        root,=g.state.hand_deadlines;draws=[v for v in g.state.draw_history if v.source_id==source]
        self.assertEqual(len(draws),3);self.assertEqual(tuple(t.entity_id for t in root.targets),tuple(v.entity_id for v in draws))
        self.assertNotIn(existing,[t.entity_id for t in root.targets]);self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual((root.request.owner_ends,root.request.retirement),(3,'destroy'));self.portable(g)

    def test_three_natural_owner_ends_include_current_and_ignore_opponent(self):
        g=self.game();self.play(g,CARD);targets=tuple(t.entity_id for t in g.state.hand_deadlines[0].targets)
        for i in range(1,6):
            self.end(g)
            self.assertEqual([g.state.entities[e].zone for e in targets],[Zone.GRAVEYARD if i==5 else Zone.HAND]*3)
        self.assertEqual(g.state.hand_deadlines[0].removed,targets);self.assertFalse(g.state.death_history or g.state.discard_history);self.portable(g)

    def test_second_seat_draws_its_own_original_cards_and_counts_its_ends(self):
        g=self.game(actor=2);self.play(g,CARD,player=2);root,=g.state.hand_deadlines
        self.assertEqual(root.request.player_id,2);self.assertTrue(all(t.player_id==2 for t in root.targets))
        self.end(g,5);self.assertEqual(root.id,g.state.hand_deadlines[0].id);self.assertEqual(len(g.state.hand_deadlines[0].removed),3)

    def test_full_hand_burns_two_without_borrowing_old_hand_cards(self):
        g=self.game(hand=(CARD,)+(OTHER,)*9);self.play(g,CARD);root,=g.state.hand_deadlines
        self.assertEqual([t.card_id for t in root.targets],[A]);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual([v.outcome for v in g.state.draw_history],['hand','burned','burned'])

    def test_empty_deck_has_three_real_fatigue_attempts_and_empty_deadline(self):
        g=self.game(deck=());self.play(g,CARD)
        self.assertEqual(len(g.state.draw_history),3);self.assertTrue(all(v.outcome=='fatigue'for v in g.state.draw_history))
        self.assertEqual(g.state.hand_deadlines[0].targets,());self.assertFalse(g.state.players[1].hand)

    def test_draw_cast_root_tracks_its_actual_final_replacement_hand_leaf(self):
        g=self.game(deck=(CWD,A,B,C)+(OTHER,)*10);self.play(g,CARD)
        self.assertEqual(len(g.state.draw_history),4);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual([t.card_id for t in g.state.hand_deadlines[0].targets],[A,B,C])
        self.assertEqual(self.entity(g,A).zone,Zone.HAND);self.assertNotIn(CWD,[t.card_id for t in g.state.hand_deadlines[0].targets])

    def test_extra_reaction_draw_is_excluded_from_the_three_original_slots(self):
        g=self.game(mode='extra',watch=True);source=self.play(g,CARD)
        self.assertEqual(len(g.state.draw_history),4);rows=[v for v in g.state.draw_history if v.source_id==source and v.parent_id is None]
        self.assertEqual(tuple(t.entity_id for t in g.state.hand_deadlines[0].targets),tuple(v.entity_id for v in rows))
        self.assertNotIn(self.entity(g,B).id,[t.entity_id for t in g.state.hand_deadlines[0].targets]);self.portable(g)

    def test_three_same_faces_keep_three_distinct_physical_targets(self):
        g=self.game(deck=(A,)*15);self.play(g,CARD);targets=g.state.hand_deadlines[0].targets
        self.assertEqual(len({t.entity_id for t in targets}),3);self.assertEqual([t.card_id for t in targets],[A]*3)

    def test_original_moved_out_and_drawn_back_escapes_old_hand_residence(self):
        g=self.game(hand=(CARD,CYCLE));self.play(g,CARD);original=self.entity(g,A).id;self.play(g,CYCLE)
        self.end(g,5);self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.assertNotIn(original,g.state.hand_deadlines[0].removed);self.portable(g)

    def test_same_hand_face_change_uses_existing_strict_deadline_policy(self):
        g=self.game(hand=(CARD,CHANGE));self.play(g,CARD);original=self.entity(g,A).id;self.play(g,CHANGE)
        self.end(g,5);self.assertEqual((g.state.entities[original].zone,g.state.entities[original].card_id),(Zone.HAND,OTHER))

    def test_played_original_minion_is_not_destroyed_from_the_board(self):
        g=self.game();self.play(g,CARD);original=self.play(g,A);self.end(g,5)
        self.assertEqual(g.state.entities[original].zone,Zone.BOARD);self.assertNotIn(original,g.state.hand_deadlines[0].removed)

    def test_two_actual_casts_keep_separate_original_target_groups(self):
        g=self.game(hand=(CARD,CARD),deck=(A,B,C,A,B,C)+(OTHER,)*10);self.play(g,CARD);self.play(g,CARD)
        a,z=g.state.hand_deadlines;self.assertEqual((len(a.targets),len(z.targets)),(3,3))
        self.assertFalse({t.entity_id for t in a.targets}&{t.entity_id for t in z.targets})

    def test_first_draw_wait_restores_owed_original_slots_before_arming(self):
        g=self.game(mode='draw_wait',watch=True);self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.hand_deadlines)
        g=self.portable(g);self.choose(g);self.assertEqual(len(g.state.hand_deadlines[0].targets),3);self.portable(g)

    def test_arming_notification_wait_keeps_complete_original_deadline_and_replays(self):
        g=self.game(mode='armed_wait',watch=True);self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.hand_deadlines[0].targets),3);g=self.portable(g);self.choose(g);self.portable(g)

    def test_destruction_notification_wait_keeps_later_targets_and_choice_failure_rolls_back(self):
        g=self.game(mode='destroy_wait',watch=True);self.play(g,CARD);self.end(g,5);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before)
        while g.state.pending_choice:self.choose(g)
        self.assertEqual(len(g.state.hand_deadlines[0].removed),3);self.portable(g)

    def test_first_draw_failure_restores_source_payment_deck_and_rng(self):
        g=self.game(mode='draw_fail',watch=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_end_destruction_failure_restores_original_end_and_complete_hand(self):
        g=self.game(mode='destroy_fail',watch=True);self.play(g,CARD);self.end(g,4);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before)

    def test_pending_group_cannot_change_three_original_draws_or_deadline_after_rehash(self):
        g=self.game(mode='draw_wait',watch=True);self.play(g,CARD);saved=json.loads(json.dumps(g.snapshot()))
        nodes=wires(saved,'DrawGroupReward');self.assertTrue(nodes)
        for node in nodes:
            if node['fields']['kind']=='destroy_drawn_after_ends':node['fields']['amount']=4
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('draw_wait','independent-reader'))

    def test_only_actual_three_plain_draws_and_three_ends_accept_new_reward(self):
        for slots,amount in (((DrawGroupSlot(),),3),((DrawGroupSlot(),)*3,2)):
            with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,slots,DrawGroupReward('destroy_drawn_after_ends',amount))

    def test_player_information_hides_original_draw_requests_and_private_deadline_proofs(self):
        g=self.game(mode='draw_wait',watch=True);self.play(g,CARD)
        for pid in (1,2):
            view=json.dumps(g.for_player(pid).observe())
            for key in ('ContinuePhysicalDrawGroup','DrawGroupArrival','hand_cursor','source_guard','resolution_frame','rng_state'):
                self.assertNotIn(key,view)

    def test_real_standard_host_draws_original_cards_and_arms_shared_deadline(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),deck=('CORE_CS2_182',)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*12)),seed=649,generation_context=f.context),f.registry)
        source=self.play(g,CARD);root,=g.state.hand_deadlines
        self.assertEqual(root.request.source_id,source);self.assertEqual(len(root.targets),3);self.assertEqual(g.state.players[1].mana,7)

    def test_real_shenanigans_converted_original_draw_arms_actual_banana(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),deck=('CORE_CS2_182',)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('YOP_017',),deck=('CORE_CS2_182',)*12,mana=10,max_mana=10)),
            active_player=2,seed=649,generation_context=f.context),f.registry)
        self.play(g,'YOP_017',player=2);self.end(g);source=self.play(g,CARD)
        rows=[v for v in g.state.draw_history if v.source_id==source and v.parent_id is None]
        self.assertEqual(len(rows),3);self.assertIsNotNone(rows[0].transformation)
        root,=g.state.hand_deadlines;self.assertEqual(root.targets[0].card_id,'EX1_014t')
        self.assertEqual(root.targets[0].entity_id,rows[0].entity_id);self.assertEqual(len(root.targets),3)


if __name__=='__main__':unittest.main()
