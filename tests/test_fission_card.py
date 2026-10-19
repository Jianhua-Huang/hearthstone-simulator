"""Real Divergence entry and the finite shared hand-minion split contract."""
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.fission_card import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption, Destroy, InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_minion_split import SplitRandomHandMinion
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, TargetSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest

P = 'divergence.test.'
PLAIN = 'CORE_CS2_182'
ARCHER = 'CORE_CS2_189'
HOARDER = 'CORE_EX1_096'
ODD = P+'odd'
EVEN = P+'even'
ZERO = P+'zero'
ONE = P+'one'


@lru_cache(None)
def registry(mode=None):
    r = build_registry()
    for cid,cost,attack,health in ((ODD,5,5,5),(EVEN,6,6,6),(ZERO,0,0,1),(ONE,1,1,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Divergence deliberate failure')))
    r.register_behavior(P+'boost', lambda c: (BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),
        3,5,c.source_id,cost=CostSpec(delta=-2)),))
    r.register_behavior(P+'copy', lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]),
        c.player_id,source_id=c.source_id),))
    r.register_behavior(P+'base', lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]),
        c.player_id,mode='base',source_id=c.source_id),))
    r.register_behavior(P+'destroy', lambda c: (Destroy(c.target_id,c.source_id),))
    for name in ('boost','copy','base','destroy'):
        target = TargetSpec(zones=(Zone.BOARD if name=='destroy' else Zone.HAND,),
            kinds=(CardType.MINION,),relation='friendly')
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,cost=1,on_play=P+name,targeting=target))
    if mode:
        def watch(c):
            if c.event.player_id != c.player_id:
                return ()
            if mode=='auto':
                return (CastSpell(c.player_id,CARD,c.source_id),)
            target=c.state.entities.get(c.event.target_id)
            if target is None or target.origin_entity_id is None:
                return ()
            if mode=='fail':
                return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='grow_first':
                copies=[e for e in c.state.entities.values() if e.origin_entity_id==target.origin_entity_id]
                return (BuffStoredCard(CardReference.capture(target),10,10,c.source_id),) if len(copies)==1 else ()
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=20,
            triggers=(TriggerSpec('turn_ended' if mode=='auto' else 'card_added_to_hand',P+'watch'),)))
    r.validate()
    return r


