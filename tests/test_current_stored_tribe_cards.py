"""Native Dinositter and explicit current/printed stored minion filtering."""
from copy import deepcopy
from dataclasses import replace
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.current_stored_tribe_cards import DINOSITTER, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, InvokeBehavior,
    RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, TribeChangeSpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes, has_any_tribe
from hs_sim.engine.zones import CardReference

YETI='CORE_CS2_182'


def registry():
    r=build_registry();meta=r.card(YETI).metadata
    for key,tribes in [('plain',()),('beast',('beast',)),('dual',('beast','dragon')),('all',('all',)),('unknown',None)]:
        r.register_card(CardDefinition('k90.'+key,key,CardType.MINION,cost=4,attack=1,health=5,
                                       metadata=replace(meta,collectible=False,tribes=tribes,deck_identity='k90.'+key)))
    r.register_behavior('k90.fail',lambda c:(AddToHand(c.player_id,'unknown.k90'),))
    def wait(c):
        return RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('bad','Fail',(InvokeBehavior('k90.fail',c.source_id,c.player_id),)),
        ),source_id=c.source_id)
    def find(c,cid,zone='hand'):
        return next(c.state.entities[i]for i in getattr(c.state.players[c.player_id],zone)
                    if c.state.entities[i].card_id==cid)
    def change(c,cid,operation,tribes):
        return (ChangeMinionTribes(CardReference.capture(find(c,cid)),TribeChangeSpec(operation,tribes),c.source_id),)
    def buff(c,basis='printed',pause=False):
        effect=RandomBuffStoredMinion(c.player_id,query=PoolQuery(tribes_any=('beast',)),
            source_id=c.source_id,cost=CostSpec(delta=-1),tribe_basis=basis)
        return (wait(c),effect)if pause else(effect,)
    scripts={
        'become':lambda c:change(c,'k90.plain','set',('beast',)),
        'known':lambda c:change(c,'k90.unknown','set',('beast',)),
        'remove':lambda c:change(c,'k90.beast','remove',('beast',)),
        'exclude':lambda c:change(c,'k90.all','remove',('beast',)),
        'printed':lambda c:buff(c),
        'current':lambda c:buff(c,'current'),
        'pause':lambda c:buff(c,'current',True),
        'silence':lambda c:(Silence(find(c,DINOSITTER,'board').id),),
        'take':lambda c:(ChangeControl(find(c,DINOSITTER,'board').id,2),),
    }
    for name,body in scripts.items():
        r.register_behavior('k90.'+name,body)
        r.register_card(CardDefinition('k90.'+name,name,CardType.SPELL,on_play='k90.'+name))
    r.register_behavior('k90.watch',lambda c:(wait(c),) if c.event.source_id is not None
        and c.state.entities[c.event.source_id].card_id==DINOSITTER else())
    r.register_card(CardDefinition('k90.watch','Cost reward observer',CardType.MINION,health=8,
                                   triggers=(TriggerSpec('stored_card_buffed','k90.watch'),)))
    return r


class CurrentStoredTribeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()

    def game(self,hand=('k90.beast',),board=(DINOSITTER,),enemy_hand=(),deck=(YETI,)*8):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(YETI,)*8,mana=10,max_mana=10),
        ),seed=90),self.r)

    def entity(self,g,cid,player=1,zone='hand'):
        return next(g.state.entities[i]for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)

    def cost(self,g,cid,player=1,zone='hand'):
        return quote_unselected_cost(g.state,self.r,self.entity(g,cid,player,zone)).amount

    def play(self,g,cid):
        eid=self.entity(g,cid).id;g.apply(PlayCard(1,eid));return eid

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for hidden in('tribe_basis','CardReference','rng_state','resolution_frame','behavior_id'):
                self.assertNotIn(hidden,public)
        return other

    def test_complete_actual_source_has_two_full_official_faces(self):
        raw,=load_batch()['cards'];card=self.r.card(DINOSITTER)
        self.assertEqual((raw['record']['dbf_id'],card.cost,card.attack,card.health),(117574,2,2,3))
        self.assertEqual(len(load_batch()['official_observations']['observations']),2)
        self.assertIsNone(card.battlecry)

    def test_native_owner_end_discounts_current_beast_not_printed_nonbeast(self):
        g=self.game(('k90.become','k90.plain'));self.play(g,'k90.become')
        self.assertTrue(has_any_tribe(self.r,self.entity(g,'k90.plain'),('beast',)))
        self.assertEqual(self.r.card('k90.plain').metadata.tribes,())
        g.apply(EndTurn(1));self.assertEqual(self.cost(g,'k90.plain'),3);self.portable(g)

    def test_removed_printed_beast_is_not_current_candidate_and_consumes_no_rng(self):
        g=self.game(('k90.remove','k90.beast'));self.play(g,'k90.remove')
        before=g._rng.getstate();g.apply(EndTurn(1))
        self.assertEqual(self.cost(g,'k90.beast'),4);self.assertEqual(g._rng.getstate(),before)

    def test_all_tribes_matches_but_explicit_beast_exclusion_does_not(self):
        g=self.game(('k90.all',));g.apply(EndTurn(1));self.assertEqual(self.cost(g,'k90.all'),3)
        h=self.game(('k90.exclude','k90.all'));self.play(h,'k90.exclude');before=h._rng.getstate()
        h.apply(EndTurn(1));self.assertEqual(self.cost(h,'k90.all'),4);self.assertEqual(h._rng.getstate(),before)

    def test_full_dual_tribe_member_is_eligible(self):
        g=self.game(('k90.dual',));g.apply(EndTurn(1));self.assertEqual(self.cost(g,'k90.dual'),3)

    def test_default_printed_basis_keeps_existing_callers_semantics(self):
        g=self.game(('k90.remove','k90.printed','k90.beast'),board=())
        self.play(g,'k90.remove');self.play(g,'k90.printed');self.assertEqual(self.cost(g,'k90.beast'),3)
        h=self.game(('k90.become','k90.printed','k90.plain'),board=())
        self.play(h,'k90.become');before=h._rng.getstate();self.play(h,'k90.printed')
        self.assertEqual(self.cost(h,'k90.plain'),4);self.assertEqual(h._rng.getstate(),before)
        self.assertEqual(RandomBuffStoredMinion(1).tribe_basis,'printed')

    def test_unknown_current_tribes_fail_explicitly_and_roll_back_whole_end(self):
        g=self.game(('k90.unknown',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unknown current tribe'):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),before)

    def test_complete_current_set_resolves_unknown_printed_tribes(self):
        g=self.game(('k90.known','k90.unknown'));self.play(g,'k90.known')
        g.apply(EndTurn(1));self.assertEqual(self.cost(g,'k90.unknown'),3)

    def test_owner_hand_only_excludes_deck_board_opponent_and_opponent_end(self):
        g=self.game(('k90.beast',),board=(DINOSITTER,'k90.beast'),enemy_hand=('k90.beast',),deck=('k90.beast',))
        g.apply(EndTurn(1));self.assertEqual(self.cost(g,'k90.beast'),3)
        self.assertEqual(self.cost(g,'k90.beast',2),4);self.assertEqual(self.cost(g,'k90.beast',zone='deck'),4)
        g.apply(EndTurn(2));self.assertEqual(self.cost(g,'k90.beast'),3)

    def test_each_physical_hand_copy_keeps_one_random_weight(self):
        g=self.game(('k90.beast','k90.beast'));rng=Random();rng.setstate(g._rng.getstate())
        ids=tuple(g.state.players[1].hand);selected=rng.choice(ids);g.apply(EndTurn(1))
        self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual({i:quote_unselected_cost(g.state,self.r,g.state.entities[i]).amount for i in ids},
                         {i:3 if i==selected else 4 for i in ids})

    def test_empty_candidate_pool_is_noop_without_rng(self):
        g=self.game((YETI,));before=g._rng.getstate();g.apply(EndTurn(1))
        self.assertEqual(g._rng.getstate(),before);self.assertEqual(self.cost(g,YETI),4)

    def test_silence_removes_future_end_discount(self):
        g=self.game(('k90.silence','k90.beast'));self.play(g,'k90.silence')
        g.apply(EndTurn(1));self.assertEqual(self.cost(g,'k90.beast'),4)

    def test_control_transfer_changes_actual_end_beneficiary(self):
        g=self.game(('k90.take','k90.beast'),enemy_hand=('k90.beast',));self.play(g,'k90.take')
        g.apply(EndTurn(1));self.assertEqual(self.cost(g,'k90.beast'),4)
        g.apply(EndTurn(2));self.assertEqual(self.cost(g,'k90.beast',2),3);self.portable(g)

    def test_repeated_owner_ends_use_common_cost_floor(self):
        g=self.game(('k90.beast',))
        for index in range(5):
            g.apply(EndTurn(1))
            self.assertEqual(self.cost(g,'k90.beast'),max(0,3-index))
            if index<4:g.apply(EndTurn(2))

    def test_new_basis_waiting_effect_restores_before_selection_and_rng(self):
        g=self.game(('k90.become','k90.pause','k90.plain'),board=())
        self.play(g,'k90.become');before=g._rng.getstate();self.play(g,'k90.pause')
        self.assertEqual(g._rng.getstate(),before);other=self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.cost(g,'k90.plain'),3)

    def test_rehashed_unknown_basis_in_pending_effect_is_rejected(self):
        g=self.game(('k90.pause','k90.beast'),board=());self.play(g,'k90.pause');saved=deepcopy(g.snapshot())
        def corrupt(value):
            count=0
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=='tribe_basis':value[key]='future';count+=1
                    else:count+=corrupt(item)
            elif isinstance(value,list):
                for item in value:count+=corrupt(item)
            return count
        self.assertGreater(corrupt(saved['resolution_frame']),0)
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(saved,registry())
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_invalid_basis_declarations_are_rejected(self):
        for value in(None,True,'CURRENT','future'):
            with self.assertRaisesRegex(ValueError,'tribe basis'):RandomBuffStoredMinion(1,tribe_basis=value)
