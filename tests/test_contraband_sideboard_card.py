"""Native original contraband construction, physical delivery and isolation."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.contraband_sideboard_card import ROOT, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    ChoicePurpose, ContrabandSideboardProfile, DeckPolicy, DeckSpec, EndTurn,
    Game, MatchSetup, OpeningHook, PlayCard, PlayerSetup, Rarity, Runes,
    Scenario, SelectChoice, SideboardProfile, SideboardSpec, SnapshotError,
    TriggerSpec, Zone, validate_deck)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption,
    InvokeBehavior, RandomDamage, RefreshMana, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonEntryMaterial, SummonCause
from hs_sim.engine.zones import CardReference, MoveCard

P = 'contraband.test.'
A, B, C = MEMBERS = tuple(P+x for x in ('priest', 'druid', 'dk'))
PREP, WATCH, FULL, BAD, BAND = (P+x for x in ('prepare', 'watch', 'full', 'bad', 'band'))
FILLERS = tuple(P+'filler.'+str(i) for i in range(30))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    neutral = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
    beast = lambda cls, **kw: CardMetadata(True, (cls,), Rarity.COMMON, tribes=('beast',), **kw)
    for cid, cls, cost, runes in ((A,CardClass.PRIEST,2,None),
            (B,CardClass.DRUID,5,None),(C,CardClass.DEATH_KNIGHT,6,Runes(unholy=2))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=3,
            metadata=beast(cls,runes=runes)))
    variants = (
        ('own',beast(CardClass.HUNTER)), ('neutral',beast(CardClass.NEUTRAL)),
        ('all',replace(beast(CardClass.WARRIOR),tribes=('all',))),
        ('dual',replace(beast(CardClass.ROGUE),classes=(CardClass.ROGUE,CardClass.WARRIOR))),
        ('unknown',replace(beast(CardClass.PRIEST),tribes=None)),
        ('token',replace(beast(CardClass.PRIEST),collectible=False)),
        ('alias',replace(beast(CardClass.PRIEST),deck_identity=A)),
    )
    for suffix, meta in variants:
        r.register_card(CardDefinition(P+suffix,P+suffix,CardType.MINION,health=3,metadata=meta))
    r.register_card(CardDefinition(P+'spell',P+'spell',CardType.SPELL,metadata=beast(CardClass.MAGE)))
    r.register_behavior(P+'noop',lambda c: ())
    r.register_card(CardDefinition(BAND,BAND,CardType.MINION,health=2,battlecry=P+'noop',
        metadata=replace(neutral,rarity=Rarity.LEGENDARY)))
    r.register_sideboard(SideboardProfile(BAND))
    def fail(c):raise ResolutionError('Contraband deliberate rollback')
    r.register_behavior(P+'fail',fail)
    def prepare(c):
        player=c.state.players[c.player_id]
        original=c.state.opening.original_entities[c.player_id-1]
        source=next(c.state.entities[eid] for eid in original if c.state.entities[eid].card_id==ROOT)
        work=(ChangeManaCrystals(c.player_id,9,filled=True),RefreshMana(c.player_id,20))
        return work+((MoveCard(CardReference.capture(source),c.player_id,Zone.HAND,source_id=c.source_id),)
            if source.zone==Zone.DECK else ())+tuple(AddToHand(c.player_id,cid,c.source_id) for cid in FILLERS[-2:])
    r.register_behavior(P+'prepare',prepare)
    r.register_card(CardDefinition(PREP,PREP,CardType.MINION,health=2,metadata=neutral,
        opening_hooks=(OpeningHook('after_mulligan',P+'prepare'),)))
    def menu(c):
        source=next((eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id==ROOT),None)
        bounce=() if source is None else (ReturnToHand(source),RefreshMana(c.player_id,20))
        return (RequestChoice(c.player_id,(
            ChoiceOption('watch','Observe acquisition',(AddToHand(c.player_id,WATCH,c.source_id),)),
            ChoiceOption('full','Fill after actual selection',(AddToHand(c.player_id,FULL,c.source_id),)),
            ChoiceOption('bad','Fail acquisition',(AddToHand(c.player_id,BAD,c.source_id),)),
            ChoiceOption('bounce','Return original King',bounce),
            ChoiceOption('summon','Summon without Battlecry',(SummonByCard(c.player_id,
                (SummonEntryMaterial(ROOT),),SummonCause.capture(c)),)),
        ),c.source_id),)
    r.register_behavior(P+'menu',menu)
    for cid in FILLERS:
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=2,on_play=P+'menu',metadata=neutral))
    def watched(c):
        if c.event.player_id!=c.player_id or c.event.target_id is None:return ()
        if c.state.entities[c.event.target_id].card_id not in MEMBERS:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'watch',watched)
    def full(c):
        if c.event.player_id!=c.player_id or dict(c.event.data).get('purpose')!=ChoicePurpose.CARD_DISCOVERY.value:return ()
        return tuple(AddToHand(c.player_id,FILLERS[0],c.source_id)
            for _ in range(10-len(c.state.players[c.player_id].hand)))
    r.register_behavior(P+'full',full)
    def bad(c):
        if c.event.player_id==c.player_id and c.event.target_id is not None and c.state.entities[c.event.target_id].card_id in MEMBERS:
            return (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id))
        return ()
    r.register_behavior(P+'bad',bad)
    for cid,event,body in ((WATCH,'card_added_to_hand',P+'watch'),(FULL,'choice_selected',P+'full'),(BAD,'card_added_to_hand',P+'bad')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=8,metadata=replace(neutral,collectible=False),
            triggers=(TriggerSpec(event,body),)))
    r.validate();r.freeze();return r


class ContrabandSideboardTests(unittest.TestCase):
    def deck(self,members=MEMBERS,*,extra=(),bands=None):
        cards=(ROOT,PREP,*extra,*FILLERS[:28-len(extra)])
        return DeckSpec('HERO_05','HERO_05bp',CardClass.HUNTER,cards,
            sideboards=(SideboardSpec(ROOT,members),) if bands is None else bands)
    def policy(self,r=None,**kw):
        r=r or registry('writer')
        return DeckPolicy(P+'policy','cn37-explicit-contraband-fixture','experimental',tuple(r.cards),**kw)
    def codes(self,deck,**kw):return {i.code for i in validate_deck(deck,registry('writer'),self.policy(**kw)).issues}
    def opening(self,*,both=False,complete=True):
        r=registry('writer')
        other=self.deck(tuple(reversed(MEMBERS))) if both else DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,FILLERS)
        g=Game.from_decks(MatchSetup((self.deck(),other),self.policy(r),'GAME_005',seed=246831,first_player=1),r)
        if complete:self.finish(g)
        return g
    def finish(self,g):
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;self.assertIn('mulligan',str(q.purpose))
            g.apply(SelectChoice(q.player_id,q.id,()))
    def play(self,g,cid):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(pid,eid))
    def choose(self,g,key):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def seed(self,g,key,play=False):
        cid=next(g.state.entities[i].card_id for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id in FILLERS)
        self.play(g,cid);self.choose(g,key)
        if play:self.play(g,dict(watch=WATCH,full=FULL,bad=BAD)[key])
    def band(self,g,pid=1):return next(b for b in g.state.players[pid].sideboards if b.source_card_id==ROOT)
    def portable(self,g):
        r=registry('reader' if g.registry is registry('writer') else 'writer')
        snapshot=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snapshot,r)
        self.assertEqual(other.snapshot(),snapshot)
        self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),r).snapshot(),snapshot)
        return other

    def test_a00_complete_raw_and_two_primary_faces_preserve_original_subset_and_class_flag(self):
        from tools.card_batch import check_face
        d=load_batch();raw=d['cards'][0]['record']
        for row in d['official_observations']:check_face(raw,row['face'],row['locale'])
        self.assertEqual((raw['cost'],raw['attack'],raw['health'],raw['tags']['ALLOWED_SIDEBOARD_SUBSET']),(6,6,5,19499))
        self.assertEqual(raw['tags']['SIDEBOARD_IGNORES_CLASS_RULE'],1)

    def test_a01_only_exact_reviewed_profile_shape_is_accepted(self):
        p=ContrabandSideboardProfile(ROOT)
        for kw in (dict(max_cards=True),dict(max_cards=2),dict(cost_reduction=2),dict(cost_reduction=True),dict(version='other')):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(p,**kw)
        self.assertEqual(registry('writer').sideboards[ROOT],p)

    def test_a02_exact_three_original_members_and_source_configuration_are_required(self):
        self.assertFalse(self.codes(self.deck()))
        for members in ((),MEMBERS[:1],MEMBERS[:2],(*MEMBERS,A)):
            with self.subTest(members=members):self.assertIn('contraband_selection',self.codes(self.deck(members)))
        self.assertIn('contraband_selection',self.codes(self.deck(bands=())))

    def test_a03_foreign_single_class_printed_beasts_only_and_unknown_members_fail_explicitly(self):
        for cid in (P+'own',P+'neutral',P+'dual',P+'spell',P+'unknown','missing.contraband'):
            with self.subTest(cid=cid):self.assertIn('contraband_selection',self.codes(self.deck((cid,B,C))))
        self.assertIn('uncollectible',self.codes(self.deck((P+'token',B,C))))

    def test_a04_foreign_death_knight_runes_and_all_tribe_input_use_scoped_exemption(self):
        self.assertFalse(self.codes(self.deck()))
        self.assertFalse(self.codes(self.deck((P+'all',B,C))))
        self.assertIsNone(self.deck().runes)

    def test_a05_format_bans_and_aggregate_copy_identity_remain_in_force(self):
        self.assertIn('format_legality',self.codes(self.deck(),banned_card_ids=(A,)))
        self.assertIn('copy_limit',self.codes(self.deck((A,A,A))))
        self.assertIn('copy_limit',self.codes(self.deck((A,A,P+'alias'))))

    def test_a06_same_card_in_main_deck_or_ordinary_band_does_not_inherit_exemption(self):
        self.assertIn('class',self.codes(self.deck(extra=(A,))))
        codes=self.codes(self.deck(extra=(C,)))
        self.assertIn('class',codes);self.assertIn('rune_requirements',codes)
        bands=(SideboardSpec(ROOT,MEMBERS),SideboardSpec(BAND,(A,)))
        self.assertIn('class',self.codes(self.deck(extra=(BAND,),bands=bands)))

    def test_b00_actual_original_king_pays_once_then_delivers_selected_discounted_new_entity(self):
        g=self.opening();before=g.state.players[1].mana
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==ROOT)
        self.assertIn(source,g.state.opening.original_entities[0]);self.play(g,ROOT)
        self.assertEqual(g.state.players[1].mana,before-6)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.CARD_DISCOVERY)
        self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),MEMBERS)
        self.assertFalse(self.band(g).taken_slots);self.choose(g,'band:1')
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==B)
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,2)
        self.assertEqual(g.state.players[1].mana,before-6);self.assertEqual(self.band(g).taken_slots,(1,))
        self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(sum(e.kind=='card_discovered' for e in g._events),1)
        self.portable(g)

    def test_b01_original_members_are_not_entities_or_part_of_main_deck(self):
        g=self.opening();before=tuple(g.state.players[1].deck)
        self.assertFalse(any(e.card_id in MEMBERS for e in g.state.entities.values()))
        self.assertFalse(set(MEMBERS).intersection(g.state.players[1].original_deck))
        self.play(g,ROOT);self.choose(g,'band:0')
        self.assertEqual(tuple(g.state.players[1].deck),before)
        self.assertEqual(sum(e.card_id in MEMBERS for e in g.state.entities.values()),1)
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==A)
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,0)

    def test_b02_repeated_battlecries_share_original_slots_and_exhaust_without_rng(self):
        g=self.opening()
        for slot in range(3):
            self.play(g,ROOT);self.assertEqual(tuple(o.id for o in g.state.pending_choice.options),tuple(f'band:{i}' for i in range(slot,3)))
            self.choose(g,f'band:{slot}');self.seed(g,'bounce')
        before=g.snapshot()['rng_state'];self.play(g,ROOT)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(self.band(g).taken_slots,(0,1,2));self.portable(g)

    def test_b03_generated_king_without_original_sideboard_has_no_fabricated_candidates(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(ROOT,),mana=10,max_mana=10),PlayerSetup('HERO_08'))),registry('writer'))
        self.play(g,ROOT);self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.card_discovery_history);self.portable(g)

    def test_b04_summoning_a_fresh_king_does_not_execute_battlecry(self):
        g=self.opening();self.seed(g,'summon')
        self.assertTrue(any(g.state.entities[i].card_id==ROOT for i in g.state.players[1].board))
        self.assertFalse(self.band(g).taken_slots);self.assertFalse(g.state.card_discovery_history)

    def test_b05_both_players_use_their_own_original_member_order_and_consumption(self):
        g=self.opening(both=True);self.play(g,ROOT);self.choose(g,'band:0');g.apply(EndTurn(1))
        self.play(g,ROOT);self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),tuple(reversed(MEMBERS)))
        self.choose(g,'band:0');self.assertEqual(self.band(g,1).taken_slots,(0,));self.assertEqual(self.band(g,2).taken_slots,(0,))
        self.assertTrue(any(g.state.entities[i].card_id==C for i in g.state.players[2].hand));self.portable(g)

    def test_c00_actual_mulligan_wait_restores_the_original_private_sideboard(self):
        g=self.opening(complete=False);g=self.portable(g);self.finish(g)
        self.assertEqual(self.band(g).cards,MEMBERS)

    def test_c01_actual_discovery_wait_preserves_full_original_work_and_payment(self):
        g=self.opening();self.play(g,ROOT);mana=g.state.players[1].mana
        g=self.portable(g);self.choose(g,'band:2')
        self.assertEqual(g.state.players[1].mana,mana);self.assertEqual(self.band(g).taken_slots,(2,))
        self.portable(g)

    def test_c02_post_acquisition_wait_keeps_consumed_slot_and_one_owed_discovery_completion(self):
        g=self.opening();self.seed(g,'watch',True);self.play(g,ROOT);self.choose(g,'band:1')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.band(g).taken_slots,(1,))
        self.assertEqual(sum(e.kind=='card_discovered' for e in g._events),0)
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==B)
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,2)
        g=self.portable(g);self.choose(g,'ok')
        self.assertEqual(sum(e.kind=='card_discovered' for e in g._events),1);self.portable(g)

    def test_c03_failed_acquisition_rolls_back_selection_allocation_slots_rng_but_keeps_prior_payment(self):
        g=self.opening();self.seed(g,'bad',True);self.play(g,ROOT);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'band:0')
        self.assertEqual(g.snapshot(),before);self.assertFalse(self.band(g).taken_slots)

    def test_c04_failed_later_resume_keeps_already_accepted_consumption_and_original_wait(self):
        g=self.opening();self.seed(g,'watch',True);self.play(g,ROOT);self.choose(g,'band:1');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.band(g).taken_slots,(1,))
        self.choose(g,'ok');self.portable(g)

    def test_d00_full_hand_after_selection_burns_the_new_card_and_still_consumes_its_slot(self):
        g=self.opening();self.seed(g,'full',True);self.play(g,ROOT);self.choose(g,'band:1')
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(self.band(g).taken_slots,(1,))
        self.assertFalse(any(g.state.entities[i].card_id==B for i in g.state.players[1].hand))
        self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(sum(e.kind=='card_burned' for e in g._events),1);self.portable(g)

    def test_d01_rehashed_waiting_state_cannot_invent_prior_slot_consumption(self):
        g=self.opening();self.play(g,ROOT);s=json.loads(json.dumps(g.snapshot()))
        s['state']['players']['1']['sideboards'][0]['taken_slots']=[0]
        from test_current_deck_empty_basics import rehash
        rehash(s)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))

    def test_d02_player_projections_keep_original_bands_and_offered_work_private(self):
        g=self.opening();self.play(g,ROOT)
        own=json.dumps(g.for_player(1).observe())
        enemy=json.dumps(g.for_player(2).observe())+json.dumps(g.for_player(2).legal_actions())+json.dumps(g.player_events(2))
        for cid in MEMBERS:self.assertIn(cid,own);self.assertNotIn(cid,enemy)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"sideboards"','"taken_slots"','"original_deck"','"original_offer"','"rng_state"'):
                self.assertNotIn(key,wire)


if __name__=='__main__':unittest.main()