class FissionCardTests(unittest.TestCase):
    def game(self,hand=(CARD,ODD),*,other_hand=(),deck=(),mode=None,seat=1,seed=280):
        own=PlayerSetup('HERO_08',hand=hand,deck=deck,board=(P+'watch',) if mode else (),
            mana=50,max_mana=50,mana_cap=50)
        other=PlayerSetup('HERO_08',hand=other_hand,mana=50,max_mana=50,mana_cap=50)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),
            active_player=seat,seed=seed),registry(mode))

    def eid(self,g,cid):
        return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)

    def play(self,g,cid=None,*,eid=None,target=None):
        eid=self.eid(g,cid) if eid is None else eid
        seat=g.state.active_player
        definition=g.registry.card(g.state.entities[eid].card_id)
        g.apply(PlayCard(seat,eid,target_id=target,
            position=len(g.state.players[seat].board) if definition.kind==CardType.MINION else None))
        return eid

    def copies(self,g,original):
        return sorted((e for e in g.state.entities.values() if e.origin_entity_id==original),key=lambda e:e.id)

    def choose(self,g,key='ok'):
        q=g.state.pending_choice
        g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g,mode=None):
        snapshot=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(snapshot,registry.__wrapped__(mode))
        self.assertEqual(other.snapshot(),snapshot)
        self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(mode)).snapshot(),snapshot)
        return other

    def test_a01_complete_source_enchantments_and_actual_shadow_spell(self):
        data=load_batch()
        self.assertEqual([x['record']['id'] for x in data['evidence_only']],['TIME_030e1','TIME_030e2'])
        for row in (*data['cards'],*data['evidence_only']):
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        card=registry().card(CARD)
        self.assertEqual((card.cost,card.spell_school.value),(5,'shadow'))
        self.assertEqual(len(data['official_observations']),2)

    def test_a02_real_paid_entry_replaces_original_with_two_independent_copies(self):
        g=self.game(hand=(CARD,PLAIN));original=self.eid(g,PLAIN)
        self.play(g,CARD);copies=self.copies(g,original)
        self.assertEqual(len(copies),2)
        self.assertEqual([(e.cost,e.attack) for e in copies],[(2,2),(2,2)])
        self.assertEqual(sorted(e.max_health for e in copies),[2,3])
        self.assertEqual(g.state.players[1].mana,45)
        self.assertEqual(g.state.entities[original].zone,Zone.SETASIDE)
        self.assertEqual(len(g.state.players[1].hand),2)
        self.assertEqual(len(g.state.cast_history),1)

    def test_a03_empty_pool_does_not_draw_rng_or_touch_enemy_minion(self):
        for seat in (1,2):
            g=self.game(hand=(CARD,P+'copy'),other_hand=(PLAIN,),seat=seat)
            before=g._rng.getstate();other=g.state.players[3-seat].hand[:]
            self.play(g,CARD)
            self.assertEqual(g._rng.getstate(),before)
            self.assertEqual(g.state.players[3-seat].hand,other)
            self.assertEqual(len(g.state.players[seat].hand),1)

    def test_a04_odd_operands_each_preserve_their_own_sum_and_frozen_rng_order(self):
        for seed in (1,2,3):
            g=self.game(seed=seed);original=self.eid(g,ODD)
            local=Random();local.setstate(g._rng.getstate());self.assertEqual(local.choice((original,)),original)
            for _ in range(3):local.randrange(2)
            self.play(g,CARD)
            copies=self.copies(g,original)
            for field in ('cost','attack','max_health'):
                self.assertEqual(sorted(getattr(e,field) for e in copies),[2,3])
            self.assertEqual(g._rng.getstate(),local.getstate())

    def test_a05_even_operands_do_not_consume_remainder_randomness(self):
        g=self.game(hand=(CARD,EVEN));original=self.eid(g,EVEN)
        local=Random();local.setstate(g._rng.getstate());local.choice((original,))
        self.play(g,CARD)
        self.assertEqual([(e.cost,e.attack,e.max_health) for e in self.copies(g,original)],[(3,3,3)]*2)
        self.assertEqual(g._rng.getstate(),local.getstate())

    def test_a06_zero_cost_and_attack_remain_zero_and_one_health_remains_playable(self):
        g=self.game(hand=(CARD,ZERO));original=self.eid(g,ZERO)
        self.play(g,CARD)
        copies=self.copies(g,original)
        self.assertEqual([(e.cost,e.attack,e.max_health) for e in copies],[(0,0,1)]*2)
        self.play(g,eid=copies[0].id)
        self.assertEqual(g.state.entities[copies[0].id].zone,Zone.BOARD)
        self.assertEqual(g.state.entities[copies[0].id].health,1)

    def test_a07_one_cost_and_attack_allocate_zero_and_one_independently(self):
        g=self.game(hand=(CARD,ONE));original=self.eid(g,ONE);self.play(g,CARD)
        copies=self.copies(g,original)
        self.assertEqual(sorted(e.cost for e in copies),[0,1])
        self.assertEqual(sorted(e.attack for e in copies),[0,1])
        self.assertEqual([e.max_health for e in copies],[1,1])

    def test_a08_current_buffs_cost_and_attachment_sources_are_copied_before_sets(self):
        g=self.game(hand=(CARD,ODD,P+'boost'));original=self.eid(g,ODD)
        self.play(g,P+'boost',target=original)
        original_ids={e.id for e in g.state.entities[original].enchantments}
        self.play(g,CARD);copies=self.copies(g,original)
        self.assertEqual(sorted(e.cost for e in copies),[1,2])
        self.assertEqual([(e.attack,e.max_health) for e in copies],[(4,5)]*2)
        a,b=({e.id for e in value.enchantments} for value in copies)
        self.assertFalse(a&b or a&original_ids or b&original_ids)
        self.assertTrue(all(any(e.label=='stored_buff' and e.attack==3 and e.health==5 for e in c.enchantments) for c in copies))

    def test_a09_replacement_does_not_fabricate_draw_discard_destruction_burn_or_death(self):
        g=self.game(hand=(CARD,HOARDER));original=self.eid(g,HOARDER)
        self.play(g,CARD)
        kinds={e.kind for e in g.events if e.target_id==original}
        self.assertFalse(kinds & {'card_drawn','card_discarded','card_burned','card_destroyed_in_hand','minion_died'})
        self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.discard_history)
        self.assertEqual(g.state.entities[original].zone,Zone.SETASIDE)

    def test_a10_copied_real_battlecry_runs_only_when_the_copy_is_played(self):
        g=self.game(hand=(CARD,ARCHER));original=self.eid(g,ARCHER)
        enemy=g.state.players[2].hero_id;self.play(g,CARD)
        self.assertEqual(g.state.entities[enemy].health,30)
        self.play(g,eid=self.copies(g,original)[0].id,target=enemy)
        self.assertEqual(g.state.entities[enemy].health,29)
        self.assertEqual(len(g.state.cast_history),1)

    def test_a11_copied_real_deathrattle_runs_once_after_ordinary_board_death(self):
        g=self.game(hand=(CARD,HOARDER,P+'destroy'),deck=(PLAIN,));original=self.eid(g,HOARDER)
        self.play(g,CARD);copy=self.copies(g,original)[0]
        self.assertEqual(len(g.state.players[1].deck),1)
        self.play(g,eid=copy.id);self.play(g,P+'destroy',target=copy.id)
        self.assertEqual(len(g.state.players[1].deck),0)
        self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(g.state.death_history[0].entity_id,copy.id)

    def test_a12_real_play_from_full_hand_has_room_for_both_halves(self):
        g=self.game(hand=(CARD,EVEN,*([P+'copy']*8)));original=self.eid(g,EVEN)
        self.play(g,CARD)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual([e.zone for e in self.copies(g,original)],[Zone.HAND,Zone.HAND])

    def test_a13_automatic_cast_at_full_hand_uses_normal_second_copy_overflow(self):
        g=self.game(hand=(EVEN,*([P+'copy']*9)),mode='auto');original=self.eid(g,EVEN)
        g.apply(EndTurn(1));copies=self.copies(g,original)
        self.assertEqual([e.zone for e in copies],[Zone.HAND,Zone.GRAVEYARD])
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned' and e.target_id==copies[1].id]),1)
        self.assertEqual(len(g.state.cast_history),1)

    def test_a14_waiting_between_deliveries_restores_frozen_second_copy_without_resampling(self):
        g=self.game(mode='wait');original=self.eid(g,ODD);self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[original].zone,Zone.SETASIDE)
        self.assertEqual(len(self.copies(g,original)),1)
        other=self.portable(g,'wait');rng=g._rng.getstate()
        for value in (g,other):
            while value.state.pending_choice is not None:self.choose(value)
        self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(self.copies(g,original)),2)
        self.portable(g,'wait')

    def test_a15_bad_continuation_rolls_back_to_the_same_waiting_boundary(self):
        g=self.game(mode='wait');self.play(g,CARD);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(g)

    def test_a16_failed_acquisition_rolls_back_payment_original_entities_and_rng(self):
        g=self.game(mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_a17_first_copy_reaction_cannot_mutate_the_frozen_second_material(self):
        g=self.game(hand=(CARD,EVEN),mode='grow_first');original=self.eid(g,EVEN)
        self.play(g,CARD);copies=self.copies(g,original)
        self.assertEqual([(e.attack,e.max_health) for e in copies],[(13,13),(3,3)])

    def test_a18_current_copy_preserves_split_sets_but_base_copy_uses_printed_stats(self):
        g=self.game(hand=(CARD,EVEN,P+'copy',P+'base'));original=self.eid(g,EVEN)
        self.play(g,CARD);half=self.copies(g,original)[0]
        self.play(g,P+'copy',target=half.id);current=self.copies(g,half.id)[0]
        self.play(g,P+'base',target=half.id);base=self.copies(g,half.id)[-1]
        self.assertEqual((current.cost,current.attack,current.max_health),(3,3,3))
        self.assertEqual((base.cost,base.attack,base.max_health),(6,6,6))

    def test_a19_second_player_and_enemy_hidden_material_are_isolated(self):
        g=self.game(hand=(CARD,PLAIN),seat=2);original=self.eid(g,PLAIN);self.play(g,CARD)
        self.assertEqual([e.controller for e in self.copies(g,original)],[2,2])
        visible=json.dumps(g.for_player(1).observe())+json.dumps(g.player_events(1))
        self.assertNotIn(PLAIN,visible)
        view=g.for_player(1).observe()['observation']
        self.assertTrue(all(e['card_id'] is None for e in view['players'][1]['hand']))

    def test_a20_countered_real_spell_does_not_select_or_replace_a_minion(self):
        g=self.game(other_hand=('CORE_EX1_287',));original=self.eid(g,ODD)
        g.apply(EndTurn(1));self.play(g,'CORE_EX1_287');g.apply(EndTurn(2))
        before=g._rng.getstate();self.play(g,CARD)
        self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        self.assertFalse(self.copies(g,original))

    def test_a21_repeated_split_reuses_current_halves_and_preserves_total_even_stats(self):
        g=self.game(hand=(CARD,CARD,EVEN));self.play(g,CARD);self.play(g,CARD)
        values=[g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual(len(values),3)
        self.assertEqual((sum(e.cost for e in values),sum(e.attack for e in values),sum(e.max_health for e in values)),(6,6,6))
        self.portable(g)

    def test_a22_effect_has_typed_finite_operands_and_existing_frame_codec_support(self):
        g=self.game();effect=SplitRandomHandMinion(1,self.eid(g,CARD))
        codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        for args in ((True,), (3,), (1,0), (1,True)):
            with self.assertRaises(ValueError):SplitRandomHandMinion(*args)


if __name__=='__main__':
    unittest.main()
