"""Vyranoth through real starting decks, balanced rewards, and stored lifecycle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.deck_stat_distribution_card import CARD, CONDITION, load_batch
from hs_sim.engine import (BattlecryRepeatSpec, CardClass, CardDefinition, CardMetadata,
    CardType, CheckDeckCondition, Game, OpeningHook, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.construction import DeckPolicy, DeckSpec, MatchSetup
from hs_sim.engine.deck_stat_distribution import EVENT, DistributeDeckStatPairs, from_dict
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Destroy,
    Draw, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.pools import GenerateFromCandidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, DestroyDeckMatching, MoveCard

P = 'k220.'
PREP, TARGET, NEW, SPELL, REPEAT, RNG, DRAW, COPY, BEFORE = (
    P+x for x in ('prepare','target','new','spell','repeat','rng','draw','copy','before'))
META = CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
DECK_META = CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
CASES = ((0,'normal'),(1,'normal'),(2,'normal'),(7,'normal'),(10,'normal'),(51,'normal'),
         (7,'wait'),(7,'move'),(7,'repeat'),(7,'repeat_move'),(7,'kill'),(7,'before'))


def config(n,mode):return P+f'config.{n}.{mode}'


@lru_cache(None)
def registry(role):
    from hs_sim.cards import build_registry
    r=build_registry();r.register_behavior(P+'nop',lambda c:())
    for cid,atk,hp in ((TARGET,1,1),(NEW,2,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=atk,health=hp,metadata=META))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,on_play=P+'nop',metadata=META))
    for cost in (93,94,95):
        r.register_card(CardDefinition(P+f'high.{cost}',str(cost),CardType.MINION,
            cost=cost,attack=1,health=1,metadata=DECK_META))
    for i in range(4):
        cid=P+f'pad.{i}'
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=P+'nop',metadata=DECK_META))
    def prepare(c):
        cid=next(cid for cid in c.state.players[c.player_id].original_deck if cid.startswith(P+'config.'))
        return (ChangeManaCrystals(c.player_id,9),*(AddToHand(c.player_id,x,c.source_id)
            for x in (CARD,cid,RNG,DRAW,COPY)))
    r.register_behavior(P+'prepare',prepare)
    r.register_card(CardDefinition(PREP,PREP,CardType.MINION,attack=1,health=1,metadata=DECK_META,
        opening_hooks=(OpeningHook('after_mulligan',P+'prepare'),)))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=20,metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    def fail(c):raise ResolutionError('Deliberate deck-stat choice rollback')
    r.register_behavior(P+'fail',fail)
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    def watch(c,mode):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=CARD:return ()
        deck=[c.state.entities[i] for i in c.state.players[c.player_id].deck
              if c.state.entities[i].kind==CardType.MINION]
        if not deck or c.event.target_id!=deck[0].id:return ()
        if any(e.attack<8 or e.health<8 for e in deck):
            raise ResolutionError('Distribution notified before all original recipients were buffed')
        if mode=='wait':return wait(c)
        if mode=='kill':return (Destroy(c.event.source_id),)
        if sum(b.payload.card_id==CARD for b in c.state.battlecry_history)!=1:return ()
        return (MoveCard(CardReference.capture(deck[-1]),c.player_id,Zone.HAND,source_id=c.source_id),
                AddToDeck(c.player_id,NEW,'bottom',c.source_id))
    for mode in ('wait','move','kill'):
        key=P+'watch.'+mode
        r.register_behavior(key,lambda c,mode=mode:watch(c,mode))
        r.register_card(CardDefinition(key,key,CardType.MINION,health=20,metadata=META,
            triggers=(TriggerSpec('stored_card_buffed',key),)))
    for n,mode in CASES:
        cid=config(n,mode)
        def setup(c,n=n,mode=mode):
            work=[DestroyDeckMatching(c.player_id,count=1000,source_id=c.source_id,reveal=False)]
            work.extend(AddToDeck(c.player_id,TARGET,'bottom',c.source_id) for _ in range(n))
            work.append(AddToDeck(c.player_id,SPELL,'bottom',c.source_id))
            if mode in ('repeat','repeat_move'):work.append(Summon(c.player_id,REPEAT))
            if mode in ('wait','move','kill','repeat_move'):
                work.append(Summon(c.player_id,P+'watch.'+('move' if mode=='repeat_move' else mode)))
            if mode=='before':work.append(AddToHand(c.player_id,BEFORE,c.source_id))
            return tuple(work)
        r.register_behavior(cid,setup)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=DECK_META))
    r.register_behavior(RNG,lambda c:(GenerateFromCandidates(c.player_id,(NEW,SPELL),c.source_id),))
    r.register_behavior(DRAW,lambda c:(Draw(c.player_id),))
    def copy(c):
        card=next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                  if c.state.entities[i].card_id==TARGET)
        return (CopyCard(CardReference.capture(card),c.player_id,source_id=c.source_id),)
    r.register_behavior(COPY,copy)
    r.register_behavior(BEFORE,lambda c:(*wait(c),CheckDeckCondition(c.player_id,CONDITION,
        (DistributeDeckStatPairs(c.player_id,50,c.source_id),),())))
    for cid in (RNG,DRAW,COPY,BEFORE):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    r.validate();return r


class DeckStatDistributionTests(unittest.TestCase):
    def game(self,n=7,mode='normal',total=100,owner=1):
        r=registry('writer')
        deck=(CARD,P+f'high.{total-6}',PREP,*(P+f'pad.{i}' for i in range(4)),config(n,mode))
        policy=DeckPolicy('k220-v1','k220','experimental',tuple(r.cards),deck_size=8)
        decks=tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,deck) for _ in (1,2))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',220,owner),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.play(g,config(n,mode))
        return g

    def play(self,g,cid):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        pos=len(g.state.players[p].board) if g.state.entities[eid].kind==CardType.MINION else None
        g.apply(PlayCard(p,eid,position=pos));return eid

    def minions(self,g,owner=None,zone='deck'):
        owner=owner or g.state.active_player
        return [g.state.entities[i] for i in getattr(g.state.players[owner],zone)
                if g.state.entities[i].kind==CardType.MINION]

    def facts(self,g):return [from_dict(json.loads(dict(e.data)['fact'])) for e in g.events if e.kind==EVENT]

    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        other=registry('reader' if g.registry is registry('writer') else 'writer')
        self.assertIsNot(g.registry,other)
        restored=Game.from_snapshot(saved,other)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),other).snapshot(),saved)
        return restored

    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))

    def rehash(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_complete_source_and_explicit_paired_semantics(self):
        d=load_batch();self.assertEqual((len(d['cards']),len(d['evidence_only']),len(d['official_observations'])),(1,2,2))
        c=registry('writer').card(CARD)
        self.assertEqual((c.cost,c.attack,c.health,c.metadata.tribes),(6,6,6,('elemental',)))
        self.assertNotIn('CATA_213e',registry('writer').cards)

    def test_two_remaining_minions_get_twenty_five_pairs_and_one_payment(self):
        g=self.game(n=2);before=g.state.players[1].mana;source=self.play(g,CARD)
        self.assertEqual([(e.attack,e.health) for e in self.minions(g)],[(26,26),(26,26)])
        self.assertEqual(g.state.players[1].mana,before-6)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(6,6))
        self.assertEqual(self.facts(g)[0].amounts,(25,25));self.check(g)

    def test_single_remaining_minion_gets_fifty_attack_and_fifty_health(self):
        g=self.game(n=1);self.play(g,CARD)
        self.assertEqual([(e.attack,e.health) for e in self.minions(g)],[(51,51)]);self.check(g)

    def test_seven_remaining_minions_get_six_sevens_and_one_eight(self):
        g=self.game();self.play(g,CARD)
        bonuses=[e.attack-1 for e in self.minions(g)]
        self.assertEqual(sorted(bonuses),[7]*6+[8])
        self.assertTrue(all(e.attack==e.health for e in self.minions(g)))
        self.assertEqual(sum(bonuses),50);self.check(g)

    def test_ten_minions_split_exactly_without_consuming_rng(self):
        g=self.game(n=10);before=g.snapshot()['rng_state'];self.play(g,CARD)
        self.assertEqual([(e.attack,e.health) for e in self.minions(g)],[(6,6)]*10)
        self.assertEqual(g.snapshot()['rng_state'],before);self.check(g)

    def test_more_than_fifty_minions_receive_unique_remainder_weights(self):
        g=self.game(n=51);self.play(g,CARD);f=self.facts(g)[0]
        self.assertEqual(len(f.candidates),51);self.assertEqual(len(set(f.selected)),50)
        self.assertEqual(sorted(e.attack-1 for e in self.minions(g)),[0]+[1]*50)
        self.assertEqual(len(f.enchantment_ids),50);self.check(g)

    def test_spell_only_current_deck_is_empty_rng_neutral_reward(self):
        g=self.game(n=0);before=g.snapshot()['rng_state'];self.play(g,CARD)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.facts(g)[0].candidates,())
        self.assertEqual(len(g.state.players[1].deck),1);self.check(g)

    def test_starting_total_is_exact_not_at_least_one_hundred(self):
        for total in (99,101):
            g=self.game(total=total);before=g.snapshot()['rng_state'];self.play(g,CARD)
            self.assertEqual(self.facts(g),[])
            self.assertTrue(all((e.attack,e.health)==(1,1) for e in self.minions(g)))
            self.assertEqual(g.snapshot()['rng_state'],before)
        self.check(g)

    def test_actual_second_seat_and_opponent_inventory_is_untouched(self):
        g=self.game(owner=2)
        before={i:(g.state.entities[i].attack,g.state.entities[i].health) for i in g.state.players[1].deck}
        self.play(g,CARD)
        self.assertEqual(self.facts(g)[0].player_id,2)
        self.assertEqual(sum(e.attack-1 for e in self.minions(g,2)),50)
        self.assertEqual({i:(g.state.entities[i].attack,g.state.entities[i].health) for i in g.state.players[1].deck},before)
        self.check(g)

    def test_arbitrary_scenario_cannot_invent_starting_deck_facts(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),mana=10,max_mana=10),
            PlayerSetup('HERO_08')),seed=220),registry('writer'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_all_original_recipients_are_changed_before_first_waiting_notification(self):
        g=self.game(mode='wait');self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(sum(e.attack-1 for e in self.minions(g)),50)
        restored=self.check(g)
        for branch in (g,restored):self.choose(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_failed_choice_rolls_back_to_exact_already_committed_group(self):
        g=self.game(mode='wait');self.play(g,CARD);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_new_card_and_later_moved_card_do_not_rebind_original_distribution(self):
        g=self.game(mode='move');self.play(g,CARD);f=self.facts(g)[0]
        moved=[g.state.entities[x.entity_id] for x in f.candidates if g.state.entities[x.entity_id].zone==Zone.HAND]
        self.assertEqual(len(moved),1);self.assertGreaterEqual(moved[0].attack,8)
        added=next(e for e in self.minions(g) if e.card_id==NEW)
        self.assertEqual((added.attack,added.health),(2,2));self.check(g)

    def test_repeated_battlecry_captures_fresh_deck_without_repaying(self):
        g=self.game(mode='repeat');before=g.state.players[1].mana;self.play(g,CARD)
        self.assertEqual(len(self.facts(g)),2)
        self.assertEqual(sum(e.attack-1 for e in self.minions(g)),100)
        self.assertEqual(g.state.players[1].mana,before-6);self.check(g)

    def test_second_battlecry_uses_actual_new_and_departed_recipients(self):
        g=self.game(mode='repeat_move');self.play(g,CARD);first,second=self.facts(g)
        a={x.entity_id for x in first.candidates};b={x.entity_id for x in second.candidates}
        self.assertEqual(len(a-b),1);self.assertEqual(len(b-a),1)
        self.assertEqual(g.state.entities[next(iter(a-b))].zone,Zone.HAND)
        self.assertEqual(g.state.entities[next(iter(b-a))].card_id,NEW);self.check(g)

    def test_original_source_death_does_not_remove_already_granted_stats(self):
        g=self.game(mode='kill');source=self.play(g,CARD)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(sum(e.attack-1 for e in self.minions(g)),50);self.check(g)

    def test_draw_and_current_copy_keep_independent_stored_material(self):
        g=self.game(n=2);self.play(g,CARD);self.play(g,DRAW);self.play(g,COPY)
        cards=[g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==TARGET]
        self.assertEqual([(e.attack,e.health) for e in cards],[(26,26),(26,26)])
        self.assertTrue(set(a.id for a in cards[0].enchantments).isdisjoint(a.id for a in cards[1].enchantments));self.check(g)

    def test_later_ordinary_random_work_does_not_invalidate_original_plan(self):
        g=self.game();self.play(g,CARD);before=g.snapshot()['rng_state'];self.play(g,RNG)
        self.assertNotEqual(g.snapshot()['rng_state'],before);self.check(g)

    def test_pending_conditional_distribution_request_restores_before_acceptance(self):
        g=self.game(mode='before');self.play(g,BEFORE)
        self.assertTrue(all((e.attack,e.health)==(1,1) for e in self.minions(g)))
        restored=self.check(g)
        for branch in (g,restored):self.choose(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(sum(e.attack-1 for e in self.minions(g)),50);self.check(g)

    def test_private_inventory_and_corrupted_remainder_rng_offsets_are_rejected(self):
        g=self.game();self.play(g,CARD)
        for owner in (1,2):
            dto=json.dumps(g.observe(owner));self.assertNotIn(EVENT,dto);self.assertNotIn('buff_offsets',dto)
        for mode in ('selected','rng','offset','allocation','actor'):
            saved=deepcopy(g.snapshot());event=next(e for e in saved['events'] if e['kind']==EVENT)
            data=dict(event['data']);fact=json.loads(data['fact'])
            if mode=='selected':fact['selected']=[]
            elif mode=='rng':fact['rng_after']=fact['rng_before']
            elif mode=='offset':fact['buff_offsets'][0]=fact['buff_offsets'][-1]
            elif mode=='allocation':fact['enchantment_ids'][0]=saved['state']['next_attachment_id']
            else:fact['player_id']=2
            data['fact']=json.dumps(fact,sort_keys=True,separators=(',',':'));event['data']=[[k,v] for k,v in data.items()]
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('reader'))

    def test_declared_pair_count_is_strict(self):
        for pairs in (True,-1,1.5,'50'):
            with self.assertRaises(ValueError):DistributeDeckStatPairs(1,pairs,1)


if __name__ == '__main__':unittest.main()
