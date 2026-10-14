"""Necessary real zone exchanges expressed with captured physical MoveCard work."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, PlayCard,
    PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, Draw, ModifyCost, RequestChoice, RevealHandCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard, ReorderZone
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

TOG,RANSOM,FINLEY='LOOT_541','LOOT_541t','TSC_908'
FIXTURE=Path(__file__).resolve().parents[1]/'data/support/zone-exchange-basics.json'
PIN='fbd7c734a34d393392f257f27da7e707242e6e42634a49ba04eedf590a84d540'


def evidence():
    raw=json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw)!=PIN:raise ValueError('Complete exchange raw changed')
    for row in raw['records']:
        if row['id']!=row['data']['id']or canonical_digest(row['data'])!=row['data_sha256']:
            raise ValueError('Exchange original row changed')
    return {row['id']:row['data']for row in raw['records']}


def decks(c):
    owner,other=c.player_id,3-c.player_id
    left=tuple(CardReference.capture(c.state.entities[eid])for eid in c.state.players[owner].deck)
    right=tuple(CardReference.capture(c.state.entities[eid])for eid in c.state.players[other].deck)
    return tuple(MoveCard(ref,other,Zone.DECK,source_id=c.source_id)for ref in left)+tuple(
        MoveCard(ref,owner,Zone.DECK,source_id=c.source_id)for ref in right)


def bottom(c):
    player=c.state.players[c.player_id]
    held=tuple(CardReference.capture(c.state.entities[eid])for eid in player.hand)
    take=min(len(held),len(player.deck))
    selected=tuple(CardReference.capture(c.state.entities[eid])for eid in reversed(player.deck[-take:]))if take else ()
    # Local bottom-depth policy: leftmost held slot maps to deepest deck slot.
    # The current held order, not hand-entry chronology, defines the selection.
    return tuple(MoveCard(ref,c.player_id,Zone.DECK,source_id=c.source_id)for ref in reversed(held))+tuple(
        MoveCard(ref,c.player_id,Zone.HAND,source_id=c.source_id)for ref in selected)


def registry(scripts=(), *,observer=None,fault=None):
    r=opening_registry();rows=evidence()
    def tog(c):
        work=decks(c)+(AddToHand(3-c.player_id,RANSOM,c.source_id),)
        return work+((AddToDeck(c.player_id,'card.1'),AddToHand(c.player_id,'missing.after.exchange'))if fault=='decks'else ())
    def finley(c):
        work=bottom(c)
        return work+((AddToDeck(c.player_id,'card.1'),AddToHand(c.player_id,'missing.after.exchange'))if fault=='bottom'else ())
    for name,callback in (('tog',tog),('ransom',decks),('finley',finley),*scripts):r.register_behavior(name,callback)
    for cid,behavior in ((TOG,'tog'),(FINLEY,'finley')):
        row=rows[cid];r.register_card(CardDefinition(cid,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],
            health=row['health'],battlecry=behavior,metadata=metadata(rarity=Rarity.LEGENDARY,tribes=('murloc',)if cid==FINLEY else ())))
    row=rows[RANSOM];r.register_card(CardDefinition(RANSOM,row['name'],CardType.SPELL,cost=row['cost'],on_play='ransom',
        metadata=metadata(collectible=False,rarity=None)))
    for name,_ in scripts:r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata()))
    if observer:
        name,event=observer
        r.register_behavior(name,lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),),c.source_id),)
            if c.state.entities[c.event.target_id].card_id=='card.1'else ())
        r.register_card(CardDefinition(name,name,CardType.MINION,health=4,
            triggers=(TriggerSpec(event,name),),metadata=metadata()))
    return r


class ZoneExchangeTests(unittest.TestCase):
    def setUp(self):self.scripts=[];self.options={}
    def script(self,name,callback):self.scripts.append((name,callback))
    def game(self,hand=(TOG,), *,deck=('card.1','card.2'),enemy_deck=('card.3','card.4','card.5'),enemy_hand=(),board=()):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,deck=deck,board=board,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,deck=enemy_deck,mana=10,max_mana=10)),seed=73),registry(self.scripts,**self.options))
    def play(self,g,cid=TOG,player=1):
        source=next(eid for eid in g.state.players[player].hand if g.state.entities[eid].card_id==cid)
        g.apply(PlayCard(player,source));return source
    def portable(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(snapshot,registry(self.scripts,**self.options))
        self.assertEqual(restored.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),registry(self.scripts,**self.options)).snapshot(),snapshot);return restored
    def cards(self,g,zone=Zone.HAND,player=1):
        return [g.state.entities[eid].card_id for eid in getattr(g.state.players[player],zone.value)]
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def no_draw_or_discard(self,g):
        self.assertFalse(g.state.draw_history);self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind in ('card_drawn','fatigue','card_discarded','card_destroyed_in_deck','card_burned')for e in g.events))

    def test_real_tog_preserves_all_physical_deck_entities_order_and_owner(self):
        g=self.game();left=tuple(g.state.players[1].deck);right=tuple(g.state.players[2].deck)
        rng=g._rng.getstate();source=self.play(g);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.players[1].deck,list(right));self.assertEqual(g.state.players[2].deck,list(left))
        for owner,received,ids in ((1,2,left),(2,1,right)):
            for eid in ids:self.assertEqual((g.state.entities[eid].owner,g.state.entities[eid].controller,g.state.entities[eid].zone),(owner,received,Zone.DECK))
        self.assertEqual(self.cards(g,player=2),[RANSOM]);self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),0)
        self.assertEqual(g.state.play_history[0].source_id,source);self.no_draw_or_discard(g);self.portable(g)

    def test_real_finley_exchanges_original_hand_slots_for_original_bottom_cards(self):
        g=self.game((FINLEY,'card.1','card.2'),deck=('card.3','card.4','card.5'))
        held=g.state.players[1].hand[1:];original=list(g.state.players[1].deck);rng=g._rng.getstate();source=self.play(g,FINLEY)
        self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.players[1].hand,list(reversed(original[-2:])))
        self.assertEqual(g.state.players[1].deck,original[:-2]+list(reversed(held)))
        self.assertEqual(g.state.players[1].board,[source]);self.assertEqual(g.state.players[1].mana,9)
        self.no_draw_or_discard(g);self.portable(g)

    def test_complete_raw_is_original_and_only_three_required_definitions(self):
        rows=evidence();originals={row['id']:row for row in json.loads((FIXTURE.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(set(rows),{TOG,RANSOM,FINLEY})
        for cid,row in rows.items():self.assertEqual(row,originals[cid])
        self.assertEqual([rows[cid]['type']for cid in (TOG,RANSOM,FINLEY)],['MINION','SPELL','MINION'])
        self.assertEqual([rows[cid]['cost']for cid in (TOG,RANSOM,FINLEY)],[8,5,1])

    def test_tog_with_empty_own_deck_gets_all_other_originals(self):
        g=self.game(deck=());other=list(g.state.players[2].deck);self.play(g)
        self.assertEqual(g.state.players[1].deck,other);self.assertFalse(g.state.players[2].deck);self.no_draw_or_discard(g);self.portable(g)

    def test_tog_with_empty_other_deck_transfers_all_own_originals(self):
        g=self.game(enemy_deck=());own=list(g.state.players[1].deck);self.play(g)
        self.assertEqual(g.state.players[2].deck,own);self.assertFalse(g.state.players[1].deck);self.no_draw_or_discard(g)

    def test_tog_with_both_empty_still_gives_ransom_without_fatigue(self):
        g=self.game(deck=(),enemy_deck=());self.play(g)
        self.assertFalse(g.state.players[1].deck);self.assertFalse(g.state.players[2].deck)
        self.assertEqual(self.cards(g,player=2),[RANSOM]);self.no_draw_or_discard(g);self.portable(g)

    def test_tog_over_thirty_cards_per_deck_does_not_burn_or_allocate_replacements(self):
        g=self.game(deck=('card.1',)*31,enemy_deck=('card.2',)*32)
        originals=set(g.state.players[1].deck+g.state.players[2].deck);count=len(g.state.entities);self.play(g)
        self.assertEqual((len(g.state.players[1].deck),len(g.state.players[2].deck)),(32,31))
        self.assertEqual(set(g.state.players[1].deck+g.state.players[2].deck),originals)
        self.assertEqual(len(g.state.entities),count+1);self.no_draw_or_discard(g);self.portable(g)

    def test_duplicate_definitions_keep_every_distinct_physical_copy(self):
        g=self.game(deck=('card.1',)*3,enemy_deck=('card.1',)*2)
        left=list(g.state.players[1].deck);right=list(g.state.players[2].deck);self.play(g)
        self.assertEqual(g.state.players[1].deck,right);self.assertEqual(g.state.players[2].deck,left)
        self.assertEqual(len(set(left+right)),5);self.portable(g)

    def test_ransom_swaps_current_decks_instead_of_restoring_old_snapshot(self):
        g=self.game();left=list(g.state.players[1].deck);right=list(g.state.players[2].deck);self.play(g)
        g.apply(EndTurn(1));self.assertEqual(g.state.players[2].hand[-1],left[0])
        self.play(g,RANSOM,2)
        self.assertEqual(g.state.players[1].deck,left[1:]);self.assertEqual(g.state.players[2].deck,right)
        self.assertEqual(g.state.players[2].hand,[left[0]]);self.assertEqual(g.state.players[2].mana,5);self.portable(g)

    def test_ransom_burns_in_full_enemy_hand_without_undoing_deck_exchange(self):
        g=self.game(enemy_hand=('card.6',)*10);left=list(g.state.players[1].deck);right=list(g.state.players[2].deck);self.play(g)
        self.assertEqual(g.state.players[1].deck,right);self.assertEqual(g.state.players[2].deck,left)
        self.assertEqual(len(g.state.players[2].hand),10)
        self.assertEqual(self.cards(g,Zone.GRAVEYARD,2),[RANSOM]);self.portable(g)

    def test_tog_preserves_local_cost_and_cannot_transfer_fatigue_counters(self):
        self.script('setup',lambda c:(Draw(1),AddToDeck(1,'card.1','bottom')))
        self.script('cost',lambda c:(ModifyCost(c.state.players[1].deck[0],CostSpec(delta=-1)),))
        g=self.game(('setup','cost',TOG),deck=());self.play(g,'setup');self.play(g,'cost')
        target=g.state.players[1].deck[0];before=g.state.entities[target].cost
        self.assertEqual(g.state.players[1].fatigue,1)
        fatigue=(g.state.players[1].fatigue,g.state.players[2].fatigue);self.play(g)
        self.assertEqual(g.state.entities[target].cost,before)
        self.assertEqual((g.state.players[1].fatigue,g.state.players[2].fatigue),fatigue);self.portable(g)

    def test_finley_uses_current_held_order_after_explicit_hand_reorder(self):
        self.script('order',lambda c:(ReorderZone(1,Zone.HAND,tuple(reversed(c.state.players[1].hand))),))
        g=self.game(('order',FINLEY,'card.1','card.2'));self.play(g,'order')
        held=[eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id!=FINLEY];self.play(g,FINLEY)
        self.assertEqual(g.state.players[1].deck[-2:],list(reversed(held)));self.no_draw_or_discard(g);self.portable(g)

    def test_finley_empty_hand_keeps_entire_deck_unchanged(self):
        g=self.game((FINLEY,));deck=list(g.state.players[1].deck);self.play(g,FINLEY)
        self.assertFalse(g.state.players[1].hand);self.assertEqual(g.state.players[1].deck,deck);self.no_draw_or_discard(g)

    def test_finley_empty_deck_sends_original_hand_to_deck_without_fatigue(self):
        g=self.game((FINLEY,'card.1','card.2'),deck=());held=g.state.players[1].hand[1:];self.play(g,FINLEY)
        self.assertFalse(g.state.players[1].hand);self.assertEqual(g.state.players[1].deck,list(reversed(held)))
        self.no_draw_or_discard(g);self.portable(g)

    def test_finley_short_deck_takes_only_original_cards_and_keeps_all_old_hand(self):
        g=self.game((FINLEY,'card.1','card.2','card.3'),deck=('card.4',));held=g.state.players[1].hand[1:];olddeck=list(g.state.players[1].deck)
        self.play(g,FINLEY);self.assertEqual(g.state.players[1].hand,olddeck)
        self.assertEqual(g.state.players[1].deck,list(reversed(held)));self.no_draw_or_discard(g);self.portable(g)

    def test_finley_nine_held_cards_replace_without_transient_hand_burn(self):
        g=self.game((FINLEY,)+('card.1',)*9,deck=('card.2',)*12);held=g.state.players[1].hand[1:];olddeck=list(g.state.players[1].deck)
        self.play(g,FINLEY);self.assertEqual(g.state.players[1].hand,list(reversed(olddeck[-9:])))
        self.assertEqual(g.state.players[1].deck,olddeck[:-9]+list(reversed(held)));self.no_draw_or_discard(g);self.portable(g)

    def test_finley_acquisitions_are_moves_with_original_entity_and_epoch(self):
        g=self.game((FINLEY,'card.1','card.2'));olddeck=list(g.state.players[1].deck);epochs={eid:g.state.entities[eid].zone_epoch for eid in olddeck}
        self.play(g,FINLEY)
        for eid in g.state.players[1].hand:
            e=g.state.entities[eid];record=g.state.hand_entries[e.hand_entry_id-1]
            self.assertEqual((e.zone_epoch,record.from_zone,record.reason),(epochs[eid]+1,Zone.DECK,'move'))
        self.no_draw_or_discard(g);self.portable(g)

    def test_finley_preserves_local_cost_in_both_original_groups(self):
        self.script('cost',lambda c:(ModifyCost(c.state.players[1].hand[-1],CostSpec(delta=-1)),
            ModifyCost(c.state.players[1].deck[-1],CostSpec(delta=-1))))
        g=self.game(('cost',FINLEY,'card.1'));held=g.state.players[1].hand[-1];incoming=g.state.players[1].deck[-1]
        self.play(g,'cost');self.play(g,FINLEY)
        self.assertEqual((g.state.entities[held].cost,g.state.entities[incoming].cost),(0,0));self.portable(g)

    def test_tog_pending_move_restores_original_captured_groups_once(self):
        self.options['observer']=('wait.deck','card_moved_to_deck')
        g=self.game(board=('wait.deck',));left=list(g.state.players[1].deck);right=list(g.state.players[2].deck);self.play(g)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.players[1].deck,right)
        self.assertEqual(g.state.players[2].deck,left);self.assertEqual(self.cards(g,player=2),[RANSOM]);self.portable(g)

    def test_finley_pending_exit_restores_selected_old_bottom_without_recapture(self):
        self.options['observer']=('wait.exit','card_moved_to_deck')
        g=self.game((FINLEY,'card.1','card.2'),board=('wait.exit',));held=g.state.players[1].hand[1:];old=list(g.state.players[1].deck);self.play(g,FINLEY)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.players[1].hand,list(reversed(old[-2:])))
        self.assertEqual(g.state.players[1].deck,list(reversed(held)));self.portable(g)

    def test_finley_pending_entry_restores_move_history_without_duplicate_entry(self):
        self.options['observer']=('wait.entry','card_moved_to_hand')
        g=self.game((FINLEY,'card.6'),deck=('card.3','card.1'),board=('wait.entry',));self.play(g,FINLEY)
        self.assertIsNotNone(g.state.pending_choice);count=len(g.state.hand_entries);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(g.state.hand_entries),count);self.portable(g)

    def test_late_exchange_fault_rolls_back_original_decks_ransom_and_rng(self):
        self.options['fault']='decks';g=self.game();before=g.snapshot();views=[g.observe(p)for p in (1,2)]
        with self.assertRaisesRegex(ResolutionError,'missing.after.exchange'):self.play(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual([g.observe(p)for p in (1,2)],views)

    def test_late_bottom_fault_rolls_back_original_hand_deck_histories_and_rng(self):
        self.options['fault']='bottom';g=self.game((FINLEY,'card.1','card.2'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'missing.after.exchange'):self.play(g,FINLEY)
        self.assertEqual(g.snapshot(),before)

    def test_exchange_player_views_keep_deck_identities_order_and_internal_history_private(self):
        g=self.game();self.play(g);before=g.snapshot()
        for p in (1,2):
            text=json.dumps(g.observe(p));self.assertNotIn('card.1',text);self.assertNotIn('card.3',text)
            for field in ('zone_epoch','original_deck','hand_entries','draw_history','rng_state'):self.assertNotIn(field,text)
            for event in g.player_events(p):
                if event['kind']=='card_moved_to_deck':self.assertIsNone(event['target']);self.assertNotIn('position',event)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_finley_conceals_old_revealed_hand_and_new_cards_stay_hidden_to_other_player(self):
        self.script('reveal',lambda c:(RevealHandCard(c.state.players[1].hand[-1]),))
        g=self.game(('reveal',FINLEY,'card.40'),deck=('card.3',));self.play(g,'reveal')
        self.assertIn('card.40',json.dumps(g.observe(2)));self.play(g,FINLEY)
        view=g.observe(2);self.assertNotIn('card.40',json.dumps(view));self.assertNotIn('card.3',json.dumps(view))
        self.assertEqual(self.cards(g),['card.3']);self.portable(g)


if __name__=='__main__':unittest.main()
