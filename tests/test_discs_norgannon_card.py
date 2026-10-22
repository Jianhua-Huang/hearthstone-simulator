"""Real deck partition, normal-turn edge choice and shared physical draws."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.discs_norgannon_card import (CARD,TOP,BOTTOM,PROGRAM,INSTALL,DRAW,load_batch,
    register_discs_norgannon_card)
from hs_sim.cards.commander_geddon_card import CARD as GEDDON, PROGRAM as GEDDON_PROGRAM, register_commander_geddon_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Registry,
    Scenario,SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.card_discoveries import discovered_cards
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass,CardMetadata,CastWhenDrawnSpec,ChoicePurpose,CostSpec,
    Keyword,PlayerEffectSpec,Rarity,SpellSchool,Zone)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.turn_start_draws import DrawDeckEdge,TurnDrawReplacementProfile
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from tools.card_batch import canonical,check_face

P='fixture.discs.'
HERO,M1,M2,S1,S2,CW,EXTRA,FILL,AUTO,BOOST,DIRECT,WATCH=(P+n for n in
    ('hero','m1','m2','s1','s2','cw','extra','fill','auto','boost','direct','watch'))
META=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=())
DECK=(M1,S1,M2,S2)


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    assert role in ('writer','reader')
    r=Registry('discs-'+mode);register_discs_norgannon_card(r);register_commander_geddon_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=replace(META,collectible=False)))
    for cid in (M1,M2):r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=3,metadata=META))
    r.register_behavior(P+'noop',lambda c:())
    for cid in (S1,S2):r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=P+'noop',metadata=META))
    def fail(c):raise ResolutionError('Deliberate deck-edge draw reaction failure')
    r.register_behavior(P+'fail',fail)
    def wait(c):
        return (RequestChoice(2,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(CW,wait if mode=='cw_wait'else lambda c:(GainArmor(c.player_id,2),))
    r.register_card(CardDefinition(CW,CW,CardType.SPELL,cost=10,on_play=CW,metadata=META,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec()))
    bodies={EXTRA:lambda c:(Draw(c.player_id,source_id=c.source_id),),
        FILL:lambda c:(AddToHand(c.player_id,M1,c.source_id),AddToHand(c.player_id,M1,c.source_id)),
        AUTO:lambda c:(CastSpell(c.player_id,CARD,c.source_id),),
        BOOST:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]]),CostSpec(delta=-1),c.source_id),),
        DIRECT:lambda c:(DrawDeckEdge(c.player_id,'bottom',c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    if mode in ('wait','fail'):
        def watch(c):
            if c.event.player_id!=1:return ()
            return (InvokeBehavior(P+'fail',c.source_id,1),)if mode=='fail'else wait(c)
        r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,
            health=4,metadata=META,triggers=(TriggerSpec('card_drawn',WATCH),)))
    r.validate();r.freeze();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class DiscsNorgannonTests(unittest.TestCase):
    def game(self,deck=DECK,hand=None,mode='normal',pid=1):
        self.mode,self.pid=mode,pid
        players=tuple(PlayerSetup(HERO,hand=((CARD,)if hand is None else hand)if p==pid else (),
            board=(WATCH,)if mode in ('wait','fail')and p==pid else (),
            deck=deck if p==pid else (M1,)*10,mana=50,max_mana=50,mana_cap=50)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=pid,seed=384),registry(mode))
    def play(self,g,cid=CARD):
        e=next(g.state.entities[i]for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,e.id,position=len(g.state.players[self.pid].board)if e.kind==CardType.MINION else None));return e.id
    def next_owner(self,g):
        g.apply(EndTurn(self.pid));g.apply(EndTurn(3-self.pid))
    def select(self,g,key='top'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def ids(self,g,zone='deck',pid=None):return list(getattr(g.state.players[self.pid if pid is None else pid],zone))
    def faces(self,g,zone='deck',pid=None):return [g.state.entities[i].card_id for i in self.ids(g,zone,pid)]
    def own_draws(self,g):return [x for x in g.state.draw_history if x.player_id==self.pid]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));reader=registry(self.mode,'reader')
        self.assertIsNot(reader,g.registry);other=Game.from_snapshot(s,reader)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),s);return other

    def test_complete_root_two_real_options_and_original_passive_sources(self):
        d=load_batch();raws={x['record']['id']:x['record']for key in ('cards','dependencies','evidence_only')for x in d[key]}
        self.assertEqual(len(raws),4);self.assertEqual(raws['BE_250e']['type'],'ENCHANTMENT')
        r=registry();c=r.card(CARD)
        self.assertEqual((c.cost,c.spell_school,c.on_play),(2,SpellSchool.ARCANE,INSTALL))
        for cid in (TOP,BOTTOM):
            self.assertTrue(r.card(cid).choice_only);self.assertFalse(r.card(cid).hand_playable);self.assertNotIn(cid,r.pool_cards)
            self.assertIsNone(raws[cid]['cost'])
        for row in d['official_observations']:
            cid=row['card_id'];check_face(raws[cid],row['face'],row['locale'],numeric_normalizations=d['numeric_normalizations'].get(cid))

    def test_actual_two_mana_spell_partitions_physical_deck_and_installs_permanent_program(self):
        g=self.game();before=self.ids(g);rng=g.snapshot()['rng_state'];eid=self.play(g)
        self.assertEqual(self.ids(g),[before[1],before[3],before[0],before[2]])
        self.assertEqual(g.state.players[1].mana,48);self.assertEqual(g.snapshot()['rng_state'],rng)
        instance,=g.state.players[1].player_effects;self.assertEqual((instance.spec_id,instance.source_id),(PROGRAM,eid))
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.pending_choice)
        self.assertFalse(self.own_draws(g));self.assertFalse(discovered_cards(g.state,1))

    def test_reorder_keeps_original_card_attachments_and_does_not_materialize_copies(self):
        g=self.game(hand=(BOOST,CARD));self.play(g,BOOST);original=self.ids(g);eid=original[0]
        cost=local_cost(g.state.entities[eid])[0];next_entity=g.state.next_entity_id
        self.play(g);self.assertEqual(set(self.ids(g)),set(original));self.assertEqual(g.state.next_entity_id,next_entity)
        self.assertEqual(local_cost(g.state.entities[eid])[0],cost)

    def test_all_spells_no_spells_and_empty_deck_keep_stable_order(self):
        for deck in ((S1,S2,S1),(M1,M2,M1),()):
            with self.subTest(deck=deck):
                g=self.game(deck);original=self.ids(g);self.play(g);self.assertEqual(self.ids(g),original)
                self.assertIsNone(g.state.pending_choice);self.assertFalse(self.own_draws(g))

    def test_normal_turn_top_option_draws_once_without_card_discovery(self):
        g=self.game();self.play(g);top=self.ids(g)[0];self.next_owner(g);q=g.state.pending_choice
        self.assertEqual((q.player_id,q.purpose), (1,ChoicePurpose.EFFECT))
        self.assertEqual([(o.id,o.card_id)for o in q.options],[('top',TOP),('bottom',BOTTOM)])
        self.select(g);row,=self.own_draws(g)
        self.assertEqual((row.entity_id,row.outcome,row.source_id,row.completed),(top,'hand',None,True))
        self.assertFalse(discovered_cards(g.state,1));self.assertNotIn(top,self.ids(g))

    def test_bottom_option_draws_actual_last_physical_card_without_reversing_the_deck(self):
        g=self.game();self.play(g);order=self.ids(g);rng=g.snapshot()['rng_state'];self.next_owner(g);self.select(g,'bottom')
        self.assertEqual(self.ids(g),order[:-1]);self.assertEqual(self.own_draws(g)[0].entity_id,order[-1])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.faces(g,'hand'),[M2])

    def test_extra_same_turn_draw_stays_ordinary_top_and_does_not_open_a_menu(self):
        g=self.game(hand=(CARD,EXTRA));self.play(g);top=self.ids(g)[0];self.play(g,EXTRA)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.own_draws(g)[0].entity_id,top)

    def test_program_persists_across_later_turns_and_each_turn_can_change_direction(self):
        g=self.game();self.play(g);order=self.ids(g);self.next_owner(g);self.select(g,'bottom')
        self.next_owner(g);self.select(g,'top');self.assertEqual([x.entity_id for x in self.own_draws(g)],[order[-1],order[0]])
        self.assertEqual(len(g.state.players[1].player_effects),1)

    def test_duplicate_casts_keep_instances_but_one_scheduled_draw_has_one_choice(self):
        g=self.game(hand=(CARD,CARD));self.play(g);last=self.play(g);self.next_owner(g)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.assertEqual(g.state.pending_choice.source_id,last)
        self.select(g,'bottom');self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.own_draws(g)),1)

    def test_latest_real_replacement_wins_between_spell_and_geddon_programs(self):
        for order,latest in (((CARD,GEDDON),GEDDON_PROGRAM),((GEDDON,CARD),PROGRAM)):
            with self.subTest(order=order):
                g=self.game(hand=order)
                for cid in order:self.play(g,cid)
                self.next_owner(g);self.assertEqual(g.state.players[1].player_effects[-1].spec_id,latest)
                q=g.state.pending_choice
                self.assertEqual(q.purpose,ChoicePurpose.EFFECT if latest==PROGRAM else ChoicePurpose.CARD_DISCOVERY)
                key='bottom'if latest==PROGRAM else q.options[0].id;self.select(g,key)
                self.assertIsNone(g.state.pending_choice)

    def test_automatic_spell_cast_installs_the_same_program_without_paying_the_discs_cost(self):
        g=self.game(hand=(AUTO,));self.play(g,AUTO)
        self.assertEqual(g.state.players[1].mana,50);self.assertEqual(self.faces(g),[S1,S2,M1,M2])
        self.next_owner(g);self.select(g,'bottom');self.assertEqual(self.faces(g,'hand'),[M2])

    def test_empty_deck_uses_normal_fatigue_without_a_choice(self):
        g=self.game(());self.play(g);self.next_owner(g)
        self.assertIsNone(g.state.pending_choice);row,=self.own_draws(g)
        self.assertEqual((row.outcome,row.completed),('fatigue',True))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)

    def test_one_card_still_has_two_direction_slots_and_draws_one_card(self):
        g=self.game((M1,));self.play(g);self.next_owner(g)
        self.assertEqual(len(g.state.pending_choice.options),2);self.select(g,'bottom')
        self.assertEqual(len(self.own_draws(g)),1);self.assertEqual(self.faces(g,'hand'),[M1])

    def test_full_hand_burns_bottom_card_and_does_not_substitute_a_top_card(self):
        g=self.game(hand=(CARD,FILL)+(M1,)*8);self.play(g);self.play(g,FILL)
        self.assertEqual(len(self.ids(g,'hand')),10);order=self.ids(g);self.next_owner(g);self.select(g,'bottom')
        row,=self.own_draws(g);self.assertEqual((row.entity_id,row.outcome),(order[-1],'burned'))
        self.assertEqual(self.ids(g),order[:-1]);self.assertEqual(len(self.ids(g,'hand')),10)

    def test_bottom_cast_when_drawn_uses_original_cast_and_ordinary_top_replacement(self):
        g=self.game((S1,S2,CW));self.play(g);order=self.ids(g);self.next_owner(g);self.select(g,'bottom')
        parent,child=self.own_draws(g)
        self.assertEqual((parent.entity_id,parent.outcome,parent.replacement_id),(order[-1],'cast',child.id))
        self.assertEqual((child.entity_id,child.parent_id,child.outcome),(order[0],parent.id,'hand'))
        self.assertTrue(parent.completed and child.completed);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(self.faces(g),[S2]);self.assertEqual(self.faces(g,'hand'),[S1])

    def test_original_edge_menu_and_draw_reaction_wait_restore_clone_and_replay(self):
        g=self.game(mode='wait');self.play(g);self.next_owner(g);restored=self.portable(g)
        for match in (g,restored):self.select(match,'bottom')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.pending_choice.player_id,2)
        restored=self.portable(g)
        for match in (g,restored):self.select(match,'ok')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertTrue(self.own_draws(g)[0].completed)
        self.portable(g)

    def test_cast_when_drawn_inner_choice_preserves_bottom_parent_and_top_replacement(self):
        g=self.game((S1,S2,CW),mode='cw_wait');self.play(g);self.next_owner(g);self.select(g,'bottom')
        self.assertEqual(g.state.pending_choice.player_id,2);self.assertEqual(self.own_draws(g)[0].outcome,'cast')
        restored=self.portable(g)
        for match in (g,restored):self.select(match,'ok')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.faces(g,'hand'),[S1])

    def test_draw_reaction_failure_rolls_back_original_choice_deck_rng_and_draw_history(self):
        g=self.game(mode='fail');self.play(g);self.next_owner(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'bottom')
        self.assertEqual(g.snapshot(),before)

    def test_second_wait_failure_rolls_back_only_its_choice(self):
        g=self.game(mode='wait');self.play(g);self.next_owner(g);self.select(g,'bottom');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),before);self.select(g,'ok');self.assertTrue(self.own_draws(g)[0].completed)

    def test_other_seat_has_its_own_program_menu_and_deck(self):
        g=self.game(pid=2);self.play(g);order=self.ids(g);self.next_owner(g)
        self.assertEqual(g.state.pending_choice.player_id,2);self.select(g,'bottom')
        self.assertEqual(self.own_draws(g)[0].entity_id,order[-1]);self.assertFalse(g.state.players[1].player_effects)

    def test_public_bottom_draw_request_uses_real_fatigue_when_empty(self):
        g=self.game((),hand=(DIRECT,));self.play(g,DIRECT)
        self.assertEqual(self.own_draws(g)[0].outcome,'fatigue');self.assertTrue(self.own_draws(g)[0].completed)

    def test_edge_request_codec_and_finite_validation_reject_unknown_or_boolean_values(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry);request=DrawDeckEdge(1,'bottom')
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(request)))),request)
        for args in ((1,'middle'),(1,''),(1,None),(1,True),(True,'top'),(3,'bottom'),(1,'top',True)):
            with self.subTest(args=args),self.assertRaises(ValueError):DrawDeckEdge(*args)

    def test_rehashed_unknown_edge_and_missing_branch_are_rejected_on_restore(self):
        g=self.game();self.play(g);self.next_owner(g)
        for kind in ('edge','branch'):
            saved=deepcopy(g.snapshot());changed=[]
            def visit(v):
                if isinstance(v,dict):
                    if v.get('type','').endswith('.DrawDeckEdge')and kind=='edge'and not changed:
                        v['fields']['edge']='middle';changed.append(True)
                    for x in v.values():visit(x)
                elif isinstance(v,list):
                    for x in v:visit(x)
            visit(saved)
            if kind=='branch':saved['resolution_frame']['fields']['options']['tuple'].pop();changed.append(True)
            self.assertTrue(changed)
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry(self.mode,'reader'))

    def test_player_opaque_command_hides_physical_deck_order_and_original_draw_work(self):
        g=self.game();self.play(g);self.next_owner(g)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('draw_history','rng_state','resolution_frame','edge','entity_ids'):
                self.assertNotIn('"'+key+'"',visible)
        port=g.for_player(1);commands=port.legal_actions()
        command=next(c for c in commands['actions']if c['type']=='select_choice')
        port.submit({'revision':commands['revision'],'action':command});self.assertEqual(len(self.own_draws(g)),1)


if __name__=='__main__':unittest.main()
